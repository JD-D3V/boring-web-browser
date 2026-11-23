// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_SHELF_ROW_H_
#define CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_SHELF_ROW_H_

#include <string>

#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/controls/button/button.h"
#include "ui/views/view.h"

namespace gfx {
struct VectorIcon;
}

namespace views {
class ImageView;
class Label;
}  // namespace views

namespace boring::shelf {

// Views for the Shelf (screen C03). They know nothing about side panels, so
// the side tabs list (item 14) uses them too.

// A section heading: the name on the left and an optional note on the right
// ("kept 30 days"). 11.5 px 600 in the quiet ink, as drawn.
class ShelfSectionHeading : public views::View {
  METADATA_HEADER(ShelfSectionHeading, views::View)

 public:
  // `regular`: the heading in the regular weight, for the side tabs list,
  // where text on the tab strip draws heavier than in the Shelf.
  ShelfSectionHeading(const std::u16string& heading,
                      const std::u16string& note,
                      bool regular = false);
  ShelfSectionHeading(const ShelfSectionHeading&) = delete;
  ShelfSectionHeading& operator=(const ShelfSectionHeading&) = delete;
  ~ShelfSectionHeading() override;
};

// One row: a 15 px icon, a one-line title that elides, and a meta on the
// right. 32 px high with a 10 px gap (the Earlier pop-up draws 34 and 12),
// 7 px corners, a wash behind it on hover.
class ShelfRow : public views::Button {
  METADATA_HEADER(ShelfRow, views::Button)

 public:
  static constexpr int kHeight = 32;
  static constexpr int kGap = 10;

  ShelfRow(PressedCallback callback,
           const gfx::VectorIcon& icon,
           const std::u16string& title,
           const std::u16string& meta,
           int height = kHeight,
           int gap = kGap);
  ShelfRow(const ShelfRow&) = delete;
  ShelfRow& operator=(const ShelfRow&) = delete;
  ~ShelfRow() override;

  // views::Button:
  void StateChanged(ButtonState old_state) override;
  void OnThemeChanged() override;

 private:
  void UpdateBackground();
};

// A Pinned tile: 40 px high, 8 px corners, the site's letter, no other text.
// The site's title is its accessible name and tooltip.
class ShelfTile : public views::Button {
  METADATA_HEADER(ShelfTile, views::Button)

 public:
  static constexpr int kHeight = 40;

  // The mark is the one letter the new tab page shows for the same site.
  ShelfTile(PressedCallback callback,
            const std::u16string& mark,
            const std::u16string& title);
  ShelfTile(const ShelfTile&) = delete;
  ShelfTile& operator=(const ShelfTile&) = delete;
  ~ShelfTile() override;

  // views::Button:
  void StateChanged(ButtonState old_state) override;
  void OnThemeChanged() override;

 private:
  void UpdateBackground();
};

}  // namespace boring::shelf

#endif  // CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_SHELF_ROW_H_
