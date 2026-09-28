// Copyright 2026 boring. BSD style license.

// The chrome/browser half of components/boring/protection/memory_saver.h.
// Built into chrome/browser/ui/views/toolbar (see toolbar-buttons.patch),
// which already depends on the performance manager. No global, nothing
// runs before main.

#include "components/boring/protection/memory_saver.h"

#include "chrome/browser/browser_process.h"
#include "chrome/browser/performance_manager/public/user_tuning/user_performance_tuning_manager.h"
#include "components/performance_manager/public/user_tuning/prefs.h"
#include "components/prefs/pref_service.h"

namespace boring {

namespace {

namespace tuning = performance_manager::user_tuning;

tuning::UserPerformanceTuningManager* Manager() {
  return tuning::UserPerformanceTuningManager::HasInstance()
             ? tuning::UserPerformanceTuningManager::GetInstance()
             : nullptr;
}

}  // namespace

MemorySaverState GetMemorySaverState() {
  MemorySaverState state;
  tuning::UserPerformanceTuningManager* manager = Manager();
  PrefService* local_state = g_browser_process->local_state();
  if (!manager || !local_state) {
    return state;
  }
  state.available = true;
  state.on = manager->IsMemorySaverModeActive();
  state.managed = manager->IsMemorySaverModeManaged();
  switch (tuning::prefs::GetCurrentMemorySaverMode(local_state)) {
    case tuning::prefs::MemorySaverModeAggressiveness::kConservative:
      state.level = MemorySaverLevel::kModerate;
      break;
    case tuning::prefs::MemorySaverModeAggressiveness::kMedium:
      state.level = MemorySaverLevel::kBalanced;
      break;
    case tuning::prefs::MemorySaverModeAggressiveness::kAggressive:
      state.level = MemorySaverLevel::kMaximum;
      break;
  }
  return state;
}

void SetMemorySaverOn(bool on) {
  tuning::UserPerformanceTuningManager* manager = Manager();
  if (manager && !manager->IsMemorySaverModeManaged()) {
    manager->SetMemorySaverModeEnabled(on);
  }
}

void SetMemorySaverLevel(MemorySaverLevel level) {
  tuning::UserPerformanceTuningManager* manager = Manager();
  PrefService* local_state = g_browser_process->local_state();
  if (!manager || !local_state || manager->IsMemorySaverModeManaged()) {
    return;
  }
  // The same pref chrome://settings/performance writes; the manager
  // follows it.
  local_state->SetInteger(tuning::prefs::kMemorySaverModeAggressiveness,
                          static_cast<int>(level));
}

}  // namespace boring
