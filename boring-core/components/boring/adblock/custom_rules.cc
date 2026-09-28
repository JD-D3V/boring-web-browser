// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/custom_rules.h"

#include <algorithm>
#include <optional>
#include <string>
#include <utility>

#include "base/json/json_reader.h"
#include "base/strings/string_split.h"
#include "base/strings/string_util.h"
#include "base/values.h"
#include "components/boring/adblock/adblock_ffi.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"

namespace boring {

std::vector<CustomRuleProblem> CheckCustomRules(std::string_view text) {
  std::vector<CustomRuleProblem> problems;
  const BoringLibrary* lib = GetBoringLibrary();
  if (!lib) {
    return problems;
  }
  char* json = lib->adblock_check_rules(
      reinterpret_cast<const unsigned char*>(text.data()), text.size());
  if (!json) {
    return problems;
  }
  std::optional<base::ListValue> list =
      base::JSONReader::ReadList(json, base::JSON_PARSE_RFC);
  lib->adblock_string_free(json);
  if (!list) {
    return problems;
  }
  for (const base::Value& item : *list) {
    const base::DictValue* entry = item.GetIfDict();
    if (!entry) {
      continue;
    }
    const std::optional<int> line = entry->FindInt("line");
    const std::string* rule = entry->FindString("rule");
    const std::string* error = entry->FindString("error");
    if (!line || *line < 1 || !rule || !error) {
      continue;
    }
    problems.push_back({static_cast<size_t>(*line), *rule, *error});
  }
  return problems;
}

bool AddCustomRule(content::BrowserContext* context, std::string_view rule) {
  const std::string_view trimmed =
      base::TrimWhitespaceASCII(rule, base::TRIM_ALL);
  if (trimmed.empty() || trimmed.find_first_of("\r\n") != std::string::npos) {
    return false;
  }
  PrefService* prefs = user_prefs::UserPrefs::Get(context);
  if (!prefs) {
    return false;
  }
  std::string text = prefs->GetString(prefs::kBoringCustomRules);
  const std::vector<std::string_view> lines = base::SplitStringPiece(
      text, "\n", base::TRIM_WHITESPACE, base::SPLIT_WANT_NONEMPTY);
  if (std::ranges::find(lines, trimmed) == lines.end()) {
    if (!text.empty() && !text.ends_with('\n')) {
      text.push_back('\n');
    }
    text.append(trimmed);
    text.push_back('\n');
    prefs->SetString(prefs::kBoringCustomRules, text);
  }
  ApplyCustomRules(context);
  return true;
}

void ApplyCustomRules(content::BrowserContext* context) {
  // Reads the prefs and starts a build when the rules changed.
  ProfileLists::ForContext(context);
}

}  // namespace boring
