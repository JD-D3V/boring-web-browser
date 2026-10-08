#!/usr/bin/env python3
"""The menu styling matches the approved mock.

The mock is the "In context" menu in design/v7/icons-dotted. Its numbers are
read from the page's own CSS, and the patch and colour mixer are checked
against them, so the real menu cannot drift from what was approved.

Usage:
  python -m unittest boring-core/tools/tests/test_menu_style.py -v
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
REPO = CORE.parent
PATCH = CORE / "patches" / "menu-style.patch"
SERIES = CORE / "patches" / "series"
MIXER = CORE / "chromium_src" / "chrome" / "browser" / "ui" / "color" / "boring_color_mixer.cc"
MOCK = REPO / "design" / "v7" / "icons-dotted" / "src" / "template.html"


def mock_css():
    text = MOCK.read_text(encoding="utf-8")
    menu = re.search(r"\.menu\{(.*?)\}", text, re.S).group(1)
    button = re.search(r"\.menu button\{(.*?)\}", text, re.S).group(1)
    hr = re.search(r"\.menu hr\{(.*?)\}", text, re.S).group(1)
    return menu, button, hr


def patch_value(name):
    text = PATCH.read_text(encoding="utf-8")
    # The value after the patch: an added line, or one the patch leaves as is.
    m = re.search(r"^[+ ]\s*%s\s*=\s*(\d+);" % re.escape(name), text, re.M)
    assert m, "%s not set in menu-style.patch" % name
    return int(m.group(1))


class MenuStyleTest(unittest.TestCase):
    def test_patch_targets_the_windows_menu_config_and_is_in_the_series(self):
        text = PATCH.read_text(encoding="utf-8")
        self.assertIn("ui/views/controls/menu/menu_config_win.cc", text)
        names = [ln.strip() for ln in SERIES.read_text().splitlines()]
        self.assertIn("menu-style.patch", names)

    def test_corner_radius_is_the_mocks(self):
        menu, _, _ = mock_css()
        radius = int(re.search(r"border-radius:(\d+)px", menu).group(1))
        self.assertEqual(patch_value("corner_radius"), radius)

    def test_outer_padding_is_the_mocks(self):
        menu, _, _ = mock_css()
        pad = int(re.search(r"padding:(\d+)px", menu).group(1))
        self.assertEqual(patch_value("rounded_menu_vertical_border_size"), pad)

    def test_row_hover_radius_and_vertical_padding_are_the_mocks(self):
        _, button, _ = mock_css()
        item_radius = int(re.search(r"border-radius:(\d+)px", button).group(1))
        vertical = int(re.search(r"padding:(\d+)px \d+px", button).group(1))
        self.assertEqual(patch_value("item_corner_radius"), item_radius)
        self.assertEqual(patch_value("item_vertical_margin"), vertical)

    def test_icon_to_text_gap_is_the_mocks(self):
        _, button, _ = mock_css()
        gap = int(re.search(r"gap:(\d+)px", button).group(1))
        self.assertEqual(patch_value("item_horizontal_padding"), gap)

    def test_separator_spacing_is_the_mocks(self):
        _, _, hr = mock_css()
        margin = int(re.search(r"margin:(\d+)px", hr).group(1))
        self.assertEqual(patch_value("separator_upper_height"), margin)
        self.assertEqual(patch_value("separator_lower_height"), margin)

    def test_menu_text_is_one_pixel_bigger_than_the_system_menu_font(self):
        # The mock's rows are 13.5 px; the Windows menu font is 12 px, and
        # Chromium sizes fonts in whole pixels, so 13 is the nearest.
        text = PATCH.read_text(encoding="utf-8")
        self.assertIn("DeriveWithSizeDelta(1)", text)

    def test_menu_colours_come_from_the_palette(self):
        src = MIXER.read_text(encoding="utf-8")
        for name, field in (("kColorMenuBackground", "paper"),
                            ("kColorMenuBorder", "line"),
                            ("kColorMenuItemForeground", "ink"),
                            ("kColorMenuItemForegroundSecondary", "muted"),
                            ("kColorMenuSeparator", "line"),
                            ("kColorMenuIcon", "ink")):
            self.assertRegex(src, r"mixer\[ui::%s\]\s*=\s*\{p\.%s\}" % (name, field))

    def test_row_hover_uses_the_accent_tint(self):
        src = MIXER.read_text(encoding="utf-8")
        self.assertRegex(src, r"mixer\[ui::kColorMenuItemBackgroundHighlighted\]\s*=\s*\{p\.tint\}")
        self.assertRegex(src, r"mixer\[ui::kColorMenuItemBackgroundSelected\]\s*=\s*\{p\.tint\}")


if __name__ == "__main__":
    unittest.main()
