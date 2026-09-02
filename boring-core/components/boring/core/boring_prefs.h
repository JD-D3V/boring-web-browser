// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_CORE_BORING_PREFS_H_
#define COMPONENTS_BORING_CORE_BORING_PREFS_H_

class PrefRegistrySimple;
class PrefService;

namespace user_prefs {
class PrefRegistrySyncable;
}

namespace boring {

namespace prefs {

// One switch that makes every protection strict. Set once by the user
// or by a caregiver.
inline constexpr char kSeniorSafeMode[] = "boring.senior_safe_mode";

// Hide sponsored results on search pages instead of only labeling them.
inline constexpr char kHideSponsoredResults[] =
    "boring.hide_sponsored_results";

}  // namespace prefs

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry);

// True when Senior Safe Mode is on, from the pref or the command line
// switch --senior-safe-mode.
bool IsSeniorSafeMode(const PrefService* prefs);

}  // namespace boring

#endif  // COMPONENTS_BORING_CORE_BORING_PREFS_H_
