// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/toolbar/boring_toolbar_menu.h"

#include <cstdint>
#include <optional>
#include <string_view>
#include <utility>

#include "base/command_line.h"
#include "base/files/file_path.h"
#include "base/files/file_util.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/single_thread_task_runner.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "build/build_config.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/actions/chrome_action_id.h"
#include "chrome/browser/ui/browser_actions.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/customize_chrome/side_panel_controller.h"
#include "chrome/browser/ui/tabs/tab_strip_model.h"
#include "chrome/browser/ui/views/toolbar/toolbar_divider.h"
#include "chrome/grit/generated_resources.h"
#include "components/tabs/public/tab_interface.h"
#include "ui/actions/actions.h"
#include "ui/base/l10n/l10n_util.h"
#include "ui/base/mojom/menu_source_type.mojom.h"
#include "ui/events/base_event_utils.h"
#include "ui/events/event.h"
#include "ui/events/event_constants.h"
#include "ui/gfx/geometry/point.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/controls/button/button.h"
#include "ui/views/controls/button/label_button.h"
#include "ui/views/controls/menu/menu_controller.h"
#include "ui/views/controls/menu/menu_item_view.h"
#include "ui/views/controls/menu/menu_runner.h"
#include "ui/views/controls/menu/submenu_view.h"
#include "ui/views/view.h"
#include "ui/views/view_utils.h"
#include "ui/views/widget/widget.h"

#if BUILDFLAG(IS_WIN)
#include "ui/views/win/hwnd_util.h"
#endif

namespace {

constexpr std::string_view kLocationBar = "LocationBarView";

// Test hook output: one line per visible button under `view`, with its
// class, name, tooltip, the words on it and whether it is enabled, and a
// "divider" line per visible toolbar divider, in order. The address bar's
// own buttons are left out.
void ListButtons(views::View* view, std::string* out) {
  for (views::View* child : view->children()) {
    if (!child->GetVisible() || child->width() == 0 ||
        child->GetClassName() == kLocationBar) {
      continue;
    }
    if (views::IsViewClass<ToolbarDivider>(child)) {
      base::StrAppend(out, {"divider\t", child->GetClassName(), "\n"});
    }
    if (views::Button::AsButton(child)) {
      const auto* label_button = views::AsViewClass<views::LabelButton>(child);
      base::StrAppend(
          out, {"button\t", child->GetClassName(), "\t",
                base::UTF16ToUTF8(child->GetViewAccessibility().GetCachedName()),
                "\t", base::UTF16ToUTF8(child->GetTooltipText()), "\t",
                label_button ? base::UTF16ToUTF8(label_button->GetText()) : "",
                "\t", child->GetEnabled() ? "on" : "off", "\n"});
    }
    ListButtons(child, out);
  }
}

// The first visible pinned button under `view`.
views::View* FindPinnedButton(views::View* view) {
  for (views::View* child : view->children()) {
    if (!child->GetVisible()) {
      continue;
    }
    if (child->GetClassName() == "PinnedActionToolbarButton") {
      return child;
    }
    if (views::View* found = FindPinnedButton(child)) {
      return found;
    }
  }
  return nullptr;
}

// A point on the toolbar where no child takes a right click, so the press
// falls through to the toolbar itself.
std::optional<gfx::Point> FindEmptyPoint(views::View* toolbar) {
  for (int y = 1; y < toolbar->height(); y += 2) {
    for (int x = 1; x < toolbar->width(); x += 4) {
      views::View* v = toolbar->GetEventHandlerForPoint(gfx::Point(x, y));
      while (v && v != toolbar && !v->context_menu_controller() &&
             !views::Button::AsButton(v) && v->GetClassName() != kLocationBar) {
        v = v->parent();
      }
      if (v == toolbar) {
        return gfx::Point(x, y);
      }
    }
  }
  return std::nullopt;
}

}  // namespace

BoringToolbarMenu::BoringToolbarMenu(BrowserWindowInterface* browser,
                                     views::View* toolbar)
    : browser_(browser), toolbar_(toolbar), model_(this) {
  model_.AddItem(IDC_SHOW_CUSTOMIZE_CHROME_TOOLBAR,
                 l10n_util::GetStringUTF16(IDS_SHOW_CUSTOMIZE_CHROME_TOOLBAR));
  // Incognito and guest windows have no Customize panel, so no menu there;
  // the test hook below still runs in them.
  if (browser_->GetProfile()->IsRegularProfile()) {
    toolbar_->set_context_menu_controller(this);
  }

  // boring: test hook. Checking this means acting without sending input
  // to the desktop, so --boring-toolbar-test=<step> does one thing a few
  // seconds after the first window is up, once per run: "menu" and
  // "pinned-menu" send a right click through the window to empty toolbar
  // space or to the first pinned button, "buttons" lists the toolbar's
  // buttons, "customize" runs what the menu item runs, "settings" and
  // "extensions" run what the pinned buttons run. Results go to
  // boring-toolbar-test.txt in the profile folder. Like the other boring
  // test hooks it ships, and does nothing without the switch.
  static bool test_step_posted = false;
  const base::CommandLine& command_line =
      *base::CommandLine::ForCurrentProcess();
  if (!test_step_posted && command_line.HasSwitch("boring-toolbar-test")) {
    test_step_posted = true;
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
        FROM_HERE,
        base::BindOnce(&BoringToolbarMenu::RunTestStep,
                       weak_factory_.GetWeakPtr(),
                       command_line.GetSwitchValueASCII("boring-toolbar-test")),
        base::Seconds(4));
  }
}

