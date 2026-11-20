// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ACCOUNTS_ACCOUNTS_STORE_H_
#define COMPONENTS_BORING_ACCOUNTS_ACCOUNTS_STORE_H_

#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "base/types/expected.h"
#include "components/boring/accounts/accounts_rules.h"
#include "url/gurl.h"

class PrefService;

namespace user_prefs {
class PrefRegistrySyncable;
}

// Accounts are shortcuts. The browser keeps a short list on this computer
// (the profile pref below) and opens each company's own pages from it. It
// never reads, stores or sends a password, cookie or token, and has no
// sign-in of its own.
//
// Stored entry: {"id": <uuid>, "provider": "google" ... "yahoo" | "other",
// "name": <text>}, and for "other" only "mail", "calendar", "files" (https
// addresses; the last two may be ""). Known providers never store an
// address: theirs come from the table compiled in (accounts_rules.cc), so
// nothing in Preferences can point a "Google" row somewhere else. Every
// entry is checked again each time it is read.
namespace boring::accounts {

inline constexpr char kAccountsPref[] = "boring.accounts.list";

// Calendar or files may be empty: that row has no such button.
struct Links {
  GURL sign_in, mail, calendar, files;
};

struct Account {
  std::string id;
  Provider provider = Provider::kOther;
  std::string name;
  Links links;
};

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry);

// The list in order, without any entry that fails the checks.
std::vector<Account> GetAccounts(const PrefService& prefs);
std::optional<Account> FindAccount(const PrefService& prefs,
                                   std::string_view id);

// Adds a known provider named after it ("Google", then "Google 2"). Returns
// the new id, or nothing when the list is full or `provider` is kOther.
std::optional<std::string> AddKnown(PrefService* prefs, Provider provider);

enum class AddError { kFull, kBadName, kBadMail, kBadCalendar, kBadFiles };
// Mail is required, calendar and files may be empty.
base::expected<std::string, AddError> AddOther(PrefService* prefs,
                                               std::string_view name,
                                               std::string_view mail,
                                               std::string_view calendar,
                                               std::string_view files);

bool Rename(PrefService* prefs, std::string_view id, std::string_view name);
bool Remove(PrefService* prefs, std::string_view id);
bool Move(PrefService* prefs, std::string_view id, int delta);  // -1 up, +1 down

// Not for kOther.
const Links& KnownLinks(Provider provider);

// The whole check for an address typed for Other: the text checks in
// accounts_rules.h, then a real parse: https, no name or password, a public
// host name with a registrable domain, not an IP address or localhost.
std::optional<GURL> CheckOtherUrl(std::string_view typed);
// The same, saying what was wrong.
UrlProblem CheckOtherUrlProblem(std::string_view typed, GURL* out);

std::u16string Initial(const Account& account);       // first letter, upper case
std::u16string ProviderName(const Account& account);  // "Google", or the Other mail host
std::u16string ProviderLine(const Account& account);  // "Google account", or the host

}  // namespace boring::accounts

#endif  // COMPONENTS_BORING_ACCOUNTS_ACCOUNTS_STORE_H_
