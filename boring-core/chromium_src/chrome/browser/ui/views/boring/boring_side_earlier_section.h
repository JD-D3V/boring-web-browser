// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_SIDE_EARLIER_SECTION_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_SIDE_EARLIER_SECTION_H_

#include <string>

#include "base/callback_list.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "chrome/browser/ui/tabs/vertical_tab_strip_state_controller.h"
#include "chrome/browser/ui/views/boring/boring_earlier_tabs_service.h"
#include "components/prefs/pref_change_registrar.h"
#include "ui/base/metadata/metadata_header_macros.h"
#include "ui/views/view.h"

class BrowserWindowInterface;

// The "Earlier" section of the side tabs list (screen C09, ledger items 14 and
// 16): the heading "Earlier" with "kept 30 days" at the right, the newest
// Earlier tab, and "Show all N". It sits in the vertical strip above the New
// tab row, because with side tabs there is no Earlier chip and the Shelf side
// panel stays closed.
//
// Built from the Shelf's own pieces (ShelfSectionHeading, ShelfRow,
// GetEarlierState). A row reopens its tab through EarlierTabsService::Reopen,
// exactly as the Shelf's rows and the pop-up's rows do. Titles are page text
// shown in plain labels (ShelfTitle cleans them), never as markup.
//
// Shown only while Earlier tabs is switched on, the list holds at least one
// tab and the strip is wide. A private or guest window has no service and so
// never shows it.
class BoringSideEarlierSection
    : public views::View,
      public boring::earlier::EarlierTabsService::Observer {
  METADATA_HEADER(BoringSideEarlierSection, views::View)

 public:
  BoringSideEarlierSection(BrowserWindowInterface* browser,
                           tabs::VerticalTabStripStateController* controller);
  BoringSideEarlierSection(const BoringSideEarlierSection&) = delete;
  BoringSideEarlierSection& operator=(const BoringSideEarlierSection&) = delete;
  ~BoringSideEarlierSection() override;

  // IDC_BORING_SHOW_EARLIER with side tabs: widen the strip if it is narrow
  // and put focus on the newest row. False when the window has no section
  // (a private window) or nothing is in Earlier.
  static bool RevealFor(BrowserWindowInterface* browser);
  // IDC_BORING_EARLIER_SHOW_ALL with side tabs: the section lists every row
  // it can hold, in a scrolling box, and is revealed.
  static bool ShowAllFor(BrowserWindowInterface* browser);

  // The newest rows shown before "Show all": screen C09 draws one.
  static constexpr size_t kNewestRows = 1;
  // Opened out, the rows scroll inside this many rows of height.
  static constexpr int kMaxVisibleRows = 8;

  // boring::earlier::EarlierTabsService::Observer:
  void OnEarlierTabsChanged() override;

  // views::View:
  void AddedToWidget() override;

 private:
  void OnCollapseChanged(tabs::VerticalTabStripCollapseState state);
  void ScheduleRebuild();
  void Rebuild();
  void Reveal(bool focus);
  void ShowAll();
  void OnRow(const std::string& id);
  // "Clear earlier tabs" at the end of the opened-out section: asks first,
  // then clears, the same way as the pop-up (BoringEarlierClearQuestion,
  // BoringEarlierClearAll).
  void OnAskClear();
  void OnCancelClear();
  void OnClear();
  void AddClearFooter(size_t total);
  bool IsWide() const;

  const raw_ptr<BrowserWindowInterface> browser_;
  const raw_ptr<tabs::VerticalTabStripStateController> controller_;
  raw_ptr<boring::earlier::EarlierTabsService> service_ = nullptr;
  PrefChangeRegistrar pref_registrar_;
  base::CallbackListSubscription collapse_subscription_;
  raw_ptr<views::View> first_row_ = nullptr;
  bool expanded_ = false;
  bool confirming_ = false;
  bool focus_pending_ = false;
  bool rebuild_pending_ = false;
  base::WeakPtrFactory<BoringSideEarlierSection> weak_factory_{this};
};

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_SIDE_EARLIER_SECTION_H_
