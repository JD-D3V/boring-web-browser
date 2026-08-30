// Copyright 2026 boring. BSD style license.

#include "components/boring/core/boring_prefs.h"

#include "base/command_line.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_service.h"

namespace boring {

namespace {
constexpr char kSeniorSafeModeSwitch[] = "senior-safe-mode";
}

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry) {
  registry->RegisterBooleanPref(prefs::kSeniorSafeMode, false);
  registry->RegisterBooleanPref(prefs::kHideSponsoredResults, false);
}

bool IsSeniorSafeMode(const PrefService* prefs) {
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          kSeniorSafeModeSwitch)) {
    return true;
  }
  return prefs && prefs->GetBoolean(prefs::kSeniorSafeMode);
}

}  // namespace boring
