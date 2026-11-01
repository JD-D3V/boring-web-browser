// Copyright 2026 boring. BSD style license.

#include "components/boring/privacy/debounce.h"

#include <algorithm>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "base/base64.h"
#include "base/json/json_reader.h"
#include "base/logging.h"
#include "base/no_destructor.h"
#include "base/strings/escape.h"
#include "base/strings/strcat.h"
#include "base/strings/string_util.h"
#include "base/values.h"
#include "net/base/url_util.h"
#include "third_party/re2/src/re2/re2.h"

namespace boring {

namespace {

// Brave's rules, unchanged and under their own licence, and ours. Each
// file is one C++ raw string holding a JSON array of rules.
const char kBraveRulesJson[] =
#include "components/boring/privacy/debounce_brave.inc"
    ;
const char kBoringRulesJson[] =
#include "components/boring/privacy/debounce_boring.inc"
    ;

// An address longer than this is not a redirector link, and every rule
// would have to read all of it.
constexpr size_t kMaxSpecLength = 32 * 1024;

// The real address, once decoded. Long shopping links run to a few
// thousand characters; nothing a person clicks needs more than this.
constexpr size_t kMaxTargetLength = 8 * 1024;

// How many redirectors in a row are followed. A link that is still
// bouncing after this many is not an honest one.
constexpr int kMaxHops = 5;

// "*" in a pattern matches any run of characters, including none, and
// everything else matches itself, "?" included.
bool GlobMatch(std::string_view text, std::string_view pattern) {
  size_t t = 0;
  size_t p = 0;
  size_t star = std::string_view::npos;
  size_t mark = 0;
  while (t < text.size()) {
    if (p < pattern.size() && pattern[p] == '*') {
      star = p++;
      mark = t;
    } else if (p < pattern.size() && pattern[p] == text[t]) {
      ++p;
      ++t;
    } else if (star != std::string_view::npos) {
      p = star + 1;
      t = ++mark;
    } else {
      return false;
    }
  }
  while (p < pattern.size() && pattern[p] == '*') {
    ++p;
  }
  return p == pattern.size();
}

// A match pattern as Chrome extensions write them, scheme://host/path,
// reduced to what Brave's rules use: scheme http, https or *, host exact,
// *.suffix or *, and a path with * wildcards. Any port matches.
class Pattern {
 public:
  static std::optional<Pattern> Parse(std::string_view text) {
    const size_t scheme_end = text.find("://");
    if (scheme_end == std::string_view::npos) {
      return std::nullopt;
    }
    Pattern pattern;
    const std::string_view scheme = text.substr(0, scheme_end);
    if (scheme == "*") {
      pattern.http_ = pattern.https_ = true;
    } else if (scheme == "http") {
      pattern.http_ = true;
    } else if (scheme == "https") {
      pattern.https_ = true;
    } else {
      return std::nullopt;
    }
    const std::string_view rest = text.substr(scheme_end + 3);
    const size_t path_start = rest.find('/');
    if (path_start == std::string_view::npos) {
      return std::nullopt;
    }
    std::string_view host = rest.substr(0, path_start);
    pattern.path_ = std::string(rest.substr(path_start));
    if (host == "*") {
      pattern.host_kind_ = HostKind::kAny;
    } else {
      if (host.starts_with("*.")) {
        pattern.host_kind_ = HostKind::kSubdomains;
        host.remove_prefix(2);
      }
      // A wildcard anywhere else, a port or an empty host are not
      // something these rules use.
      if (host.empty() || host.find_first_of("*:") != std::string_view::npos) {
        return std::nullopt;
      }
      pattern.host_ = base::ToLowerASCII(host);
    }
    return pattern;
  }

  bool Matches(const GURL& url, std::string_view path_and_query) const {
    if (!(url.SchemeIs("http") && http_) && !(url.SchemeIs("https") && https_)) {
      return false;
    }
    const std::string_view host = url.host();
    switch (host_kind_) {
      case HostKind::kAny:
        break;
      case HostKind::kExact:
        if (host != host_) {
          return false;
        }
        break;
      case HostKind::kSubdomains:
        if (host != host_ &&
            !(host.size() > host_.size() && host.ends_with(host_) &&
              host[host.size() - host_.size() - 1] == '.')) {
          return false;
        }
        break;
    }
    return GlobMatch(path_and_query, path_);
  }

 private:
  enum class HostKind { kExact, kSubdomains, kAny };

