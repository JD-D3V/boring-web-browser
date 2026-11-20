// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_CHIP_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_CHIP_H_

#include <optional>
#include <string>

#include "components/boring/passport/passport_words.h"
#include "third_party/skia/include/core/SkColor.h"
#include "ui/base/models/image_model.h"
#include "ui/gfx/font_list.h"
#include "ui/gfx/geometry/insets.h"

class LocationBarView;
class LocationIconView;

// The Passport's chip at the left end of the address field: Known site,
// New to you, Blocked or Scam list, in place of Chromium's page icon on web
// pages. Each function is one line in location_icon_view.cc (passport.patch);
// where no chip of ours applies they leave Chromium's icon as it was.
class PassportChip {
 public:
  // The chip drawn now, and the Passport layout a press opens.
  static boring::passport::Chip ChipFor(const LocationIconView* icon);
  static boring::passport::Chip LayoutFor(const LocationIconView* icon);

  static bool Applies(const LocationIconView* icon);
  // Empty where no chip applies, so Chromium's text is used.
  static std::u16string Text(const LocationIconView* icon);
  static std::optional<SkColor> Foreground(const LocationIconView* icon);
  // After Chromium's background: the chip's fill, outline and corners, and
  // its word in 13px semibold (`font` is the icon's current one).
  static void StyleBackground(LocationIconView* icon, const gfx::FontList& font);
  // The drawn chip is 28 high; the address field gives its icon `height`
  // (24 in a 34 field). Where a chip applies and there is room, 28.
  static int HeightFor(const LocationIconView* icon, int height);
  // The drawn chip's padding, 0 10, in place of Chromium's insets.
  static void AdjustInsets(const LocationIconView* icon, gfx::Insets* insets);
  // The chip's dot where a chip applies.
  static std::optional<ui::ImageModel> Dot(const LocationIconView* icon);
  // After Chromium's: a button named by the chip, that opens a dialog.
  static void UpdateAccessibility(LocationIconView* icon);

  static LocationBarView* BarFor(const LocationIconView* icon);
};

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_CHIP_H_
