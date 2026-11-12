// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_BORING_LAYOUT_CONSTANTS_H_
#define CHROME_BROWSER_UI_BORING_LAYOUT_CONSTANTS_H_

// Our own sizes for the browser window, in one place. GetLayoutConstant()
// and GetLayoutInsets() in layout_constants.cc ask here first and fall back
// to Chromium's value when we return nothing (layout-constants.patch).
// Touch mode always keeps Chromium's sizes.

#include <optional>

#include "chrome/browser/ui/layout_constants.h"
#include "ui/gfx/geometry/insets.h"

namespace boring {

inline std::optional<int> LayoutConstantOverride(LayoutConstant constant,
                                                 bool touch_ui) {
  if (touch_ui) {
    return std::nullopt;
  }
  // The round 32 DIP toolbar buttons of the approved mock (Chromium: 34).
  if (constant == LayoutConstant::kToolbarButtonHeight) {
    return 32;
  }
  // 10 DIP either side of the address field (Chromium: 9).
  if (constant == LayoutConstant::kLocationBarMargin) {
    return 10;
  }
  return std::nullopt;
}

inline std::optional<gfx::Insets> LayoutInsetsOverride(LayoutInset inset,
                                                       bool touch_ui) {
  if (touch_ui) {
    return std::nullopt;
  }
  // 6 DIP around the 20 DIP glyph, so a toolbar button is 32 DIP square
  // (Chromium: 7). ToolbarButton::GetTargetSize() derives from this.
  if (inset == TOOLBAR_BUTTON) {
    return gfx::Insets(6);
  }
  return std::nullopt;
}

}  // namespace boring

#endif  // CHROME_BROWSER_UI_BORING_LAYOUT_CONSTANTS_H_
