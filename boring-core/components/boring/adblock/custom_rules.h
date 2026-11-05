// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_CUSTOM_RULES_H_
#define COMPONENTS_BORING_ADBLOCK_CUSTOM_RULES_H_

#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

#include "base/files/file_path.h"
#include "base/time/time.h"

class PrefService;

namespace content {
class BrowserContext;
}

namespace boring {

// A person's own filter rules, prefs::kBoringCustomRules: one rule per
// line, uBO syntax, applied after every list so their exceptions win,
// like uBO's "My filters". They get standard permissions only: a
// trusted scriptlet (trusted-*) never runs from them.

// One line the engine will not use.
struct CustomRuleProblem {
  size_t line = 0;    // 1-based, as an editor counts
  std::string rule;   // the line, trimmed
  std::string error;  // why, in the engine's words
};

// Every line of `text` that the engine will not use, so the Protection
// page can say so instead of dropping it silently. Comments ("!") and
// blank lines are fine. At most 1000 are listed. Empty when all is well,
// and also when the engine library did not load, since then no rule is
// used at all and the page says blocking is off.
//
// Loads the engine library on first use, so call it where blocking is
// allowed, such as a base::ThreadPool task with base::MayBlock().
std::vector<CustomRuleProblem> CheckCustomRules(std::string_view text);

// Adds `rule` as a line of the profile's custom rules, unless an
// identical line is already there, and applies the rules at once.
// Returns false, changing nothing, for an empty rule or one with a line
// break in it. UI thread.
bool AddCustomRule(content::BrowserContext* context, std::string_view rule);

// Applies the profile's custom rules now. Setting the pref is enough on
// its own (the next page load picks it up); calling this after a change
// just gets the new engine built sooner. UI thread.
void ApplyCustomRules(content::BrowserContext* context);

// Filter lists a person added by address (prefs::kBoringUserLists).
// https only, fetched when added and then weekly, at most 5 MB each, no
// cookies, no identifier. A list is read by the same parser as the rules
// above and applied in the same engine, with standard permissions only.

// One added list as the Protection page shows it.
struct UserListInfo {
  std::string url;
  std::string host;
  // When the copy in use was downloaded; null while there is none.
  base::Time updated;
  // A plain sentence about the last try that failed, empty when fine.
  std::string error;
  // A download is queued or running.
  bool busy = false;
};

std::vector<UserListInfo> GetUserLists(content::BrowserContext* context);

// Adds the list at `address` and starts downloading it. Returns an empty
// string when it was added, else a plain sentence on why not (nothing is
// changed then). UI thread.
std::string AddUserList(content::BrowserContext* context,
                        std::string_view address);

// Removes the list and its downloaded copy, and stops using its rules.
void RemoveUserList(content::BrowserContext* context, std::string_view url);

// Downloads lists that are due: never finished, a week old, or a day
// since a failed try. Does nothing when list updates are off. Cheap, so
// it is called on every navigation. Not for incognito. UI thread.
void MaybeRefreshUserLists(content::BrowserContext* context);

// What the engine is built from: the downloaded copies in use, and a key
// that changes whenever any of them does ("" when there are none).
struct UserListFiles {
  std::string key;
  std::vector<base::FilePath> paths;
};
UserListFiles GetUserListFiles(const PrefService* prefs,
                               const base::FilePath& profile_dir);

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_CUSTOM_RULES_H_
