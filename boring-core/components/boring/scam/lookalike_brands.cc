// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/lookalike_brands.h"

#include <cstddef>
#include <string>
#include <string_view>
#include <vector>

namespace boring {

namespace {

struct Brand {
  std::string_view name;
  std::string_view domain;
};

constexpr Brand kBrands[] = {
#include "components/boring/scam/lookalike_brands.inc"
};

// Shorter than this, a name is too likely to be an ordinary word.
constexpr size_t kMinLength = 4;

bool IsNameCharacter(char c) {
  return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-';
}

// How the name reads at a glance: "rn" is m, "vv" is w, 0 is o. A 1 is an
// l or an i, so the caller says which (`one`) and tries both.
std::string Skeleton(std::string_view name, char one) {
  std::string out;
  out.reserve(name.size());
  for (size_t i = 0; i < name.size(); ++i) {
    const char c = name[i];
    const char next = i + 1 < name.size() ? name[i + 1] : '\0';
    if (c == 'r' && next == 'n') {
      out.push_back('m');
      ++i;
    } else if (c == 'v' && next == 'v') {
      out.push_back('w');
      ++i;
    } else if (c == '0') {
      out.push_back('o');
    } else if (c == '1') {
      out.push_back(one);
    } else {
      out.push_back(c);
    }
  }
  return out;
}

// One spelling of the name to compare, and the text the person would be
// looking at when they read it. The text is what must differ from the
// brand: "paypal" in "paypal-support" is the brand's own name, but
// "pay-pal" as one name is not.
struct Candidate {
  std::string form;
  std::string_view shown;
};

std::vector<Candidate> Candidates(std::string_view label) {
  std::vector<Candidate> out;
  out.push_back({std::string(label), label});
  if (label.find('-') == std::string_view::npos) {
    return out;
  }
  std::string joined;
  size_t start = 0;
  for (;;) {
    const size_t dash = label.find('-', start);
    const std::string_view token = label.substr(
        start, dash == std::string_view::npos ? dash : dash - start);
    if (!token.empty()) {
      joined.append(token);
      out.push_back({std::string(token), token});
    }
    if (dash == std::string_view::npos) {
      break;
    }
    start = dash + 1;
  }
  out.push_back({joined, label});
  return out;
}

}  // namespace

std::string FindLookalikeBrand(std::string_view registrable_domain) {
  for (const Brand& brand : kBrands) {
    if (registrable_domain == brand.domain) {
      return std::string();
    }
  }
  const std::string_view label =
      registrable_domain.substr(0, registrable_domain.find('.'));
  if (label.size() < kMinLength) {
    return std::string();
  }
  for (const char c : label) {
    if (!IsNameCharacter(c)) {
      return std::string();
    }
  }
  // "xn--" names are other alphabets: Chromium's checks do those.
  if (label.find("xn--") != std::string_view::npos) {
    return std::string();
  }

  for (const Candidate& candidate : Candidates(label)) {
    if (candidate.form.size() < kMinLength) {
      continue;
    }
    const std::string as_l = Skeleton(candidate.form, 'l');
    const bool has_one = candidate.form.find('1') != std::string::npos;
    const std::string as_i = has_one ? Skeleton(candidate.form, 'i') : as_l;
    for (const Brand& brand : kBrands) {
      if (candidate.shown == brand.name) {
        continue;
      }
      const std::string brand_skeleton = Skeleton(brand.name, 'l');
      if (as_l == brand_skeleton || as_i == brand_skeleton) {
        return std::string(brand.domain);
      }
    }
  }
  return std::string();
}

}  // namespace boring
