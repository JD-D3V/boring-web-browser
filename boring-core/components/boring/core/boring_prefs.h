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

// "Stop screen takeovers": do not let a page lock the screen, keyboard
// or pointer behind fake alerts. On by default. The rules that read it
// come in a later change; for now this is the switch and its pref.
inline constexpr char kStopTakeovers[] = "boring.protection.stop_takeovers";

// "Warn about scam tricks": ask before a download of a remote access tool
// (AnyDesk, TeamViewer and the like) and stop a page from putting a
// command on the clipboard for the person to paste into Windows. On by
// default. See components/boring/guards.
inline constexpr char kWarnScamTricks[] = "boring.protection.warn_scam_tricks";

// "No way past scam warnings": the scam warning page has no "continue
// anyway". Off by default.
inline constexpr char kNoScamBypass[] = "boring.protection.no_scam_bypass";

// Look-alike sites (by eTLD+1) the person chose "Continue anyway" on, so
// the warning does not come back for them. Per profile, never synced and
// never sent anywhere. Not used in private windows.
inline constexpr char kLookalikeAllowedSites[] =
    "boring.protection.lookalike_allowed_sites";

// "Hide sponsored results": hide sponsored results on search pages
// instead of only labeling them. On by default.
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

// Skip tracking redirects and AMP cache pages: a link that goes through
// a known redirector opens the page it leads to instead (Brave's debounce
// rules, plus ours for Facebook, Google and similar). On by default.
inline constexpr char kSkipRedirects[] = "boring.privacy.skip_redirects";

// Sites where the person turned ad, tracker and tab-under blocking off,
// from the toolbar shield. A list of site keys, see GetBlockingSite().
// Per profile and never synced: a site one person trusts on one
// computer is not a choice for their other devices.
inline constexpr char kBlockingOffSites[] = "boring.blocking_off_sites";

// Block cookie banners: hide them with the Easylist Cookie List
// (boring\cookies.txt) and answer the ones we know how to with "reject"
// (components/boring/adblock/cosmetic/cookie_reject.js). On by default.
// Off leaves the cookie list out of use and every banner alone. Per
// profile, and a site with blocking turned off is left alone too.
inline constexpr char kBoringBlockCookieBanners[] =
    "boring.privacy.block_cookie_banners";

// Regional lists to block with as well, by id from
// boring\regional\index.json (see IsValidRegionalListId()). Empty by
// default. Per profile and never synced.
inline constexpr char kBoringRegionalLists[] = "boring.adblock.regional_lists";

// Blocking level: 0 standard, 1 aggressive (extra lists, see
// components/boring/adblock). Standard by default.
inline constexpr char kBoringBlockingLevel[] = "boring.adblock.level";

// The person's own filter rules, as typed on the Protection page, one
// per line. Standard permissions only: never trusted scriptlets.
inline constexpr char kBoringCustomRules[] = "boring.adblock.custom_rules";

// Sites (scheme://host) whose tabs are never frozen or put to sleep.
inline constexpr char kBoringNeverSleepSites[] =
    "boring.performance.never_sleep_sites";

// Native messaging hosts (apps on this computer) the person switched on,
// by host name. With no enterprise policy, a host that is not in this
// list is blocked: chrome_messaging_delegate.cc (patch
// native-hosts-check) reads it by this name. Per profile, never synced.
inline constexpr char kNativeHostsAllowed[] = "boring.native_hosts_allowed";

// Set once the list above has been started for the profile, see
// MigrateObsoleteProfilePrefs().
inline constexpr char kNativeHostsDecided[] = "boring.native_hosts_decided";

}  // namespace prefs

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry);

// Run once for each profile as it loads, from Chromium's
// MigrateObsoleteProfilePrefs(). A profile that had the old all-in-one
// mode on starts with all three switches it covered on, and the old
// pref is cleared either way. A profile that existed before native
// messaging hosts could be switched keeps the hosts registered now, a
// new one starts with none (see kNativeHostsAllowed).
void MigrateObsoleteProfilePrefs(PrefService* prefs);

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
