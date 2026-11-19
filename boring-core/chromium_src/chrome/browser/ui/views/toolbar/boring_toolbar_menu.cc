// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/toolbar/boring_toolbar_menu.h"

#include <utility>

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/ui/actions/chrome_action_id.h"
#include "chrome/browser/ui/browser_actions.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/grit/generated_resources.h"
#include "ui/actions/actions.h"
#include "ui/base/l10n/l10n_util.h"
#include "ui/base/mojom/menu_source_type.mojom.h"
#include "ui/gfx/geometry/point.h"
#include "ui/views/controls/menu/menu_runner.h"
#include "ui/views/view.h"
#include "ui/views/widget/widget.h"

BoringToolbarMenu::BoringToolbarMenu(BrowserWindowInterface* browser,
                                     views::View* toolbar)
    : browser_(browser), toolbar_(toolbar), model_(this) {
  model_.AddItem(IDC_SHOW_CUSTOMIZE_CHROME_TOOLBAR,
                 l10n_util::GetStringUTF16(IDS_SHOW_CUSTOMIZE_CHROME_TOOLBAR));
  toolbar_->set_context_menu_controller(this);

  // boring: test hook. Checking this means acting without sending input
  // to the desktop, so --boring-toolbar-test=<step> does one thing a few
  // seconds after the window is up: "menu" shows the right click menu,
  // "customize" runs what its item runs, "settings" and "extensions" run
  // what the pinned buttons run. It does nothing without the switch.
  const base::CommandLine& command_line =
      *base::CommandLine::ForCurrentProcess();
  if (command_line.HasSwitch("boring-toolbar-test")) {
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
        FROM_HERE,
        base::BindOnce(&BoringToolbarMenu::RunTestStep,
                       weak_factory_.GetWeakPtr(),
                       command_line.GetSwitchValueASCII("boring-toolbar-test")),
        base::Seconds(4));
  }
}

BoringToolbarMenu::~BoringToolbarMenu() {
  toolbar_->set_context_menu_controller(nullptr);
}

void BoringToolbarMenu::ExecuteCommand(int command_id, int event_flags) {
  chrome::ExecuteCommand(browser_, command_id);
}

void BoringToolbarMenu::ShowContextMenuForViewImpl(
    views::View* source,
    const gfx::Point& point,
    ui::mojom::MenuSourceType source_type) {
  runner_ = std::make_unique<views::MenuRunner>(
      &model_, views::MenuRunner::HAS_MNEMONICS |
                   views::MenuRunner::CONTEXT_MENU);
  runner_->RunMenuAt(source->GetWidget(), nullptr, gfx::Rect(point, gfx::Size()),
                     views::MenuAnchorPosition::kTopLeft, source_type);
}

void BoringToolbarMenu::RunTestStep(const std::string& step) {
  if (step == "menu") {
    ShowContextMenuForView(toolbar_, toolbar_->GetBoundsInScreen().CenterPoint(),
                           ui::mojom::MenuSourceType::kMouse);
  } else if (step == "customize") {
    ExecuteCommand(IDC_SHOW_CUSTOMIZE_CHROME_TOOLBAR, 0);
  } else if (step == "settings" || step == "extensions") {
    actions::ActionItem* item = actions::ActionManager::Get().FindAction(
        step == "settings" ? kActionOptions : kActionManageExtensions,
        BrowserActions::From(browser_)->root_action_item());
    if (item) {
      item->InvokeAction();
    }
  }
}
