// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_LOOKALIKE_BRANDS_H_
#define COMPONENTS_BORING_SCAM_LOOKALIKE_BRANDS_H_

#include <string>
#include <string_view>

namespace boring {

// Finds the well known site that a plain-letter address is dressed up as.
//
// `registrable_domain` is the part of the address a person can buy: the
// site name plus its ending, lower case, as in "paypa1.com" or
// "paypa1.co.uk". Only the name before the first dot is looked at, so any
// ending counts.
//
// The name is rewritten the way the eye reads it: "rn" as m, "vv" as w, a
// zero as o, a one as l (or i). It matches when that reading is the name
// of a brand in lookalike_brands.inc and the name itself is not. Names
// are also taken apart at hyphens, and with their hyphens removed, so
// "paypa1-support" and "pay-pal" are caught too.
//
// Returns the brand's real domain ("paypal.com"), or an empty string.
// An address that is the brand itself ("paypal.org"), or only adds words
// to it ("paypal-support.com"), is left alone: that is a different kind of
// trouble, and warning about it would be wrong far too often.
//
// Names with letters of other alphabets (xn--) are not handled here:
// Chromium's own spoof checks do those. Plain standard C++, so
// tools/tests/test_lookalike.py can build it without Chromium.
std::string FindLookalikeBrand(std::string_view registrable_domain);

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_LOOKALIKE_BRANDS_H_
