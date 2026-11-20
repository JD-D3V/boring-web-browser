// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_earlier_chip.h"

#include <map>
#include <utility>

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/no_destructor.h"
#include "base/strings/string_number_conversions.h"
#include "base/task/single_thread_task_runner.h"
#include "chrome/app/vector_icons/vector_icons.h"
#include "chrome/browser/profiles/profile.h"
#include "chrome/browser/ui/browser_window/public/browser_window_interface.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "chrome/browser/ui/views/boring/boring_earlier_popup.h"
#include "ui/accessibility/ax_action_data.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/base/models/image_model.h"
#include "ui/gfx/font.h"
#include "ui/gfx/font_list.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/background.h"
#include "ui/views/border.h"
#include "ui/views/controls/image_view.h"
#include "ui/views/controls/label.h"
#include "ui/views/layout/box_layout.h"

namespace {

constexpr int kRadius = 7;
constexpr int kSidePadding = 10;
constexpr int kGap = 7;
constexpr int kIcon = 13;

// The chips by window, so the command can find the one to open.
std::map<BrowserWindowInterface*, BoringEarlierChip*>& Chips() {
  static base::NoDestructor<std::map<BrowserWindowInterface*, BoringEarlierChip*>>
      chips;
  return *chips;
}

void SetFont(views::Label* label, int size, gfx::Font::Weight weight) {
  const gfx::FontList base = label->font_list();
  label->SetFontList(
      base.DeriveWithSizeDelta(size - base.GetFontSize())
          .DeriveWithWeight(weight));
}

}  // namespace

BoringEarlierChip::BoringEarlierChip(BrowserWindowInterface* browser)
    : views::Button(views::Button::PressedCallback()),
      browser_(browser),
      service_(boring::earlier::EarlierTabsService::Get(browser->GetProfile())) {
  SetCallback(base::BindRepeating(&BoringEarlierChip::OnPressed,
                                  base::Unretained(this)));
  SetFocusBehavior(FocusBehavior::ALWAYS);
  GetViewAccessibility().SetIsCollapsed();
  auto* layout = SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal,
      gfx::Insets::VH(0, kSidePadding), kGap));
  layout->set_cross_axis_alignment(
      views::BoxLayout::CrossAxisAlignment::kCenter);

  auto* image = AddChildView(std::make_unique<views::ImageView>());
  image->SetImage(ui::ImageModel::FromVectorIcon(
      kBoringClockIcon, kColorBoringShelfHeading, kIcon));
  image->SetCanProcessEventsWithinSubtree(false);

  auto* word = AddChildView(std::make_unique<views::Label>(u"Earlier"));
  word->SetEnabledColor(kColorBoringShelfHeading);
  word->SetCanProcessEventsWithinSubtree(false);
  SetFont(word, 13, gfx::Font::Weight::NORMAL);

  count_label_ = AddChildView(std::make_unique<views::Label>());
  count_label_->SetEnabledColor(kColorBoringShelfText);
  count_label_->SetCanProcessEventsWithinSubtree(false);
  SetFont(count_label_, 13, gfx::Font::Weight::SEMIBOLD);

  SetBorder(views::CreateRoundedRectBorder(1, kRadius, kColorBoringEdge));
  open_pending_ = base::CommandLine::ForCurrentProcess()->HasSwitch(
      boring::earlier::kOpenEarlierSwitch);

  SetVisible(false);
  Chips()[browser_] = this;
  if (service_) {
    service_->AddObserver(this);
    Update();
  }
}

BoringEarlierChip::~BoringEarlierChip() {
  auto it = Chips().find(browser_);
  if (it != Chips().end() && it->second == this) {
    Chips().erase(it);
  }
  if (service_) {
    service_->RemoveObserver(this);
  }
}

// static
void BoringEarlierChip::ShowPopupFor(BrowserWindowInterface* browser) {
  auto it = Chips().find(browser);
  if (it != Chips().end()) {
    it->second->ShowPopup();
  }
}

int BoringEarlierChip::LayoutWidth() const {
  return GetVisible() ? GetPreferredSize().width() + kLeftMargin : 0;
}

gfx::Size BoringEarlierChip::CalculatePreferredSize(
    const views::SizeBounds& available_size) const {
  return gfx::Size(
      views::Button::CalculatePreferredSize(available_size).width(), kHeight);
}

void BoringEarlierChip::AddedToWidget() {
  views::Button::AddedToWidget();
  Update();
}

void BoringEarlierChip::OnThemeChanged() {
  views::Button::OnThemeChanged();
  UpdateLook();
}

void BoringEarlierChip::OnEarlierTabsChanged() {
  Update();
}

void BoringEarlierChip::UpdateLook() {
  // Open: the chip sits on a plain wash; closed: nothing behind it.
  if (popup_) {
    SetBackground(
        views::CreateRoundedRectBackground(kColorBoringShelfTile, kRadius));
  } else {
    SetBackground(nullptr);
  }
  SchedulePaint();
}

void BoringEarlierChip::Update() {
  const size_t count = service_ ? service_->count() : 0;
  count_label_->SetText(base::NumberToString16(count));
  GetViewAccessibility().SetName(u"Earlier " + base::NumberToString16(count));
  SetTooltipText(u"Earlier tabs");
  const bool visible = count > 0;
  if (visible != GetVisible()) {
    SetVisible(visible);
    // The tab strip leaves room for the chip: lay the row out again.
    if (parent()) {
      parent()->InvalidateLayout();
    }
  }
  if (visible && open_pending_ && GetWidget()) {
    open_pending_ = false;
    base::SingleThreadTaskRunner::GetCurrentDefault()->PostTask(
        FROM_HERE, base::BindOnce(&BoringEarlierChip::ShowPopup,
                                  weak_factory_.GetWeakPtr()));
  }
}

void BoringEarlierChip::ShowPopup() {
  if (popup_ || !GetVisible() || !GetWidget()) {
    return;
  }
  popup_ = std::make_unique<BoringEarlierPopup>(
      this, browser_,
      base::BindOnce(&BoringEarlierChip::OnPopupClosed,
                     weak_factory_.GetWeakPtr()));
  GetViewAccessibility().SetIsExpanded();
  popup_->Show();
  UpdateLook();
}

bool BoringEarlierChip::HandleAccessibleAction(
    const ui::AXActionData& action_data) {
  // The chip says it opens a pop-up, so UI Automation offers Expand and
  // Collapse for it and no Invoke; View answers neither.
  if (action_data.action == ax::mojom::Action::kExpand) {
    ShowPopup();
    return true;
  }
  if (action_data.action == ax::mojom::Action::kCollapse) {
    if (popup_) {
      popup_->Close();
    }
    return true;
  }
  return views::Button::HandleAccessibleAction(action_data);
}

void BoringEarlierChip::OnPressed() {
  if (popup_) {
    popup_->Close();
  } else {
    ShowPopup();
  }
}

void BoringEarlierChip::OnPopupClosed() {
  popup_.reset();
  GetViewAccessibility().SetIsCollapsed();
  UpdateLook();
}

BEGIN_METADATA(BoringEarlierChip)
END_METADATA