BoringToolbarMenu::~BoringToolbarMenu() {
  if (toolbar_->context_menu_controller() == this) {
    toolbar_->set_context_menu_controller(nullptr);
  }
}

bool BoringToolbarMenu::IsCommandIdEnabled(int command_id) const {
  // boring: grey the item where the panel cannot open, the same test the
  // pinned buttons' own menu uses.
  tabs::TabInterface* tab = browser_->GetTabStripModel()->GetActiveTab();
  customize_chrome::SidePanelController* controller =
      tab ? customize_chrome::SidePanelController::Get(
                tab->GetUnownedUserDataHost())
          : nullptr;
  return controller && controller->IsCustomizeChromeEntryAvailable();
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
  if (step == "menu" || step == "pinned-menu") {
    std::optional<gfx::Point> point = FindEmptyPoint(toolbar_);
    if (step == "pinned-menu") {
      views::View* button = FindPinnedButton(toolbar_);
      point.reset();
      if (button) {
        point = button->bounds().CenterPoint();
        views::View::ConvertPointToTarget(button->parent(), toolbar_,
                                          &*point);
      }
    }
    if (!point) {
      WriteTestReport("no point\nend\n");
      return;
    }
    // A real right click, sent through the window's root view, so the hit
    // test and the registered menu controllers decide what opens.
    gfx::Point p = *point;
    views::View::ConvertPointToWidget(toolbar_, &p);
    views::View* root = toolbar_->GetWidget()->GetRootView();
    std::string report =
        base::StrCat({"hit\t", root->GetEventHandlerForPoint(p)->GetClassName(),
                      "\n"});
    ui::MouseEvent press(ui::EventType::kMousePressed, p, p,
                         ui::EventTimeForNow(), ui::EF_RIGHT_MOUSE_BUTTON,
                         ui::EF_RIGHT_MOUSE_BUTTON);
    ui::MouseEvent release(ui::EventType::kMouseReleased, p, p,
                           ui::EventTimeForNow(), ui::EF_RIGHT_MOUSE_BUTTON,
                           ui::EF_RIGHT_MOUSE_BUTTON);
    root->OnMousePressed(press);
    root->OnMouseReleased(release);
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
        FROM_HERE,
        base::BindOnce(&BoringToolbarMenu::ReportMenu,
                       weak_factory_.GetWeakPtr(), std::move(report)),
        base::Milliseconds(1500));
  } else if (step == "buttons") {
    std::string report;
    ListButtons(toolbar_, &report);
    WriteTestReport(report + "end\n");
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

void BoringToolbarMenu::ReportMenu(std::string report) {
  // Which menu is open, its window and its items.
  views::MenuController* controller = views::MenuController::GetActiveInstance();
  views::MenuItemView* item =
      controller ? controller->GetSelectedMenuItem() : nullptr;
  views::MenuItemView* menu = item ? item->GetRootMenuItem() : nullptr;
  base::StrAppend(&report,
                  {"ours\t", runner_ && runner_->IsRunning() ? "1" : "0", "\n"});
  if (menu && menu->HasSubmenu()) {
#if BUILDFLAG(IS_WIN)
    base::StrAppend(
        &report,
        {"hwnd\t",
         base::NumberToString(reinterpret_cast<uintptr_t>(
             views::HWNDForWidget(menu->GetSubmenu()->GetWidget()))),
         "\n"});
#endif
    for (views::MenuItemView* row : menu->GetSubmenu()->GetMenuItems()) {
      base::StrAppend(&report, {"item\t", base::UTF16ToUTF8(row->title()), "\t",
                                row->GetEnabled() ? "on" : "off", "\n"});
    }
  }
  WriteTestReport(report + "end\n");
}

void BoringToolbarMenu::WriteTestReport(std::string text) {
  base::ThreadPool::PostTask(
      FROM_HERE, {base::MayBlock()},
      base::BindOnce(
          [](const base::FilePath& path, const std::string& text) {
            base::WriteFile(path, text);
          },
          browser_->GetProfile()->GetPath().AppendASCII(
              "boring-toolbar-test.txt"),
          std::move(text)));
}
