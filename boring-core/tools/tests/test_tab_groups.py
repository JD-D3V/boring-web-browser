#!/usr/bin/env python3
"""Tab groups (compiled UI ledger item 4): the patch, the colours and the
smoke's picture checks, without a browser.

Usage:
  python -m unittest boring-core/tools/tests/test_tab_groups.py -v
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CORE / "tools"))

import smoke_tabgroups as sm  # noqa: E402

PATCH = CORE / "patches" / "157" / "tab-groups.patch"
SERIES = CORE / "patches" / "series"
# The compiled design's TOKENS rows (design/v12-compiled/canvas-source/Window.dc.html).
DESIGN = {
    "light": {"frame": (0xEC, 0xEA, 0xE6), "ink2": (0x5D, 0x5A, 0x54),
              "group": (0x0F, 0x6F, 0x66), "groupTint": (0xD9, 0xEC, 0xEA)},
    "dark": {"frame": (0x11, 0x11, 0x10), "ink2": (0xA9, 0xA7, 0x9F),
             "group": (0x6F, 0xCF, 0xC4), "groupTint": (0x15, 0x30, 0x2E)},
}


def series():
    return [ln.strip() for ln in SERIES.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


class Patch(unittest.TestCase):
    def test_in_the_series_after_every_tab_patch(self):
        names = series()
        self.assertIn("tab-groups.patch", names)
        for older in ("tab-underline.patch", "tab-connected.patch",
                      "tab-mock-metrics.patch", "tab-chrome-sizes.patch"):
            self.assertLess(names.index(older), names.index("tab-groups.patch"))

    def test_every_file_it_touches_has_a_boring_marker(self):
        text = PATCH.read_text(encoding="utf-8")
        for part in text.split("diff --git ")[1:]:
            name = part.split("\n", 1)[0]
            added = [ln for ln in part.splitlines() if ln.startswith("+") and not ln.startswith("+++")]
            self.assertTrue(any("boring:" in ln for ln in added), name)

    def test_line_is_3_dip_top_and_side(self):
        text = PATCH.read_text(encoding="utf-8")
        self.assertIn("+  static constexpr int kStrokeThickness = 3;", text)
        self.assertIn("+constexpr int kGroupLineWidth = 3;", text)

    def test_wash_formula_matches_the_smoke(self):
        text = PATCH.read_text(encoding="utf-8")
        self.assertIn("dark ? SK_ColorBLACK : SK_ColorWHITE", text)
        self.assertIn("dark ? 0.22f : 0.15f", text)
        self.assertEqual(sm.tint((100, 100, 100), dark=True), (22, 22, 22))
        self.assertEqual(sm.tint((0, 0, 0), dark=False), (217, 217, 217))

    def test_wash_on_top_tabs_side_tabs_and_the_label(self):
        text = PATCH.read_text(encoding="utf-8")
        for f in ("horizontal_tab_style_views.cc", "vertical_tab_style_views.cc",
                  "tab_group_header.cc"):
            part = text.split(f"diff --git a/chrome/browser/ui/views/tabs/")
            hunk = next(p for p in part if p.split(" ", 1)[0].endswith(f))
            self.assertIn("TabGroupStyle::GetTabTint(", hunk, f)

    def test_refresh_flag_left_alone(self):
        self.assertNotIn("TabGroupColorRefresh", PATCH.read_text(encoding="utf-8"))


class Colours(unittest.TestCase):
    def setUp(self):
        self.colours = sm.group_colours()

    def test_all_nine_group_colours(self):
        self.assertEqual(sorted(self.colours), sorted(sm.COLOURS))

    def test_cyan_is_the_designs_teal(self):
        light, dark = self.colours["cyan"]
        self.assertEqual(light, DESIGN["light"]["group"])
        self.assertEqual(dark, DESIGN["dark"]["group"])

    def test_label_text_at_least_4_5_to_1(self):
        for name, (light, dark) in self.colours.items():
            self.assertTrue(sm.is_dark(light), f"{name} light gets white text")
            self.assertFalse(sm.is_dark(dark), f"{name} dark gets near black text")
            self.assertGreaterEqual(sm.contrast(light, sm.label_ink(light)), 4.5, name)
            self.assertGreaterEqual(sm.contrast(dark, sm.label_ink(dark)), 4.5, name)

    def test_tab_titles_on_the_wash_at_least_4_5_to_1(self):
        for name, (light, dark) in self.colours.items():
            self.assertGreaterEqual(
                sm.contrast(DESIGN["light"]["ink2"], sm.tint(light, False)), 4.5, name)
            self.assertGreaterEqual(
                sm.contrast(DESIGN["dark"]["ink2"], sm.tint(dark, True)), 4.5, name)

    def test_line_stands_out_from_the_strip(self):
        for name, (light, dark) in self.colours.items():
            self.assertGreaterEqual(sm.contrast(light, DESIGN["light"]["frame"]), 3, name)
            self.assertGreaterEqual(sm.contrast(dark, DESIGN["dark"]["frame"]), 3, name)

    def test_cyan_wash_is_close_to_the_designs(self):
        light, dark = self.colours["cyan"]
        self.assertTrue(sm.near(sm.tint(light, False), DESIGN["light"]["groupTint"], 4))
        self.assertTrue(sm.near(sm.tint(dark, True), DESIGN["dark"]["groupTint"], 4))


def blank(w, h, rgb):
    return [[rgb] * w for _ in range(h)]


def fill(rows, x0, x1, y0, y1, rgb):
    for y in range(y0, y1):
        for x in range(x0, x1):
            rows[y][x] = rgb


class Pictures(unittest.TestCase):
    G = DESIGN["light"]["group"]
    T = sm.tint(G, False)

    def strip(self, line=3, gaps=False):
        rows = blank(400, 70, DESIGN["light"]["frame"])
        fill(rows, 10, 300, 6, 44, self.T)              # header and tab wash
        if gaps:
            for x in (110, 190, 270):
                fill(rows, x, x + 6, 6, 44, DESIGN["light"]["frame"])
        fill(rows, 16, 46, 12, 33, self.G)              # label chip
        fill(rows, 20, 30, 20, 23, sm.WHITE)            # its text
        fill(rows, 10, 300, 41, 41 + line, self.G)      # the line
        return rows

    def test_a_drawn_group_passes(self):
        found = sm.top_group(self.strip(), self.G, self.T, 1.0)
        self.assertTrue(all(sm.top_group_ok(found, 1.0, 200).values()), found)

    def test_a_2_dip_line_fails(self):
        found = sm.top_group(self.strip(line=2), self.G, self.T, 1.0)
        self.assertFalse(sm.top_group_ok(found, 1.0, 200)["line is 3 DIP"])

    def test_separators_in_the_wash_fail(self):
        found = sm.top_group(self.strip(gaps=True), self.G, self.T, 1.0)
        self.assertFalse(sm.top_group_ok(found, 1.0, 200)["wash unbroken along the group"])

    def test_side_group(self):
        rows = blank(400, 400, (0x11, 0x11, 0x10))
        g = DESIGN["dark"]["group"]
        t = sm.tint(g, True)
        fill(rows, 10, 13, 50, 250, g)
        fill(rows, 16, 300, 50, 250, t)
        found = sm.side_group(rows, g, t, 1.0)
        self.assertTrue(all(sm.side_group_ok(found, 1.0).values()), found)
        fill(rows, 13, 14, 50, 250, g)                   # a 4 px line
        self.assertFalse(sm.side_group_ok(sm.side_group(rows, g, t, 1.0), 1.0)["side line is 3 DIP"])

    def test_png_round_trip(self):
        from capture_native import write_png
        rows = self.strip()
        bgra = bytes(b for r in rows for (cr, cg, cb) in r for b in (cb, cg, cr, 255))
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.png"
            write_png(str(path), 400, 70, bgra)
            w, h, back = sm.read_png(path)
        self.assertEqual((w, h), (400, 70))
        self.assertEqual(back, rows)

    def test_scenes_cover_light_and_dark_beside_compiled_screens(self):
        self.assertEqual([s[0] for s in sm.SCENES], ["light", "dark"])
        for _, _, design in sm.SCENES:
            self.assertEqual(len(design), 2)


if __name__ == "__main__":
    unittest.main()
