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

// A scheme is a palette for light and one for dark, following the system
// light/dark setting. The Look in Settings, Appearance picks Soft white
// (the default), Slate or Dusk. Slate is the Cool palette we shipped
// before. Beige is the warm scheme we shipped first. Green is Cool's
// surfaces with the brand mark's green as the accent. Beige and Green are
// picked by their seed colour, not the Look.
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
  SkColor edge;     // Fields, outline buttons and off switches: 3 to 1.
};

// Soft white, the default Look, and its neutral charcoal for dark: the
// two TOKENS rows in design/v12-compiled/canvas-source/Window.dc.html,
// value for value. frame is the design's frame, toolbar its bar, field
// its field, paper its pop, ink its ink, muted its ink2, line its line,
// edge its edge, and the accent its default accent. The design washes
// nothing in the accent (selection is its neutral sel), so tint is sel.
// It draws no window that is not in front, so window is the frame.
constexpr Palette kSoftWhiteLight = {
    SkColorSetRGB(0xec, 0xea, 0xe6), SkColorSetRGB(0xec, 0xea, 0xe6),
    SK_ColorWHITE,                   SkColorSetRGB(0xf4, 0xf3, 0xef),
    SK_ColorWHITE,                   SkColorSetRGB(0x1f, 0x1e, 0x1c),
    SkColorSetRGB(0x5d, 0x5a, 0x54), SkColorSetRGB(0xe2, 0xdf, 0xd9),
    SkColorSetRGB(0x4f, 0x46, 0xe5), SkColorSetRGB(0xf0, 0xee, 0xea),
    SkColorSetRGB(0x8a, 0x86, 0x7d)};

constexpr Palette kSoftWhiteDark = {
    SkColorSetRGB(0x11, 0x11, 0x10), SkColorSetRGB(0x11, 0x11, 0x10),
    SkColorSetRGB(0x1c, 0x1c, 0x1a), SkColorSetRGB(0x12, 0x12, 0x11),
    SkColorSetRGB(0x20, 0x20, 0x1e), SkColorSetRGB(0xec, 0xeb, 0xe7),
    SkColorSetRGB(0xa9, 0xa7, 0x9f), SkColorSetRGB(0x2d, 0x2d, 0x2a),
    SkColorSetRGB(0x9b, 0x98, 0xff), SkColorSetRGB(0x29, 0x29, 0x27),
    SkColorSetRGB(0x77, 0x75, 0x6d)};

// The palettes below had no edge colour of their own; their edge is
// their line, so they look as they did.

constexpr Palette kCoolLight = {
    SkColorSetRGB(0xdc, 0xde, 0xe8), SkColorSetRGB(0xd3, 0xd6, 0xe3),
    SK_ColorWHITE,                   SkColorSetRGB(0xee, 0xf0, 0xf6),
    SK_ColorWHITE,                   SkColorSetRGB(0x23, 0x24, 0x2e),
    SkColorSetRGB(0x50, 0x52, 0x65), SkColorSetRGB(0xd9, 0xdb, 0xe6),
    SkColorSetRGB(0x4f, 0x46, 0xe5), SkColorSetRGB(0xe6, 0xe5, 0xfb),
    SkColorSetRGB(0xd9, 0xdb, 0xe6)};

constexpr Palette kCoolDark = {
    SkColorSetRGB(0x07, 0x08, 0x0b), SkColorSetRGB(0x0a, 0x0b, 0x0f),
    SkColorSetRGB(0x1d, 0x1e, 0x28), SkColorSetRGB(0x0f, 0x10, 0x15),
    SkColorSetRGB(0x1d, 0x1e, 0x28), SkColorSetRGB(0xdc, 0xdd, 0xe6),
    SkColorSetRGB(0xa0, 0xa2, 0xb4), SkColorSetRGB(0x2c, 0x2d, 0x3a),
    SkColorSetRGB(0x9d, 0x9a, 0xff), SkColorSetRGB(0x2a, 0x29, 0x50),
    SkColorSetRGB(0x2c, 0x2d, 0x3a)};

