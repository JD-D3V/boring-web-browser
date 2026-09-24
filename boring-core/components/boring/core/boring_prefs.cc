// Copyright 2026 boring. BSD style license.

#include "components/boring/core/boring_prefs.h"

#include <string_view>

#include "base/command_line.h"
#include "base/values.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "net/base/registry_controlled_domains/registry_controlled_domain.h"
#include "url/gurl.h"

namespace boring {

namespace {
constexpr char kSeniorSafeModeSwitch[] = "senior-safe-mode";
}

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry) {
  registry->RegisterBooleanPref(prefs::kSeniorSafeMode, false);
  // Sponsored results are removed out of the box. Turning this off in
  // Protection leaves them in place with a quiet "Sponsored" chip.
  registry->RegisterBooleanPref(prefs::kHideSponsoredResults, true);
  registry->RegisterBooleanPref(prefs::kListUpdates, true);
  registry->RegisterBooleanPref(prefs::kFingerprintNoise, true);
  registry->RegisterBooleanPref(prefs::kStripTrackingParams, true);
  // No sync flag: stays on this profile on this computer.
  registry->RegisterListPref(prefs::kBlockingOffSites);
}

bool IsSeniorSafeMode(const PrefService* prefs) {
  if (IsSeniorSafeModeForced()) {
    return true;
  }
  return prefs && prefs->GetBoolean(prefs::kSeniorSafeMode);
}

bool IsSeniorSafeModeForced() {
  return base::CommandLine::ForCurrentProcess()->HasSwitch(
      kSeniorSafeModeSwitch);
}

std::string GetBlockingSite(const GURL& url) {
  if (!url.is_valid() || !url.SchemeIsHTTPOrHTTPS() || !url.has_host()) {
    return std::string();
  }
  std::string site = net::registry_controlled_domains::GetDomainAndRegistry(
      url, net::registry_controlled_domains::INCLUDE_PRIVATE_REGISTRIES);
  if (site.empty()) {
    site = url.HostNoBrackets();
  }
  return site;
}

bool IsBlockingOffForSite(const PrefService* prefs, const GURL& top_frame_url) {
  if (!prefs) {
    return false;
  }
  const std::string site = GetBlockingSite(top_frame_url);
  return !site.empty() &&
         prefs->GetList(prefs::kBlockingOffSites).contains(site);
}

void SetBlockingOffForSite(PrefService* prefs,
                           const std::string& site,
                           bool off) {
  if (!prefs || site.empty()) {
    return;
  }
  if (prefs->GetList(prefs::kBlockingOffSites).contains(site) == off) {
    return;
  }
  ScopedListPrefUpdate update(prefs, prefs::kBlockingOffSites);
  if (off) {
    update->Append(std::string_view(site));
  } else {
    update->EraseValue(base::Value(site));
  }
}

}  // namespace boring
