// Copyright 2026 boring. BSD style license.

#include "components/boring/accounts/accounts_store.h"

#include <array>
#include <utility>

#include "base/i18n/case_conversion.h"
#include "base/no_destructor.h"
#include "base/strings/utf_string_conversion_utils.h"
#include "base/strings/utf_string_conversions.h"
#include "base/uuid.h"
#include "base/values.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "components/url_formatter/elide_url.h"
#include "net/base/registry_controlled_domains/registry_controlled_domain.h"
#include "url/url_constants.h"

namespace boring::accounts {

namespace {

constexpr char kIdKey[] = "id";
constexpr char kProviderKey[] = "provider";
constexpr char kNameKey[] = "name";
constexpr char kMailKey[] = "mail";
constexpr char kCalendarKey[] = "calendar";
constexpr char kFilesKey[] = "files";
constexpr size_t kMaxIdLength = 64;

// An optional Other address: empty stays empty, anything else must pass.
bool ReadOptionalUrl(const base::DictValue& dict, const char* key, GURL* out) {
  const std::string* text = dict.FindString(key);
  if (!text || text->empty()) {
    *out = GURL();
    return true;
  }
  std::optional<GURL> url = CheckOtherUrl(*text);
  if (!url) {
    return false;
  }
  *out = std::move(*url);
  return true;
}

std::string FallbackName(const Account& account) {
  return base::UTF16ToUTF8(ProviderName(account));
}

// One stored entry, checked as if it had been typed in: a hand-edited
// Preferences file gets no further than the Settings page would.
std::optional<Account> ReadEntry(const base::Value& item) {
  if (!item.is_dict()) {
    return std::nullopt;
  }
  const base::DictValue& dict = item.GetDict();
  const std::string* id = dict.FindString(kIdKey);
  const std::string* provider_key = dict.FindString(kProviderKey);
  const std::string* name = dict.FindString(kNameKey);
  if (!id || id->empty() || id->size() > kMaxIdLength || !provider_key) {
    return std::nullopt;
  }
  std::optional<Provider> provider = ProviderFromKey(*provider_key);
  if (!provider) {
    return std::nullopt;
  }
  Account account;
  account.id = *id;
  account.provider = *provider;
  if (*provider == Provider::kOther) {
    const std::string* mail = dict.FindString(kMailKey);
    std::optional<GURL> mail_url = mail ? CheckOtherUrl(*mail) : std::nullopt;
    if (!mail_url) {
      return std::nullopt;
    }
    account.links.mail = std::move(*mail_url);
    if (!ReadOptionalUrl(dict, kCalendarKey, &account.links.calendar) ||
        !ReadOptionalUrl(dict, kFilesKey, &account.links.files)) {
      return std::nullopt;
    }
  } else {
    account.links = KnownLinks(*provider);
  }
  account.name = name ? CleanName(*name) : std::string();
  if (account.name.empty()) {
    account.name = FallbackName(account);
  }
  return account;
}

// Takes out entries that fail the checks, so the limit counts only what is
// shown and nothing hidden can sit in the list.
void Prune(base::ListValue& list) {
  list.EraseIf([](const base::Value& item) { return !ReadEntry(item); });
}

std::vector<std::string> Names(const PrefService& prefs) {
  std::vector<std::string> names;
  for (const Account& account : GetAccounts(prefs)) {
    names.push_back(account.name);
  }
  return names;
}

std::string NewId() {
  return base::Uuid::GenerateRandomV4().AsLowercaseString();
}

// The index of the entry with this id, or -1.
int IndexOf(const base::ListValue& list, std::string_view id) {
  for (size_t i = 0; i < list.size(); ++i) {
    if (list[i].is_dict()) {
      const std::string* entry_id = list[i].GetDict().FindString(kIdKey);
      if (entry_id && *entry_id == id) {
        return static_cast<int>(i);
      }
    }
  }
  return -1;
}

}  // namespace

void RegisterProfilePrefs(user_prefs::PrefRegistrySyncable* registry) {
  // On this computer only: no sync flag.
  registry->RegisterListPref(kAccountsPref);
}

std::vector<Account> GetAccounts(const PrefService& prefs) {
  std::vector<Account> accounts;
  for (const base::Value& item : prefs.GetList(kAccountsPref)) {
    if (accounts.size() >= kMaxAccounts) {
      break;
    }
    if (std::optional<Account> account = ReadEntry(item)) {
      accounts.push_back(std::move(*account));
    }
  }
  return accounts;
}

std::optional<Account> FindAccount(const PrefService& prefs,
                                   std::string_view id) {
  for (Account& account : GetAccounts(prefs)) {
    if (account.id == id) {
      return std::move(account);
    }
  }
  return std::nullopt;
}

std::optional<std::string> AddKnown(PrefService* prefs, Provider provider) {
  const KnownProvider* known = FindKnown(provider);
  if (!prefs || !known) {
    return std::nullopt;
  }
  const std::string name = DefaultName(known->name, Names(*prefs));
  ScopedListPrefUpdate update(prefs, kAccountsPref);
  Prune(update.Get());
  if (update->size() >= kMaxAccounts) {
    return std::nullopt;
  }
  base::DictValue entry;
  std::string id = NewId();
  entry.Set(kIdKey, id);
  entry.Set(kProviderKey, known->key);
  entry.Set(kNameKey, name);
  update->Append(std::move(entry));
  return id;
}

base::expected<std::string, AddError> AddOther(PrefService* prefs,
                                               std::string_view name,
                                               std::string_view mail,
                                               std::string_view calendar,
                                               std::string_view files) {
  if (!prefs) {
    return base::unexpected(AddError::kFull);
  }
  std::optional<GURL> mail_url = CheckOtherUrl(mail);
  if (!mail_url) {
    return base::unexpected(AddError::kBadMail);
  }
  std::optional<GURL> calendar_url;
  if (!calendar.empty()) {
    calendar_url = CheckOtherUrl(calendar);
    if (!calendar_url) {
      return base::unexpected(AddError::kBadCalendar);
    }
  }
  std::optional<GURL> files_url;
  if (!files.empty()) {
    files_url = CheckOtherUrl(files);
    if (!files_url) {
      return base::unexpected(AddError::kBadFiles);
    }
  }
  ScopedListPrefUpdate update(prefs, kAccountsPref);
  Prune(update.Get());
  if (update->size() >= kMaxAccounts) {
    return base::unexpected(AddError::kFull);
  }
  base::DictValue entry;
  std::string id = NewId();
  entry.Set(kIdKey, id);
  entry.Set(kProviderKey, ProviderKey(Provider::kOther));
  // Empty means the provider's name, which for Other is the mail host.
  entry.Set(kNameKey, CleanName(name));
  entry.Set(kMailKey, mail_url->spec());
  entry.Set(kCalendarKey, calendar_url ? calendar_url->spec() : std::string());
  entry.Set(kFilesKey, files_url ? files_url->spec() : std::string());
  update->Append(std::move(entry));
  return id;
}

bool Rename(PrefService* prefs, std::string_view id, std::string_view name) {
  if (!prefs) {
    return false;
  }
  ScopedListPrefUpdate update(prefs, kAccountsPref);
  Prune(update.Get());
  const int index = IndexOf(update.Get(), id);
  if (index < 0) {
    return false;
  }
  // Empty is allowed: the row then shows the provider's name.
  (*update)[index].GetDict().Set(kNameKey, CleanName(name));
  return true;
}

bool Remove(PrefService* prefs, std::string_view id) {
  if (!prefs) {
    return false;
  }
  ScopedListPrefUpdate update(prefs, kAccountsPref);
  Prune(update.Get());
  const int index = IndexOf(update.Get(), id);
  if (index < 0) {
    return false;
  }
  update->erase(update->begin() + index);
  return true;
}

bool Move(PrefService* prefs, std::string_view id, int delta) {
  if (!prefs || (delta != -1 && delta != 1)) {
    return false;
  }
  ScopedListPrefUpdate update(prefs, kAccountsPref);
  Prune(update.Get());
  const int index = IndexOf(update.Get(), id);
  const int other = index + delta;
  if (index < 0 || other < 0 || other >= static_cast<int>(update->size())) {
    return false;
  }
  std::swap((*update)[index], (*update)[other]);
  return true;
}

const Links& KnownLinks(Provider provider) {
  static const base::NoDestructor<std::array<Links, 5>> table([] {
    std::array<Links, 5> links;
    size_t i = 0;
    for (const KnownProvider& known : KnownProviders()) {
      links[i++] = Links{GURL(known.sign_in), GURL(known.mail),
                         GURL(known.calendar), GURL(known.files)};
    }
    return links;
  }());
  size_t i = 0;
  for (const KnownProvider& known : KnownProviders()) {
    if (known.provider == provider) {
      return (*table)[i];
    }
    ++i;
  }
  static const base::NoDestructor<Links> none;
  return *none;
}

UrlProblem CheckOtherUrlProblem(std::string_view typed, GURL* out) {
  std::string text;
  const UrlProblem problem = PreCheckOtherUrl(typed, &text);
  if (problem != UrlProblem::kNone) {
    return problem;
  }
  GURL url(text);
  if (!url.is_valid() || !url.has_host()) {
    return UrlProblem::kNotWebAddress;
  }
  if (!url.SchemeIs(url::kHttpsScheme)) {
    return UrlProblem::kNotHttps;
  }
  if (url.has_username() || url.has_password()) {
    return UrlProblem::kCredentials;
  }
  if (url.HostIsIPAddress() || url.DomainIs("localhost") ||
      net::registry_controlled_domains::GetDomainAndRegistry(
          url, net::registry_controlled_domains::EXCLUDE_PRIVATE_REGISTRIES)
          .empty()) {
    return UrlProblem::kNotWebAddress;
  }
  if (url.spec().size() > kMaxUrlLength) {
    return UrlProblem::kTooLong;
  }
  *out = std::move(url);
  return UrlProblem::kNone;
}

std::optional<GURL> CheckOtherUrl(std::string_view typed) {
  GURL url;
  if (CheckOtherUrlProblem(typed, &url) != UrlProblem::kNone) {
    return std::nullopt;
  }
  return url;
}

std::u16string Initial(const Account& account) {
  const std::u16string name = base::UTF8ToUTF16(account.name);
  if (name.empty()) {
    return u"?";
  }
  // One character, which may be two UTF-16 units.
  const size_t length =
      (name.size() > 1 && name[0] >= 0xD800 && name[0] <= 0xDBFF) ? 2 : 1;
  return base::i18n::ToUpper(std::u16string_view(name).substr(0, length));
}

std::u16string ProviderName(const Account& account) {
  if (const KnownProvider* known = FindKnown(account.provider)) {
    return base::UTF8ToUTF16(known->name);
  }
  // Shown the way Chromium shows a host in its own prompts: look-alike
  // letters come out as punycode.
  return url_formatter::FormatUrlForSecurityDisplay(
      account.links.mail, url_formatter::SchemeDisplay::OMIT_HTTP_AND_HTTPS);
}

std::u16string ProviderLine(const Account& account) {
  if (FindKnown(account.provider)) {
    return ProviderName(account) + u" account";
  }
  return ProviderName(account);
}

}  // namespace boring::accounts
