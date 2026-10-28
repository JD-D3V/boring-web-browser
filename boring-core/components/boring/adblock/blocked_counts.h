// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_BLOCKED_COUNTS_H_
#define COMPONENTS_BORING_ADBLOCK_BLOCKED_COUNTS_H_

#include <array>
#include <cstdint>
#include <string>

class GURL;

namespace boring {

// What a blocked request was, in words a person would use. Worked out
// from the request, since the filter engine only says block or not.
enum class BlockedKind {
  kAds,
  kTrackers,
  kCookieBanners,
  kScripts,
};
inline constexpr int kBlockedKindCount = 4;

// How many requests were blocked on the current page, by kind.
struct BlockedTotals {
  std::array<uint32_t, kBlockedKindCount> by_kind{};

  uint32_t total() const;
  uint32_t of(BlockedKind kind) const {
    return by_kind[static_cast<int>(kind)];
  }
};

// Guesses the kind from the address and the request type (the filter
// list names: script, image, subdocument, xmlhttprequest, ping, ...).
// Words in the host and path decide first: consent and cookie vendors,
// then ad networks, then trackers. What is left goes by type: a script
// is a script, a picture or frame is an ad, anything else a tracker.
BlockedKind ClassifyBlocked(const GURL& url, const std::string& request_type);

// Counts for the pages being shown, keyed by the page's origin, so the
// toolbar shield can say what was blocked on the page in the tab. Both
// places that block (the browser side throttle and the answers to
// renderers) note here from any thread. Two tabs on the same origin
// share one count.
class BlockedCounts {
 public:
  // Notes one blocked request for the page at `top_frame_url`. Does
  // nothing when that is not an http(s) page.
  static void Note(const GURL& top_frame_url,
                   const GURL& blocked_url,
                   const std::string& request_type);

  // A document is starting to load at `page_url`: its count starts again.
  static void Reset(const GURL& page_url);

  // The count so far for the page at `page_url`.
  static BlockedTotals Get(const GURL& page_url);
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_BLOCKED_COUNTS_H_
