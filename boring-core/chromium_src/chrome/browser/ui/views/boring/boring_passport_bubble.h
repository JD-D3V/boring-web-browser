// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_BUBBLE_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_BUBBLE_H_

#include <memory>
#include <string>
#include <vector>

#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "base/values.h"
#include "chrome/browser/ui/views/boring/boring_popup.h"
#include "components/boring/passport/passport_words.h"
#include "ui/views/view_tracker.h"
#include "ui/views/widget/widget.h"
#include "url/gurl.h"

class LocationIconView;

namespace content {
class WebContents;
}

namespace views {
class BubbleDialogDelegate;
class View;
}  // namespace views

// "Site passport": the pop-up under the address field's chip (screens C04
// and C05). A snapshot of the tab's facts when it opens; it changes only
// after its own buttons, and gains the card row if that answer comes late. A browser view: a page cannot open, close, press
// or draw into it, and every string in it is ours, a count, a month name,
// the committed origin's host formatted for security display, or a domain
// from the person's own site engagement.
class BoringPassportBubble {
 public:
  ~BoringPassportBubble();

  // Opens the Passport for the page under `icon` and returns true, or
  // returns false where there is none (no chip, or Blocked, which keeps
  // Chromium's page info).
  static bool Show(LocationIconView* icon);
  static bool IsShowingFor(const LocationIconView* icon);
  static BoringPassportBubble* GetShowing();
  // A fact the rows rest on changed for `contents` (a late card answer): an
  // open Passport for that tab's same page rebuilds its rows. The layout,
  // verdict and buttons stay as they were.
  static void FactsChangedFor(content::WebContents* contents);

  void Close();

  // Test only.
  base::DictValue StateForTesting() const;
  bool PressForTesting(const std::u16string& label);

 private:
  struct Row {
    std::u16string text;
    std::string icon;
    std::string color;
  };

  BoringPassportBubble(LocationIconView* icon,
                       content::WebContents* contents,
                       boring::passport::Chip layout);

  std::vector<Row> MakeRows(content::WebContents* contents) const;
  std::unique_ptr<views::View> MakeContents();
  void FillFacts();
  void ShowButtons();
  void ShowQuestion();
  void Press(const std::u16string& label);
  void OnCloseRequested(views::Widget::ClosedReason reason);
  void OnClosed();

  views::ViewTracker icon_;
  base::WeakPtr<content::WebContents> contents_;
  const boring::passport::Chip layout_;
  GURL url_;
  std::u16string verdict_;
  std::u16string host_;
  std::vector<Row> rows_;
  std::u16string footer_;
  bool asking_ = false;
  raw_ptr<views::View> facts_view_ = nullptr;
  raw_ptr<views::View> button_row_ = nullptr;
  std::unique_ptr<views::BubbleDialogDelegate> delegate_;
  std::unique_ptr<views::Widget> widget_;
  boring_ui::PopupMotion motion_{boring_ui::PopupMotion::Style::kDrop};
  base::WeakPtrFactory<BoringPassportBubble> weak_factory_{this};
};

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_PASSPORT_BUBBLE_H_
