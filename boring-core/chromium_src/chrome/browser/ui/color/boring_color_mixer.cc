// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/color/boring_color_mixer.h"

#include "chrome/browser/ui/color/chrome_color_id.h"
#include "ui/color/color_id.h"
#include "ui/color/color_mixer.h"
#include "ui/color/color_recipe.h"

namespace {

// The palette. Same values as our own pages use, so the window and the
// page inside it are one browser rather than two designs.
struct Palette {
  SkColor window;   // A window that is not the one in front.
  SkColor chrome;   // The whole band at the top: frame, tabs, toolbar.
  SkColor paper;    // The tab you are on, and the address bar.
  SkColor ink;      // Text and icons.
  SkColor muted;    // Text and icons that are not the point.
  SkColor line;     // Edges and separators.
  SkColor accent;   // The one colour with a job: focus and selection.
  SkColor tint;     // A wash of the accent, behind accented things.
};

constexpr Palette kLight = {SkColorSetRGB(0xe8, 0xe7, 0xe2),
                            SkColorSetRGB(0xee, 0xed, 0xe8),
                            SK_ColorWHITE,
                            SkColorSetRGB(0x24, 0x2e, 0x2d),
                            SkColorSetRGB(0x5d, 0x69, 0x66),
                            SkColorSetRGB(0xd8, 0xdd, 0xd7),
                            SkColorSetRGB(0x17, 0x6b, 0x5b),
                            SkColorSetRGB(0xe5, 0xf1, 0xeb)};

constexpr Palette kDark = {
    SkColorSetRGB(0x13, 0x18, 0x17), SkColorSetRGB(0x17, 0x1f, 0x1d),
    SkColorSetRGB(0x25, 0x2e, 0x2b), SkColorSetRGB(0xe8, 0xed, 0xe7),
    SkColorSetRGB(0xad, 0xb9, 0xb2), SkColorSetRGB(0x41, 0x4e, 0x47),
    SkColorSetRGB(0x92, 0xd4, 0xbb), SkColorSetRGB(0x27, 0x3f, 0x35)};

// The seed colour we register as the default. Anyone who picks their own
// colour, or grey, in Customize Chrome gets Chromium's palette instead of
// ours, which is what they asked for.
constexpr SkColor kSeed = SkColorSetRGB(0x17, 0x6b, 0x5b);

bool UsingOurTheme(const ui::ColorProviderKey& key) {
  return !key.custom_theme &&
         key.user_color_source ==
             ui::ColorProviderKey::UserColorSource::kAccent &&
         key.user_color == kSeed;
}

}  // namespace

