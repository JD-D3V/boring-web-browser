// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_CNAME_UNCLOAKER_H_
#define COMPONENTS_BORING_ADBLOCK_CNAME_UNCLOAKER_H_

#include <string>
#include <vector>

#include "base/functional/callback_forward.h"

class GURL;
class PrefService;

namespace boring {

// Finds the names a request's host is an alias of, so a tracker hiding
// behind a site's own subdomain (metrics.example.com, a CNAME to a
// tracking company) can be checked under its real name.
//
// Lookups go only through the renderer's own network context, the same
// resolver and the same DNS cache the request itself uses. And only while
// secure DNS is in secure mode, where that resolver is Quad9 over HTTPS
// with no fallback: with secure DNS off or automatic, nothing is looked
// up here at all, so this never sends a name anywhere the browser was not
// already sending it privately.
class CnameUncloaker {
 public:
  using AliasesCallback = base::OnceCallback<void(std::vector<std::string>)>;

  // Where the secure DNS mode is kept (local state). UI thread; the
  // first call wins, later ones are ignored.
  static void SetLocalState(PrefService* local_state);

  // Any sequence. Runs `callback` on the calling sequence with the names
  // the host of `url` is an alias of, leaving out the host itself and
  // names on the same site as it (uBO's cnameIgnore1stParty). Empty when
  // there is nothing to check: not http(s), an IP address, secure DNS not
  // in secure mode, the renderer gone, a lookup error, or no answer
  // within a few seconds.
  static void GetAliases(int render_process_id,
                         const GURL& url,
                         const GURL& initiator,
                         const GURL& top_frame_url,
                         AliasesCallback callback);
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_CNAME_UNCLOAKER_H_
