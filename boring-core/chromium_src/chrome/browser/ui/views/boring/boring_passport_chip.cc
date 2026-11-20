// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/views/boring/boring_passport_chip.h"

#include "cc/paint/paint_flags.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "chrome/browser/ui/views/boring/boring_passport_bubble.h"
#include "chrome/browser/ui/views/boring/boring_passport_tab_helper.h"
#include "chrome/browser/ui/views/location_bar/location_bar_view.h"
#include "chrome/browser/ui/views/location_bar/location_icon_state_helper.h"
#include "chrome/browser/ui/views/location_bar/location_icon_view.h"
#include "ui/accessibility/ax_enums.mojom.h"
#include "ui/base/models/image_model.h"
#include "ui/color/color_id.h"
#include "ui/color/color_provider.h"
#include "ui/gfx/canvas.h"
#include "ui/gfx/geometry/rounded_corners_f.h"
#include "ui/gfx/image/canvas_image_source.h"
#include "ui/views/accessibility/view_accessibility.h"
#include "ui/views/background.h"
#include "ui/views/painter.h"
#include "ui/views/view_utils.h"

namespace {

using boring::passport::Chip;

constexpr int kDotSize = 7;
constexpr float kChipRadius = 6;

// The chip's dot: a 7px circle in the tone's colour.
class DotSource : public gfx::CanvasImageSource {
 public:
  explicit DotSource(SkColor color)
      : gfx::CanvasImageSource(gfx::Size(kDotSize, kDotSize)), color_(color) {}

  void Draw(gfx::Canvas* canvas) override {
    cc::PaintFlags flags;
    flags.setAntiAlias(true);
    flags.setColor(color_);
    canvas->DrawCircle(gfx::PointF(kDotSize / 2.f, kDotSize / 2.f),
                       kDotSize / 2.f, flags);
  }

 private:
  const SkColor color_;
};

struct Tone {
  ui::ColorId text;
  ui::ColorId dot;
  ui::ColorId fill;
  std::optional<ui::ColorId> outline;
};

// The TOKENS rows of Window.dc.html: Known on the surface with the edge,
// New to you in the warn tones, Blocked and the scam list in the bad ones.
Tone ToneFor(Chip chip) {
  switch (chip) {
    case Chip::kKnown:
      return {kColorOmniboxText, kColorBoringOk, kColorToolbar,
              kColorBoringEdge};
    case Chip::kNewToYou:
      return {kColorBoringPassportWarnText, kColorBoringPassportWarnDot,
              kColorBoringPassportWarnTint, kColorBoringPassportWarnLine};
    case Chip::kBlocked:
    case Chip::kScamList:
    case Chip::kNone:
      break;
  }
  return {kColorBoringPassportBad, kColorBoringPassportBad,
          kColorBoringPassportBadTint, std::nullopt};
}

boring::passport::ChipInputs InputsFor(const LocationIconView* icon) {
  LocationBarView* bar = PassportChip::BarFor(icon);
  content::WebContents* contents = bar ? bar->GetWebContents() : nullptr;
  BoringPassportTabHelper* helper =
      BoringPassportTabHelper::GetOrCreate(contents);
  if (!helper) {
    return {};
  }
  const bool editing = bar->IsEditingOrEmpty();
  // Chromium's own words in the field ("Not secure") stay where it has
  // them; the Passport still opens there.
  const bool chromium_text = !location_bar::GetSecurityChipText(
                                  bar->GetLocationBarModel(), contents, editing)
                                  .empty();
  return helper->Inputs(editing, chromium_text);
}

}  // namespace

// static
LocationBarView* PassportChip::BarFor(const LocationIconView* icon) {
  return icon ? views::AsViewClass<LocationBarView>(
                    const_cast<views::View*>(icon->parent()))
              : nullptr;
}

// static
Chip PassportChip::ChipFor(const LocationIconView* icon) {
  return boring::passport::DecideChip(InputsFor(icon));
}

// static
Chip PassportChip::LayoutFor(const LocationIconView* icon) {
  return boring::passport::DecideLayout(InputsFor(icon));
}

// static
bool PassportChip::Applies(const LocationIconView* icon) {
  return ChipFor(icon) != Chip::kNone;
}

// static
std::u16string PassportChip::Text(const LocationIconView* icon) {
  return boring::passport::ChipText(ChipFor(icon));
}

// static
std::optional<SkColor> PassportChip::Foreground(const LocationIconView* icon) {
  const Chip chip = ChipFor(icon);
  if (chip == Chip::kNone || !icon->GetColorProvider()) {
    return std::nullopt;
  }
  return icon->GetColorProvider()->GetColor(ToneFor(chip).text);
}

// static
void PassportChip::StyleBackground(LocationIconView* icon) {
  const Chip chip = ChipFor(icon);
  const ui::ColorProvider* colors = icon->GetColorProvider();
  if (chip == Chip::kNone || !colors) {
    return;
  }
  const Tone tone = ToneFor(chip);
  const SkColor fill = colors->GetColor(tone.fill);
  icon->SetCornerRadii(gfx::RoundedCornersF(kChipRadius));
  // A 1px inset outline where the design draws one; the fill alone where
  // it does not (stroke the same as the fill).
  icon->SetBackground(views::CreateBackgroundFromPainter(
      views::Painter::CreateRoundRectWith1PxBorderPainter(
          fill, tone.outline ? colors->GetColor(*tone.outline) : fill,
          kChipRadius)));
}

// static
std::optional<ui::ImageModel> PassportChip::Dot(const LocationIconView* icon) {
  const Chip chip = ChipFor(icon);
  const ui::ColorProvider* colors = icon->GetColorProvider();
  if (chip == Chip::kNone || !colors) {
    return std::nullopt;
  }
  return ui::ImageModel::FromImageSkia(
      gfx::CanvasImageSource::MakeImageSkia<DotSource>(
          colors->GetColor(ToneFor(chip).dot)));
}

// static
void PassportChip::UpdateAccessibility(LocationIconView* icon) {
  const Chip chip = ChipFor(icon);
  if (chip == Chip::kNone) {
    return;
  }
  views::ViewAccessibility& a11y = icon->GetViewAccessibility();
  a11y.SetRole(ax::mojom::Role::kButton);
  a11y.SetName(boring::passport::ChipText(chip));
  // Blocked opens Chromium's page info, the scam list and the rest the
  // Passport: both are dialogs.
  a11y.SetHasPopup(ax::mojom::HasPopup::kDialog);
  if (BoringPassportBubble::IsShowingFor(icon)) {
    a11y.SetIsExpanded();
  } else {
    a11y.SetIsCollapsed();
  }
}
