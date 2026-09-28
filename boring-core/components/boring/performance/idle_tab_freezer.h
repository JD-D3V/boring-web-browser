// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PERFORMANCE_IDLE_TAB_FREEZER_H_
#define COMPONENTS_BORING_PERFORMANCE_IDLE_TAB_FREEZER_H_

#include <map>
#include <memory>

#include "base/memory/raw_ptr.h"
#include "base/timer/timer.h"
#include "components/performance_manager/public/decorators/page_live_state_decorator.h"
#include "components/performance_manager/public/graph/graph.h"
#include "components/performance_manager/public/graph/page_node.h"

namespace performance_manager::freezing {
class FreezingVote;
}

namespace boring::performance {

// Freezes tabs that have sat in the background for a few minutes. A
// frozen tab stays in memory with its page as it was, runs no script
// and no timers, and wakes at once when it is shown again. Putting a
// tab to sleep (discarding it) is a different, later step, left to
// Chromium's Memory Saver.
//
// This only casts Chromium's freezing vote for background tabs. The
// FreezingPolicy that counts the votes does the rest: it waits until
// the tab has been hidden and silent for a while (5 minutes by default,
// the feature param freezing_visible_protection_time) and never freezes
// a tab that plays sound, is on a call, shares the screen or uses the
// camera or microphone, holds a lock, is loading, may show
// notifications, or is on a site kept awake (see never_sleep_sites.h).
//
// On top of those, no vote at all for a tab that is pinned, has a form
// the person started filling in, plays a video, or has a download
// running.
//
// Lives in the performance manager graph, on the UI thread.
class IdleTabFreezer : public performance_manager::GraphOwned,
                       public performance_manager::PageNodeObserver,
                       public performance_manager::PageLiveStateObserver {
 public:
  IdleTabFreezer();
  IdleTabFreezer(const IdleTabFreezer&) = delete;
  IdleTabFreezer& operator=(const IdleTabFreezer&) = delete;
  ~IdleTabFreezer() override;

  // GraphOwned:
  void OnPassedToGraph(performance_manager::Graph* graph) override;
  void OnTakenFromGraph(performance_manager::Graph* graph) override;

  // PageNodeObserver:
  void OnPageNodeAdded(const performance_manager::PageNode* page) override;
  void OnBeforePageNodeRemoved(
      const performance_manager::PageNode* page) override;
  void OnTypeChanged(const performance_manager::PageNode* page,
                     performance_manager::PageType previous_type) override;
  void OnIsVisibleChanged(const performance_manager::PageNode* page) override;
  void OnHadFormInteractionChanged(
      const performance_manager::PageNode* page) override;
  void OnHadUserEditsChanged(
      const performance_manager::PageNode* page) override;

  // PageLiveStateObserver:
  void OnIsPinnedTabChanged(
      const performance_manager::PageNode* page) override;

 private:
  // Casts or withdraws the vote for one page, as it stands now.
  void Update(const performance_manager::PageNode* page);

  // Video and downloads send no graph notification, so background tabs
  // are looked at again every little while.
  void UpdateAll();

  std::map<const performance_manager::PageNode*,
           std::unique_ptr<performance_manager::freezing::FreezingVote>>
      votes_;
  base::RepeatingTimer recheck_timer_;
};

}  // namespace boring::performance

#endif  // COMPONENTS_BORING_PERFORMANCE_IDLE_TAB_FREEZER_H_
