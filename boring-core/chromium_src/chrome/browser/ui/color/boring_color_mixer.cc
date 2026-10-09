// Copyright 2026 boring. BSD style license.

#include "chrome/browser/ui/color/boring_color_mixer.h"

#include <string>

#include "base/command_line.h"
#include "chrome/browser/ui/color/chrome_color_id.h"
#include "ui/color/color_id.h"
#include "ui/color/color_mixer.h"
#include "ui/color/color_recipe.h"
#include "ui/gfx/color_utils.h"

namespace {

// A scheme is a palette for light and one for dark. Cool is the default
// and follows the system light/dark setting. Beige is the warm scheme we
// shipped first.
//
// The top of the window is built from three tones: the frame band behind
// the tabs, the toolbar, and the open tab, which is the toolbar's own
// colour so the two read as one piece (the tab is a folder tab joined to
// the bar). The address bar is a field a little off that surface.
struct Palette {
  SkColor window;   // A window that is not the one in front.
  SkColor frame;    // The band behind the tabs.
  SkColor toolbar;  // The toolbar and the open tab, one surface.
  SkColor field;    // The address bar.
  SkColor paper;    // Popovers, dialogs and result lists.
  SkColor ink;      // Text and icons.
  SkColor muted;    // Text and icons that are not the point.
  SkColor line;     // Edges and separators.
  SkColor accent;   // The one colour with a job: focus and selection.
  SkColor tint;     // A wash of the accent, behind accented things.
};

constexpr Palette kCoolLight = {
    SkColorSetRGB(0xdc, 0xde, 0xe8), SkColorSetRGB(0xd3, 0xd6, 0xe3),
    SK_ColorWHITE,                   SkColorSetRGB(0xee, 0xf0, 0xf6),
    SK_ColorWHITE,                   SkColorSetRGB(0x23, 0x24, 0x2e),
    SkColorSetRGB(0x50, 0x52, 0x65), SkColorSetRGB(0xd9, 0xdb, 0xe6),
    SkColorSetRGB(0x4f, 0x46, 0xe5), SkColorSetRGB(0xe6, 0xe5, 0xfb)};

constexpr Palette kCoolDark = {
    SkColorSetRGB(0x07, 0x08, 0x0b), SkColorSetRGB(0x0a, 0x0b, 0x0f),
    SkColorSetRGB(0x1d, 0x1e, 0x28), SkColorSetRGB(0x0f, 0x10, 0x15),
    SkColorSetRGB(0x1d, 0x1e, 0x28), SkColorSetRGB(0xdc, 0xdd, 0xe6),
    SkColorSetRGB(0xa0, 0xa2, 0xb4), SkColorSetRGB(0x2c, 0x2d, 0x3a),
    SkColorSetRGB(0x9d, 0x9a, 0xff), SkColorSetRGB(0x2a, 0x29, 0x50)};

constexpr Palette kBeigeLight = {
    SkColorSetRGB(0xe8, 0xe7, 0xe2), SkColorSetRGB(0xe6, 0xe5, 0xdf),
    SkColorSetRGB(0xf7, 0xf6, 0xf2), SK_ColorWHITE,
    SK_ColorWHITE,                   SkColorSetRGB(0x24, 0x2e, 0x2d),
    SkColorSetRGB(0x5d, 0x69, 0x66), SkColorSetRGB(0xd8, 0xdd, 0xd7),
    SkColorSetRGB(0x17, 0x6b, 0x5b), SkColorSetRGB(0xe5, 0xf1, 0xeb)};

constexpr Palette kBeigeDark = {
    SkColorSetRGB(0x13, 0x18, 0x17), SkColorSetRGB(0x0e, 0x13, 0x12),
    SkColorSetRGB(0x1c, 0x25, 0x23), SkColorSetRGB(0x13, 0x18, 0x17),
    SkColorSetRGB(0x25, 0x2e, 0x2b), SkColorSetRGB(0xe8, 0xed, 0xe7),
    SkColorSetRGB(0xad, 0xb9, 0xb2), SkColorSetRGB(0x41, 0x4e, 0x47),
    SkColorSetRGB(0x92, 0xd4, 0xbb), SkColorSetRGB(0x27, 0x3f, 0x35)};

// The seed colours we recognise. Cool is registered as the default (see
// frame-color.patch). Beige's is the teal we shipped first, so a profile
// that already holds it keeps the look it has. Anyone who picks their own
// colour, or grey, in Customize Chrome gets Chromium's palette instead of
// ours, which is what they asked for.
constexpr SkColor kCoolSeed = SkColorSetRGB(0x4f, 0x46, 0xe5);
// A warm sand colour, so the swatch and the tonal palette Chromium derives
// for its own pages are warm, matching the scheme. Both swatches are in
// Customize Chrome's colour picker (patches/colour-picker-schemes.patch).
constexpr SkColor kBeigeSeed = SkColorSetRGB(0xc8, 0xbd, 0xa4);
// The teal Beige used as its seed before it had a swatch. A profile that
// stored it keeps the look it has.
constexpr SkColor kLegacyBeigeSeed = SkColorSetRGB(0x17, 0x6b, 0x5b);

bool UsingOurTheme(const ui::ColorProviderKey& key) {
  return !key.custom_theme &&
         key.user_color_source ==
             ui::ColorProviderKey::UserColorSource::kAccent &&
         (key.user_color == kCoolSeed || key.user_color == kBeigeSeed ||
          key.user_color == kLegacyBeigeSeed);
}

// Beige when the profile holds one of Beige's seeds, or when launched with
// --boring-scheme=beige (kept for the capture tools).
bool WantsBeige(const ui::ColorProviderKey& key) {
  if (key.user_color == kBeigeSeed || key.user_color == kLegacyBeigeSeed) {
    return true;
  }
  return base::CommandLine::ForCurrentProcess()->GetSwitchValueASCII(
             "boring-scheme") == "beige";
}

}  // namespace

