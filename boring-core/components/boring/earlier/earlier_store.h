// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_EARLIER_EARLIER_STORE_H_
#define COMPONENTS_BORING_EARLIER_EARLIER_STORE_H_

#include <stddef.h>

#include <string>
#include <string_view>
#include <vector>

#include "base/time/time.h"
#include "url/gurl.h"

// Earlier tabs (ledger item 16): tabs not used for a day move off the tab
// strip into a list kept in the profile for 30 days. This is the plain data
// side: no views, no tabs, nothing that needs a browser.
namespace boring::earlier {

// The file's format number. A file with a bigger one came from a newer build
// and is only read, never written.
inline constexpr int kFileVersion = 1;
// Nothing more moves when the list is this long. Nothing is dropped to make
// room.
inline constexpr size_t kMaxEntries = 500;
// Back and forward pages kept with each entry, each side of the current one.
inline constexpr int kMaxNavigationsEachSide = 6;
// Longest title kept.
inline constexpr size_t kMaxTitleLength = 200;
// The file's name, beside "Preferences" in the profile folder.
inline constexpr char kFileName[] = "Boring Earlier Tabs";

// One page in a tab's history.
struct EarlierNav {
  GURL url;
  std::u16string title;
};

struct EarlierEntry {
  std::string id;
  base::Time moved;
  base::Time last_used;
  std::u16string title;
  GURL url;
  // Index into navigations of the page the tab was showing.
  int selected_index = 0;
  std::vector<EarlierNav> navigations;
};

// The times. Defaults are the product's: one day idle, 30 days kept, a check
// every 10 minutes, the first 10 minutes after start-up. Tests shorten them
// with command-line switches; see GetLimits().
struct EarlierLimits {
  base::TimeDelta idle = base::Days(1);
  base::TimeDelta keep = base::Days(30);
  base::TimeDelta check = base::Minutes(10);
  base::TimeDelta settle = base::Minutes(10);
};

inline constexpr char kIdleSecondsSwitch[] = "boring-earlier-idle-seconds";
inline constexpr char kKeepSecondsSwitch[] = "boring-earlier-keep-seconds";
inline constexpr char kCheckSecondsSwitch[] = "boring-earlier-check-seconds";
inline constexpr char kSettleSecondsSwitch[] = "boring-earlier-settle-seconds";
// Opens the Earlier pop-up as soon as the chip shows (tests).
inline constexpr char kOpenEarlierSwitch[] = "boring-open-earlier";

// The limits, with each time replaced by its switch when that switch holds a
// whole number of seconds from 1 up. They only shorten timers. Anything else
// leaves the product's value.
EarlierLimits GetLimits();

// Pure form of the above: switch values in, limits out. A null pointer means
// the switch is absent.
EarlierLimits LimitsFromSwitchValues(const std::string* idle,
                                     const std::string* keep,
                                     const std::string* check,
                                     const std::string* settle);

enum class ParseStatus {
  kOk,
  // Not our JSON, or a field of the wrong kind. Nothing is trusted.
  kCorrupt,
  // A newer build wrote it. Entries that can be read are returned; the
  // caller must not write.
  kNewer,
};

struct ParseResult {
  ParseStatus status = ParseStatus::kCorrupt;
  std::vector<EarlierEntry> entries;
};

// Reads the file's text. Entries that are not usable (no address, not http
// or https, no id, a duplicate id) are skipped, the rest are kept, and the
// list is cut at kMaxEntries. The file is data: nothing in it is trusted.
ParseResult ParseEarlierFile(std::string_view json);

// The file's text for these entries, version kFileVersion.
std::string SerializeEarlierFile(const std::vector<EarlierEntry>& entries);

// True for the only addresses that are ever kept or reopened.
bool IsKeepableUrl(const GURL& url);

// One line of plain text from a page title: control characters and runs of
// white space become one space, at most kMaxTitleLength characters.
std::u16string CleanTitle(std::u16string_view title);

// Entries moved `keep` or more before `now` are removed. Returns how many.
size_t RemoveExpired(std::vector<EarlierEntry>* entries,
                     base::Time now,
                     base::TimeDelta keep);

// The groups the pop-up puts entries in, by when the tab was last used.
enum class EarlierBucket { kYesterday, kThisWeek, kLastWeek, kOlder };

// Calendar days between the local day of `last_used` and the local day of
// `now`: 1 or less is Yesterday (a test with a shortened limit lands here
// too), up to 6 This week, up to 13 Last week, else Older.
EarlierBucket BucketFor(base::Time now, base::Time last_used);

const char16_t* BucketName(EarlierBucket bucket);

}  // namespace boring::earlier

#endif  // COMPONENTS_BORING_EARLIER_EARLIER_STORE_H_
