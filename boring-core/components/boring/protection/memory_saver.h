// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PROTECTION_MEMORY_SAVER_H_
#define COMPONENTS_BORING_PROTECTION_MEMORY_SAVER_H_

namespace boring {

// Chromium's Memory Saver, for the Memory section of the Protection
// page. Memory Saver is a browser-wide setting kept in local state and
// run by UserPerformanceTuningManager, both of which live in
// chrome/browser, so these are declared here and defined in
// chrome/browser/ui/views/boring/boring_memory_saver_bridge.cc, built
// into chrome/browser/ui. The same split as search/search_engines.h.

// Chromium's own levels, in its own order and with its own values
// (performance_manager::user_tuning::prefs::MemorySaverModeAggressiveness).
enum class MemorySaverLevel {
  kModerate = 0,
  kBalanced = 1,
  kMaximum = 2,
};

struct MemorySaverState {
  // False when the browser has no performance tuning manager yet.
  bool available = false;
  bool on = false;
  MemorySaverLevel level = MemorySaverLevel::kBalanced;
  // Set by policy: the page shows it and changes nothing.
  bool managed = false;
};

MemorySaverState GetMemorySaverState();

// Both do nothing when Memory Saver is managed.
void SetMemorySaverOn(bool on);
void SetMemorySaverLevel(MemorySaverLevel level);

}  // namespace boring

#endif  // COMPONENTS_BORING_PROTECTION_MEMORY_SAVER_H_
