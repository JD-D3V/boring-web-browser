// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PERFORMANCE_NEVER_SLEEP_SITES_H_
#define COMPONENTS_BORING_PERFORMANCE_NEVER_SLEEP_SITES_H_

#include <string>
#include <vector>

class GURL;
class PrefService;

namespace content {
class BrowserContext;
}

// Sites whose tabs are never frozen or put to sleep, kept in the
// profile pref boring.performance.never_sleep_sites. The toolbar shield
// and the Memory section on the Protection page change the list; the
// performance manager reads it (see GetNeverSleepPatterns()).
namespace boring::performance {

// The key a site is stored under: scheme://host, with :port only when
// it is not the scheme's default, so https://mail.example.com and
// http://localhost:8080. Empty for anything but http and https, where
// tabs are not frozen or put to sleep by site.
std::string GetNeverSleepKey(const GURL& url);

// True when tabs showing `url` are kept awake in this profile. The
// match is on the exact site: keeping example.com awake does not keep
// mail.example.com awake.
bool IsNeverSleep(content::BrowserContext* context, const GURL& url);

// Adds the site of `url` to the list, or takes it off. Does nothing for
// a url with no key.
void SetNeverSleep(content::BrowserContext* context,
                   const GURL& url,
                   bool never_sleep);

// The list as url_matcher patterns (the URLBlocklist format), for
// Chromium's discard opt-out list, which also stops freezing. Each
// pattern matches its site only, not the site's subdomains, the same
// answer IsNeverSleep() gives.
std::vector<std::string> GetNeverSleepPatterns(const PrefService* prefs);

}  // namespace boring::performance

#endif  // COMPONENTS_BORING_PERFORMANCE_NEVER_SLEEP_SITES_H_