void AddBoringColorMixer(ui::ColorProvider* provider,
                         const ui::ColorProviderKey& key) {
  if (!UsingOurTheme(key)) {
    return;
  }
  const bool dark = key.color_mode == ui::ColorProviderKey::ColorMode::kDark;
  const bool beige = WantsBeige(key);
  const Palette& p = beige ? (dark ? kBeigeDark : kBeigeLight)
                           : (dark ? kCoolDark : kCoolLight);
  ui::ColorMixer& mixer = provider->AddMixer();

  // The band behind the tabs is its own tone. The toolbar and the open
  // tab are one surface below it, so the open tab reads as joined to the
  // bar. A window that is not in front steps back a little.
  mixer[ui::kColorFrameActive] = {p.frame};
  mixer[ui::kColorFrameInactive] = {p.window};
  mixer[kColorToolbar] = {p.toolbar};
  mixer[kColorToolbarContentAreaSeparator] = {p.line};
  mixer[kColorToolbarTopSeparatorFrameActive] = {SK_ColorTRANSPARENT};
  mixer[kColorToolbarTopSeparatorFrameInactive] = {SK_ColorTRANSPARENT};

  // Tabs. The open tab is the toolbar's own colour, with an accent line
  // along its bottom edge painted by the tab itself. The rest have no
  // background of their own and sit on the band as just their titles.
  mixer[kColorTabBackgroundActiveFrameActive] = {p.toolbar};
  mixer[kColorTabBackgroundActiveFrameInactive] = {p.toolbar};
  mixer[kColorTabBackgroundInactiveFrameActive] = {p.frame};
  mixer[kColorTabBackgroundInactiveFrameInactive] = {p.window};
  mixer[kColorTabForegroundActiveFrameActive] = {p.ink};
  mixer[kColorTabForegroundActiveFrameInactive] = {p.muted};
  mixer[kColorTabForegroundInactiveFrameActive] = {p.muted};
  mixer[kColorTabForegroundInactiveFrameInactive] = {p.muted};
  // A tab you hover is a soft neutral wash of the ink on the band, as in the
  // approved mock, not the tinted colour Chromium derives from the seed.
  // Tabs picked together (ctrl-click) take a wash of the accent.
  mixer[kColorTabBackgroundInactiveHoverFrameActive] = {
      color_utils::AlphaBlend(p.ink, p.frame, 0.11f)};
  mixer[kColorTabBackgroundInactiveHoverFrameInactive] = {
      color_utils::AlphaBlend(p.ink, p.window, 0.11f)};
  mixer[kColorTabBackgroundSelectedFrameActive] = {
      color_utils::AlphaBlend(p.accent, p.frame, 0.22f)};
  mixer[kColorTabBackgroundSelectedFrameInactive] = {
      color_utils::AlphaBlend(p.accent, p.window, 0.22f)};
  mixer[kColorTabBackgroundSelectedHoverFrameActive] = {
      color_utils::AlphaBlend(p.accent, p.frame, 0.33f)};
  mixer[kColorTabBackgroundSelectedHoverFrameInactive] = {
      color_utils::AlphaBlend(p.accent, p.window, 0.33f)};
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
  mixer[kColorLocationBarBackground] = {p.field};
  mixer[kColorLocationBarBackgroundHovered] = {p.field};
  mixer[kColorToolbarBackgroundSubtleEmphasis] = {p.field};
  mixer[kColorToolbarBackgroundSubtleEmphasisHovered] = {p.field};
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

  // Menus: the main menu and context menus read as the same paper panel
  // as our popovers. A row you hover takes a wash of the accent, the
  // shortcut beside it is quiet, and the separators are the same hairline
  // as everywhere else.
  mixer[ui::kColorMenuBackground] = {p.paper};
  mixer[ui::kColorMenuBorder] = {p.line};
  mixer[ui::kColorMenuItemForeground] = {p.ink};
  mixer[ui::kColorMenuItemForegroundSecondary] = {p.muted};
  mixer[ui::kColorMenuSeparator] = {p.line};
  mixer[ui::kColorMenuIcon] = {p.ink};
  mixer[ui::kColorMenuItemBackgroundHighlighted] = {p.tint};
  mixer[ui::kColorMenuItemBackgroundSelected] = {p.tint};
  // Rows in our own popups (the search engine list) hover the same way.
  // It is painted over the row, so it has to be see-through or it covers
  // the text: a light wash of the accent.
  mixer[kColorHoverButtonBackgroundHovered] = {SkColorSetA(p.accent, 0x24)};
}
