// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_CORE_BORING_PREFS_H_
#define COMPONENTS_BORING_CORE_BORING_PREFS_H_

#include <string>

class GURL;
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
inline constexpr char kHideSponsoredResults[] = "boring.hide_sponsored_results";

// Keep the ad and tracker lists current by downloading newer ones.
// On by default: a list that is never replaced stops recognising what
// is being served this month. (No scam list ships in this version, see
// boring_capabilities.h.)
inline constexpr char kListUpdates[] = "boring.list_updates";

// Add a little noise to what pages can read back from canvas drawing,
// text measurement and element sizes, so those readings stop working as
// a fingerprint. Uses ungoogled-chromium's own switches (from Bromite),
// passed to each page's process for this profile. On by default.
inline constexpr char kFingerprintNoise[] = "boring.fingerprint_noise";

// Take known tracking parameters (fbclid, gclid and the rest of Brave's
// list) out of an address when one site sends a person to another.
// On by default.
inline constexpr char kStripTrackingParams[] = "boring.strip_tracking_params";

// Sites where the person turned ad, tracker and tab-under blocking off,
// from the toolbar shield. A list of site keys, see GetBlockingSite().
// Per profile and never synced: a site one person trusts on one
// computer is not a choice for their other devices.
inline constexpr char kBlockingOffSites[] = "boring.blocking_off_sites";

}  // namespace prefs

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry);

// True when Senior Safe Mode is on, from the pref or the command line
// switch --senior-safe-mode.
bool IsSeniorSafeMode(const PrefService* prefs);

// True when the command line switch turned Senior Safe Mode on. The
// settings page cannot turn it off then, and says so.
bool IsSeniorSafeModeForced();

// The key the per site switch is stored under: the registrable domain
// of the page (eTLD+1, counting private registries such as github.io),
// so news.example.co.uk and www.example.co.uk are one site and
// alice.github.io and bob.github.io are two. Scheme and port are
// ignored, so http and https share one answer. An IP address, localhost
// or an intranet name is its own site. Empty for anything that is not
// http or https, where the switch is not offered.
std::string GetBlockingSite(const GURL& url);

// True when blocking is off for the site of `top_frame_url`, the page
// in the tab. Always false with no prefs or no site.
bool IsBlockingOffForSite(const PrefService* prefs, const GURL& top_frame_url);

// Adds `site` (a key from GetBlockingSite()) to the list, or takes it
// off. Does nothing for an empty site.
void SetBlockingOffForSite(PrefService* prefs,
                           const std::string& site,
                           bool off);

}  // namespace boring

#endif  // COMPONENTS_BORING_CORE_BORING_PREFS_H_
