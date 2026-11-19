// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_BORING_BORING_APP_MENU_H_
#define CHROME_BROWSER_UI_VIEWS_BORING_BORING_APP_MENU_H_

#include <stddef.h>

#include "base/functional/callback.h"

namespace gfx {
class FontList;
}

namespace ui {
class ButtonMenuItemModel;
}

namespace views {
class MenuItemView;
}

// The main menu's look: a row of tiles on top, rows in filled cards under
// plain headings, and a bar along the bottom (design/v9-menu, mockup A).
// AppMenu (app_menu.cc) builds the menu as before and calls these.
namespace boring {

// Runs a button's command: the model it belongs to and its index there.
using AppMenuPress =
    base::RepeatingCallback<void(ui::ButtonMenuItemModel*, size_t)>;

// Turns `item` into the tile row (`bar` false) or the bottom bar (`bar`
// true), one button for each entry of `model`.
void AddAppMenuButtonRow(views::MenuItemView* item,
                         ui::ButtonMenuItemModel* model,
                         AppMenuPress press,
                         bool bar);

// Puts the top level rows of a built menu into cards and styles its
// headings. Call once, after the menu is populated.
void StyleAppMenu(views::MenuItemView* root);

// The headings' font.
const gfx::FontList& AppMenuHeadingFont();

}  // namespace boring

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_APP_MENU_H_
