// Copyright 2026 boring. BSD style license.

// A copy of connections.json for the Protection page to read. Written
// by tools/check_connections.py --write, which CI runs in check mode, so
// the two cannot drift. Do not edit by hand. (Not listed in BUILD.gn on
// purpose: it is only included, and a BUILD.gn change would force a
// full regenerate of the build files.)

#ifndef COMPONENTS_BORING_PROTECTION_CONNECTIONS_DATA_H_
#define COMPONENTS_BORING_PROTECTION_CONNECTIONS_DATA_H_

namespace boring {

inline constexpr char kConnectionsJson[] = R"json({
  "comment": "Every connection the browser makes on its own. The Protection page, net_audit.py and tools/check_connections.py all read this file. After editing it run: python boring-core/tools/check_connections.py --write",
  "connections": [
    {
      "id": "secure_dns",
      "label": "Secure DNS",
      "hosts": ["dns.quad9.net"],
      "why": "Looks up site addresses privately. Also blocks known scam sites.",
      "off_note": "With this off, scam blocking gets weaker.",
      "switch": {
        "kind": "local_state",
        "pref": "dns_over_https.mode",
        "on": "secure",
        "off": "off"
      },
      "scenario": "idle",
      "code": [
        "chromium_src/chrome/browser/boring/privacy_bridge.cc",
        "patches/154/privacy-defaults.patch",
        "patches/privacy-defaults.patch"
      ]
    },
    {
      "id": "blocking_lists",
      "label": "Blocking and scam lists",
      "hosts": ["github.com"],
      "why": "Checks for newer lists about once a week. No account, no cookie.",
      "switch": {
        "kind": "profile",
        "pref": "boring.list_updates",
        "on": true,
        "off": false
      },
      "scenario": "lists",
      "code": [
        "components/boring/lists/list_updater.cc",
        "components/boring/lists/list_updater.h"
      ]
    },
    {
      "id": "browser_updates",
      "label": "Browser updates",
      "hosts": ["jd-d3v.github.io"],
      "why": "Asks once a day whether a newer version exists.",
      "switch": {
        "kind": "updater"
      },
      "scenario": "idle",
      "code": ["components/boring/update/browser_updater.cc"]
    },
    {
      "id": "web_store",
      "label": "Chrome Web Store",
      "hosts": ["clients2.google.com"],
      "why": "Only while you have store add-ons. Checks for their updates.",
      "switch": {
        "kind": "extension",
        "extension_id": "ocaahdebbfolfmndjeplogmgcagdmblk"
      },
      "scenario": "idle",
      "code": []
    }
  ]
})json";

}  // namespace boring

#endif  // COMPONENTS_BORING_PROTECTION_CONNECTIONS_DATA_H_
