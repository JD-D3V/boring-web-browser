#!/usr/bin/env python3
"""Tests for the colour schemes in boring_color_mixer.cc.

The palettes are plain constants in the C++ file; these tests read them
from the source so a bad colour fails here and not after a build.

Usage:
  python -m unittest boring-core/tools/tests/test_palettes.py -v
"""

import colorsys
import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
MIXER = (
    CORE
    / "chromium_src"
    / "chrome"
    / "browser"
    / "ui"
    / "color"
    / "boring_color_mixer.cc"
)
FRAME_PATCH = CORE / "patches" / "frame-color.patch"

FIELDS = [
    "window",
    "frame",
    "toolbar",
    "field",
    "paper",
    "ink",
    "muted",
    "line",
    "accent",
    "tint",
    "edge",
]
# The palettes from before the compiled UI. Their rules (the band six
# points off the toolbar) came from the earlier mockup.
OLD_NAMES = [
    "kCoolLight",
    "kCoolDark",
    "kBeigeLight",
    "kBeigeDark",
    "kGreenLight",
    "kGreenDark",
]
NAMES = ["kSoftWhiteLight", "kSoftWhiteDark", "kDuskDark", *OLD_NAMES]

# The two TOKENS rows of design/v12-compiled/canvas-source/Window.dc.html,
# mapped to the palette's fields (see the Soft white comment in the mixer).
SOFT_WHITE = {
    "kSoftWhiteLight": {
        "window": "#eceae6", "frame": "#eceae6", "toolbar": "#ffffff",
        "field": "#f4f3ef", "paper": "#ffffff", "ink": "#1f1e1c",
        "muted": "#5d5a54", "line": "#e2dfd9", "accent": "#4f46e5",
        "tint": "#f0eeea", "edge": "#8a867d",
    },
    "kSoftWhiteDark": {
        "window": "#111110", "frame": "#111110", "toolbar": "#1c1c1a",
        "field": "#121211", "paper": "#20201e", "ink": "#ecebe7",
        "muted": "#a9a79f", "line": "#2d2d2a", "accent": "#9b98ff",
        "tint": "#292927", "edge": "#77756d",
    },
}
PREFS_H = CORE / "components" / "boring" / "core" / "boring_prefs.h"
PREFS_CC = CORE / "components" / "boring" / "core" / "boring_prefs.cc"
COLOURS_PATCH = CORE / "patches" / "157" / "cui-colours.patch"
SERIES = CORE / "patches" / "series"

RGB = re.compile(
    r"SkColorSetRGB\(\s*0x([0-9a-fA-F]{2}),\s*0x([0-9a-fA-F]{2}),\s*0x([0-9a-fA-F]{2})\s*\)"
)
TOKEN = re.compile(RGB.pattern + r"|SK_ColorWHITE")


def parse_palettes():
    src = MIXER.read_text(encoding="utf-8")
    out = {}
    for name in NAMES:
        m = re.search(rf"constexpr Palette {name}\s*=\s*\{{(.*?)\}};", src, re.S)
        if not m:
            continue
        colours = []
        for t in TOKEN.finditer(m.group(1)):
            if t.group(0) == "SK_ColorWHITE":
                colours.append((255, 255, 255))
            else:
                colours.append(tuple(int(t.group(i), 16) for i in (1, 2, 3)))
        out[name] = dict(zip(FIELDS, colours, strict=False))
        out[name]["_count"] = len(colours)
    return out


def hexof(c):
    return "#{:02x}{:02x}{:02x}".format(*c)


