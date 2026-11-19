// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_NEWTAB_SEARCH_ENGINE_MENU_H_
#define COMPONENTS_BORING_NEWTAB_SEARCH_ENGINE_MENU_H_

#include <string>
#include <vector>

#include "base/functional/callback.h"
#include "base/time/time.h"
#include "base/values.h"
#include "url/gurl.h"

namespace base {
class CancelableTaskTracker;
}

namespace content {
class WebContents;
}

namespace boring {

// Test only. With this switch the new tab page takes "searchMenuTest"
// messages, which smoke_search_menu.py uses to open and drive the menu
// without any input from the OS.
inline constexpr char kSearchMenuTestSwitch[] = "boring-search-menu-test";

// Declared here for the new tab page and defined in
// chrome/browser/ui/views/boring/boring_search_engine_menu.cc, which is
// built into chrome/browser/ui (the menu is a browser window's native
// menu, which components/boring cannot reach). The same split as
// components/boring/search/search_engines.h.

// Runs one test command, see kSearchMenuTestSwitch. Returns none
// without the switch.
base::Value RunSearchEngineMenuTestCommand(content::WebContents* page,
                                           const base::ListValue& args);

// One page from history, for the new tab page's "Pick up where you left
// off".
struct RecentPage {
  GURL url;
  std::u16string title;
  base::Time when;
};

// Up to `max` of the most recent web pages (http and https only) in the
// history of the profile that holds `page`, newest first, one per
// address. Empty in Incognito, which shows none. `tracker` cancels the
// query, and `done` with it, when the page goes away.
void GetRecentPagesForPage(
    content::WebContents* page,
    size_t max,
    base::CancelableTaskTracker* tracker,
    base::OnceCallback<void(std::vector<RecentPage>)> done);

}  // namespace boring

#endif  // COMPONENTS_BORING_NEWTAB_SEARCH_ENGINE_MENU_H_