// Dusk, the deep blue grey Look, and always dark. The design gives Dusk
// only its swatch in Settings (canvas-source/PageSettings.dc.html): the
// frame band, the bar and the field are those. The rest is a token row in
// the charcoal row's shape, worked out to sit with them (ink, ink2 as
// muted, line, edge, pop as paper, sel as tint, the design's dark accent):
// every text pair at 4.5 to 1 and the edge at 3 to 1 or better (the table
// is in .workflow/scratch/compiled/fix-look/progress.md). As in Soft white,
// window is the frame and nothing washes in the accent.
constexpr Palette kDuskDark = {
    SkColorSetRGB(0x0f, 0x10, 0x17), SkColorSetRGB(0x0f, 0x10, 0x17),
    SkColorSetRGB(0x1b, 0x1d, 0x2b), SkColorSetRGB(0x26, 0x28, 0x38),
    SkColorSetRGB(0x1f, 0x22, 0x32), SkColorSetRGB(0xe6, 0xe7, 0xf0),
    SkColorSetRGB(0xa7, 0xaa, 0xc2), SkColorSetRGB(0x30, 0x33, 0x47),
    SkColorSetRGB(0x9b, 0x98, 0xff), SkColorSetRGB(0x28, 0x2b, 0x3c),
    SkColorSetRGB(0x7c, 0x80, 0x9c)};

constexpr Palette kBeigeLight = {
    SkColorSetRGB(0xe8, 0xe7, 0xe2), SkColorSetRGB(0xe6, 0xe5, 0xdf),
    SkColorSetRGB(0xf7, 0xf6, 0xf2), SK_ColorWHITE,
    SK_ColorWHITE,                   SkColorSetRGB(0x24, 0x2e, 0x2d),
    SkColorSetRGB(0x5d, 0x69, 0x66), SkColorSetRGB(0xd8, 0xdd, 0xd7),
    SkColorSetRGB(0x17, 0x6b, 0x5b), SkColorSetRGB(0xe5, 0xf1, 0xeb),
    SkColorSetRGB(0xd8, 0xdd, 0xd7)};

constexpr Palette kBeigeDark = {
    SkColorSetRGB(0x13, 0x18, 0x17), SkColorSetRGB(0x0e, 0x13, 0x12),
    SkColorSetRGB(0x1c, 0x25, 0x23), SkColorSetRGB(0x13, 0x18, 0x17),
    SkColorSetRGB(0x25, 0x2e, 0x2b), SkColorSetRGB(0xe8, 0xed, 0xe7),
    SkColorSetRGB(0xad, 0xb9, 0xb2), SkColorSetRGB(0x41, 0x4e, 0x47),
    SkColorSetRGB(0x92, 0xd4, 0xbb), SkColorSetRGB(0x27, 0x3f, 0x35),
    SkColorSetRGB(0x41, 0x4e, 0x47)};

// Green keeps Cool's surfaces; only the accent and its washes change. The
// accent is the brand mark's green, lifted in dark so it reads on the dark
// toolbar. The tint is the accent at about 11% over white in light and 18%
// over the toolbar in dark, as the other palettes derive theirs.
constexpr Palette kGreenLight = {
    SkColorSetRGB(0xdc, 0xde, 0xe8), SkColorSetRGB(0xd3, 0xd6, 0xe3),
    SK_ColorWHITE,                   SkColorSetRGB(0xee, 0xf0, 0xf6),
    SK_ColorWHITE,                   SkColorSetRGB(0x23, 0x24, 0x2e),
    SkColorSetRGB(0x50, 0x52, 0x65), SkColorSetRGB(0xd9, 0xdb, 0xe6),
    SkColorSetRGB(0x17, 0x6b, 0x5b), SkColorSetRGB(0xe5, 0xef, 0xed),
    SkColorSetRGB(0xd9, 0xdb, 0xe6)};

constexpr Palette kGreenDark = {
    SkColorSetRGB(0x07, 0x08, 0x0b), SkColorSetRGB(0x0a, 0x0b, 0x0f),
    SkColorSetRGB(0x1d, 0x1e, 0x28), SkColorSetRGB(0x0f, 0x10, 0x15),
    SkColorSetRGB(0x1d, 0x1e, 0x28), SkColorSetRGB(0xdc, 0xdd, 0xe6),
    SkColorSetRGB(0xa0, 0xa2, 0xb4), SkColorSetRGB(0x2c, 0x2d, 0x3a),
    SkColorSetRGB(0x4f, 0xc9, 0xae), SkColorSetRGB(0x26, 0x3d, 0x40),
    SkColorSetRGB(0x2c, 0x2d, 0x3a)};

