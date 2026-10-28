// Copyright 2026 boring. BSD style license.

#include "components/boring/core/boring_prefs.h"

#include <string>
#include <string_view>

#include "base/values.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "net/base/registry_controlled_domains/registry_controlled_domain.h"
#include "url/gurl.h"

namespace boring {

namespace {
// The all-in-one mode these three switches replaced. Registered only so
// MigrateObsoleteProfilePrefs() can read it once and clear it.
constexpr char kObsoleteModePref[] = "boring.senior_safe_mode";
}  // namespace

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry) {
  registry->RegisterBooleanPref(kObsoleteModePref, false);
  registry->RegisterBooleanPref(prefs::kStopTakeovers, true);
  registry->RegisterBooleanPref(prefs::kNoScamBypass, false);
  // Sponsored results are removed out of the box. Turning this off in
  // Protection leaves them in place with a quiet "Sponsored" chip.
  registry->RegisterBooleanPref(prefs::kHideSponsoredResults, true);
  registry->RegisterBooleanPref(prefs::kListUpdates, true);
  registry->RegisterBooleanPref(prefs::kFingerprintNoise, true);
  registry->RegisterBooleanPref(prefs::kStripTrackingParams, true);
  // No sync flag: stays on this profile on this computer.
  registry->RegisterListPref(prefs::kBlockingOffSites);
  registry->RegisterBooleanPref(prefs::kBoringHideCookieNotices, false);
  // No sync flag, like the list above.
  registry->RegisterListPref(prefs::kBoringRegionalLists);
  registry->RegisterIntegerPref(prefs::kBoringBlockingLevel, 0);
  registry->RegisterStringPref(prefs::kBoringCustomRules, std::string());
  registry->RegisterListPref(prefs::kBoringNeverSleepSites);
}

void MigrateObsoleteProfilePrefs(PrefService* prefs) {
  if (!prefs) {
    return;
  }
  if (prefs->GetBoolean(kObsoleteModePref)) {
    prefs->SetBoolean(prefs::kStopTakeovers, true);
    prefs->SetBoolean(prefs::kNoScamBypass, true);
    prefs->SetBoolean(prefs::kHideSponsoredResults, true);
  }
  prefs->ClearPref(kObsoleteModePref);
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
