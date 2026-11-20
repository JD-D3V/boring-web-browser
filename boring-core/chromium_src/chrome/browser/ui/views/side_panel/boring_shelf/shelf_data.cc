// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/side_panel/boring_shelf/shelf_data.h"

#include <memory>

#include "base/i18n/case_conversion.h"
#include "base/i18n/time_formatting.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/values.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/views/boring/boring_earlier_tabs_service.h"
#include "components/boring/newtab/newtab_ui.h"
#include "components/prefs/pref_service.h"
#include "components/url_formatter/elide_url.h"
#include "third_party/icu/source/common/unicode/unistr.h"
#include "third_party/icu/source/common/unicode/utf16.h"
#include "third_party/icu/source/i18n/unicode/datefmt.h"

namespace boring::shelf {

namespace {

constexpr size_t kMaxTitleLength = 200;

// The weekday as the locale writes it short ("Mon"), or an empty string.
std::u16string WeekdayName(base::Time then) {
  UErrorCode status = U_ZERO_ERROR;
  std::unique_ptr<icu::DateFormat> format(
      icu::DateFormat::createInstanceForSkeleton(icu::UnicodeString("EEE"),
                                                 status));
  if (U_FAILURE(status) || !format) {
    return std::u16string();
  }
  icu::UnicodeString out;
  format->format(then.InMillisecondsFSinceUnixEpoch(), out);
  return std::u16string(
      reinterpret_cast<const char16_t*>(out.getBuffer()),
      static_cast<size_t>(out.length()));
}

// What the new tab page puts in a pinned site's mark: the first character of
// its name, upper case, or "?" when there is no name. The page does it with
// (name || "?").charAt(0).toUpperCase(); this takes a whole character where
// a name starts with a surrogate pair.
std::u16string TileMark(const std::u16string& name) {
  if (name.empty()) {
    return u"?";
  }
  const size_t length =
      (name.size() > 1 && U16_IS_LEAD(name[0]) && U16_IS_TRAIL(name[1])) ? 2
                                                                         : 1;
  return base::i18n::ToUpper(std::u16string_view(name).substr(0, length));
}

}  // namespace

std::u16string ShelfTitle(std::u16string_view title, const GURL& url) {
  // A page controls its title, so it is flattened to one plain line: every
  // run of white space, new lines and tabs included, becomes one space, and
  // control characters go. Bidi marks are left to the label, which handles
  // direction the way the tab strip does.
  std::u16string text;
  text.reserve(title.size());
  for (char16_t c : title) {
    if (c < 0x20 || c == 0x7f) {
      text.push_back(u' ');
    } else {
      text.push_back(c);
    }
  }
  text = std::u16string(base::CollapseWhitespace(text, true));
  if (text.size() > kMaxTitleLength) {
    text.resize(kMaxTitleLength);
  }
  if (text.empty()) {
    text = url_formatter::FormatUrlForSecurityDisplay(
        url, url_formatter::SchemeDisplay::OMIT_HTTP_AND_HTTPS);
  }
  return text;
}

std::u16string TabCountText(size_t count) {
  return count == 1 ? u"1 tab"
                    : base::NumberToString16(count) + u" tabs";
}

std::u16string ShowAllText(size_t count) {
  return u"Show all " + base::NumberToString16(count);
}

std::u16string AgeText(base::Time now, base::Time then) {
  if (then.is_null()) {
    return std::u16string();
  }
  const base::Time today = now.LocalMidnight();
  if (then >= today) {
    return u"Today";
  }
  if (then >= today - base::Days(6)) {
    return WeekdayName(then);
  }
  return base::TimeFormatShortDate(then);
}

EarlierState GetEarlierState(Profile* profile) {
  // boring: item 16. The profile's Earlier list; off and empty for a private
  // or guest window, which have none.
  EarlierState state;
  boring::earlier::EarlierTabsService* service =
      boring::earlier::EarlierTabsService::Get(profile);
  if (!service) {
    return state;
  }
  state.enabled = service->IsEnabled();
  state.total = service->count();
  const base::Time now = base::Time::Now();
  for (const boring::earlier::EarlierEntry& entry : service->entries()) {
    if (state.newest.size() >= kMaxEarlierRows) {
      break;
    }
    ShelfItem item;
    item.title = ShelfTitle(entry.title, entry.url);
    item.meta = AgeText(now, entry.last_used);
    item.icon = &kBoringDocIcon;
    item.url = entry.url;
    item.kind = ShelfKind::kEarlier;
    item.id = entry.id;
    state.newest.push_back(std::move(item));
  }
  return state;
}

std::vector<ShelfItem> PinnedItems(Profile* profile) {
  std::vector<ShelfItem> items;
  const base::ListValue& list =
      profile->GetPrefs()->GetList(boring::kNewTabShortcutsPref);
  for (const base::Value& entry : list) {
    if (items.size() >= kMaxPinned) {
      break;
    }
    const base::DictValue* dict = entry.GetIfDict();
    if (!dict) {
      continue;
    }
    const std::string* url_text = dict->FindString("url");
    if (!url_text) {
      continue;
    }
    GURL url(*url_text);
    // The list is ours, but it is data in a file: only web addresses open.
    if (!url.is_valid() || !url.SchemeIsHTTPOrHTTPS()) {
      continue;
    }
    const std::string* title = dict->FindString("title");
    ShelfItem item;
    item.title =
        ShelfTitle(title ? base::UTF8ToUTF16(*title) : std::u16string(), url);
    item.icon = &kBoringLinkIcon;
    item.mark = TileMark(item.title);
    item.url = url;
    item.kind = ShelfKind::kPinned;
    items.push_back(std::move(item));
  }
  return items;
}

}  // namespace boring::shelf