void AddBoringColorMixer(ui::ColorProvider* provider,
                         const ui::ColorProviderKey& key) {
  if (!UsingOurTheme(key)) {
    return;
  }
  const bool dark = key.color_mode == ui::ColorProviderKey::ColorMode::kDark;
  const Palette& p = dark ? kDark : kLight;
  ui::ColorMixer& mixer = provider->AddMixer();

  // The top of the window is one flat band: frame, tab strip and
  // toolbar are the same colour, so the open tab can sit on it as a
  // card. A window that is not in front steps back a little.
  mixer[ui::kColorFrameActive] = {p.chrome};
  mixer[ui::kColorFrameInactive] = {p.window};
  mixer[kColorToolbar] = {p.chrome};
  mixer[kColorToolbarContentAreaSeparator] = {p.line};
  mixer[kColorToolbarTopSeparatorFrameActive] = {SK_ColorTRANSPARENT};
  mixer[kColorToolbarTopSeparatorFrameInactive] = {SK_ColorTRANSPARENT};

  // Tabs. The open tab is a page-white card lifted off the band, with an
  // accent line along its bottom edge painted by the tab itself. The
  // rest have no background at all and are just their titles.
  mixer[kColorTabBackgroundActiveFrameActive] = {p.paper};
  mixer[kColorTabBackgroundActiveFrameInactive] = {p.paper};
  mixer[kColorTabBackgroundInactiveFrameActive] = {p.chrome};
  mixer[kColorTabBackgroundInactiveFrameInactive] = {p.window};
  mixer[kColorTabForegroundActiveFrameActive] = {p.ink};
  mixer[kColorTabForegroundActiveFrameInactive] = {p.muted};
  mixer[kColorTabForegroundInactiveFrameActive] = {p.muted};
  mixer[kColorTabForegroundInactiveFrameInactive] = {p.muted};
  mixer[kColorTabStrokeFrameActive] = {p.line};
  mixer[kColorTabStrokeFrameInactive] = {p.line};
  mixer[kColorTabDividerFrameActive] = {p.line};
  mixer[kColorTabDividerFrameInactive] = {p.line};

  // Toolbar controls.
  mixer[kColorToolbarText] = {p.ink};
  mixer[kColorToolbarButtonIcon] = {p.ink};
  mixer[kColorToolbarButtonIconInactive] = {p.muted};
  mixer[kColorToolbarButtonIconHovered] = {p.ink};
  mixer[kColorToolbarSeparator] = {p.line};
  mixer[kColorNewTabButtonForegroundFrameActive] = {p.ink};
  mixer[kColorNewTabButtonForegroundFrameInactive] = {p.muted};

  // The address bar reads as a field you can type in, like the boxes on
  // our own pages. The location bar reads its own two ids, not the
  // subtle-emphasis pair, so both have to be set.
  mixer[kColorLocationBarBackground] = {p.paper};
  mixer[kColorLocationBarBackgroundHovered] = {p.paper};
  mixer[kColorToolbarBackgroundSubtleEmphasis] = {p.paper};
  mixer[kColorToolbarBackgroundSubtleEmphasisHovered] = {p.paper};
  mixer[kColorOmniboxText] = {p.ink};
  mixer[kColorOmniboxTextDimmed] = {p.muted};
  mixer[kColorLocationBarBorder] = {p.line};
  mixer[kColorLocationBarBorderOpaque] = {p.line};
  mixer[kColorOmniboxResultsBackground] = {p.paper};

  // One accent, used where something is focused or selected.
  mixer[ui::kColorFocusableBorderFocused] = {p.accent};
  mixer[kColorOmniboxResultsIconSelected] = {p.accent};

  // Chromium's own pages are painted from this same colour provider.
  // Without these, settings and history keep Chromium's blue and the
  // browser reads as two products stuck together.
  mixer[ui::kColorSysPrimary] = {p.accent};
  mixer[ui::kColorSysOnPrimary] = {dark ? p.window : SK_ColorWHITE};
  mixer[ui::kColorSysPrimaryContainer] = {p.tint};
  mixer[ui::kColorSysOnPrimaryContainer] = {p.ink};
  mixer[ui::kColorSysStateFocusRing] = {p.accent};
  mixer[ui::kColorLinkForegroundDefault] = {p.accent};
  mixer[ui::kColorCheckboxForegroundChecked] = {p.accent};

  // Popovers: page info, downloads, the star, and the rest of the
  // bubbles read as the same paper panel our pages use. Links in native
  // text read kColorLinkForeground, not the Default id above.
  mixer[ui::kColorBubbleBackground] = {p.paper};
  mixer[ui::kColorBubbleBorder] = {p.line};
  mixer[ui::kColorBubbleFooterBackground] = {p.paper};
  mixer[ui::kColorBubbleFooterBorder] = {p.line};
  mixer[ui::kColorDialogBackground] = {p.paper};
  mixer[ui::kColorDialogForeground] = {p.ink};
  mixer[ui::kColorLabelForeground] = {p.ink};
  mixer[ui::kColorLabelForegroundSecondary] = {p.muted};
  mixer[ui::kColorLinkForeground] = {p.accent};
}
