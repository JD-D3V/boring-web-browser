// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PRIVACY_PRIVACY_STATE_H_
#define COMPONENTS_BORING_PRIVACY_PRIVACY_STATE_H_

#include <string>

namespace content {
class BrowserContext;
}

namespace boring {

// What the browser's own settings say right now about the protections
// that live in Chromium rather than in our code, read fresh each time
// so the Protection page never shows a default the person has changed.
struct PrivacyState {
  // Secure DNS: "off", "automatic" or "secure", and the server address.
  std::string dns_mode;
  std::string dns_server;
  // True when the resolver in use is Quad9, whose filtering is what
  // blocks known malware and phishing domains.
  bool dns_filters_threats = false;
  // Set by an administrator or policy, so the person cannot change it.
  bool dns_managed = false;

  // "Always use secure connections": on, and balanced or strict.
  bool https_first = false;
  bool https_balanced = false;

  // WebRTC IP handling, Chromium's own names, e.g.
  // "disable_non_proxied_udp".
  std::string webrtc_policy;
};

// Declared here for our pages, defined in
// chrome/browser/boring/privacy_bridge.cc, which is built into
// chrome/browser, for the same reason as search_engines.h: the prefs it
// reads are named in chrome/common, which components/boring may not
// depend on.
PrivacyState GetPrivacyState(content::BrowserContext* context);

}  // namespace boring

#endif  // COMPONENTS_BORING_PRIVACY_PRIVACY_STATE_H_
