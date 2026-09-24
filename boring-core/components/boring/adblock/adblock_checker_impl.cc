// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/adblock_checker_impl.h"

#include <memory>
#include <utility>

#include "base/functional/bind.h"
#include "base/no_destructor.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/thread_pool.h"
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

void BindOnTaskRunner(scoped_refptr<BlockingOffSites> off_sites,
                      mojo::PendingReceiver<mojom::AdblockChecker> receiver) {
  mojo::MakeSelfOwnedReceiver(
      std::make_unique<AdblockCheckerImpl>(std::move(off_sites)),
      std::move(receiver));
}

}  // namespace

// static
void AdblockCheckerImpl::Bind(
    scoped_refptr<BlockingOffSites> off_sites,
    mojo::PendingReceiver<mojom::AdblockChecker> receiver) {
  AdblockService::GetInstance()->EnsureLoading();
  CheckTaskRunner()->PostTask(
      FROM_HERE, base::BindOnce(&BindOnTaskRunner, std::move(off_sites),
                                std::move(receiver)));
}

AdblockCheckerImpl::AdblockCheckerImpl(
    scoped_refptr<BlockingOffSites> off_sites)
    : off_sites_(std::move(off_sites)) {}
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
    std::move(callback).Run(false);
    return;
  }
  std::move(callback).Run(
      AdblockService::GetInstance()->ShouldBlock(url, initiator, request_type));
}

void AdblockCheckerImpl::Clone(
    mojo::PendingReceiver<mojom::AdblockChecker> receiver) {
  mojo::MakeSelfOwnedReceiver(std::make_unique<AdblockCheckerImpl>(off_sites_),
                              std::move(receiver));
}

}  // namespace boring