def luminance(c):
    def lin(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def lightness_pct(c):
    return colorsys.rgb_to_hls(*(v / 255 for v in c))[1] * 100


PALETTES = parse_palettes()


class PaletteTest(unittest.TestCase):
    def test_every_palette_exists_with_eleven_colours(self):
        self.assertEqual(sorted(PALETTES), sorted(NAMES))
        for name, p in PALETTES.items():
            self.assertEqual(p["_count"], len(FIELDS), name)

    def test_frame_band_differs_from_toolbar_by_6_points_of_lightness(self):
        # Soft white is drawn closer than that in dark (TOKENS row).
        for name in OLD_NAMES:
            p = PALETTES[name]
            diff = abs(lightness_pct(p["frame"]) - lightness_pct(p["toolbar"]))
            self.assertGreaterEqual(
                diff, 6, f"{name} band/toolbar differ by {diff:.1f}"
            )

    def test_ink_contrast_at_least_4_5_on_every_surface(self):
        for name, p in PALETTES.items():
            for surface in ("frame", "toolbar", "field", "paper"):
                self.assertGreaterEqual(
                    contrast(p["ink"], p[surface]),
                    4.5,
                    f"{name} ink on {surface}",
                )

    def test_muted_contrast_at_least_4_5_on_every_surface(self):
        # Inactive tab titles are small text on the frame band.
        for name, p in PALETTES.items():
            for surface in ("frame", "window", "toolbar", "field", "paper"):
                self.assertGreaterEqual(
                    contrast(p["muted"], p[surface]),
                    4.5,
                    f"{name} muted on {surface}",
                )

    def test_accent_is_legible_on_toolbar(self):
        for name, p in PALETTES.items():
            self.assertGreaterEqual(
                contrast(p["accent"], p["toolbar"]),
                3,
                f"{name} accent on toolbar",
            )

    def test_cool_matches_the_approved_mockup(self):
        light, dark = PALETTES["kCoolLight"], PALETTES["kCoolDark"]
        self.assertEqual(hexof(light["frame"]), "#d3d6e3")
        self.assertEqual(hexof(light["toolbar"]), "#ffffff")
        self.assertEqual(hexof(light["field"]), "#eef0f6")
        self.assertEqual(hexof(light["ink"]), "#23242e")
        self.assertEqual(hexof(light["accent"]), "#4f46e5")
        self.assertEqual(hexof(dark["frame"]), "#0a0b0f")
        self.assertEqual(hexof(dark["toolbar"]), "#1d1e28")
        self.assertEqual(hexof(dark["field"]), "#0f1015")
        self.assertEqual(hexof(dark["accent"]), "#9d9aff")

    def test_beige_keeps_the_existing_warm_values(self):
        light, dark = PALETTES["kBeigeLight"], PALETTES["kBeigeDark"]
        self.assertEqual(hexof(light["window"]), "#e8e7e2")
        self.assertEqual(hexof(light["ink"]), "#242e2d")
        self.assertEqual(hexof(light["muted"]), "#5d6966")
        self.assertEqual(hexof(light["line"]), "#d8ddd7")
        self.assertEqual(hexof(light["accent"]), "#176b5b")
        self.assertEqual(hexof(light["tint"]), "#e5f1eb")
        self.assertEqual(hexof(dark["window"]), "#131817")
        self.assertEqual(hexof(dark["ink"]), "#e8ede7")
        self.assertEqual(hexof(dark["muted"]), "#adb9b2")
        self.assertEqual(hexof(dark["line"]), "#414e47")
        self.assertEqual(hexof(dark["accent"]), "#92d4bb")
        self.assertEqual(hexof(dark["tint"]), "#273f35")

    def test_green_is_cool_surfaces_with_the_brand_green_accent(self):
        for mode in ("Light", "Dark"):
            green, cool = PALETTES["kGreen" + mode], PALETTES["kCool" + mode]
            for field in FIELDS:
                if field not in ("accent", "tint"):
                    self.assertEqual(green[field], cool[field], f"{mode} {field}")
        self.assertEqual(hexof(PALETTES["kGreenLight"]["accent"]), "#176b5b")
        self.assertEqual(hexof(PALETTES["kGreenDark"]["accent"]), "#4fc9ae")

    def test_green_tints_are_washes_of_the_accent(self):
        # About 11% over white in light and 18% over the toolbar in dark.
        for mode, base, alpha in (
            ("Light", (255, 255, 255), 0.11),
            ("Dark", None, 0.18),
        ):
            p = PALETTES["kGreen" + mode]
            base = base or p["toolbar"]
            want = tuple(
                round(b + (a - b) * alpha)
                for a, b in zip(p["accent"], base, strict=False)
            )
            for got, w in zip(p["tint"], want, strict=False):
                self.assertLessEqual(
                    abs(got - w),
                    1,
                    "{} tint {} vs {}".format(mode, hexof(p["tint"]), hexof(want)),
                )

    def test_default_seed_in_the_frame_patch_is_the_cool_seed(self):
        src = MIXER.read_text(encoding="utf-8")
        cool = RGB.search(re.search(r"kCoolSeed\s*=\s*([^;]+);", src).group(1))
        cool_rgb = tuple(int(cool.group(i), 16) for i in (1, 2, 3))
        patch = FRAME_PATCH.read_text(encoding="utf-8")
        added = [
            ln
            for ln in patch.splitlines()
            if ln.startswith("+") and "SkColorSetRGB" in ln
        ]
        self.assertEqual(len(added), 1)
        m = RGB.search(added[0])
        self.assertEqual(tuple(int(m.group(i), 16) for i in (1, 2, 3)), cool_rgb)
        self.assertEqual(hexof(cool_rgb), "#4f46e5")

    def test_custom_themes_and_other_colours_still_fall_back_to_chromium(self):
        src = MIXER.read_text(encoding="utf-8")
        self.assertIn("!key.custom_theme", src)
        self.assertRegex(src, r"if \(!UsingOurTheme\(key\)\)\s*\{\s*return;")

    def test_tab_hover_is_a_neutral_wash_of_ink_not_chromiums_tinted_default(self):
        src = MIXER.read_text(encoding="utf-8")
        for name, base in (
            ("kColorTabBackgroundInactiveHoverFrameActive", "frame"),
            ("kColorTabBackgroundInactiveHoverFrameInactive", "window"),
        ):
            self.assertRegex(
                src,
                rf"mixer\[{name}\]\s*=\s*\{{\s*color_utils::AlphaBlend\(p\.ink,\s*p\.{base},\s*hover_wash\)\}}",
            )
        self.assertIn("const float hover_wash = dark ? 0.09f : 0.07f;", src)

    def test_toolbar_buttons_wash_on_hover_and_turn_accent_like_the_mock(self):
        src = MIXER.read_text(encoding="utf-8")
        for name in (
            "kColorToolbarButtonIconHovered",
            "kColorToolbarButtonIconPressed",
        ):
            self.assertRegex(src, rf"mixer\[{name}\]\s*=\s*\{{p\.accent\}}")
        self.assertRegex(
            src, r"mixer\[kColorToolbarInkDropHover\]\s*=\s*\{\s*SkColorSetA\(p\.ink,"
        )
        self.assertRegex(
            src,
            r"mixer\[kColorToolbarInkDropRipple\]\s*=\s*\{\s*SkColorSetA\(p\.accent,",
        )

    def test_multi_selected_tabs_use_the_accent_not_chromiums_default(self):
        src = MIXER.read_text(encoding="utf-8")
        for name in (
            "kColorTabBackgroundSelectedFrameActive",
            "kColorTabBackgroundSelectedFrameInactive",
            "kColorTabBackgroundSelectedHoverFrameActive",
            "kColorTabBackgroundSelectedHoverFrameInactive",
        ):
            self.assertRegex(
                src,
                rf"mixer\[{name}\]\s*=\s*\{{\s*color_utils::AlphaBlend\(p\.accent,",
            )

    def test_soft_white_is_the_tokens_rows_value_for_value(self):
        for name, want in SOFT_WHITE.items():
            got = {f: hexof(PALETTES[name][f]) for f in FIELDS}
            self.assertEqual(got, want, name)

    def test_edge_is_3_to_1_on_every_surface_where_it_is_drawn(self):
        for name, p in PALETTES.items():
            if p["edge"] == p["line"]:
                continue
            for surface in ("window", "frame", "toolbar", "field", "paper"):
                self.assertGreaterEqual(
                    contrast(p["edge"], p[surface]), 3, f"{name} edge on {surface}"
                )

    def test_palettes_with_no_drawn_edge_keep_their_line(self):
        for name in (*OLD_NAMES, "kDuskDark"):
            self.assertEqual(PALETTES[name]["edge"], PALETTES[name]["line"], name)

    def test_dusk_takes_its_swatch_and_slate_dark_for_the_rest(self):
        dusk, slate = PALETTES["kDuskDark"], PALETTES["kCoolDark"]
        self.assertEqual(hexof(dusk["frame"]), "#0f1017")
        self.assertEqual(hexof(dusk["toolbar"]), "#1b1d2b")
        self.assertEqual(hexof(dusk["field"]), "#262838")
        self.assertEqual(dusk["paper"], dusk["toolbar"])
        for field in ("window", "ink", "muted", "line", "accent", "tint"):
            self.assertEqual(dusk[field], slate[field], field)

    def test_edge_goes_on_fields_outline_buttons_and_off_switches(self):
        src = MIXER.read_text(encoding="utf-8")
        for name in (
            "kColorLocationBarBorder",
            "kColorLocationBarBorderOpaque",
            "ui::kColorTextfieldOutline",
            "ui::kColorButtonBorder",
            "ui::kColorToggleButtonTrackOff",
            "kColorBoringEdge",
        ):
            self.assertRegex(src, rf"mixer\[{name}\]\s*=\s*\{{p\.edge\}}")
        patch = COLOURS_PATCH.read_text(encoding="utf-8")
        self.assertIn("+  E_CPONLY(kColorBoringEdge) \\", patch)

    def test_ok_is_the_tokens_green_and_legible_on_every_toolbar(self):
        src = MIXER.read_text(encoding="utf-8")
        m = re.search(r"mixer\[kColorBoringOk\]\s*=\s*\{dark \? (.*?)\s*:\s*(SkColorSetRGB\(.*?\))\}", src, re.S)
        dark_ok, light_ok = (
            tuple(int(g, 16) for g in RGB.search(s).groups()) for s in m.groups()
        )
        self.assertEqual((hexof(light_ok), hexof(dark_ok)), ("#1a7f55", "#4cc38a"))
        for name, p in PALETTES.items():
            ok = dark_ok if "Dark" in name else light_ok
            self.assertGreaterEqual(contrast(ok, p["toolbar"]), 4.5, name)
        self.assertIn("+  E_CPONLY(kColorBoringOk) \\", COLOURS_PATCH.read_text(encoding="utf-8"))

    def test_look_pref_is_one_name_everywhere_and_soft_white_by_default(self):
        prefs_h = PREFS_H.read_text(encoding="utf-8")
        self.assertIn('kAppearanceLook[] = "boring.appearance.look"', prefs_h)
        for value in ("soft_white", "slate", "dusk"):
            self.assertIn(f'"{value}"', prefs_h)
        self.assertIn(
            "RegisterStringPref(prefs::kAppearanceLook, prefs::kLookSoftWhite)",
            PREFS_CC.read_text(encoding="utf-8"),
        )
        patch = COLOURS_PATCH.read_text(encoding="utf-8")
        self.assertIn('+constexpr char kBoringLookPref[] = "boring.appearance.look";', patch)
        # Repaints when the pref changes, and carries it in the key.
        self.assertRegex(patch, r"\+\s+kBoringLookPref, base::BindRepeating\(&ThemeService::NotifyThemeChanged")
        self.assertIn("+  key.boring_look =", patch)
        self.assertIn("+  BoringLook boring_look = BoringLook::kSoftWhite;", patch)
        # The key compares it, or a new Look would reuse the old colours.
        self.assertEqual(patch.count("other.boring_look"), 4)
        self.assertIn("cui-colours.patch", SERIES.read_text(encoding="utf-8").split())

    def test_look_picks_the_palette_with_soft_white_the_default(self):
        src = MIXER.read_text(encoding="utf-8")
        body = re.search(r"const Palette& LookPalette\(.*?\n\}", src, re.S).group(0)
        self.assertRegex(body, r"kSlate:\s*return dark \? kCoolDark : kCoolLight;")
        self.assertRegex(body, r"kDusk:\s*return dark \? kDuskDark : kCoolLight;")
        self.assertTrue(body.rstrip("}").rstrip().endswith(
            "return dark ? kSoftWhiteDark : kSoftWhiteLight;"))
        self.assertIn(": LookPalette(key, dark);", src)

    def test_scheme_switch_reads_the_command_line(self):
        src = MIXER.read_text(encoding="utf-8")
        self.assertIn('"boring-scheme"', src)
        self.assertIn("beige", src)
        self.assertIn("green", src)
        for look in ("soft_white", "slate", "dusk"):
            self.assertIn(f'scheme == "{look}"', src)


if __name__ == "__main__":
    unittest.main()
