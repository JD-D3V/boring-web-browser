// Copyright 2026 boring. BSD style license.

// The chrome/browser half of components/boring/privacy/privacy_state.h,
// built as part of chrome/browser (see its sources in
// chrome/browser/BUILD.gn). No global, nothing runs before main.

#include "components/boring/privacy/privacy_state.h"

#include <string>

#include "base/strings/string_util.h"
#include "chrome/browser/browser_process.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/common/pref_names.h"
#include "components/prefs/pref_service.h"
#include "content/public/browser/browser_context.h"

namespace boring {

PrivacyState GetPrivacyState(content::BrowserContext* context) {
  PrivacyState state;

  // Secure DNS is a machine-wide setting, kept in local state.
  PrefService* local_state = g_browser_process->local_state();
  if (local_state) {
    state.dns_mode = local_state->GetString(prefs::kDnsOverHttpsMode);
    state.dns_server = local_state->GetString(prefs::kDnsOverHttpsTemplates);
    state.dns_managed =
        local_state->IsManagedPreference(prefs::kDnsOverHttpsMode);
  }
  // Only Quad9's filtering service blocks threats; its unfiltered
  // address (dns10.quad9.net) does not, and neither does anyone else's
  // resolver as far as we know, so nothing else is credited with it.
  state.dns_filters_threats =
      state.dns_mode != "off" && !state.dns_mode.empty() &&
      base::StartsWith(state.dns_server, "https://dns.quad9.net/");

  Profile* profile = Profile::FromBrowserContext(context);
  const PrefService* prefs = profile ? profile->GetPrefs() : nullptr;
  if (prefs) {
    state.https_first = prefs->GetBoolean(prefs::kHttpsOnlyModeEnabled);
    state.https_balanced = prefs->GetBoolean(prefs::kHttpsFirstBalancedMode);
    state.webrtc_policy = prefs->GetString(prefs::kWebRTCIPHandlingPolicy);
  }
  return state;
}

}  // namespace boring
