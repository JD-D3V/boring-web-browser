// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/side_panel/boring_shelf/boring_shelf_coordinator.h"

#include <memory>
#include <utility>

#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/side_panel/side_panel_entry.h"
#include "chrome/browser/ui/side_panel/side_panel_entry_scope.h"
#include "chrome/browser/ui/side_panel/side_panel_registry.h"
#include "chrome/browser/ui/side_panel/side_panel_ui.h"
#include "chrome/browser/ui/views/side_panel/boring_shelf/boring_shelf_view.h"

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
  if (SidePanelUI* ui = SidePanelUI::From(browser)) {
    ui->Toggle(ShelfKey(), SidePanelOpenTrigger::kToolbarButton);
  }
}

bool IsShelfShowing(BrowserWindowInterface* browser) {
  SidePanelUI* ui = browser ? SidePanelUI::From(browser) : nullptr;
  return ui && ui->IsSidePanelEntryShowing(ShelfKey());
}

}  // namespace boring::shelf
