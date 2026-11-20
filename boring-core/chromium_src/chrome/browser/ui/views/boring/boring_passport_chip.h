// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_CHIP_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_CHIP_H_

#include <optional>
#include <string>

#include "components/boring/passport/passport_words.h"
#include "third_party/skia/include/core/SkColor.h"
#include "ui/base/models/image_model.h"

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
  // After Chromium's background: the chip's fill, outline and corners.
  static void StyleBackground(LocationIconView* icon);
  // The chip's dot where a chip applies.
  static std::optional<ui::ImageModel> Dot(const LocationIconView* icon);
  // After Chromium's: a button named by the chip, that opens a dialog.
  static void UpdateAccessibility(LocationIconView* icon);

  static LocationBarView* BarFor(const LocationIconView* icon);
};

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_CHIP_H_
