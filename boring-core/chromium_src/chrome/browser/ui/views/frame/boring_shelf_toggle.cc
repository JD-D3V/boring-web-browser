// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/frame/boring_shelf_toggle.h"

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "chrome/app/chrome_command_ids.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/ui/browser_commands.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "chrome/browser/ui/side_panel/side_panel_entry_key.h"
#include "chrome/browser/ui/side_panel/side_panel_ui.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/base/models/image_model.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/animation/ink_drop.h"
#include "ui/views/background.h"
#include "ui/views/controls/focus_ring.h"
#include "ui/views/controls/highlight_path_generator.h"

namespace {

constexpr int kIconSize = 16;
constexpr int kCornerRadius = 7;

SidePanelEntryKey ShelfKey() {
  return SidePanelEntryKey(SidePanelEntryId::kBoringShelf);
}

}  // namespace

BoringShelfToggle::BoringShelfToggle(BrowserWindowInterface* browser)
    : views::ImageButton(base::BindRepeating(&BoringShelfToggle::OnPressed,
                                             base::Unretained(this))),
      browser_(browser) {
  SetFocusBehavior(FocusBehavior::ALWAYS);
  views::InstallRoundRectHighlightPathGenerator(this, gfx::Insets(),
                                                kCornerRadius);
  views::FocusRing::Install(this);
  views::InkDrop::Get(this)->SetMode(views::InkDropHost::InkDropMode::OFF);
  SetTooltipText(u"Show or hide the Shelf");
  GetViewAccessibility().SetName(u"Show or hide the Shelf");
  GetViewAccessibility().SetRole(ax::mojom::Role::kToggleButton);
  SetPressedLook(false);
}

BoringShelfToggle::~BoringShelfToggle() = default;

gfx::Size BoringShelfToggle::CalculatePreferredSize(
    const views::SizeBounds& available_size) const {
  return gfx::Size(kWidth, kHeight);
}

void BoringShelfToggle::AddedToWidget() {
  views::ImageButton::AddedToWidget();
  if (SidePanelUI* ui = SidePanelUI::From(browser_)) {
    // Told when a panel opens or changes, which is when the Shelf is shown
    // or put away by another panel.
    shown_subscription_ = ui->RegisterSidePanelShown(base::BindRepeating(
        &BoringShelfToggle::SyncWithPanel, base::Unretained(this)));
  }
  // boring: test hook, as --boring-open-app-menu is for the main menu. A
  // desktop test cannot send input, so this opens the Shelf a few seconds
  // after the window is up. Does nothing unless the switch is given.
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(
          "boring-open-shelf")) {
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
        FROM_HERE,
        base::BindOnce(
            [](base::WeakPtr<BoringShelfToggle> toggle) {
              if (toggle && !toggle->pressed_) {
                toggle->OnPressed();
              }
            },
            weak_factory_.GetWeakPtr()),
        base::Seconds(3));
  }
}

void BoringShelfToggle::OnThemeChanged() {
  views::ImageButton::OnThemeChanged();
  SetPressedLook(pressed_);
}

void BoringShelfToggle::OnPressed() {
  const bool opening = !pressed_;
  chrome::ExecuteCommand(browser_, IDC_BORING_TOGGLE_SHELF);
  // Opening takes a moment, and closing sends no notice, so the look follows
  // the press; the panel's own notice corrects it if something else won.
  SetPressedLook(opening);
}

void BoringShelfToggle::SyncWithPanel() {
  SidePanelUI* ui = SidePanelUI::From(browser_);
  SetPressedLook(ui && ui->IsSidePanelEntryShowing(ShelfKey()));
}

void BoringShelfToggle::SetPressedLook(bool pressed) {
  pressed_ = pressed;
  SetImageModel(
      views::Button::STATE_NORMAL,
      ui::ImageModel::FromVectorIcon(
          kBoringShelfIcon,
          pressed ? kColorBoringShelfText : kColorBoringShelfHeading,
          kIconSize));
  SetBackground(pressed ? views::CreateRoundedRectBackground(
                              kColorBoringShelfToggleOn, kCornerRadius)
                        : nullptr);
  GetViewAccessibility().SetCheckedState(
      pressed ? ax::mojom::CheckedState::kTrue
              : ax::mojom::CheckedState::kFalse);
  SchedulePaint();
}

BEGIN_METADATA(BoringShelfToggle)
END_METADATA