  bool http_ = false;
  bool https_ = false;
  HostKind host_kind_ = HostKind::kExact;
  std::string host_;
  std::string path_;
};

enum class Action {
  kRedirect,          // the target is a query parameter
  kBase64Redirect,    // the target is a base64 encoded query parameter
  kRegexPath,         // the target is what the regex captures from the path
  kRegexPathTemplate  // the captures go into a template address
};

struct Rule {
  std::vector<Pattern> include;
  std::vector<Pattern> exclude;
  Action action = Action::kRedirect;
  // The query parameter, or the regex, depending on the action.
  std::string param;
  std::unique_ptr<re2::RE2> regex;
  // "http" or "https", put in front of a target that has no scheme.
  std::string prepend_scheme;
  std::string url_template;
};

// True when the text holds a percent escape of a control character
// (%00 to %1F) or of DEL. Looked at before decoding, so a decoder that
// leaves such an escape alone cannot get one through.
bool HasEscapedControl(std::string_view text) {
  for (size_t i = 0; i + 2 < text.size(); ++i) {
    if (text[i] != '%') {
      continue;
    }
    const char high = text[i + 1];
    const char low = text[i + 2];
    if ((high == '0' || high == '1') && base::IsHexDigit(low)) {
      return true;
    }
    if (high == '7' && (low == 'f' || low == 'F')) {
      return true;
    }
  }
  return false;
}

// Control characters, spaces and backslashes have no place in an address
// that came out of another one. A tab or newline would be dropped by the
// URL parser, so "java\tscript:" would pass a scheme check and then
// become something else; a backslash is a slash to some parsers and not
// to others.
bool HasForbiddenCharacters(std::string_view text) {
  return std::ranges::any_of(text, [](char c) {
    const unsigned char u = static_cast<unsigned char>(c);
    return u <= 0x20 || u == 0x7f || u == '\\';
  });
}

// The value of query parameter `key`, only when it is there exactly once.
// A parameter given twice is read differently by different servers, and
// the one we would pick may not be the one the redirector would.
bool UniqueQueryValue(const GURL& url,
                      std::string_view key,
                      std::string* value) {
  bool found = false;
  for (net::QueryIterator it(url); !it.IsAtEnd(); it.Advance()) {
    if (it.GetKey() != key) {
      continue;
    }
    if (found || HasEscapedControl(it.GetValue())) {
      return false;
    }
    found = true;
    *value = it.GetUnescapedValue();
  }
  return found;
}

// Base64 as redirectors write it: standard or URL safe, with or without
// padding.
std::optional<std::string> DecodeBase64(std::string_view encoded) {
  std::string standard(encoded);
  std::ranges::replace(standard, '-', '+');
  std::ranges::replace(standard, '_', '/');
  std::string decoded;
  if (!base::Base64Decode(standard, &decoded,
                          base::Base64DecodePolicy::kForgiving)) {
    return std::nullopt;
  }
  return decoded;
}

// Text taken from a path: once, and without turning a plus into a space.
std::string DecodePathText(std::string_view text) {
  return base::UnescapeURLComponent(
      text, base::UnescapeRule::SPACES | base::UnescapeRule::PATH_SEPARATORS |
                base::UnescapeRule::URL_SPECIAL_CHARS_EXCEPT_PATH_SEPARATORS);
}

// The groups the regex captured from `subject`, or nothing when it does
// not match the whole of it.
std::optional<std::vector<std::string>> Capture(const re2::RE2& regex,
                                                std::string_view subject) {
  const int groups = regex.NumberOfCapturingGroups();
  std::vector<std::string> captured(groups);
  std::vector<re2::RE2::Arg> args;
  args.reserve(groups);
  std::vector<const re2::RE2::Arg*> arg_pointers;
  arg_pointers.reserve(groups);
  for (std::string& group : captured) {
    args.emplace_back(&group);
    arg_pointers.push_back(&args.back());
  }
  if (!re2::RE2::FullMatchN(subject, regex, arg_pointers.data(), groups)) {
    return std::nullopt;
  }
  return captured;
}

// A template with its captures put in. Each is escaped as a query value,
// so a capture can add to the address but never change its shape.
// `probe` instead puts a plain "x" in each place, to work out which host
// the template means.
std::optional<std::string> ExpandTemplate(
    std::string_view tmpl,
    const std::vector<std::string>& captured,
    bool probe) {
  std::string out;
  for (size_t i = 0; i < tmpl.size(); ++i) {
    if (tmpl[i] == '$' && i + 1 < tmpl.size() && base::IsAsciiDigit(tmpl[i + 1])) {
      const size_t index = tmpl[i + 1] - '0';
      if (index == 0 || index > captured.size()) {
        return std::nullopt;
      }
      out += probe ? std::string("x")
                   : base::EscapeQueryParamValue(captured[index - 1],
                                                 /*use_plus=*/false);
      ++i;
    } else {
      out += tmpl[i];
    }
  }
  return out;
}

// The address the text stands for, when it can safely be navigated to.
// This is the one gate every rule goes through, whatever the rule said.
std::optional<GURL> MakeTarget(std::string_view text,
                               std::string_view prepend_scheme,
                               const GURL& original) {
  if (text.empty() || text.size() > kMaxTargetLength ||
      !base::IsStringUTF8(text) || HasForbiddenCharacters(text)) {
    return std::nullopt;
  }
  std::string address;
  if (prepend_scheme.empty()) {
    // Spelled out in full. "http:evil", "https:/evil", "//evil",
    // "javascript:", "data:" and the rest are not an address a redirector
    // meant, and the parser would be left to guess at some of them.
    if (!base::StartsWith(text, "http://",
                          base::CompareCase::INSENSITIVE_ASCII) &&
        !base::StartsWith(text, "https://",
                          base::CompareCase::INSENSITIVE_ASCII)) {
      return std::nullopt;
    }
    address = std::string(text);
  } else {
    // A host and path with the scheme left off. It has to start like a
    // host, which keeps "//evil", ":x" and an address that already has
    // its own scheme from being given a second one.
    if (!base::IsAsciiAlphaNumeric(text[0]) && text[0] != '[') {
      return std::nullopt;
    }
    address = base::StrCat({prepend_scheme, "://", text});
  }
  GURL target(address);
  // Checked again on what the parser made of it, not on what it was
  // given.
  if (!target.is_valid() || !target.SchemeIsHTTPOrHTTPS() ||
      !target.has_host() || target.host().empty() ||
      target.has_username() || target.has_password()) {
    return std::nullopt;
  }
  // A real site has a dot in its name, or is an address. "https://https/"
  // is what a doubled scheme turns into.
  if (target.host().find('.') == std::string_view::npos &&
      !target.HostIsIPAddress()) {
    return std::nullopt;
  }
  if (target == original) {
    return std::nullopt;
  }
  return target;
}

std::optional<Rule> ParseRule(const base::DictValue& dict) {
  Rule rule;
  const base::ListValue* include = dict.FindList("include");
  if (!include) {
    return std::nullopt;
  }
  for (const base::Value& entry : *include) {
    if (entry.is_string()) {
      if (std::optional<Pattern> pattern = Pattern::Parse(entry.GetString())) {
        rule.include.push_back(std::move(*pattern));
      }
    }
  }
  if (rule.include.empty()) {
    return std::nullopt;
  }
  if (const base::ListValue* exclude = dict.FindList("exclude")) {
    for (const base::Value& entry : *exclude) {
      if (entry.is_string()) {
        if (std::optional<Pattern> pattern =
                Pattern::Parse(entry.GetString())) {
          rule.exclude.push_back(std::move(*pattern));
        }
      }
    }
  }
  const std::string* action = dict.FindString("action");
  const std::string* param = dict.FindString("param");
  if (!action || !param || param->empty()) {
    return std::nullopt;
  }
  rule.param = *param;
  if (*action == "redirect") {
    rule.action = Action::kRedirect;
  } else if (*action == "base64,redirect") {
    rule.action = Action::kBase64Redirect;
  } else if (*action == "regex-path" || *action == "regex-path-template") {
    rule.action = *action == "regex-path" ? Action::kRegexPath
                                          : Action::kRegexPathTemplate;
    re2::RE2::Options options;
    options.set_log_errors(false);
    rule.regex = std::make_unique<re2::RE2>(*param, options);
    if (!rule.regex->ok() || rule.regex->NumberOfCapturingGroups() < 1) {
      return std::nullopt;
    }
  } else {
    return std::nullopt;
  }
  if (const std::string* scheme = dict.FindString("prepend_scheme")) {
    if (*scheme != "http" && *scheme != "https") {
      return std::nullopt;
    }
    rule.prepend_scheme = *scheme;
  }
  if (rule.action == Action::kRegexPathTemplate) {
    const std::string* tmpl = dict.FindString("redirect_url_template");
    if (!tmpl) {
      return std::nullopt;
    }
    rule.url_template = *tmpl;
  }
  // Brave's "pref" key names its own AMP switch. Ours is the one switch
  // for all of it, and the throttle has already checked it.
  return rule;
}

void AddRules(std::string_view json, std::vector<Rule>& rules) {
  std::optional<base::ListValue> list = base::JSONReader::ReadList(json, base::JSON_PARSE_RFC);
  if (!list) {
    DLOG(ERROR) << "debounce rules are not a JSON list";
    return;
  }
  for (const base::Value& entry : *list) {
    if (!entry.is_dict()) {
      continue;
    }
    if (std::optional<Rule> rule = ParseRule(entry.GetDict())) {
      rules.push_back(std::move(*rule));
    } else {
      DLOG(WARNING) << "debounce rule skipped";
    }
  }
}

const std::vector<Rule>& Rules() {
  static const base::NoDestructor<std::vector<Rule>> rules([] {
    std::vector<Rule> all;
    AddRules(kBraveRulesJson, all);
    AddRules(kBoringRulesJson, all);
    return all;
  }());
  return *rules;
}

// Where this rule says `url` is going, or nothing when the rule does not
// cover it, or covers it but gives nothing usable.
std::optional<GURL> Apply(const Rule& rule,
                          const GURL& url,
                          std::string_view path_and_query) {
  const auto matches = [&](const Pattern& pattern) {
    return pattern.Matches(url, path_and_query);
  };
  if (!std::ranges::any_of(rule.include, matches) ||
      std::ranges::any_of(rule.exclude, matches)) {
    return std::nullopt;
  }
  switch (rule.action) {
    case Action::kRedirect: {
      std::string value;
      if (!UniqueQueryValue(url, rule.param, &value)) {
        return std::nullopt;
      }
      return MakeTarget(value, rule.prepend_scheme, url);
    }
    case Action::kBase64Redirect: {
      std::string value;
      if (!UniqueQueryValue(url, rule.param, &value)) {
        return std::nullopt;
      }
      std::optional<std::string> decoded = DecodeBase64(value);
      if (!decoded) {
        return std::nullopt;
      }
      return MakeTarget(*decoded, rule.prepend_scheme, url);
    }
    case Action::kRegexPath: {
      std::optional<std::vector<std::string>> captured =
          Capture(*rule.regex, path_and_query);
      if (!captured) {
        return std::nullopt;
      }
      std::string joined;
      for (const std::string& group : *captured) {
        if (HasEscapedControl(group)) {
          return std::nullopt;
        }
        joined += group;
      }
      // A single piece with no slash in it is an address that was
      // escaped whole, to fit in one path segment. A piece with slashes
      // is already a host and path, and decoding it would turn %2F into
      // a slash and change what it means.
      if (joined.find('/') == std::string::npos) {
        joined = DecodePathText(joined);
      }
      return MakeTarget(joined, rule.prepend_scheme, url);
    }
    case Action::kRegexPathTemplate: {
      std::optional<std::vector<std::string>> captured =
          Capture(*rule.regex, path_and_query);
      if (!captured) {
        return std::nullopt;
      }
      std::optional<std::string> expanded =
          ExpandTemplate(rule.url_template, *captured, /*probe=*/false);
      std::optional<std::string> probe =
          ExpandTemplate(rule.url_template, *captured, /*probe=*/true);
      if (!expanded || !probe) {
        return std::nullopt;
      }
      std::optional<GURL> target = MakeTarget(*expanded, "", url);
      // The template says which site this is. Whatever was captured must
      // not have moved it somewhere else.
      if (!target || target->host() != GURL(*probe).host()) {
        return std::nullopt;
      }
      return target;
    }
  }
  return std::nullopt;
}

// One step: the first rule that covers `url` and gives an address.
std::optional<GURL> Step(const GURL& url) {
  const std::string path_and_query = url.PathForRequest();
  for (const Rule& rule : Rules()) {
    if (std::optional<GURL> target = Apply(rule, url, path_and_query)) {
      return target;
    }
  }
  return std::nullopt;
}

}  // namespace

std::optional<GURL> Debounce(const GURL& url) {
  if (!url.is_valid() || !url.SchemeIsHTTPOrHTTPS() ||
      url.spec().size() > kMaxSpecLength) {
    return std::nullopt;
  }
  std::set<std::string> seen = {url.spec()};
  GURL current = url;
  for (int hop = 0; hop < kMaxHops; ++hop) {
    std::optional<GURL> next = Step(current);
    if (!next) {
      // Nothing covers this one: the end of the chain. It is a result
      // only if at least one step was taken.
      return hop == 0 ? std::nullopt : std::optional<GURL>(current);
    }
    // Back at an address already passed: a loop.
    if (!seen.insert(next->spec()).second) {
      return std::nullopt;
    }
    current = std::move(*next);
  }
  return std::nullopt;
}

}  // namespace boring
