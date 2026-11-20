// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_FRAME_BORING_SHELF_TOGGLE_H_
#define CHROME_BROWSER_UI_VIEWS_FRAME_BORING_SHELF_TOGGLE_H_

#include "base/callback_list.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/controls/button/image_button.h"

class BrowserWindowInterface;

// The Shelf's toggle, first thing in the tab strip (screen C03): a 32 by 30
// button, 7 px corners, a box with a left column drawn 16 px. Open: the ink
// on the line2 wash. Closed: the quiet ink on nothing.
class BoringShelfToggle : public views::ImageButton {
  METADATA_HEADER(BoringShelfToggle, views::ImageButton)

 public:
  static constexpr int kWidth = 32;
  static constexpr int kHeight = 30;
  // The divider after it: 8 px, a 1 px line, 8 px.
  static constexpr int kDividerGap = 8;
  // 8 in from the window edge, then the toggle, then the divider block
  // (8, a 1 px line, 8): the width the tab strip's left margin makes room for.
  static constexpr int kLeadingPadding = 8;
  static constexpr int kLeadingWidth =
      kLeadingPadding + kWidth + kDividerGap + 1 + kDividerGap;

  explicit BoringShelfToggle(BrowserWindowInterface* browser);
  BoringShelfToggle(const BoringShelfToggle&) = delete;
  BoringShelfToggle& operator=(const BoringShelfToggle&) = delete;
  ~BoringShelfToggle() override;

  // views::View:
  gfx::Size CalculatePreferredSize(
      const views::SizeBounds& available_size) const override;
  void AddedToWidget() override;
  void OnThemeChanged() override;

 private:
  void OnPressed();
  // Follows the side panel: whether the Shelf is what it is showing.
  void SyncWithPanel();
  void SetPressedLook(bool pressed);

  raw_ptr<BrowserWindowInterface> browser_;
  bool pressed_ = false;
  base::CallbackListSubscription shown_subscription_;
  base::WeakPtrFactory<BoringShelfToggle> weak_factory_{this};
};

#endif  // CHROME_BROWSER_UI_VIEWS_FRAME_BORING_SHELF_TOGGLE_H_
