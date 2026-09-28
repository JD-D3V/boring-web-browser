// Copyright 2026 boring. BSD style license.

#include "components/boring/performance/never_sleep_sites.h"

#include <string>
#include <string_view>
#include <vector>

#include "base/values.h"
#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "url/gurl.h"
#include "url/origin.h"

namespace boring::performance {

namespace {

PrefService* PrefsFor(content::BrowserContext* context) {
  return context ? user_prefs::UserPrefs::Get(context) : nullptr;
}

}  // namespace

std::string GetNeverSleepKey(const GURL& url) {
  if (!url.is_valid() || !url.SchemeIsHTTPOrHTTPS()) {
    return std::string();
  }
  // An origin already drops a default port and keeps any other one.
  return url::Origin::Create(url).Serialize();
}

bool IsNeverSleep(content::BrowserContext* context, const GURL& url) {
  const PrefService* prefs = PrefsFor(context);
  const std::string key = GetNeverSleepKey(url);
  return prefs && !key.empty() &&
         prefs->GetList(prefs::kBoringNeverSleepSites).contains(key);
}

void SetNeverSleep(content::BrowserContext* context,
                   const GURL& url,
                   bool never_sleep) {
  PrefService* prefs = PrefsFor(context);
  const std::string key = GetNeverSleepKey(url);
  if (!prefs || key.empty()) {
    return;
  }
  if (prefs->GetList(prefs::kBoringNeverSleepSites).contains(key) ==
      never_sleep) {
    return;
  }
  ScopedListPrefUpdate update(prefs, prefs::kBoringNeverSleepSites);
  if (never_sleep) {
    update->Append(std::string_view(key));
  } else {
    update->EraseValue(base::Value(key));
  }
}

std::vector<std::string> GetNeverSleepPatterns(const PrefService* prefs) {
  std::vector<std::string> patterns;
  if (!prefs) {
    return patterns;
  }
  for (const base::Value& entry :
       prefs->GetList(prefs::kBoringNeverSleepSites)) {
    const std::string* site = entry.GetIfString();
    if (!site) {
      continue;
    }
    // Only entries written the way SetNeverSleep() writes them, so a
    // hand-edited profile cannot slip in a wildcard that keeps every
    // tab awake.
    const GURL url(*site);
    if (GetNeverSleepKey(url) != *site) {
      continue;
    }
    // A leading dot on the host means this host only, no subdomains.
    std::string pattern = url.GetScheme() + "://." + url.GetHost();
    if (url.has_port()) {
      pattern += ":" + url.GetPort();
    }
    patterns.push_back(std::move(pattern));
  }
  return patterns;
}

}  // namespace boring::performance
