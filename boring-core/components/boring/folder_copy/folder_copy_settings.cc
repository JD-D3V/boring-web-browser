// Copyright 2026 boring. BSD style license.

#include "components/boring/folder_copy/folder_copy_settings.h"

#include <algorithm>
#include <set>
#include <string>
#include <utility>

#include "base/json/json_reader.h"
#include "base/json/json_writer.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/string_util.h"
#include "components/boring/ai/ai_prefs.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/lists/list_paths.h"
#include "components/prefs/pref_service.h"

namespace boring::folder_copy {

namespace {

enum class Kind {
  kSwitch,    // on is the protective side
  kLevel,     // 0 standard, 1 aggressive
  kText,      // the person's own filter rules
  kSites,     // a list of site names
  kRegional,  // a list of regional list ids
  kProvider,  // the AI provider name, never a key
};

struct Setting {
  const char* pref;
  const char* label;
  Kind kind;
};

// The whole list. Anything not here never reaches the file and is ignored
// when read.
constexpr Setting kSettings[] = {
    {prefs::kStopTakeovers, "Stop screen takeovers", Kind::kSwitch},
    {prefs::kWarnScamTricks, "Warn about scam tricks", Kind::kSwitch},
    {prefs::kNoScamBypass, "No way past scam warnings", Kind::kSwitch},
    {prefs::kHideSponsoredResults, "Hide sponsored results", Kind::kSwitch},
    {prefs::kListUpdates, "Keep blocking lists current", Kind::kSwitch},
    {prefs::kFingerprintNoise, "Fingerprint noise", Kind::kSwitch},
    {prefs::kStripTrackingParams, "Remove tracking parameters",
     Kind::kSwitch},
    {prefs::kSkipRedirects, "Skip tracking redirects", Kind::kSwitch},
    {prefs::kBoringBlockCookieBanners, "Block cookie banners", Kind::kSwitch},
    {prefs::kBoringRegionalLists, "Regional lists", Kind::kRegional},
    {prefs::kBoringBlockingLevel, "Blocking level", Kind::kLevel},
    {prefs::kBoringCustomRules, "My filter rules", Kind::kText},
    {prefs::kBoringNeverSleepSites, "Sites that never sleep", Kind::kSites},
    {ai::prefs::kProvider, "AI assistant", Kind::kProvider},
};

constexpr size_t kMaxTextBytes = 32 * 1024;
constexpr size_t kMaxListEntries = 500;
constexpr size_t kMaxEntryBytes = 253;
constexpr int kFileVersion = 1;

constexpr struct {
  const char* id;
  const char* name;
} kProviders[] = {
    {"off", "Off"},           {"ollama", "Ollama"},
    {"gemini", "Gemini"},     {"openai", "OpenAI"},
    {"openrouter", "OpenRouter"}, {"groq", "Groq"},
};

const Setting* Find(std::string_view pref) {
  for (const Setting& setting : kSettings) {
    if (pref == setting.pref) {
      return &setting;
    }
  }
  return nullptr;
}

bool IsPlainName(const std::string& name) {
  return !name.empty() && name.size() <= kMaxEntryBytes &&
         std::all_of(name.begin(), name.end(), [](unsigned char c) {
           return c > 0x20 && c < 0x7f;
         });
}

bool IsValid(const Setting& setting, const base::Value& value) {
  switch (setting.kind) {
    case Kind::kSwitch:
      return value.is_bool();
    case Kind::kLevel:
      return value.is_int() &&
             (value.GetInt() == 0 || value.GetInt() == 1);
    case Kind::kText:
      return value.is_string() && value.GetString().size() <= kMaxTextBytes;
    case Kind::kSites:
    case Kind::kRegional: {
      if (!value.is_list() || value.GetList().size() > kMaxListEntries) {
        return false;
      }
      for (const base::Value& item : value.GetList()) {
        if (!item.is_string() || !IsPlainName(item.GetString())) {
          return false;
        }
        if (setting.kind == Kind::kRegional &&
            !IsValidRegionalListId(item.GetString())) {
          return false;
        }
      }
      return true;
    }
    case Kind::kProvider:
      if (!value.is_string()) {
        return false;
      }
      return std::any_of(std::begin(kProviders), std::end(kProviders),
                         [&](const auto& p) {
                           return value.GetString() == p.id;
                         });
  }
  return false;
}

std::string CountOf(size_t n, const char* one, const char* many) {
  return base::NumberToString(n) + " " + (n == 1 ? one : many);
}

std::string Describe(const Setting& setting, const base::Value& value) {
  switch (setting.kind) {
    case Kind::kSwitch:
      return value.GetBool() ? "On" : "Off";
    case Kind::kLevel:
      return value.GetInt() == 1 ? "Aggressive" : "Standard";
    case Kind::kText: {
      const std::string& text = value.GetString();
      size_t lines = 0;
      size_t start = 0;
      while (start <= text.size()) {
        size_t end = text.find('\n', start);
        if (end == std::string::npos) {
          end = text.size();
        }
        if (text.find_first_not_of(" \t\r", start) < end) {
          ++lines;
        }
        start = end + 1;
      }
      return CountOf(lines, "rule", "rules");
    }
    case Kind::kSites:
      return CountOf(value.GetList().size(), "site", "sites");
    case Kind::kRegional:
      return CountOf(value.GetList().size(), "list", "lists");
    case Kind::kProvider:
      for (const auto& p : kProviders) {
        if (value.GetString() == p.id) {
          return p.name;
        }
      }
      break;
  }
  return std::string();
}

// Filter rules that switch blocking off: a network exception (@@) or a
// cosmetic or scriptlet exception (#@#). Only lines that are new count.
bool AddsException(const std::string& from, const std::string& to) {
  auto lines = [](const std::string& text) {
    std::set<std::string> out;
    size_t start = 0;
    while (start <= text.size()) {
      size_t end = text.find('\n', start);
      if (end == std::string::npos) {
        end = text.size();
      }
      out.insert(std::string(base::TrimWhitespaceASCII(
          text.substr(start, end - start), base::TRIM_ALL)));
      start = end + 1;
    }
    return out;
  };
  const std::set<std::string> old_lines = lines(from);
  for (const std::string& line : lines(to)) {
    if (!old_lines.count(line) &&
        (line.rfind("@@", 0) == 0 || line.find("#@") != std::string::npos)) {
      return true;
    }
  }
  return false;
}

bool Weakens(const Setting& setting,
             const base::Value& from,
             const base::Value& to) {
  if (setting.kind == Kind::kSwitch) {
    return from.GetBool() && !to.GetBool();
  }
  if (setting.kind == Kind::kLevel) {
    return from.GetInt() == 1 && to.GetInt() == 0;
  }
  if (setting.kind == Kind::kText) {
    return AddsException(from.GetString(), to.GetString());
  }
  return false;
}

}  // namespace

std::vector<std::string> SettingNames() {
  std::vector<std::string> names;
  for (const Setting& setting : kSettings) {
    names.push_back(setting.pref);
  }
  return names;
}

std::string BuildSettingsFile(const PrefService* prefs) {
  base::DictValue settings;
  if (prefs) {
    for (const Setting& setting : kSettings) {
      const base::Value* value = prefs->GetUserPrefValue(setting.pref);
      if (value && IsValid(setting, *value)) {
        settings.Set(setting.pref, value->Clone());
      }
    }
  }
  base::DictValue file;
  file.Set("version", kFileVersion);
  file.Set("settings", std::move(settings));
  return base::WriteJsonWithOptions(file, base::JSONWriter::OPTIONS_PRETTY_PRINT)
      .value_or(std::string());
}

std::optional<base::DictValue> ParseSettingsFile(std::string_view text) {
  if (text.size() > kMaxSettingsFileBytes) {
    return std::nullopt;
  }
  std::optional<base::DictValue> file =
      base::JSONReader::ReadDict(text, base::JSON_PARSE_RFC);
  if (!file || file->FindInt("version") != kFileVersion) {
    return std::nullopt;
  }
  const base::DictValue* settings = file->FindDict("settings");
  if (!settings) {
    return std::nullopt;
  }
  base::DictValue valid;
  for (const auto [name, value] : *settings) {
    const Setting* setting = Find(name);
    if (setting && IsValid(*setting, value)) {
      valid.Set(name, value.Clone());
    }
  }
  return valid;
}

std::vector<SettingChange> DiffSettings(const PrefService* prefs,
                                        const base::DictValue& values) {
  std::vector<SettingChange> changes;
  if (!prefs) {
    return changes;
  }
  for (const auto [name, value] : values) {
    const Setting* setting = Find(name);
    const PrefService::Preference* pref = prefs->FindPreference(name);
    if (!setting || !pref || !IsValid(*setting, value) ||
        *pref->GetValue() == value) {
      continue;
    }
    SettingChange change;
    change.pref = name;
    change.label = setting->label;
    change.from = Describe(*setting, *pref->GetValue());
    change.to = Describe(*setting, value);
    change.weakens = Weakens(*setting, *pref->GetValue(), value);
    if (setting->kind == Kind::kText && change.weakens) {
      change.to += ", and some turn blocking off for certain sites";
    }
    changes.push_back(std::move(change));
  }
  std::stable_sort(changes.begin(), changes.end(),
                   [](const SettingChange& a, const SettingChange& b) {
                     return a.weakens && !b.weakens;
                   });
  return changes;
}

int ApplySettings(PrefService* prefs, const base::DictValue& values) {
  int applied = 0;
  if (!prefs) {
    return applied;
  }
  for (const SettingChange& change : DiffSettings(prefs, values)) {
    const base::Value* value = values.Find(change.pref);
    const PrefService::Preference* pref = prefs->FindPreference(change.pref);
    if (value && pref && pref->IsUserModifiable()) {
      prefs->Set(change.pref, value->Clone());
      ++applied;
    }
  }
  return applied;
}

}  // namespace boring::folder_copy
