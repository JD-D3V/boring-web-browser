// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_CORE_BORING_CAPABILITIES_H_
#define COMPONENTS_BORING_CORE_BORING_CAPABILITIES_H_

namespace boring {

// What this build can actually do, as opposed to what the code can do.
//
// Blocking scam and phishing sites needs a list of them, and a list we
// are allowed to hand to other people. The two feeds this browser was
// built against, URLhaus and OpenPhish, do not give that permission:
// their terms cover access, not redistribution through an installer and
// an update feed. See docs/release/URLHAUS_PERMISSION_REVIEW.md.
//
// So v1 ships no scam list. The matching code, the warning page and
// their tests all stay, because the gap is permission, not engineering,
// and this goes back on the day a feed we may redistribute is in place.
//
// While this is false the browser must not claim scam or phishing
// protection anywhere, and must not offer a control that implies it has
// any. Ad and tracker blocking and the popup and tab-under blocking are
// unaffected: those lists are redistributable and stay on.
inline constexpr bool kScamBlockingAvailable = false;

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
