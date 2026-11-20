// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_BORING_SHELF_COORDINATOR_H_
#define CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_BORING_SHELF_COORDINATOR_H_

class BrowserWindowInterface;
class SidePanelRegistry;

// Registers the Shelf as a side panel entry and opens and closes it. Free
// functions: the entry holds no state of its own, the view does.
namespace boring::shelf {

// The Shelf's fixed width, as drawn on screen C03.
inline constexpr int kShelfWidth = 248;

// Adds the Shelf to the window's registry. Only a normal window gets one:
// app and pop-up windows have no Shelf.
void RegisterShelfEntry(BrowserWindowInterface* browser,
                        SidePanelRegistry* window_registry);

// Opens the Shelf, or closes it when it is the panel showing.
void ToggleShelf(BrowserWindowInterface* browser);

bool IsShelfShowing(BrowserWindowInterface* browser);

// "Show all" in the Earlier pop-up: opens the Shelf with Earlier out to every
// entry. With side tabs the strip is the Shelf and is left as it is.
void ShowShelfWithEarlier(BrowserWindowInterface* browser);

// True when this kind of window has a Shelf.
bool WindowHasShelf(BrowserWindowInterface* browser);

}  // namespace boring::shelf

#endif  // CHROME_BROWSER_UI_VIEWS_SIDE_PANEL_BORING_SHELF_BORING_SHELF_COORDINATOR_H_
