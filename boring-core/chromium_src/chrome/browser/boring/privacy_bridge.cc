// Copyright 2026 boring. BSD style license.

// The chrome/browser half of components/boring/privacy/privacy_state.h,
// built as part of chrome/browser (see its sources in
// chrome/browser/BUILD.gn). No global, nothing runs before main.

#include "components/boring/privacy/privacy_state.h"

#include <string>

#include "base/strings/string_util.h"
#include "chrome/browser/browser_process.h"
#include "chrome/browser/net/secure_dns_config.h"
#include "chrome/browser/net/stub_resolver_config_reader.h"
#include "chrome/browser/net/system_network_context_manager.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/common/pref_names.h"
#include "components/prefs/pref_service.h"
#include "content/public/browser/browser_context.h"
#include "net/dns/public/dns_over_https_config.h"
#include "net/dns/public/secure_dns_mode.h"

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
  // True only when the lookup really goes to Quad9 and nowhere else: secure
  // mode (not automatic, which can fall back to the system resolver), Quad9
  // the only server, and no policy or parental control in the way.
  SecureDnsConfig config = SystemNetworkContextManager::
      GetStubResolverConfigReader()->GetSecureDnsConfiguration(false);
  const auto& servers = config.doh_servers().servers();
  state.dns_filters_threats =
      config.mode() == net::SecureDnsMode::kSecure &&
      config.management_mode() == SecureDnsConfig::ManagementMode::kNoOverride &&
      !state.dns_managed && servers.size() == 1 &&
      base::StartsWith(servers[0].server_template(),
                       "https://dns.quad9.net/") &&
      !(local_state &&
        local_state->IsManagedPreference(prefs::kDnsOverHttpsTemplates));

  Profile* profile = Profile::FromBrowserContext(context);
  const PrefService* prefs = profile ? profile->GetPrefs() : nullptr;
  if (prefs) {
    state.https_first = prefs->GetBoolean(prefs::kHttpsOnlyModeEnabled);
    state.https_balanced = prefs->GetBoolean(prefs::kHttpsFirstBalancedMode);
    state.webrtc_policy = prefs->GetString(prefs::kWebRTCIPHandlingPolicy);
  }
  return state;
}

void SetSecureDnsEnabled(bool enabled) {
  PrefService* local_state = g_browser_process->local_state();
  if (!local_state ||
      local_state->IsManagedPreference(prefs::kDnsOverHttpsMode)) {
    return;
  }
  local_state->SetString(prefs::kDnsOverHttpsMode,
                         enabled ? "secure" : "off");
}

}  // namespace boring
