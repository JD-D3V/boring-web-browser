// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PRIVACY_DEBOUNCE_H_
#define COMPONENTS_BORING_PRIVACY_DEBOUNCE_H_

#include <optional>

#include "url/gurl.h"

namespace boring {

// Where a tracking redirect or an AMP cache page is really sending
// someone, or nothing when `url` is not one of those, or anything about
// it looks wrong.
//
// The rules are Brave's (debounce_brave.inc, MPL-2.0) and ours
// (debounce_boring.inc). A rule names the addresses it covers and where
// in them the real address sits: a query parameter, that parameter
// base64 encoded, or a part of the path. Redirectors that lead to other
// redirectors are followed to the end.
//
// An address comes out only when it is plain http or https, with a host
// and no user name or password, whatever the input said. A javascript:,
// data: or file: address, an address with control characters or
// backslashes, one that is not clean UTF-8 or is absurdly long, a
// parameter given twice, a chain that loops or runs past a few hops:
// each of these gives nothing, so the original address is used as it
// was. See debounce.cc for the full list.
std::optional<GURL> Debounce(const GURL& url);

}  // namespace boring

#endif  // COMPONENTS_BORING_PRIVACY_DEBOUNCE_H_
