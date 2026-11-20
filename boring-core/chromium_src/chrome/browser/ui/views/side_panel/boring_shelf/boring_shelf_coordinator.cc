// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/side_panel/boring_shelf/boring_shelf_coordinator.h"

#include <memory>
#include <utility>

#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/side_panel/side_panel_entry.h"
#include "chrome/browser/ui/side_panel/side_panel_entry_scope.h"
#include "chrome/browser/ui/side_panel/side_panel_registry.h"
#include "chrome/browser/ui/side_panel/side_panel_ui.h"
#include "chrome/browser/ui/views/side_panel/boring_shelf/boring_shelf_view.h"
#include "chrome/common/pref_names.h"
#include "components/prefs/pref_service.h"

namespace boring::shelf {

namespace {

SidePanelEntryKey ShelfKey() {
  return SidePanelEntryKey(SidePanelEntryId::kBoringShelf);
}

SidePanelNativeView CreateShelfView(SidePanelEntryScope& scope) {
  return std::make_unique<BoringShelfView>(&scope.GetBrowserWindowInterface());
}

int ShelfWidth() {
  return kShelfWidth;
}

}  // namespace

bool WindowHasShelf(BrowserWindowInterface* browser) {
  return browser && browser->GetType() == BrowserWindowInterface::TYPE_NORMAL;
}

void RegisterShelfEntry(BrowserWindowInterface* browser,
                        SidePanelRegistry* window_registry) {
  if (!WindowHasShelf(browser)) {
    return;
  }
  auto entry = std::make_unique<SidePanelEntry>(
      ShelfKey(), base::BindRepeating(&CreateShelfView),
      base::BindRepeating(&ShelfWidth));
  // No title, no pin, no close mark: the screen draws none. The toggle in
  // the tab strip is the way to close it.
  entry->set_should_show_header(false);
  window_registry->Register(std::move(entry));
}

void ToggleShelf(BrowserWindowInterface* browser) {
  if (!WindowHasShelf(browser)) {
    return;
  }
  // With side tabs (item 14) the list is the Shelf: the command narrows it
  // to icons and widens it again, so the Shelf is one thing in both modes.
  if (browser->GetProfile()->GetPrefs()->GetBoolean(
          prefs::kVerticalTabsEnabled)) {
    chrome::ExecuteCommand(browser, IDC_TOGGLE_VERTICAL_TABS_COLLAPSE);
    return;
  }
  if (SidePanelUI* ui = SidePanelUI::From(browser)) {
    ui->Toggle(ShelfKey(), SidePanelOpenTrigger::kToolbarButton);
  }
}

void ShowShelfWithEarlier(BrowserWindowInterface* browser) {
  if (!WindowHasShelf(browser) ||
      browser->GetProfile()->GetPrefs()->GetBoolean(
          prefs::kVerticalTabsEnabled)) {
    return;
  }
  BoringShelfView::ExpandEarlierFor(browser);
  if (SidePanelUI* ui = SidePanelUI::From(browser)) {
    ui->Show(ShelfKey());
  }
}

bool IsShelfShowing(BrowserWindowInterface* browser) {
  SidePanelUI* ui = browser ? SidePanelUI::From(browser) : nullptr;
  return ui && ui->IsSidePanelEntryShowing(ShelfKey());
}

void CloseShelf(BrowserWindowInterface* browser) {
  if (!IsShelfShowing(browser)) {
    return;
  }
  // The Shelf is the entry showing, so this closes the Shelf only.
  SidePanelUI::From(browser)->Close();
}

}  // namespace boring::shelf
