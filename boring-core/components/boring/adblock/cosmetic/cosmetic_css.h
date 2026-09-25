// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_COSMETIC_COSMETIC_CSS_H_
#define COMPONENTS_BORING_ADBLOCK_COSMETIC_COSMETIC_CSS_H_

#include <string>
#include <string_view>
#include <vector>

namespace boring {

// Selectors and styles come from filter lists and end up in one user
// stylesheet with a rule each. A rule that is merely invalid is dropped
// by the CSS parser on its own, but one that is malformed in the wrong
// way (an unclosed bracket or string, a brace, a comment) changes how
// every rule after it parses, and could hide far more than it names.
// These checks keep those out.

// True if `selector` is safe to use as a rule's selector.
bool IsSafeSelector(std::string_view selector);

// True if `declarations` is safe inside a rule's braces. Also refuses
// anything that would load a resource, as adblock-rust does.
bool IsSafeDeclarations(std::string_view declarations);

// One "selector{declarations}" rule per safe selector. One rule each,
// not one combined rule, because a single invalid selector in a
// selector list drops the whole rule.
std::string BuildRules(const std::vector<std::string>& selectors,
                       std::string_view declarations);

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_COSMETIC_COSMETIC_CSS_H_
