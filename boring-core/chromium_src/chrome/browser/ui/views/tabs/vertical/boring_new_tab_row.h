// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_TABS_VERTICAL_BORING_NEW_TAB_ROW_H_
#define CHROME_BROWSER_UI_VIEWS_TABS_VERTICAL_BORING_NEW_TAB_ROW_H_

#include <memory>

#include "base/memory/raw_ptr.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/controls/button/button.h"

class BrowserWindowInterface;

namespace views {
class ActionViewController;
}  // namespace views

// The "New tab" row at the foot of the side tabs list (screen C09): 34 px
// high, a 1 px ring, a plus, the label, and the shortcut on the right. It
// runs Chromium's own new tab action, so it opens a tab exactly as the old
// button did. Shown when the list is wide; the narrow list keeps the button.
class BoringNewTabRow : public views::Button {
  METADATA_HEADER(BoringNewTabRow, views::Button)

 public:
  static constexpr int kHeight = 34;

  explicit BoringNewTabRow(BrowserWindowInterface* browser);
  BoringNewTabRow(const BoringNewTabRow&) = delete;
  BoringNewTabRow& operator=(const BoringNewTabRow&) = delete;
  ~BoringNewTabRow() override;

  // views::View:
  gfx::Size CalculatePreferredSize(
      const views::SizeBounds& available_size) const override;
  void OnThemeChanged() override;

 private:
  std::unique_ptr<views::ActionViewController> action_view_controller_;
};

#endif  // CHROME_BROWSER_UI_VIEWS_TABS_VERTICAL_BORING_NEW_TAB_ROW_H_