// The seed colours we recognise. Cool's is registered as the default (see
// frame-color.patch); with it the Look picks the palette. Beige's is the teal we shipped first, so a profile
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
// Green's swatch. Not the accent itself, which is the legacy Beige seed
// above, so a profile that holds that teal stays Beige.
constexpr SkColor kGreenSeed = SkColorSetRGB(0x1f, 0x8a, 0x72);

bool UsingOurTheme(const ui::ColorProviderKey& key) {
  return !key.custom_theme &&
         key.user_color_source ==
             ui::ColorProviderKey::UserColorSource::kAccent &&
         (key.user_color == kCoolSeed || key.user_color == kBeigeSeed ||
          key.user_color == kLegacyBeigeSeed || key.user_color == kGreenSeed);
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

// Green when the profile holds Green's seed, or with --boring-scheme=green.
bool WantsGreen(const ui::ColorProviderKey& key) {
  if (key.user_color == kGreenSeed) {
    return true;
  }
  return base::CommandLine::ForCurrentProcess()->GetSwitchValueASCII(
             "boring-scheme") == "green";
}

// The Look picked in Settings, Appearance: the profile pref
// boring.appearance.look, which theme_service.cc puts in the key
// (patches/157/cui-colours.patch), so a new Look repaints at once. Or
// --boring-scheme=soft_white, slate or dusk, for the capture tools.
ui::ColorProviderKey::BoringLook GetLook(const ui::ColorProviderKey& key) {
  using Look = ui::ColorProviderKey::BoringLook;
  const std::string scheme =
      base::CommandLine::ForCurrentProcess()->GetSwitchValueASCII(
          "boring-scheme");
  if (scheme == "soft_white") {
    return Look::kSoftWhite;
  }
  if (scheme == "slate") {
    return Look::kSlate;
  }
  if (scheme == "dusk") {
    return Look::kDusk;
  }
  return key.boring_look;
}

const Palette& LookPalette(const ui::ColorProviderKey& key, bool dark) {
  switch (GetLook(key)) {
    case ui::ColorProviderKey::BoringLook::kSlate:
      return dark ? kCoolDark : kCoolLight;
    case ui::ColorProviderKey::BoringLook::kDusk:
      return kDuskDark;
    case ui::ColorProviderKey::BoringLook::kSoftWhite:
      break;
  }
  return dark ? kSoftWhiteDark : kSoftWhiteLight;
}

// The accent picked in Settings, Appearance: the profile pref
// boring.appearance.accent, which theme_service.cc checks and puts in the
// key (patches/157/cui-colours.patch), so a new accent repaints at once.
// The default is the indigo Soft white and Slate are drawn with; it, or no
// valid value at all, leaves every palette exactly as it is, the Look's
// own accent lifted in dark. Any other colour replaces the accent and its
// wash under every Look; the surfaces, ink, line and edge stay the Look's.
constexpr SkColor kDefaultAccent = SkColorSetRGB(0x4f, 0x46, 0xe5);

bool HasCustomAccent(const ui::ColorProviderKey& key) {
  return key.boring_accent && *key.boring_accent != kDefaultAccent;
}

// The Look's palette with a custom accent in place. Soft white and Dusk
// wash nothing in the accent (their tint is the neutral sel); the other
// palettes wash it about 11% over the toolbar in light and 18% in dark,
// as Green's tints are made.
Palette WithAccent(const Palette& look,
                   const ui::ColorProviderKey& key,
                   bool dark) {
  Palette p = look;
  if (!HasCustomAccent(key)) {
    return p;
  }
  p.accent = *key.boring_accent;
  if (&look != &kSoftWhiteLight && &look != &kSoftWhiteDark &&
      &look != &kDuskDark) {
    p.tint = color_utils::AlphaBlend(p.accent, p.toolbar, dark ? 0.18f : 0.11f);
  }
  return p;
}

// Text and icons drawn on the accent: buttons, selected text. The palettes'
// own pairs are as drawn. On a custom accent, white when it reaches 4.5 to
// 1; when it does not, the accent is light enough (relative luminance past
// 0.18) that black reaches more than 4.6 to 1.
SkColor OnAccent(const Palette& p, const ui::ColorProviderKey& key, bool dark) {
  if (!HasCustomAccent(key)) {
    return dark ? p.window : SK_ColorWHITE;
  }
  return color_utils::GetContrastRatio(SK_ColorWHITE, p.accent) >= 4.5f
             ? SK_ColorWHITE
             : SK_ColorBLACK;
}

// The accent where it is drawn on a surface rather than filled: focus
// rings and accented icons need 3 to 1, links 4.5 to 1, on the frame,
// toolbar, field and paper. A custom accent that falls short is moved
// toward the ink in 5% steps until it gets there; the person's own colour
// still fills buttons, switches that are on and selections. The ink is
// past 4.5 to 1 on every surface (test_palettes.py), so this always ends.
SkColor AccentOnSurfaces(const Palette& p,
                         const ui::ColorProviderKey& key,
                         float ratio) {
  if (!HasCustomAccent(key)) {
    return p.accent;
  }
  for (int step = 0; step < 20; ++step) {
    const SkColor c = color_utils::AlphaBlend(p.ink, p.accent, step / 20.0f);
    if (color_utils::GetContrastRatio(c, p.frame) >= ratio &&
        color_utils::GetContrastRatio(c, p.toolbar) >= ratio &&
        color_utils::GetContrastRatio(c, p.field) >= ratio &&
        color_utils::GetContrastRatio(c, p.paper) >= ratio) {
      return c;
    }
  }
  return p.ink;
}

}  // namespace

