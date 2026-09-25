// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/adblock_checker_impl.h"

#include <memory>
#include <optional>
#include <string>
#include <utility>

#include "base/functional/bind.h"
#include "base/no_destructor.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/thread_pool.h"
#include "components/boring/adblock/adblock_redirect_proxy.h"
#include "components/boring/adblock/adblock_service.h"
#include "mojo/public/cpp/bindings/self_owned_receiver.h"

namespace boring {

namespace {

// One background sequence answers all renderer checks.
scoped_refptr<base::SequencedTaskRunner> CheckTaskRunner() {
  static base::NoDestructor<scoped_refptr<base::SequencedTaskRunner>> runner(
      base::ThreadPool::CreateSequencedTaskRunner(
          {base::TaskPriority::USER_BLOCKING}));
  return *runner;
}

void BindOnTaskRunner(int render_process_id,
                      scoped_refptr<BlockingOffSites> off_sites,
                      scoped_refptr<ProfileLists> lists,
                      mojo::PendingReceiver<mojom::AdblockChecker> receiver) {
  mojo::MakeSelfOwnedReceiver(
      std::make_unique<AdblockCheckerImpl>(
          render_process_id, std::move(off_sites), std::move(lists)),
      std::move(receiver));
}

}  // namespace

// static
void AdblockCheckerImpl::Bind(
    int render_process_id,
    scoped_refptr<BlockingOffSites> off_sites,
    scoped_refptr<ProfileLists> lists,
    mojo::PendingReceiver<mojom::AdblockChecker> receiver) {
  AdblockService::GetInstance()->EnsureLoading();
  CheckTaskRunner()->PostTask(
      FROM_HERE,
      base::BindOnce(&BindOnTaskRunner, render_process_id, std::move(off_sites),
                     std::move(lists), std::move(receiver)));
}

AdblockCheckerImpl::AdblockCheckerImpl(
    int render_process_id,
    scoped_refptr<BlockingOffSites> off_sites,
    scoped_refptr<ProfileLists> lists)
    : render_process_id_(render_process_id),
      off_sites_(std::move(off_sites)),
      lists_(std::move(lists)) {}
AdblockCheckerImpl::~AdblockCheckerImpl() = default;

void AdblockCheckerImpl::Check(const GURL& url,
                               const GURL& initiator,
                               const std::string& request_type,
                               const GURL& top_frame_url,
                               CheckCallback callback) {
  // The switch that turns ad blocking off for this run has to reach
  // page requests too, not only the browser side throttle.
  if (AdblockService::IsDisabled() ||
      (off_sites_ && off_sites_->IsOff(top_frame_url))) {
    std::move(callback).Run(false, std::nullopt);
    return;
  }
  AdblockService::Decision decision = AdblockService::GetInstance()->Check(
      url, initiator, request_type, lists_ ? lists_->Get() : EnabledLists());
  // Offering the stub tells the renderer to let the request go on, for
  // the proxy to answer. Without a proxy in front of this renderer it
  // would reach the real server, so it is plainly blocked instead.
  std::optional<std::string> redirect;
  if (decision.block && !decision.redirect.empty() &&
      AdblockRedirectProxy::CoversProcess(render_process_id_)) {
    redirect = std::move(decision.redirect);
  }
  std::move(callback).Run(decision.block, std::move(redirect));
}

void AdblockCheckerImpl::Clone(
    mojo::PendingReceiver<mojom::AdblockChecker> receiver) {
  mojo::MakeSelfOwnedReceiver(std::make_unique<AdblockCheckerImpl>(
                                  render_process_id_, off_sites_, lists_),
                              std::move(receiver));
}

}  // namespace boring
