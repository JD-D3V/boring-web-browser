// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_EARLIER_CHIP_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_EARLIER_CHIP_H_

#include <memory>

#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/ui/views/boring/boring_earlier_tabs_service.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/controls/button/button.h"

class BoringEarlierPopup;
class BrowserWindowInterface;

namespace views {
class Label;
}

// The Earlier chip (screen C08): a clock, the word "Earlier" and the count,
// at the end of the tabs just before the New tab button. Hidden while the
// list is empty. Pressing it opens the pop-up.
class BoringEarlierChip : public views::Button,
                          public boring::earlier::EarlierTabsService::Observer {
  METADATA_HEADER(BoringEarlierChip, views::Button)

 public:
  static constexpr int kHeight = 26;
  // The space left of the chip and under it, as drawn (margin 0 0 4 8).
  static constexpr int kLeftMargin = 8;
  static constexpr int kBottomMargin = 4;

  explicit BoringEarlierChip(BrowserWindowInterface* browser);
  BoringEarlierChip(const BoringEarlierChip&) = delete;
  BoringEarlierChip& operator=(const BoringEarlierChip&) = delete;
  ~BoringEarlierChip() override;

  // The room the chip takes in the tab strip row: its width and the left
  // margin, or 0 while it is hidden.
  int LayoutWidth() const;

  // Opens the pop-up of the chip in this window, when it has one showing.
  static void ShowPopupFor(BrowserWindowInterface* browser);

  // Opens the pop-up (the chip must be showing).
  void ShowPopup();
  bool IsPopupShowing() const { return popup_ != nullptr; }

  // boring::earlier::EarlierTabsService::Observer:
  void OnEarlierTabsChanged() override;

  // views::Button:
  gfx::Size CalculatePreferredSize(
      const views::SizeBounds& available_size) const override;
  void OnThemeChanged() override;
  void AddedToWidget() override;

 private:
  void Update();
  void OnPressed();
  void OnPopupClosed();
  void UpdateLook();

  raw_ptr<BrowserWindowInterface> browser_;
  raw_ptr<boring::earlier::EarlierTabsService> service_;
  raw_ptr<views::Label> count_label_ = nullptr;
  std::unique_ptr<BoringEarlierPopup> popup_;
  // --boring-open-earlier: open the pop-up the first time there is a chip.
  bool open_pending_ = false;
  base::WeakPtrFactory<BoringEarlierChip> weak_factory_{this};
};

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_EARLIER_CHIP_H_
