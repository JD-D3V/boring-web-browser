// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PRIVACY_TRACKING_PARAMS_H_
#define COMPONENTS_BORING_PRIVACY_TRACKING_PARAMS_H_

#include <optional>

#include "url/gurl.h"

namespace boring {

// The same address with known tracking parameters (fbclid, gclid,
// msclkid and the rest of Brave's list) taken out of the query, or
// nothing when there were none. Everything else about the address is
// left exactly as it was. See tracking_params.cc, MPL-2.0.
std::optional<GURL> StripTrackingParams(const GURL& url);

// Same registrable domain, the test for "this site linking to itself".
bool IsSameSite(const GURL& a, const GURL& b);

}  // namespace boring

#endif  // COMPONENTS_BORING_PRIVACY_TRACKING_PARAMS_H_
