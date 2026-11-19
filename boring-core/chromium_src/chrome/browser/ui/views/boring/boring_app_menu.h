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

// The command id StyleAppMenu gives the main menu's own headings (Browse,
// Page, Browser), so AppMenu can tell them from titles in submenus, which
// share ui::MenuModel::kTitleId (-2). Negative like that one, so AppMenu
// treats it as a row you cannot use (IsCommandEnabled, GetAccelerator).
inline constexpr int kAppMenuHeadingId = -3;

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
// headings: their own id (kAppMenuHeadingId) and a heading role, which
// also keeps the keyboard selection off them (menu_item_view.cc). Call
// once, after the menu is populated.
void StyleAppMenu(views::MenuItemView* root);

// The headings' font: the mock's 12px at the default text size, larger with
// the menu's own font when the system text size is larger.
const gfx::FontList& AppMenuHeadingFont();

}  // namespace boring

#endif  // CHROME_BROWSER_UI_VIEWS_BORING_BORING_APP_MENU_H_
