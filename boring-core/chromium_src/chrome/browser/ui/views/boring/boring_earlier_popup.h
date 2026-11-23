// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_EARLIER_POPUP_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_EARLIER_POPUP_H_

#include <memory>

#include "base/functional/callback.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/ui/views/boring/boring_earlier_tabs_service.h"
#include "ui/color/color_id.h"
#include "ui/views/bubble/bubble_dialog_delegate_view.h"
#include "ui/views/controls/button/button.h"
#include "ui/views/widget/widget.h"

class BrowserWindowInterface;

namespace views {
class LabelButton;
class View;
}

// Shared by the pop-up and the side tabs Earlier section, so both clear the
// list the same way: the footer's text button (32 high, as wide as its text;
// `strong` for the medium weight), the question "Clear earlier tabs" asks
// before anything goes, and the clear itself.
std::unique_ptr<views::LabelButton> BoringEarlierTextButton(
    views::Button::PressedCallback callback,
    const std::u16string& text,
    ui::ColorId color,
    bool strong);
std::u16string BoringEarlierClearQuestion(size_t total);
void BoringEarlierClearAll(boring::earlier::EarlierTabsService* service);

// The "Earlier tabs" pop-up (screen C08), under the chip. A browser view, not
// a page: nothing a page does can open, press or draw into it. Titles are
// page text and are shown in plain labels, one line, elided; the site under a
// title is the address formatted for security display.
//
// Rows open a tab through EarlierTabsService::Reopen. "Show all" opens the
// Shelf with Earlier expanded. "Clear earlier tabs" asks once, inside the
// pop-up, then empties the list.
class BoringEarlierPopup : public boring::earlier::EarlierTabsService::Observer {
 public:
  // `closed` is posted, not run, when the pop-up has closed, so the owner may
  // delete this object from it.
  BoringEarlierPopup(views::View* anchor,
                     BrowserWindowInterface* browser,
                     base::OnceClosure closed);
  BoringEarlierPopup(const BoringEarlierPopup&) = delete;
  BoringEarlierPopup& operator=(const BoringEarlierPopup&) = delete;
  ~BoringEarlierPopup() override;

  void Show();
  void Close();

  // boring::earlier::EarlierTabsService::Observer:
  void OnEarlierTabsChanged() override;

 private:
  void Rebuild();
  void ScheduleRebuild();
  void OnRow(const std::string& id);
  void OnShowAll();
  void OnAskClear();
  void OnCancelClear();
  void OnClear();
  void OnCloseRequested(views::Widget::ClosedReason reason);

  raw_ptr<BrowserWindowInterface> browser_;
  raw_ptr<boring::earlier::EarlierTabsService> service_;
  base::OnceClosure closed_;
  bool confirming_ = false;
  bool rebuild_pending_ = false;
  std::unique_ptr<views::BubbleDialogDelegate> delegate_;
  std::unique_ptr<views::Widget> widget_;
  raw_ptr<views::View> contents_ = nullptr;
  base::WeakPtrFactory<BoringEarlierPopup> weak_factory_{this};
};

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_EARLIER_POPUP_H_
