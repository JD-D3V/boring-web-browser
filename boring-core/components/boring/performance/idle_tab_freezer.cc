// Copyright 2026 boring. BSD style license.

#include "components/boring/performance/idle_tab_freezer.h"

#include <utility>

#include "base/functional/bind.h"
#include "base/location.h"
#include "base/task/sequenced_task_runner.h"
#include "base/time/time.h"
#include "components/boring/performance/tab_activity.h"
#include "components/performance_manager/public/freezing/freezing.h"
#include "components/performance_manager/public/performance_manager.h"
#include "content/public/browser/web_contents.h"

namespace boring::performance {

namespace {

using performance_manager::Graph;
using performance_manager::PageLiveStateDecorator;
using performance_manager::PageNode;
using performance_manager::PageType;
using performance_manager::freezing::FreezingVote;

// How often background tabs are looked at again for a video or a
// download. Freezing itself waits minutes, so this only has to be well
// inside that.
constexpr base::TimeDelta kRecheckInterval = base::Seconds(30);

// Things that keep a tab awake which Chromium's FreezingPolicy does not
// check for itself.
bool KeepAwake(const PageNode* page) {
  const PageLiveStateDecorator::Data* live_state =
      PageLiveStateDecorator::Data::FromPageNode(page);
  if (live_state && live_state->IsPinnedTab()) {
    return true;
  }
  if (page->HadFormInteraction() || page->HadUserEdits()) {
    return true;
  }
  return IsBusyInBackground(page->GetWebContents().get());
}

}  // namespace

IdleTabFreezer::IdleTabFreezer() = default;
IdleTabFreezer::~IdleTabFreezer() = default;

void IdleTabFreezer::OnPassedToGraph(Graph* graph) {
  graph->AddPageNodeObserver(this);
  for (const PageNode* page : graph->GetAllPageNodes()) {
    OnPageNodeAdded(page);
    Update(page);
  }
  recheck_timer_.Start(FROM_HERE, kRecheckInterval, this,
                       &IdleTabFreezer::UpdateAll);
}

void IdleTabFreezer::OnTakenFromGraph(Graph* graph) {
  recheck_timer_.Stop();
  // Every page is gone by now (the graph removes its nodes first), so
  // these votes point at nothing and let go without asking anything.
  votes_.clear();
  graph->RemovePageNodeObserver(this);
}

void IdleTabFreezer::OnPageNodeAdded(const PageNode* page) {
  PageLiveStateDecorator::Data::GetOrCreateForPageNode(page)->AddObserver(this);
}

void IdleTabFreezer::OnBeforePageNodeRemoved(const PageNode* page) {
  PageLiveStateDecorator::Data::GetOrCreateForPageNode(page)->RemoveObserver(
      this);
  auto it = votes_.find(page);
  if (it == votes_.end()) {
    return;
  }
  // Withdrawing a vote now would have the freezing policy unfreeze a
  // page whose tab is already being torn down. Let it go once the page
  // is gone instead, when withdrawing does nothing.
  base::SequencedTaskRunner::GetCurrentDefault()->DeleteSoon(
      FROM_HERE, std::move(it->second));
  votes_.erase(it);
}

void IdleTabFreezer::OnTypeChanged(const PageNode* page,
                                   PageType previous_type) {
  Update(page);
}

void IdleTabFreezer::OnIsVisibleChanged(const PageNode* page) {
  Update(page);
}

void IdleTabFreezer::OnHadFormInteractionChanged(const PageNode* page) {
  Update(page);
}

void IdleTabFreezer::OnHadUserEditsChanged(const PageNode* page) {
  Update(page);
}

void IdleTabFreezer::OnIsPinnedTabChanged(const PageNode* page) {
  Update(page);
}

void IdleTabFreezer::Update(const PageNode* page) {
  content::WebContents* contents = page->GetWebContents().get();
  // A vote lands on the tab's primary page, so only that page gets one.
  const bool vote =
      contents && page->GetType() == PageType::kTab && !page->IsVisible() &&
      performance_manager::PerformanceManager::GetPrimaryPageNodeForWebContents(
          contents)
              .get() == page &&
      !KeepAwake(page);
  auto it = votes_.find(page);
  if (vote == (it != votes_.end())) {
    return;
  }
  if (vote) {
    votes_.emplace(page, std::make_unique<FreezingVote>(contents));
  } else {
    votes_.erase(it);
  }
}

void IdleTabFreezer::UpdateAll() {
  for (const PageNode* page : GetOwningGraph()->GetAllPageNodes()) {
    Update(page);
  }
}

}  // namespace boring::performance
