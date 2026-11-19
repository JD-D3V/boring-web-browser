// Copyright 2026 boring. BSD style license.

#ifndef CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_TOOLBAR_MENU_H_
#define CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_TOOLBAR_MENU_H_

#include <memory>
#include <string>

#include "base/memory/raw_ptr.h"
#include "base/memory/weak_ptr.h"
#include "ui/menus/simple_menu_model.h"
#include "ui/views/context_menu_controller.h"

class BrowserWindowInterface;

namespace views {
class MenuRunner;
class View;
}  // namespace views

// The right click menu of the toolbar. It has one item, "Customize
// toolbar", which opens the list where buttons are added and removed.
// Pinned buttons keep the menu Chromium gives them: a button that has a
// menu of its own gets the click first, so this one shows on the empty
// space around them.
class BoringToolbarMenu : public views::ContextMenuController,
                          public ui::SimpleMenuModel::Delegate {
 public:
  BoringToolbarMenu(BrowserWindowInterface* browser, views::View* toolbar);

  BoringToolbarMenu(const BoringToolbarMenu&) = delete;
  BoringToolbarMenu& operator=(const BoringToolbarMenu&) = delete;

  ~BoringToolbarMenu() override;

  // ui::SimpleMenuModel::Delegate:
  void ExecuteCommand(int command_id, int event_flags) override;

 private:
  // views::ContextMenuController:
  void ShowContextMenuForViewImpl(
      views::View* source,
      const gfx::Point& point,
      ui::mojom::MenuSourceType source_type) override;

  // Test hook, see the constructor.
  void RunTestStep(const std::string& step);

  const raw_ptr<BrowserWindowInterface> browser_;
  const raw_ptr<views::View> toolbar_;
  ui::SimpleMenuModel model_;
  std::unique_ptr<views::MenuRunner> runner_;
  base::WeakPtrFactory<BoringToolbarMenu> weak_factory_{this};
};

#endif  // CHROME_BROWSER_UI_VIEWS_TOOLBAR_BORING_TOOLBAR_MENU_H_
