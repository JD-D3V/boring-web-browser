// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/tabs/vertical/boring_new_tab_row.h"

#include <utility>

#include "chrome/app/chrome_command_ids.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/ui/actions/chrome_action_id.h"
#include "chrome/browser/ui/browser_actions.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "chrome/browser/ui/views/frame/browser_view.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/actions/actions.h"
#include "ui/base/accelerators/accelerator.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/base/models/image_model.h"
#include "ui/gfx/font.h"
#include "ui/gfx/font_list.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/actions/action_view_controller.h"
#include "ui/views/border.h"
#include "ui/views/controls/image_view.h"
#include "ui/views/controls/label.h"
#include "ui/views/layout/box_layout.h"

namespace {

// Sizes from the design (Window.dc.html, the side tabs "New tab" row).
constexpr int kRadius = 8;
constexpr int kSidePadding = 10;
constexpr int kGap = 10;
constexpr int kPlusSize = 15;

void SetFont(views::Label* label, int size) {
  const gfx::FontList base = label->font_list();
  label->SetFontList(base.DeriveWithSizeDelta(size - base.GetFontSize()));
}

}  // namespace

BoringNewTabRow::BoringNewTabRow(BrowserWindowInterface* browser)
    : views::Button(views::Button::PressedCallback()),
      action_view_controller_(std::make_unique<views::ActionViewController>()) {
  SetFocusBehavior(FocusBehavior::ALWAYS);
  auto* layout = SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal,
      gfx::Insets::VH(0, kSidePadding), kGap));
  layout->set_cross_axis_alignment(
      views::BoxLayout::CrossAxisAlignment::kCenter);

  auto* plus = AddChildView(std::make_unique<views::ImageView>());
  plus->SetImage(ui::ImageModel::FromVectorIcon(
      kBoringPlusIcon, kColorBoringShelfHeading, kPlusSize));
  plus->SetCanProcessEventsWithinSubtree(false);

  auto* label = AddChildView(std::make_unique<views::Label>(u"New tab"));
  label->SetEnabledColor(kColorBoringShelfHeading);
  label->SetAutoColorReadabilityEnabled(false);
  label->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  label->SetCanProcessEventsWithinSubtree(false);
  SetFont(label, 13);
  layout->SetFlexForView(label, 1);

  // The shortcut is read from the window's own accelerators, so it is right
  // for the platform and for a person's changes, and is never typed here.
  ui::Accelerator accelerator;
  BrowserView* browser_view = BrowserView::GetBrowserViewForBrowser(browser);
  if (browser_view && browser_view->GetAcceleratorProvider() &&
      browser_view->GetAcceleratorProvider()->GetAcceleratorForCommandId(
          IDC_NEW_TAB, &accelerator)) {
    auto* shortcut = AddChildView(
        std::make_unique<views::Label>(accelerator.GetShortcutText()));
    shortcut->SetEnabledColor(kColorBoringShelfHeading);
    shortcut->SetAutoColorReadabilityEnabled(false);
    shortcut->SetCanProcessEventsWithinSubtree(false);
    SetFont(shortcut, 12);
  }

  // The click runs the new tab action, the one the old button ran.
  if (BrowserActions* actions = BrowserActions::From(browser)) {
    if (actions::ActionItem* item = actions::ActionManager::Get().FindAction(
            kActionNewTab, actions->root_action_item())) {
      action_view_controller_->CreateActionViewRelationship(
          this, item->GetAsWeakPtr());
    }
  }

  GetViewAccessibility().SetName(u"New tab");
  GetViewAccessibility().SetRole(ax::mojom::Role::kButton);
  SetTooltipText(u"New tab");
}

BoringNewTabRow::~BoringNewTabRow() = default;

gfx::Size BoringNewTabRow::CalculatePreferredSize(
    const views::SizeBounds& available_size) const {
  // Width comes from the list; the flex rule of the container fills it.
  return gfx::Size(views::Button::CalculatePreferredSize(available_size).width(),
                   kHeight);
}

void BoringNewTabRow::OnThemeChanged() {
  views::Button::OnThemeChanged();
  SetBorder(views::CreateRoundedRectBorder(1, kRadius,
                                           kColorBoringSideNewTabRing));
}

BEGIN_METADATA(BoringNewTabRow)
END_METADATA
