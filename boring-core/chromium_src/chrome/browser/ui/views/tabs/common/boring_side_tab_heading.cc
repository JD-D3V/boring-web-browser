// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/tabs/common/boring_side_tab_heading.h"

#include "chrome/browser/ui/color/chrome_color_id.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/base/metadata/metadata_impl_macros.h"
#include "ui/gfx/font.h"
#include "ui/gfx/font_list.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/border.h"

namespace {
constexpr int kSideInset = 8;
constexpr int kBottomInset = 4;
constexpr int kFontSize = 12;
}  // namespace

BoringSideTabHeading::BoringSideTabHeading(const std::u16string& text)
    : views::Label(text) {
  SetEnabledColor(kColorBoringShelfHeading);
  SetAutoColorReadabilityEnabled(false);
  SetHorizontalAlignment(gfx::ALIGN_LEFT);
  const gfx::FontList base = font_list();
  SetFontList(base.DeriveWithSizeDelta(kFontSize - base.GetFontSize())
                  .DeriveWithWeight(gfx::Font::Weight::SEMIBOLD));
  SetBorder(views::CreateEmptyBorder(
      gfx::Insets::TLBR(0, kSideInset, kBottomInset, kSideInset)));
  // A heading names what is under it; it is not a control.
  GetViewAccessibility().SetRole(ax::mojom::Role::kHeading);
  GetViewAccessibility().SetName(text);
}

BoringSideTabHeading::~BoringSideTabHeading() = default;

BEGIN_METADATA(BoringSideTabHeading)
END_METADATA
