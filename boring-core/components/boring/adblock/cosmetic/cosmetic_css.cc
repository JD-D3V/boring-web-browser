// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/cosmetic/cosmetic_css.h"

#include <algorithm>
#include <cctype>

namespace boring {

namespace {

// True if brackets and quotes in `css` all close, and it holds no brace
// or comment that could end a rule or swallow the ones after it.
bool IsSelfContained(std::string_view css) {
  if (css.find("/*") != std::string_view::npos) {
    return false;
  }
  char quote = 0;
  int parens = 0;
  int brackets = 0;
  for (size_t i = 0; i < css.size(); ++i) {
    const char c = css[i];
    if (c == '\\') {
      // An escape at the very end would escape whatever we append.
      if (i + 1 == css.size()) {
        return false;
      }
      ++i;
      continue;
    }
    if (quote) {
      if (c == quote) {
        quote = 0;
      } else if (c == '\n' || c == '\r' || c == '\f') {
        return false;
      }
      continue;
    }
    switch (c) {
      case '"':
      case '\'':
        quote = c;
        break;
      case '(':
        ++parens;
        break;
      case ')':
        if (--parens < 0) {
          return false;
        }
        break;
      case '[':
        ++brackets;
        break;
      case ']':
        if (--brackets < 0) {
          return false;
        }
        break;
      case '{':
      case '}':
        return false;
      default:
        break;
    }
  }
  return quote == 0 && parens == 0 && brackets == 0;
}

bool ContainsIgnoringCase(std::string_view text, std::string_view needle) {
  return std::search(text.begin(), text.end(), needle.begin(), needle.end(),
                     [](char a, char b) {
                       return std::tolower(static_cast<unsigned char>(a)) ==
                              std::tolower(static_cast<unsigned char>(b));
                     }) != text.end();
}

}  // namespace

bool IsSafeSelector(std::string_view selector) {
  const size_t start = selector.find_first_not_of(" \t\r\n\f");
  if (start == std::string_view::npos) {
    return false;
  }
  // A leading @ would turn the rule into an at-rule.
  if (selector[start] == '@') {
    return false;
  }
  return IsSelfContained(selector);
}

bool IsSafeDeclarations(std::string_view declarations) {
  if (declarations.find_first_not_of(" \t\r\n\f;") == std::string_view::npos) {
    return false;
  }
  if (declarations.find('\\') != std::string_view::npos ||
      ContainsIgnoringCase(declarations, "url(") ||
      ContainsIgnoringCase(declarations, "image-set(")) {
    return false;
  }
  return IsSelfContained(declarations);
}

std::string BuildRules(const std::vector<std::string>& selectors,
                       std::string_view declarations) {
  std::string css;
  for (const std::string& selector : selectors) {
    if (!IsSafeSelector(selector)) {
      continue;
    }
    css.append(selector);
    css.push_back('{');
    css.append(declarations);
    css.append("}\n");
  }
  return css;
}

}  // namespace boring
