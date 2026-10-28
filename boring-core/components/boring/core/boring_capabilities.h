// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_CORE_BORING_CAPABILITIES_H_
#define COMPONENTS_BORING_CORE_BORING_CAPABILITIES_H_

namespace boring {

// What this build can actually do, as opposed to what the code can do.
//
// Blocking scam and phishing sites needs a list of them, and a list we
// are allowed to hand to other people. The two feeds this browser was
// first built against, URLhaus and OpenPhish, do not give that
// permission (docs/release/URLHAUS_PERMISSION_REVIEW.md). Two others do:
// CERT Polska's Warning List and DurableNapkin's Scam Blocklist, whose
// terms are written down in tools/get_scamlist.py, and the list built
// from them ships beside the browser with their notices.
//
// Coverage is thin outside Poland, so the browser must not describe
// this as complete protection. If the list is missing the service
// reports a failure and the shield says so; ad and tracker blocking and
// the popup and tab-under blocking do not depend on it.
inline constexpr bool kScamBlockingAvailable = true;

// Whether a downloaded copy of this browser can play DRM video.
//
// Widevine support is compiled in (enable_widevine=true), but the CDM
// itself is a separate proprietary binary that Chrome fetches from
// Google at run time. We do not talk to that service, and
// check_package.py refuses to ship the CDM, so a copy somebody
// downloads has none and no way to get one. Netflix, Spotify and
// anything else behind Widevine will not play.
//
// v1 states that as a known limitation rather than implying streaming
// works. Turning this on means a build that really can obtain a CDM,
// and smoke_widevine.py checks the claim both ways: a build that says
// it has DRM must play it, and a build that says it has none must not
// quietly have it.
inline constexpr bool kDrmPlaybackAvailable = false;

}  // namespace boring

#endif  // COMPONENTS_BORING_CORE_BORING_CAPABILITIES_H_
