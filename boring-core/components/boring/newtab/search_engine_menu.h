// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_NEWTAB_SEARCH_ENGINE_MENU_H_
#define COMPONENTS_BORING_NEWTAB_SEARCH_ENGINE_MENU_H_

#include <string>

#include "base/functional/callback.h"
#include "base/values.h"
#include "ui/gfx/geometry/rect.h"

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

// Shows the browser's search engine menu under `anchor_in_page`, a
// rectangle in `page`'s own CSS pixels. `on_pick` gets the keyword of an
// engine chosen to search with once; `on_default_changed` runs after
// "Make default"; `on_closed` when the menu has rolled up. False when
// `page` is not in a browser window with an address bar.
bool ShowSearchEngineMenuForPage(
    content::WebContents* page,
    const gfx::Rect& anchor_in_page,
    base::RepeatingCallback<void(const std::string&)> on_pick,
    base::RepeatingClosure on_default_changed,
    base::OnceClosure on_closed);

// Runs one test command, see kSearchMenuTestSwitch. Returns none
// without the switch.
base::Value RunSearchEngineMenuTestCommand(content::WebContents* page,
                                           const base::ListValue& args);

}  // namespace boring

#endif  // COMPONENTS_BORING_NEWTAB_SEARCH_ENGINE_MENU_H_