void AddBoringColorMixer(ui::ColorProvider* provider,
                         const ui::ColorProviderKey& key) {
  // The edge id has a colour under every theme: with Chromium's own
  // colours it is the outline button's border.
  // The ok id is the accent there, as the shield was before.
  ui::ColorMixer& ids = provider->AddMixer();
  ids[kColorBoringEdge] = {ui::kColorButtonBorder};
  ids[kColorBoringOk] = {ui::kColorSysPrimary};
  if (!UsingOurTheme(key)) {
    return;
  }
  // Dusk is always dark. With the Look picked in Settings, theme_service.cc
  // already puts dark in the key (cui-colours.patch); this covers
  // --boring-scheme=dusk too.
  const bool dark =
      key.color_mode == ui::ColorProviderKey::ColorMode::kDark ||
      GetLook(key) == ui::ColorProviderKey::BoringLook::kDusk;
  const Palette& look = WantsBeige(key)
                            ? (dark ? kBeigeDark : kBeigeLight)
                            : WantsGreen(key)
                                  ? (dark ? kGreenDark : kGreenLight)
                                  : LookPalette(key, dark);
  // The accent from Settings, Appearance, over whichever palette that is.
  const Palette p = WithAccent(look, key, dark);
  const SkColor on_accent = OnAccent(p, key, dark);
  const SkColor accent_ring = AccentOnSurfaces(p, key, 3.0f);
  const SkColor accent_text = AccentOnSurfaces(p, key, 4.5f);
  ui::ColorMixer& mixer = provider->AddMixer();
  // The mock's hover wash: 7% of the ink in light, 9% in dark.
  const float hover_wash = dark ? 0.09f : 0.07f;

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
      color_utils::AlphaBlend(p.ink, p.frame, hover_wash)};
  mixer[kColorTabBackgroundInactiveHoverFrameInactive] = {
      color_utils::AlphaBlend(p.ink, p.window, hover_wash)};
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
  // The side tab strip's buttons (new tab, tab search) are filled from
  // Chromium's header container, which comes from the seed colour and so
  // stayed indigo under Green. A wash of the accent instead.
  mixer[kColorNewTabButtonCRBackgroundFrameActive] = {p.tint};
  mixer[kColorNewTabButtonCRBackgroundFrameInactive] = {p.tint};
  mixer[kColorTabSearchButtonCRForegroundFrameActive] = {p.ink};
  mixer[kColorTabSearchButtonCRForegroundFrameInactive] = {p.muted};

  // Toolbar controls.
  mixer[kColorToolbarText] = {p.ink};
  mixer[kColorToolbarButtonIcon] = {p.ink};
  mixer[kColorToolbarButtonIconInactive] = {p.muted};
  // As in the mock, a button you hover or press gets a wash of the ink
  // behind it and its icon turns accent; pressing deepens the wash to
  // the accent's own.
  mixer[kColorToolbarButtonIconHovered] = {accent_ring};
  mixer[kColorToolbarButtonIconPressed] = {accent_ring};
  mixer[kColorToolbarInkDrop] = {p.ink};
  mixer[kColorToolbarInkDropHover] = {
      SkColorSetA(p.ink, dark ? 0x17 : 0x12)};
  mixer[kColorToolbarInkDropRipple] = {
      SkColorSetA(p.accent, dark ? 0x38 : 0x29)};
  mixer[kColorToolbarSeparator] = {p.line};
  mixer[kColorNewTabButtonForegroundFrameActive] = {p.ink};
  mixer[kColorNewTabButtonForegroundFrameInactive] = {p.muted};

  // The bookmarks bar is one surface with the toolbar above it (Chromium's
  // Material mixer gives it the page base colour instead). Its buttons
  // are made with the toolbar's ink drop, so they already take the same
  // hover and press wash.
  mixer[kColorBookmarkBarBackground] = {p.toolbar};
  mixer[kColorBookmarkBarForeground] = {p.ink};
  mixer[kColorBookmarkBarForegroundDisabled] = {p.muted};
  mixer[kColorBookmarkButtonIcon] = {p.ink};
  mixer[kColorBookmarkFolderIcon] = {p.ink};
  mixer[kColorBookmarkBarSeparatorChromeRefresh] = {p.line};

  // The address bar reads as a field you can type in, like the boxes on
  // our own pages. The location bar reads its own two ids, not the
  // subtle-emphasis pair, so both have to be set.
  mixer[kColorLocationBarBackground] = {p.field};
  mixer[kColorLocationBarBackgroundHovered] = {p.field};
  mixer[kColorToolbarBackgroundSubtleEmphasis] = {p.field};
  mixer[kColorToolbarBackgroundSubtleEmphasisHovered] = {p.field};
  mixer[kColorOmniboxText] = {p.ink};
  mixer[kColorOmniboxTextDimmed] = {p.muted};
  // Its edge is the design's 3 to 1 edge, as on every field.
  mixer[kColorLocationBarBorder] = {p.edge};
  mixer[kColorLocationBarBorderOpaque] = {p.edge};
  // The focus glow around the address bar: the mock's soft accent, 10% in
  // light and 14% in dark. LocationBarView reads this id for its focus
  // ring (see location-bar-focus-glow.patch).
  mixer[kColorLocationBarBorderOnMismatch] = {
      SkColorSetA(p.accent, dark ? 0x24 : 0x1A)};
  mixer[kColorOmniboxResultsBackground] = {p.paper};

  // One accent, used where something is focused or selected.
  mixer[ui::kColorFocusableBorderFocused] = {accent_ring};
  mixer[kColorOmniboxResultsIconSelected] = {accent_ring};
  // Selected text, in the address bar and on Chromium's own pages. Its
  // default is a tone of the seed colour, which stayed indigo under
  // Green. Filled with the accent, as a button is, so the text on it
  // reads at the same contrast.
  mixer[ui::kColorSysStateTextHighlight] = {p.accent};
  mixer[ui::kColorSysStateOnTextHighlight] = {on_accent};

  // Chromium's own pages are painted from this same colour provider.
  // Without these, settings and history keep Chromium's blue and the
  // browser reads as two products stuck together.
  mixer[ui::kColorSysPrimary] = {p.accent};
  mixer[ui::kColorSysOnPrimary] = {on_accent};
  mixer[ui::kColorSysPrimaryContainer] = {p.tint};
  mixer[ui::kColorSysOnPrimaryContainer] = {p.ink};
  mixer[ui::kColorSysStateFocusRing] = {accent_ring};
  mixer[ui::kColorLinkForegroundDefault] = {accent_text};
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
  mixer[ui::kColorLinkForeground] = {accent_text};

  // Text fields, outline buttons and switches that are off take the same
  // edge as the address bar. A palette with no edge of its own (its edge
  // is its line) keeps Chromium's colours for them, as before.
  mixer[kColorBoringEdge] = {p.edge};
  // The design's ok green, the same in every Look (TOKENS rows): 5 to 1 on
  // the light toolbar, 7.7 to 1 on the dark one.
  mixer[kColorBoringOk] = {dark ? SkColorSetRGB(0x4c, 0xc3, 0x8a)
                                : SkColorSetRGB(0x1a, 0x7f, 0x55)};
  if (p.edge != p.line) {
    mixer[ui::kColorTextfieldOutline] = {p.edge};
    mixer[ui::kColorButtonBorder] = {p.edge};
    mixer[ui::kColorToggleButtonTrackOff] = {p.edge};
  }

  // Rows in our own popups (the search engine list) hover the same way as
  // the menus below. It is painted over the row, so it has to be
  // see-through or it covers the text: a light wash of the accent.
  mixer[kColorHoverButtonBackgroundHovered] = {SkColorSetA(p.accent, 0x24)};

  // The compiled UI's other pieces add their colour ids in their own
  // block below, from the palette `p` (tokens to fields: see the Soft
  // white comment above), so their merges stay apart. These come before
  // the high contrast return; a piece that must leave high contrast alone
  // puts its lines after it.
  // boring: cui-icons
  // boring: end cui-icons
  // boring: cui-tabgroups
  // The nine group colours, quieter than Chromium's Google tones. Each is
  // the solid label, the line under the group and, washed out, the band
  // behind its tabs (TabGroupStyle::GetTabTint). Light ones are dark enough
  // for white label text and dark ones light enough for Chromium's
  // near-black label text, both at least 5.3 to 1; the tab titles on the
  // wash stay above 5.3 to 1 too. Cyan is the compiled design's teal.
  struct GroupColour {
    ui::ColorId active;
    ui::ColorId inactive;
    SkColor light;
    SkColor dark;
  };
  const GroupColour group_colours[] = {
      {kColorTabGroupTabStripFrameActiveGrey,
       kColorTabGroupTabStripFrameInactiveGrey, SkColorSetRGB(0x5c, 0x5f, 0x66),
       SkColorSetRGB(0xb9, 0xbc, 0xc2)},
      {kColorTabGroupTabStripFrameActiveBlue,
       kColorTabGroupTabStripFrameInactiveBlue, SkColorSetRGB(0x2f, 0x5f, 0xb3),
       SkColorSetRGB(0x8a, 0xb4, 0xf8)},
      {kColorTabGroupTabStripFrameActiveRed,
       kColorTabGroupTabStripFrameInactiveRed, SkColorSetRGB(0xb3, 0x26, 0x1e),
       SkColorSetRGB(0xf2, 0x8b, 0x82)},
      {kColorTabGroupTabStripFrameActiveYellow,
       kColorTabGroupTabStripFrameInactiveYellow,
       SkColorSetRGB(0x83, 0x5c, 0x00), SkColorSetRGB(0xf2, 0xc3, 0x5b)},
      {kColorTabGroupTabStripFrameActiveGreen,
       kColorTabGroupTabStripFrameInactiveGreen,
       SkColorSetRGB(0x1e, 0x7a, 0x3c), SkColorSetRGB(0x7f, 0xcf, 0x96)},
      {kColorTabGroupTabStripFrameActivePink,
       kColorTabGroupTabStripFrameInactivePink, SkColorSetRGB(0xad, 0x2f, 0x69),
       SkColorSetRGB(0xf4, 0x8f, 0xb9)},
      {kColorTabGroupTabStripFrameActivePurple,
       kColorTabGroupTabStripFrameInactivePurple,
       SkColorSetRGB(0x6b, 0x45, 0xb8), SkColorSetRGB(0xc3, 0xa6, 0xf5)},
      {kColorTabGroupTabStripFrameActiveCyan,
       kColorTabGroupTabStripFrameInactiveCyan, SkColorSetRGB(0x0f, 0x6f, 0x66),
       SkColorSetRGB(0x6f, 0xcf, 0xc4)},
      {kColorTabGroupTabStripFrameActiveOrange,
       kColorTabGroupTabStripFrameInactiveOrange,
       SkColorSetRGB(0x9c, 0x47, 0x00), SkColorSetRGB(0xf5, 0xa3, 0x5c)},
  };
  for (const GroupColour& group : group_colours) {
    mixer[group.active] = {dark ? group.dark : group.light};
    mixer[group.inactive] = {dark ? group.dark : group.light};
  }
  // boring: end cui-tabgroups
  // boring: cui-toolbar
  // The hairline ahead of the menu button is a ToolbarDivider, which
  // paints in this id: the line token, as drawn.
  mixer[kColorToolbarExtensionSeparatorEnabled] = {p.line};
  // A disabled toolbar button (back or forward with nowhere to go) in the
  // design's faint ink (ink3 in the TOKENS rows); other Looks take their
  // quiet ink halfway to the bar. toolbar_button.cc reads this id for a
  // disabled button (cui-toolbar.patch).
  mixer[kColorToolbarButtonIconDisabled] = {
      &look == &kSoftWhiteLight  ? SkColorSetRGB(0xaa, 0xa6, 0x9d)
      : &look == &kSoftWhiteDark ? SkColorSetRGB(0x63, 0x61, 0x5b)
                                 : color_utils::AlphaBlend(p.muted, p.toolbar,
                                                           0.5f)};
  // boring: end cui-toolbar
  // boring: cui-menu
  // The Customize toolbar panel (screen C11) and every other side panel
  // sit on the toolbar's own surface, as drawn, not on the tonal container
  // Chromium derives from the seed colour (lavender in light, indigo in
  // dark). The button of an open panel takes the toolbar's hover wash.
  mixer[kColorSidePanelBackground] = {p.toolbar};
  mixer[kColorSidePanelContentBackground] = {p.toolbar};
  mixer[kColorToolbarButtonBackgroundHighlightedDefault] = {
      SkColorSetA(p.ink, dark ? 0x17 : 0x12)};
  // boring: end cui-menu
  // boring: cui-pages
  // The page token (Window.dc.html TOKENS, and the Look previews in
  // PageSettings.dc.html): the ground under Settings and our own pages,
  // which read it as --color-new-tab-page-background, so it follows the
  // Look. A Look the design gives no page for takes its field halfway to
  // the bar.
  SkColor page = color_utils::AlphaBlend(p.field, p.toolbar, 0.5f);
  if (&look == &kSoftWhiteLight) {
    page = SkColorSetRGB(0xf8, 0xf7, 0xf4);
  } else if (&look == &kSoftWhiteDark) {
    page = SkColorSetRGB(0x15, 0x15, 0x14);
  } else if (&look == &kCoolLight) {
    page = SkColorSetRGB(0xf5, 0xf6, 0xf8);
  } else if (&look == &kDuskDark) {
    page = SkColorSetRGB(0x14, 0x15, 0x20);
  }
  mixer[kColorNewTabPageBackground] = {page};
  // boring: end cui-pages

  // Windows high contrast: menus keep the system colours Chromium maps
  // them to (ui/color/win/native_color_mixers_win.cc), as the stock menu
  // does: the main menu's cards take the menu's own background, a row or
  // tile you hover the system highlight. Known limit: the rest of the
  // window, and the accent (kColorSysPrimary) on the menu's icons, keep
  // the palette.
  if (key.contrast_mode == ui::ColorProviderKey::ContrastMode::kHigh) {
    return;
  }

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

  // The main menu's cards and tiles (views/boring/boring_app_menu.cc), as
  // in design/v9-menu: the address bar's field colour in light, a little
  // of the ink over the paper in dark. A palette whose field is the paper
  // itself (Beige light) takes the ink wash too, so the cards still show.
  mixer[kColorAppMenuToolsAndActionsBackground] = {
      !dark && p.field != p.paper
          ? p.field
          : color_utils::AlphaBlend(p.ink, p.paper, 0.058f)};
  // A row or tile you hover in the main menu takes the mock's wash of the
  // accent, 14% in light and 20% in dark. The tint above hardly shows on
  // the card's fill.
  const SkColor menu_card_hover = SkColorSetA(p.accent, dark ? 0x33 : 0x24);
  mixer[ui::kColorAppMenuRowBackgroundHovered] = {menu_card_hover};
  // The zoom row's round buttons sit on a card: paper in light, a faint
  // ink in dark.
  mixer[ui::kColorMenuButtonBackground] = {dark ? SkColorSetA(p.ink, 0x1A)
                                                : p.paper};
  mixer[ui::kColorMenuButtonBackgroundSelected] = {menu_card_hover};

  // boring: cui-menu. The main menu's cards in the compiled design's card
  // token (design/v12-compiled, Window.dc.html TOKENS), fainter than the
  // field colour above. The top buttons' outline is kColorBoringEdge
  // (cui-colours).
  mixer[kColorAppMenuToolsAndActionsBackground] = {
      dark ? SkColorSetRGB(0x27, 0x27, 0x25) : SkColorSetRGB(0xf6, 0xf5, 0xf1)};
  // boring: end cui-menu.
}
