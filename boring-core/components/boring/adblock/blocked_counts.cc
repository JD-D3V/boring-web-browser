// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/blocked_counts.h"

#include <map>
#include <string>
#include <string_view>
#include <vector>

#include "base/no_destructor.h"
#include "base/strings/string_util.h"
#include "base/synchronization/lock.h"
#include "url/gurl.h"
#include "url/origin.h"

namespace boring {

namespace {

// More pages than anyone has open. Past this an entry goes to make room,
// so the table cannot grow without end over a long session.
constexpr size_t kMaxPages = 256;

// Whole words, matched against the host and path split at anything that
// is not a letter or digit.
constexpr std::string_view kAdWords[] = {"ad", "ads", "banner", "banners",
                                         "sponsor", "sponsored"};
// Words matched by their start, so pagead2 and adservice both count.
constexpr std::string_view kCookiePrefixes[] = {
    "cookie", "consent", "onetrust", "trustarc", "usercentrics",
    "didomi", "osano",   "cmp",      "gdpr"};
constexpr std::string_view kAdPrefixes[] = {
    "pagead",      "adserv", "adsys",  "adsby",    "advert",
    "doubleclick", "adnxs",  "taboola", "outbrain", "criteo",
    "googlesyndication"};
constexpr std::string_view kTrackerPrefixes[] = {
    "track",  "analytic", "beacon", "pixel",   "telemetry", "metric",
    "stats",  "scorecard", "collect", "pageview", "quantserve", "hotjar",
    "segment", "mixpanel", "omniture", "newrelic"};

std::vector<std::string> Words(const GURL& url) {
  std::vector<std::string> words;
  std::string current;
  auto flush = [&] {
    if (!current.empty()) {
      words.push_back(std::move(current));
      current.clear();
    }
  };
  for (char c : base::ToLowerASCII(std::string(url.host()) + std::string(url.path()))) {
    if (base::IsAsciiAlpha(c) || base::IsAsciiDigit(c)) {
      current.push_back(c);
    } else {
      flush();
    }
  }
  flush();
  return words;
}

template <size_t N>
bool HasPrefix(const std::vector<std::string>& words,
               const std::string_view (&prefixes)[N]) {
  for (const std::string& word : words) {
    for (std::string_view prefix : prefixes) {
      if (base::StartsWith(word, prefix)) {
        return true;
      }
    }
  }
  return false;
}

bool HasWord(const std::vector<std::string>& words) {
  for (const std::string& word : words) {
    for (std::string_view ad : kAdWords) {
      if (word == ad) {
        return true;
      }
    }
  }
  return false;
}

struct Store {
  base::Lock lock;
  std::map<std::string, BlockedTotals> pages;
};

Store& GetStore() {
  static base::NoDestructor<Store> store;
  return *store;
}

// The key for a page, empty for anything that is not http or https.
std::string PageKey(const GURL& url) {
  if (!url.SchemeIsHTTPOrHTTPS()) {
    return std::string();
  }
  return url::Origin::Create(url).Serialize();
}

}  // namespace

uint32_t BlockedTotals::total() const {
  uint32_t sum = 0;
  for (uint32_t n : by_kind) {
    sum += n;
  }
  return sum;
}

BlockedKind ClassifyBlocked(const GURL& url, const std::string& request_type) {
  const std::vector<std::string> words = Words(url);
  if (HasPrefix(words, kCookiePrefixes)) {
    return BlockedKind::kCookieBanners;
  }
  if (HasWord(words) || HasPrefix(words, kAdPrefixes)) {
    return BlockedKind::kAds;
  }
  if (HasPrefix(words, kTrackerPrefixes)) {
    return BlockedKind::kTrackers;
  }
  if (request_type == "script") {
    return BlockedKind::kScripts;
  }
  if (request_type == "image" || request_type == "subdocument" ||
      request_type == "media" || request_type == "stylesheet") {
    return BlockedKind::kAds;
  }
  return BlockedKind::kTrackers;
}

// static
void BlockedCounts::Note(const GURL& top_frame_url,
                         const GURL& blocked_url,
                         const std::string& request_type) {
  const std::string key = PageKey(top_frame_url);
  if (key.empty()) {
    return;
  }
  const BlockedKind kind = ClassifyBlocked(blocked_url, request_type);
  Store& store = GetStore();
  base::AutoLock lock(store.lock);
  if (store.pages.size() >= kMaxPages && !store.pages.contains(key)) {
    store.pages.erase(store.pages.begin());
  }
  ++store.pages[key].by_kind[static_cast<int>(kind)];
}

// static
void BlockedCounts::Reset(const GURL& page_url) {
  const std::string key = PageKey(page_url);
  if (key.empty()) {
    return;
  }
  Store& store = GetStore();
  base::AutoLock lock(store.lock);
  store.pages.erase(key);
}

// static
BlockedTotals BlockedCounts::Get(const GURL& page_url) {
  const std::string key = PageKey(page_url);
  Store& store = GetStore();
  base::AutoLock lock(store.lock);
  auto it = store.pages.find(key);
  return it == store.pages.end() ? BlockedTotals() : it->second;
}

}  // namespace boring
