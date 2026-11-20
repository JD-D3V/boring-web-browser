"""The pure parts of smoke_customize_toolbar.py, without a browser."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import smoke_customize_toolbar as smoke  # noqa: E402

GOOD = {
    "cardBg": "rgba(0, 0, 0, 0)", "cardRadius": "0px", "introSize": "13px",
    "headSize": "11.5px", "headWeight": "600", "headColor": "rgb(93, 90, 84)",
    "quiet": "#5d5a54", "rowHeight": 36, "rowPad": "18px", "icon": [16, 16],
    "bar": [34, 20], "knob": 16, "offColor": "rgb(138, 134, 125)",
    "onColor": "rgb(79, 70, 229)", "accent": "#4f46e5", "visibleHrs": 0,
    "sepTop": "1px",
    "panelBg": smoke.BAR["light"], "miniBg": smoke.FRAME["light"], "miniBase": smoke.BAR["light"], "miniGlyph": smoke.INK["light"],
}  # fmt: skip
# The panel and preview surfaces (item 27), in dark.
DARK_SURFACES = {"panelBg": smoke.BAR["dark"], "miniBg": smoke.FRAME["dark"], "miniBase": smoke.BAR["dark"], "miniGlyph": smoke.INK["dark"], "headColor": smoke.MUTED["dark"]}


class Recorder:
    def __init__(self):
        self.failed = []

    def __call__(self, name, ok, detail=""):
        if not ok:
            self.failed.append(name)


class NormTest(unittest.TestCase):
    def test_hex_becomes_rgb(self):
        self.assertEqual(smoke.norm("#8A867D"), "rgb(138, 134, 125)")

    def test_rgb_is_kept(self):
        self.assertEqual(smoke.norm(" rgb(1, 2, 3) "), "rgb(1, 2, 3)")


class StylesTest(unittest.TestCase):
    def test_the_design_passes(self):
        r = Recorder()
        smoke.check_styles(r, "light", GOOD)
        self.assertEqual(r.failed, [])

    def test_stock_switch_and_rows_fail(self):
        r = Recorder()
        smoke.check_styles(r, "light", {**GOOD, "bar": [26, 16], "rowHeight": 40, "offColor": "rgb(1, 2, 3)"})
        self.assertEqual(len(r.failed), 3)

    def test_dark_wants_the_dark_edge(self):
        r = Recorder()
        smoke.check_styles(r, "dark", {**GOOD, **DARK_SURFACES})
        self.assertEqual(r.failed, ["dark: an off switch is the edge colour"])

    def test_nothing_to_check_fails(self):
        # Ledger item 33: no on switch, no accent or no heading colour is a
        # failure, not a pass; sizes more than a pixel off fail too.
        for bad, name in (
            ({"onColor": None}, "light: an on switch is the accent"),
            ({"accent": ""}, "light: an on switch is the accent"),
            ({"headColor": None, "quiet": ""}, "light: headings are our quiet ink"),
            ({"headColor": "rgb(120, 116, 140)"}, "light: headings are our quiet ink"),
            ({"bar": [32.5, 20]}, "light: a switch is 34 by 20 with a 16 knob"),
            ({"rowHeight": None}, "light: rows are 36 high with 18 at the sides"),
        ):
            r = Recorder()
            smoke.check_styles(r, "light", {**GOOD, **bad})
            self.assertEqual(r.failed, [name], bad)

    def test_no_panel_is_one_failure(self):
        r = Recorder()
        smoke.check_styles(r, "light", None)
        self.assertEqual(len(r.failed), 1)


class PatchTest(unittest.TestCase):
    def test_panel_css_is_in_the_patch_and_the_series(self):
        core = Path(__file__).resolve().parents[2]
        text = (core / "patches" / "157" / "cui-menu.patch").read_text(encoding="utf-8")
        self.assertIn("customize_toolbar/toolbar.css", text)
        for line in ("+  --cr-toggle-track-width: 34px;", "+  height: 36px;", "+  font-size: 11.5px;"):
            self.assertIn(line, text)
        names = (core / "patches" / "series").read_text().split()
        self.assertLess(names.index("cui-toolbar.patch"), names.index("cui-menu.patch"))


if __name__ == "__main__":
    unittest.main()
