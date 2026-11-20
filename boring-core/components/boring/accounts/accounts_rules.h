// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ACCOUNTS_ACCOUNTS_RULES_H_
#define COMPONENTS_BORING_ACCOUNTS_ACCOUNTS_RULES_H_

#include <cstddef>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

// The parts of Accounts that need nothing from Chromium: the fixed table of
// the five companies' own pages, how a name is cleaned, and the first, text
// level checks on an address typed for "Other". Kept apart so a test can
// build them on their own (tools/tests/accounts_probe.cc). accounts_store.h
// adds the checks that need a real URL parser.
namespace boring::accounts {

inline constexpr size_t kMaxAccounts = 12;
inline constexpr size_t kMaxNameLength = 40;
inline constexpr size_t kMaxUrlLength = 2048;

enum class Provider { kGoogle, kProton, kOutlook, kICloud, kYahoo, kOther };

// One company's own pages. Plain https pages a person could type: no query
// strings, no account hints. `files` is empty where the company has no files
// service (Yahoo), and that row then has no Files button.
struct KnownProvider {
  Provider provider;
  const char* key;   // as stored in boring.accounts.list
  const char* name;  // as shown: "Google"
  const char* sign_in;
  const char* mail;
  const char* calendar;
  const char* files;
};

// The five companies, in the order the Add buttons show them.
std::span<const KnownProvider> KnownProviders();
// Null for kOther.
const KnownProvider* FindKnown(Provider provider);

// "google" ... "yahoo", or "other".
const char* ProviderKey(Provider provider);
std::optional<Provider> ProviderFromKey(std::string_view key);

// A name as typed, made safe to show: control characters, line breaks and
// the invisible marks that can reorder text removed, spaces trimmed, at most
// kMaxNameLength characters. UTF-8 in and out; broken UTF-8 is dropped.
std::string CleanName(std::string_view typed);

// `base` itself, or "base 2", "base 3" ... whichever is not taken yet.
std::string DefaultName(std::string_view base,
                        const std::vector<std::string>& taken);

// What is wrong with an address typed for Other, in the words Settings
// gives back (see accounts_handler.cc).
enum class UrlProblem {
  kNone,
  kEmpty,
  kTooLong,
  kNotHttps,     // "Use an address that starts with https://"
  kCredentials,  // "That address has a name and password in it. ..."
  kNotWebAddress,
};

// The text level checks, before a URL parser sees the address. With no
// scheme typed, "https://" goes in front. On kNone, `out` holds the text to
// parse. The parser's own checks follow in accounts_store.cc.
UrlProblem PreCheckOtherUrl(std::string_view typed, std::string* out);

}  // namespace boring::accounts

#endif  // COMPONENTS_BORING_ACCOUNTS_ACCOUNTS_RULES_H_
