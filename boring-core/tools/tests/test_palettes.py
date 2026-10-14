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
MIXER = CORE / "chromium_src" / "chrome" / "browser" / "ui" / "color" / "boring_color_mixer.cc"
FRAME_PATCH = CORE / "patches" / "frame-color.patch"

FIELDS = ["window", "frame", "toolbar", "field", "paper", "ink", "muted",
          "line", "accent", "tint"]
NAMES = ["kCoolLight", "kCoolDark", "kBeigeLight", "kBeigeDark"]

RGB = re.compile(r"SkColorSetRGB\(\s*0x([0-9a-fA-F]{2}),\s*0x([0-9a-fA-F]{2}),\s*0x([0-9a-fA-F]{2})\s*\)")
TOKEN = re.compile(RGB.pattern + r"|SK_ColorWHITE")


def parse_palettes():
    src = MIXER.read_text(encoding="utf-8")
    out = {}
    for name in NAMES:
        m = re.search(r"constexpr Palette %s\s*=\s*\{(.*?)\};" % name, src, re.S)
        if not m:
            continue
        colours = []
        for t in TOKEN.finditer(m.group(1)):
            if t.group(0) == "SK_ColorWHITE":
                colours.append((255, 255, 255))
            else:
                colours.append(tuple(int(t.group(i), 16) for i in (1, 2, 3)))
        out[name] = dict(zip(FIELDS, colours))
        out[name]["_count"] = len(colours)
    return out


def hexof(c):
    return "#%02x%02x%02x" % c


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
    def test_four_palettes_exist_with_ten_colours_each(self):
        self.assertEqual(sorted(PALETTES), sorted(NAMES))
        for name, p in PALETTES.items():
            self.assertEqual(p["_count"], len(FIELDS), name)

    def test_frame_band_differs_from_toolbar_by_6_points_of_lightness(self):
        for name, p in PALETTES.items():
            diff = abs(lightness_pct(p["frame"]) - lightness_pct(p["toolbar"]))
            self.assertGreaterEqual(diff, 6, "%s band/toolbar differ by %.1f" % (name, diff))

    def test_ink_contrast_at_least_4_5_on_every_surface(self):
        for name, p in PALETTES.items():
            for surface in ("frame", "toolbar", "field", "paper"):
                self.assertGreaterEqual(contrast(p["ink"], p[surface]), 4.5,
                                        "%s ink on %s" % (name, surface))

    def test_muted_contrast_at_least_4_5_on_every_surface(self):
        # Inactive tab titles are small text on the frame band.
        for name, p in PALETTES.items():
            for surface in ("frame", "window", "toolbar", "field", "paper"):
                self.assertGreaterEqual(contrast(p["muted"], p[surface]), 4.5,
                                        "%s muted on %s" % (name, surface))

    def test_accent_is_legible_on_toolbar(self):
        for name, p in PALETTES.items():
            self.assertGreaterEqual(contrast(p["accent"], p["toolbar"]), 3,
                                    "%s accent on toolbar" % name)

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

    def test_default_seed_in_the_frame_patch_is_the_cool_seed(self):
        src = MIXER.read_text(encoding="utf-8")
        cool = RGB.search(re.search(r"kCoolSeed\s*=\s*([^;]+);", src).group(1))
        cool_rgb = tuple(int(cool.group(i), 16) for i in (1, 2, 3))
        patch = FRAME_PATCH.read_text(encoding="utf-8")
        added = [ln for ln in patch.splitlines() if ln.startswith("+") and "SkColorSetRGB" in ln]
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
        for name, base in (("kColorTabBackgroundInactiveHoverFrameActive", "frame"),
                           ("kColorTabBackgroundInactiveHoverFrameInactive", "window")):
            self.assertRegex(
                src, r"mixer\[%s\]\s*=\s*\{\s*color_utils::AlphaBlend\(p\.ink,\s*p\.%s,\s*hover_wash\)\}" % (name, base))
        self.assertIn("const float hover_wash = dark ? 0.09f : 0.07f;", src)

    def test_toolbar_buttons_wash_on_hover_and_turn_accent_like_the_mock(self):
        src = MIXER.read_text(encoding="utf-8")
        for name in ("kColorToolbarButtonIconHovered", "kColorToolbarButtonIconPressed"):
            self.assertRegex(src, r"mixer\[%s\]\s*=\s*\{p\.accent\}" % name)
        self.assertRegex(src, r"mixer\[kColorToolbarInkDropHover\]\s*=\s*\{\s*SkColorSetA\(p\.ink,")
        self.assertRegex(src, r"mixer\[kColorToolbarInkDropRipple\]\s*=\s*\{\s*SkColorSetA\(p\.accent,")

    def test_multi_selected_tabs_use_the_accent_not_chromiums_default(self):
        src = MIXER.read_text(encoding="utf-8")
        for name in ("kColorTabBackgroundSelectedFrameActive",
                     "kColorTabBackgroundSelectedFrameInactive",
                     "kColorTabBackgroundSelectedHoverFrameActive",
                     "kColorTabBackgroundSelectedHoverFrameInactive"):
            self.assertRegex(src, r"mixer\[%s\]\s*=\s*\{\s*color_utils::AlphaBlend\(p\.accent," % name)

    def test_scheme_switch_reads_the_command_line(self):
        src = MIXER.read_text(encoding="utf-8")
        self.assertIn('"boring-scheme"', src)
        self.assertIn("beige", src)


if __name__ == "__main__":
    unittest.main()
