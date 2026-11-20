// Copyright 2026 boring. BSD style license.

#include "components/boring/earlier/earlier_store.h"

#include <algorithm>
#include <optional>
#include <set>
#include <utility>

#include "base/command_line.h"
#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/values.h"

namespace boring::earlier {

namespace {

std::string TimeText(base::Time t) {
  return base::NumberToString(t.InMillisecondsSinceUnixEpoch());
}

// Times are kept as decimal text of milliseconds since 1970: a JSON number
// would lose digits above 2^53 and base::Value has no 64 bit integer.
bool ReadTime(const base::DictValue& dict, const char* key, base::Time* out) {
  const std::string* text = dict.FindString(key);
  int64_t ms = 0;
  if (!text || !base::StringToInt64(*text, &ms) || ms <= 0) {
    return false;
  }
  *out = base::Time::FromMillisecondsSinceUnixEpoch(ms);
  return true;
}

std::optional<EarlierEntry> ReadEntry(const base::DictValue& dict) {
  EarlierEntry entry;
  const std::string* id = dict.FindString("id");
  const std::string* url_text = dict.FindString("url");
  if (!id || id->empty() || id->size() > 64 || !url_text) {
    return std::nullopt;
  }
  entry.id = *id;
  entry.url = GURL(*url_text);
  if (!IsKeepableUrl(entry.url) || !ReadTime(dict, "moved", &entry.moved) ||
      !ReadTime(dict, "last_used", &entry.last_used)) {
    return std::nullopt;
  }
  const std::string* title = dict.FindString("title");
  entry.title =
      CleanTitle(title ? base::UTF8ToUTF16(*title) : std::u16string());
  const base::ListValue* navs = dict.FindList("navigations");
  if (navs) {
    for (const base::Value& value : *navs) {
      if (entry.navigations.size() >=
          static_cast<size_t>(2 * kMaxNavigationsEachSide + 1)) {
        break;
      }
      const base::DictValue* nav = value.GetIfDict();
      const std::string* nav_url = nav ? nav->FindString("url") : nullptr;
      if (!nav_url) {
        continue;
      }
      EarlierNav item;
      item.url = GURL(*nav_url);
      if (!IsKeepableUrl(item.url)) {
        continue;
      }
      const std::string* nav_title = nav->FindString("title");
      item.title = CleanTitle(
          nav_title ? base::UTF8ToUTF16(*nav_title) : std::u16string());
      entry.navigations.push_back(std::move(item));
    }
  }
  if (entry.navigations.empty()) {
    // Only the page itself is known: reopening gives a tab with no history.
    entry.navigations.push_back({entry.url, entry.title});
    entry.selected_index = 0;
  } else {
    const std::optional<int> selected = dict.FindInt("selected_index");
    const int last = static_cast<int>(entry.navigations.size()) - 1;
    entry.selected_index = std::clamp(selected.value_or(last), 0, last);
  }
  return entry;
}

std::optional<int64_t> SecondsFromSwitch(const std::string* text) {
  int64_t seconds = 0;
  if (!text || !base::StringToInt64(*text, &seconds) || seconds < 1 ||
      seconds > 100000000) {
    return std::nullopt;
  }
  return seconds;
}

}  // namespace

EarlierLimits LimitsFromSwitchValues(const std::string* idle,
                                     const std::string* keep,
                                     const std::string* check,
                                     const std::string* settle) {
  EarlierLimits limits;
  if (auto s = SecondsFromSwitch(idle)) {
    limits.idle = base::Seconds(*s);
  }
  if (auto s = SecondsFromSwitch(keep)) {
    limits.keep = base::Seconds(*s);
  }
  if (auto s = SecondsFromSwitch(check)) {
    limits.check = base::Seconds(*s);
  }
  if (auto s = SecondsFromSwitch(settle)) {
    limits.settle = base::Seconds(*s);
  }
  return limits;
}

EarlierLimits GetLimits() {
  const base::CommandLine* line = base::CommandLine::ForCurrentProcess();
  auto value = [&](const char* name) -> std::optional<std::string> {
    if (!line->HasSwitch(name)) {
      return std::nullopt;
    }
    return line->GetSwitchValueASCII(name);
  };
  const auto idle = value(kIdleSecondsSwitch);
  const auto keep = value(kKeepSecondsSwitch);
  const auto check = value(kCheckSecondsSwitch);
  const auto settle = value(kSettleSecondsSwitch);
  return LimitsFromSwitchValues(idle ? &*idle : nullptr,
                                keep ? &*keep : nullptr,
                                check ? &*check : nullptr,
                                settle ? &*settle : nullptr);
}

bool IsKeepableUrl(const GURL& url) {
  return url.is_valid() && url.SchemeIsHTTPOrHTTPS();
}

std::u16string CleanTitle(std::u16string_view title) {
  std::u16string text;
  text.reserve(title.size());
  for (char16_t c : title) {
    text.push_back((c < 0x20 || c == 0x7f) ? u' ' : c);
  }
  text = std::u16string(base::CollapseWhitespace(text, true));
  if (text.size() > kMaxTitleLength) {
    text.resize(kMaxTitleLength);
  }
  return text;
}

ParseResult ParseEarlierFile(std::string_view json) {
  ParseResult result;
  std::optional<base::DictValue> root =
      base::JSONReader::ReadDict(json, base::JSON_PARSE_RFC);
  if (!root) {
    return result;
  }
  const std::optional<int> version = root->FindInt("version");
  const base::ListValue* list = root->FindList("entries");
  if (!version || *version < 1 || !list) {
    return result;
  }
  std::set<std::string> seen;
  for (const base::Value& value : *list) {
    if (result.entries.size() >= kMaxEntries) {
      break;
    }
    const base::DictValue* dict = value.GetIfDict();
    if (!dict) {
      continue;
    }
    std::optional<EarlierEntry> entry = ReadEntry(*dict);
    if (!entry || !seen.insert(entry->id).second) {
      continue;
    }
    result.entries.push_back(std::move(*entry));
  }
  result.status =
      *version > kFileVersion ? ParseStatus::kNewer : ParseStatus::kOk;
  return result;
}

std::string SerializeEarlierFile(const std::vector<EarlierEntry>& entries) {
  base::ListValue list;
  for (const EarlierEntry& entry : entries) {
    base::DictValue dict;
    dict.Set("id", entry.id);
    dict.Set("moved", TimeText(entry.moved));
    dict.Set("last_used", TimeText(entry.last_used));
    dict.Set("title", base::UTF16ToUTF8(entry.title));
    dict.Set("url", entry.url.spec());
    dict.Set("selected_index", entry.selected_index);
    base::ListValue navs;
    for (const EarlierNav& nav : entry.navigations) {
      base::DictValue item;
      item.Set("url", nav.url.spec());
      item.Set("title", base::UTF16ToUTF8(nav.title));
      navs.Append(std::move(item));
    }
    dict.Set("navigations", std::move(navs));
    list.Append(std::move(dict));
  }
  base::DictValue root;
  root.Set("version", kFileVersion);
  root.Set("entries", std::move(list));
  return base::WriteJson(root).value_or(std::string());
}

size_t RemoveExpired(std::vector<EarlierEntry>* entries,
                     base::Time now,
                     base::TimeDelta keep) {
  const size_t before = entries->size();
  std::erase_if(*entries,
                [&](const EarlierEntry& e) { return now - e.moved >= keep; });
  return before - entries->size();
}

EarlierBucket BucketFor(base::Time now, base::Time last_used) {
  const int days =
      ((now.LocalMidnight() - last_used.LocalMidnight()) + base::Hours(12))
          .InDays();
  if (days <= 1) {
    return EarlierBucket::kYesterday;
  }
  if (days <= 6) {
    return EarlierBucket::kThisWeek;
  }
  if (days <= 13) {
    return EarlierBucket::kLastWeek;
  }
  return EarlierBucket::kOlder;
}

const char16_t* BucketName(EarlierBucket bucket) {
  switch (bucket) {
    case EarlierBucket::kYesterday:
      return u"Yesterday";
    case EarlierBucket::kThisWeek:
      return u"This week";
    case EarlierBucket::kLastWeek:
      return u"Last week";
    case EarlierBucket::kOlder:
      return u"Older";
  }
  return u"";
}

}  // namespace boring::earlier
