#!/usr/bin/env python3
"""Cool, Beige and Green are choices in Customize Chrome's colour picker.

Chromium's picker saves the picked colour per profile and already has a
Light / Dark / Device mode. Three of its swatches become our schemes: picking
one stores that scheme's seed colour, and boring_color_mixer.cc recognises
the seed. The tests keep the swatches and the mixer in step.

Usage:
  python -m unittest boring-core/tools/tests/test_color_picker.py -v
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PATCH = CORE / "patches" / "colour-picker-schemes.patch"
SERIES = CORE / "patches" / "series"
MIXER = CORE / "chromium_src" / "chrome" / "browser" / "ui" / "color" / "boring_color_mixer.cc"

RGB = re.compile(r"SkColorSetRGB\(\s*(?:0x)?([0-9a-fA-F]+),\s*(?:0x)?([0-9a-fA-F]+),\s*(?:0x)?([0-9a-fA-F]+)\s*\)")


def added():
    return "\n".join(ln[1:] for ln in PATCH.read_text(encoding="utf-8").splitlines()
                     if ln.startswith("+") and not ln.startswith("+++"))


def after():
    """The patched text as the build sees it: added and untouched lines."""
    return "\n".join(ln[1:] for ln in PATCH.read_text(encoding="utf-8").splitlines()
                     if ln[:1] in ("+", " ") and not ln.startswith("+++"))


def seed(src, name):
    m = re.search(r"%s\s*=\s*(SkColorSetRGB\([^)]*\))" % name, src)
    r = RGB.search(m.group(1))
    base = 16 if "0x" in m.group(1) else 10
    return tuple(int(r.group(i), base) for i in (1, 2, 3))


def picker_entry(label):
    """The seed colour of the swatch with this label in the patch."""
    text = after()
    m = re.search(r"DynamicColorInfo\(\s*/\*id=\*/\d+,\s*(SkColorSetRGB\([^)]*\)),\s*%s," % label, text)
    assert m, label
    r = RGB.search(m.group(1))
    base = 16 if "0x" in m.group(1) else 10
    return tuple(int(r.group(i), base) for i in (1, 2, 3))


class ColourPickerTest(unittest.TestCase):
    def test_patch_is_in_the_series(self):
        names = [ln.strip() for ln in SERIES.read_text().splitlines()]
        self.assertIn("colour-picker-schemes.patch", names)

    def test_cool_swatch_stores_the_mixers_cool_seed(self):
        src = MIXER.read_text(encoding="utf-8")
        self.assertEqual(picker_entry("IDS_NTP_COLORS_BLUE"), seed(src, "kCoolSeed"))

    def test_beige_swatch_stores_the_mixers_beige_seed(self):
        src = MIXER.read_text(encoding="utf-8")
        self.assertEqual(picker_entry("IDS_NTP_COLORS_BEIGE"), seed(src, "kBeigeSeed"))

    def test_green_swatch_stores_the_mixers_green_seed_under_the_name_green(self):
        src = MIXER.read_text(encoding="utf-8")
        self.assertEqual(picker_entry("IDS_NTP_COLORS_GREEN"), seed(src, "kGreenSeed"))

    def test_the_seeds_differ_and_the_old_teal_still_means_beige(self):
        src = MIXER.read_text(encoding="utf-8")
        seeds = [seed(src, n) for n in ("kCoolSeed", "kBeigeSeed", "kLegacyBeigeSeed", "kGreenSeed")]
        self.assertEqual(len(set(seeds)), 4)
        self.assertEqual(seed(src, "kLegacyBeigeSeed"), (0x17, 0x6b, 0x5b))
        self.assertRegex(src, r"key\.user_color == kLegacyBeigeSeed")
        self.assertRegex(src, r"key\.user_color == kBeigeSeed")

    def test_all_schemes_are_recognised_as_ours(self):
        src = MIXER.read_text(encoding="utf-8")
        body = re.search(r"bool UsingOurTheme.*?\n\}", src, re.S).group(0)
        for name in ("kCoolSeed", "kBeigeSeed", "kLegacyBeigeSeed", "kGreenSeed"):
            self.assertIn(name, body)

    def test_labels_are_strings_chromium_already_ships(self):
        # A new string in generated_resources.grd regenerates a header that
        # over a thousand files include, so the names reuse existing ones.
        text = after()
        self.assertIn("IDS_NTP_COLORS_BLUE", text)
        self.assertIn("IDS_NTP_COLORS_BEIGE", text)
        self.assertIn("IDS_NTP_COLORS_GREEN", text)
        self.assertNotIn("generated_resources.grd", PATCH.read_text(encoding="utf-8"))

    def test_green_is_picked_by_its_seed_and_has_its_own_palette(self):
        src = MIXER.read_text(encoding="utf-8")
        self.assertRegex(src, r"bool WantsGreen[^{]*\{\s*if \(key\.user_color == kGreenSeed\)")
        self.assertRegex(src, r"WantsGreen\(key\)\s*\?\s*\(dark \? kGreenDark : kGreenLight\)")

    def test_only_the_picker_file_changes(self):
        files = sorted(ln for ln in PATCH.read_text(encoding="utf-8").splitlines() if ln.startswith("+++ "))
        self.assertEqual(files, [
            "+++ b/chrome/browser/ui/webui/cr_components/theme_color_picker/customize_chrome_colors.cc",
        ])


if __name__ == "__main__":
    unittest.main()
