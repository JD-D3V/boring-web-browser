// Copyright 2026 boring. BSD style license.

#include "components/boring/accounts/accounts_rules.h"

#include <algorithm>
#include <cstdint>
#include <iterator>
#include <utility>

namespace boring::accounts {

namespace {

// Each company's own pages, as listed in the spec (accounts.md, section 3).
// Outlook is the personal service; work and school accounts use Other.
constexpr KnownProvider kKnown[] = {
    {Provider::kGoogle, "google", "Google", "https://accounts.google.com/",
     "https://mail.google.com/", "https://calendar.google.com/",
     "https://drive.google.com/"},
    {Provider::kProton, "proton", "Proton", "https://account.proton.me/login",
     "https://mail.proton.me/", "https://calendar.proton.me/",
     "https://drive.proton.me/"},
    {Provider::kOutlook, "outlook", "Outlook", "https://login.live.com/",
     "https://outlook.live.com/mail/", "https://outlook.live.com/calendar/",
     "https://onedrive.live.com/"},
    {Provider::kICloud, "icloud", "iCloud", "https://www.icloud.com/",
     "https://www.icloud.com/mail/", "https://www.icloud.com/calendar/",
     "https://www.icloud.com/iclouddrive/"},
    {Provider::kYahoo, "yahoo", "Yahoo", "https://login.yahoo.com/",
     "https://mail.yahoo.com/", "https://calendar.yahoo.com/", ""},
};

constexpr char kOtherKey[] = "other";

// Schemes that are written without "//" after the colon. Anything typed
// with one of these in front is taken as that scheme, and refused, rather
// than having https:// put in front of it.
constexpr std::string_view kBareSchemes[] = {
    "about",      "blob",   "chrome", "chrome-extension", "chrome-untrusted",
    "data",       "devtools", "file", "filesystem",       "ftp",
    "http",       "https",  "javascript", "mailto",       "vbscript",
    "view-source", "ws",    "wss",
};

constexpr std::string_view kHttps = "https://";

bool IsAsciiAlpha(char c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}

bool IsAsciiDigit(char c) {
  return c >= '0' && c <= '9';
}

char ToLowerAscii(char c) {
  return (c >= 'A' && c <= 'Z') ? static_cast<char>(c - 'A' + 'a') : c;
}

std::string LowerAscii(std::string_view s) {
  std::string out(s);
  std::transform(out.begin(), out.end(), out.begin(), ToLowerAscii);
  return out;
}

bool IsSpace(char c) {
  return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' ||
         c == '\v';
}

std::string_view TrimSpaces(std::string_view s) {
  while (!s.empty() && IsSpace(s.front())) {
    s.remove_prefix(1);
  }
  while (!s.empty() && IsSpace(s.back())) {
    s.remove_suffix(1);
  }
  return s;
}

bool IsSchemeToken(std::string_view s) {
  if (s.empty() || !IsAsciiAlpha(s[0])) {
    return false;
  }
  return std::all_of(s.begin(), s.end(), [](char c) {
    return IsAsciiAlpha(c) || IsAsciiDigit(c) || c == '+' || c == '-' ||
           c == '.';
  });
}

// Whether the person typed a scheme of their own: "x://..." or one of the
// bare schemes above ("javascript:...").
bool HasTypedScheme(std::string_view text) {
  const size_t colon = text.find(':');
  if (colon == std::string_view::npos) {
    return false;
  }
  const std::string head = LowerAscii(text.substr(0, colon));
  if (!IsSchemeToken(head)) {
    return false;
  }
  if (text.substr(colon + 1).starts_with("//")) {
    return true;
  }
  return std::find(std::begin(kBareSchemes), std::end(kBareSchemes), head) !=
         std::end(kBareSchemes);
}

// Reads one code point from UTF-8. Returns false on a broken sequence, and
// then steps over one byte.
bool NextCodePoint(std::string_view s, size_t* at, uint32_t* cp) {
  const auto byte = [&](size_t i) { return static_cast<uint8_t>(s[i]); };
  const uint8_t first = byte(*at);
  size_t length = 0;
  uint32_t value = 0;
  if (first < 0x80) {
    *cp = first;
    *at += 1;
    return true;
  } else if ((first & 0xE0) == 0xC0) {
    length = 2;
    value = first & 0x1F;
  } else if ((first & 0xF0) == 0xE0) {
    length = 3;
    value = first & 0x0F;
  } else if ((first & 0xF8) == 0xF0) {
    length = 4;
    value = first & 0x07;
  } else {
    *at += 1;
    return false;
  }
  if (*at + length > s.size()) {
    *at += 1;
    return false;
  }
  for (size_t i = 1; i < length; ++i) {
    if ((byte(*at + i) & 0xC0) != 0x80) {
      *at += 1;
      return false;
    }
    value = (value << 6) | (byte(*at + i) & 0x3F);
  }
  // Overlong forms, surrogates and values past Unicode are refused.
  static constexpr uint32_t kSmallest[] = {0, 0, 0x80, 0x800, 0x10000};
  if (value < kSmallest[length] || value > 0x10FFFF ||
      (value >= 0xD800 && value <= 0xDFFF)) {
    *at += 1;
    return false;
  }
  *cp = value;
  *at += length;
  return true;
}

// Control characters, line breaks, and the invisible marks that can hide
// or reorder text beside a name: zero width characters, direction marks,
// embeddings, overrides and isolates, the byte order mark.
bool IsHiddenOrControl(uint32_t cp) {
  return cp < 0x20 || (cp >= 0x7F && cp <= 0x9F) ||
         (cp >= 0x200B && cp <= 0x200F) || (cp >= 0x2028 && cp <= 0x202E) ||
         (cp >= 0x2060 && cp <= 0x206F) || cp == 0xFEFF ||
         (cp >= 0xFFF9 && cp <= 0xFFFB);
}

}  // namespace

std::span<const KnownProvider> KnownProviders() {
  return kKnown;
}

const KnownProvider* FindKnown(Provider provider) {
  for (const KnownProvider& known : kKnown) {
    if (known.provider == provider) {
      return &known;
    }
  }
  return nullptr;
}

const char* ProviderKey(Provider provider) {
  const KnownProvider* known = FindKnown(provider);
  return known ? known->key : kOtherKey;
}

std::optional<Provider> ProviderFromKey(std::string_view key) {
  for (const KnownProvider& known : kKnown) {
    if (key == known.key) {
      return known.provider;
    }
  }
  if (key == kOtherKey) {
    return Provider::kOther;
  }
  return std::nullopt;
}

std::string CleanName(std::string_view typed) {
  std::string kept;
  size_t at = 0;
  while (at < typed.size()) {
    const size_t start = at;
    uint32_t cp = 0;
    if (!NextCodePoint(typed, &at, &cp) || IsHiddenOrControl(cp)) {
      continue;
    }
    kept.append(typed.substr(start, at - start));
  }
  std::string_view trimmed = TrimSpaces(kept);
  // At most kMaxNameLength characters, cut between characters.
  size_t count = 0;
  at = 0;
  while (at < trimmed.size() && count < kMaxNameLength) {
    uint32_t cp = 0;
    NextCodePoint(trimmed, &at, &cp);
    ++count;
  }
  return std::string(TrimSpaces(trimmed.substr(0, at)));
}

std::string DefaultName(std::string_view base,
                        const std::vector<std::string>& taken) {
  const auto is_taken = [&](const std::string& name) {
    return std::find(taken.begin(), taken.end(), name) != taken.end();
  };
  std::string name(base);
  for (int n = 2; is_taken(name); ++n) {
    name = std::string(base) + " " + std::to_string(n);
  }
  return name;
}

UrlProblem PreCheckOtherUrl(std::string_view typed, std::string* out) {
  const std::string_view text = TrimSpaces(typed);
  if (text.empty()) {
    return UrlProblem::kEmpty;
  }
  if (text.size() > kMaxUrlLength) {
    return UrlProblem::kTooLong;
  }
  // A URL parser drops tabs and line breaks inside an address without a
  // word; an address with any space or control character in it is refused.
  for (char c : text) {
    if (static_cast<uint8_t>(c) <= 0x20 || c == 0x7F) {
      return UrlProblem::kNotWebAddress;
    }
  }
  std::string url =
      HasTypedScheme(text) ? std::string(text) : std::string(kHttps) + std::string(text);
  if (url.size() > kMaxUrlLength) {
    return UrlProblem::kTooLong;
  }
  if (LowerAscii(std::string_view(url).substr(0, kHttps.size())) != kHttps) {
    return UrlProblem::kNotHttps;
  }
  // The part between "https://" and the path. A backslash ends it too: the
  // URL parser reads it as a slash in a web address.
  const std::string_view rest = std::string_view(url).substr(kHttps.size());
  const std::string_view authority = rest.substr(0, rest.find_first_of("/?#\\"));
  if (authority.find('@') != std::string_view::npos) {
    return UrlProblem::kCredentials;
  }
  if (authority.empty() || authority.front() == '[') {
    return UrlProblem::kNotWebAddress;
  }
  std::string_view host = authority;
  if (const size_t colon = host.rfind(':'); colon != std::string_view::npos) {
    const std::string_view port = host.substr(colon + 1);
    if (!std::all_of(port.begin(), port.end(), IsAsciiDigit)) {
      return UrlProblem::kNotWebAddress;
    }
    host = host.substr(0, colon);
  }
  if (!host.empty() && host.back() == '.') {
    host.remove_suffix(1);
  }
  const std::string lower = LowerAscii(host);
  const bool all_digits = std::all_of(lower.begin(), lower.end(), [](char c) {
    return IsAsciiDigit(c) || c == '.';
  });
  if (lower.empty() || lower.find('.') == std::string::npos ||
      lower.front() == '.' || lower.find("..") != std::string::npos ||
      all_digits || lower == "localhost" || lower.ends_with(".localhost")) {
    return UrlProblem::kNotWebAddress;
  }
  *out = std::move(url);
  return UrlProblem::kNone;
}

}  // namespace boring::accounts
