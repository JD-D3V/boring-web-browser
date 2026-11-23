// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/side_panel/boring_shelf/shelf_row.h"

#include <utility>

#include "chrome/browser/ui/color/chrome_color_id.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/base/models/image_model.h"
#include "ui/gfx/font.h"
#include "ui/gfx/font_list.h"
#include "ui/views/background.h"
#include "ui/views/border.h"
#include "ui/views/controls/image_view.h"
#include "ui/views/controls/label.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/layout/box_layout.h"
#include "ui/views/layout/box_layout_view.h"
#include "ui/views/view_class_properties.h"

namespace boring::shelf {

namespace {

// Sizes from the design (Window.dc.html, the Shelf markup).
constexpr int kRowRadius = 7;
constexpr int kTileRadius = 8;
constexpr int kRowIcon = 15;
constexpr int kTileLetter = 13;  // The site's letter, as on the new tab page.
constexpr int kRowSidePadding = 8;

// A label with the font at an exact pixel size (the design draws 11.5, 12
// and 13 px; the font list takes whole pixels, so 11.5 becomes 12).
void SetFont(views::Label* label, int size, gfx::Font::Weight weight) {
  const gfx::FontList base = label->font_list();
  label->SetFontList(
      base.DeriveWithSizeDelta(size - base.GetFontSize())
          .DeriveWithWeight(weight));
}

}  // namespace

ShelfSectionHeading::ShelfSectionHeading(const std::u16string& heading,
                                         const std::u16string& note,
                                         bool regular) {
  auto* layout = SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal,
      gfx::Insets::TLBR(0, kRowSidePadding, 4, kRowSidePadding)));
  layout->set_cross_axis_alignment(
      views::BoxLayout::CrossAxisAlignment::kCenter);

  auto* title = AddChildView(std::make_unique<views::Label>(heading));
  title->SetEnabledColor(kColorBoringShelfHeading);
  title->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  SetFont(title, 12,
          regular ? gfx::Font::Weight::NORMAL : gfx::Font::Weight::SEMIBOLD);
  layout->SetFlexForView(title, 1);

  if (!note.empty()) {
    auto* note_label = AddChildView(std::make_unique<views::Label>(note));
    note_label->SetEnabledColor(kColorBoringShelfHeading);
    SetFont(note_label, 12, gfx::Font::Weight::NORMAL);
  }
  // A heading is a name for what is under it, not a control.
  GetViewAccessibility().SetRole(ax::mojom::Role::kHeading);
  GetViewAccessibility().SetName(heading);
}

ShelfSectionHeading::~ShelfSectionHeading() = default;

BEGIN_METADATA(ShelfSectionHeading)
END_METADATA

ShelfRow::ShelfRow(PressedCallback callback,
                   const gfx::VectorIcon& icon,
                   const std::u16string& title,
                   const std::u16string& meta,
                   int height,
                   int gap)
    : views::Button(std::move(callback)) {
  SetFocusBehavior(FocusBehavior::ALWAYS);
  auto* layout = SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal,
      gfx::Insets::VH(0, kRowSidePadding), gap));
  layout->set_cross_axis_alignment(
      views::BoxLayout::CrossAxisAlignment::kCenter);

  auto* image = AddChildView(std::make_unique<views::ImageView>());
  image->SetImage(ui::ImageModel::FromVectorIcon(icon, kColorBoringShelfText,
                                                  kRowIcon));
  image->SetCanProcessEventsWithinSubtree(false);

  // The title is page text: a plain label, one line, elided at the end.
  auto* title_label = AddChildView(std::make_unique<views::Label>(title));
  title_label->SetEnabledColor(kColorBoringShelfText);
  title_label->SetHorizontalAlignment(gfx::ALIGN_LEFT);
  title_label->SetElideBehavior(gfx::ELIDE_TAIL);
  title_label->SetMultiLine(false);
  title_label->SetAllowCharacterBreak(false);
  title_label->SetCanProcessEventsWithinSubtree(false);
  SetFont(title_label, 13, gfx::Font::Weight::NORMAL);
  layout->SetFlexForView(title_label, 1);

  if (!meta.empty()) {
    auto* meta_label = AddChildView(std::make_unique<views::Label>(meta));
    meta_label->SetEnabledColor(kColorBoringShelfHeading);
    meta_label->SetCanProcessEventsWithinSubtree(false);
    SetFont(meta_label, 12, gfx::Font::Weight::NORMAL);
  }

  SetPreferredSize(gfx::Size(0, height));
  GetViewAccessibility().SetName(title);
  SetTooltipText(title);
}

ShelfRow::~ShelfRow() = default;

void ShelfRow::StateChanged(ButtonState old_state) {
  views::Button::StateChanged(old_state);
  UpdateBackground();
}

void ShelfRow::OnThemeChanged() {
  views::Button::OnThemeChanged();
  UpdateBackground();
}

void ShelfRow::UpdateBackground() {
  const ButtonState state = GetState();
  if (state == STATE_HOVERED || state == STATE_PRESSED) {
    SetBackground(views::CreateRoundedRectBackground(kColorBoringShelfRowHover,
                                                     kRowRadius));
  } else {
    SetBackground(nullptr);
  }
}

BEGIN_METADATA(ShelfRow)
END_METADATA

ShelfTile::ShelfTile(PressedCallback callback,
                     const std::u16string& mark,
                     const std::u16string& title)
    : views::Button(std::move(callback)) {
  SetFocusBehavior(FocusBehavior::ALWAYS);
  SetLayoutManager(std::make_unique<views::BoxLayout>(
      views::BoxLayout::Orientation::kHorizontal))
      ->set_main_axis_alignment(views::BoxLayout::MainAxisAlignment::kCenter);
  auto* letter = AddChildView(std::make_unique<views::Label>(mark));
  letter->SetEnabledColor(kColorBoringShelfText);
  letter->SetAutoColorReadabilityEnabled(false);
  letter->SetCanProcessEventsWithinSubtree(false);
  SetFont(letter, kTileLetter, gfx::Font::Weight::SEMIBOLD);
  SetPreferredSize(gfx::Size(0, kHeight));
  GetViewAccessibility().SetName(title);
  SetTooltipText(title);
  UpdateBackground();
}

ShelfTile::~ShelfTile() = default;

void ShelfTile::StateChanged(ButtonState old_state) {
  views::Button::StateChanged(old_state);
  UpdateBackground();
}

void ShelfTile::OnThemeChanged() {
  views::Button::OnThemeChanged();
  UpdateBackground();
}

void ShelfTile::UpdateBackground() {
  const ButtonState state = GetState();
  const bool lit = state == STATE_HOVERED || state == STATE_PRESSED;
  // The tile is the surface with a 1 px ring in the line; a hover takes the
  // row wash instead of the surface.
  SetBackground(views::CreateRoundedRectBackground(
      lit ? kColorBoringShelfRowHover : kColorBoringShelfTile, kTileRadius));
  SetBorder(views::CreateRoundedRectBorder(1, kTileRadius,
                                           kColorBoringShelfTileRing));
}

BEGIN_METADATA(ShelfTile)
END_METADATA

}  // namespace boring::shelf
