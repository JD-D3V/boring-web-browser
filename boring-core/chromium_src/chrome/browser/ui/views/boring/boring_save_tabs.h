// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_SAVE_TABS_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_SAVE_TABS_H_

#include <string>

#include "base/time/time.h"

class BrowserWindowInterface;

namespace boring {

// "Save all tabs", from the app menu and the tab menu. One click saves
// every open tab of every window of `browser`'s profile as plain
// bookmarks, in a new folder under Other bookmarks named for the date
// and time, with one folder per window when there is more than one. New
// tab pages and blank tabs are left out. Then a small dialog says where
// they went, with a button that opens the folder on the bookmarks page.
// Nothing is saved, and nothing is shown, when no tab has a page.
void SaveAllTabs(BrowserWindowInterface* browser);

// The new folder's name: "Tabs " and the short local date and time.
std::u16string SavedTabsFolderName(base::Time when);

}  // namespace boring

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_SAVE_TABS_H_
