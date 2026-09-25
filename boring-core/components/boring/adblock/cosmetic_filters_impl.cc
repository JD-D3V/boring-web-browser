// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/cosmetic_filters_impl.h"

#include <memory>
#include <utility>

#include "base/functional/bind.h"
#include "base/no_destructor.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/thread_pool.h"
#include "mojo/public/cpp/bindings/self_owned_receiver.h"
#include "url/gurl.h"

namespace boring {

namespace {

// Pages can list thousands of class names; a renderer asking about more
// than this at once is not a page we want to spend the browser's time on.
constexpr size_t kMaxNames = 10000;

// One background sequence answers all renderers' cosmetic questions.
// USER_BLOCKING because a frame's scripts wait on GetUrlResources.
scoped_refptr<base::SequencedTaskRunner> CosmeticTaskRunner() {
  static base::NoDestructor<scoped_refptr<base::SequencedTaskRunner>> runner(
      base::ThreadPool::CreateSequencedTaskRunner(
          {base::TaskPriority::USER_BLOCKING}));
  return *runner;
}

void BindOnTaskRunner(scoped_refptr<BlockingOffSites> off_sites,
                      scoped_refptr<ProfileLists> lists,
                      mojo::PendingReceiver<mojom::CosmeticFilters> receiver) {
  mojo::MakeSelfOwnedReceiver(std::make_unique<CosmeticFiltersImpl>(
                                  std::move(off_sites), std::move(lists)),
                              std::move(receiver));
}

}  // namespace

// static
void CosmeticFiltersImpl::Bind(
    scoped_refptr<BlockingOffSites> off_sites,
    scoped_refptr<ProfileLists> lists,
    mojo::PendingReceiver<mojom::CosmeticFilters> receiver) {
  AdblockService::GetInstance()->EnsureLoading();
  CosmeticTaskRunner()->PostTask(
      FROM_HERE, base::BindOnce(&BindOnTaskRunner, std::move(off_sites),
                                std::move(lists), std::move(receiver)));
}

CosmeticFiltersImpl::CosmeticFiltersImpl(
    scoped_refptr<BlockingOffSites> off_sites,
    scoped_refptr<ProfileLists> lists)
    : off_sites_(std::move(off_sites)), lists_(std::move(lists)) {}

CosmeticFiltersImpl::~CosmeticFiltersImpl() = default;

bool CosmeticFiltersImpl::IsOn(const GURL& top_frame_url) const {
  if (AdblockService::IsDisabled()) {
    return false;
  }
  return !off_sites_ || !off_sites_->IsOff(top_frame_url);
}

void CosmeticFiltersImpl::GetUrlResources(const GURL& frame_url,
                                          const GURL& top_frame_url,
                                          GetUrlResourcesCallback callback) {
  // GetCosmeticResources also answers null for a URL that is not http
  // or https, and while the engine is not ready.
  if (!IsOn(top_frame_url)) {
    std::move(callback).Run(nullptr);
    return;
  }
  AdblockService* service = AdblockService::GetInstance();
  service->EnsureLoading();
  std::move(callback).Run(service->GetCosmeticResources(
      frame_url, lists_ ? lists_->Get() : EnabledLists()));
}

void CosmeticFiltersImpl::GetHiddenClassIdSelectors(
    const std::vector<std::string>& classes,
    const std::vector<std::string>& ids,
    const std::vector<std::string>& exceptions,
    const GURL& top_frame_url,
    GetHiddenClassIdSelectorsCallback callback) {
  if (!IsOn(top_frame_url) || classes.size() > kMaxNames ||
      ids.size() > kMaxNames || exceptions.size() > kMaxNames) {
    std::move(callback).Run({});
    return;
  }
  std::move(callback).Run(
      AdblockService::GetInstance()->GetHiddenClassIdSelectors(
          classes, ids, exceptions, lists_ ? lists_->Get() : EnabledLists()));
}

}  // namespace boring
