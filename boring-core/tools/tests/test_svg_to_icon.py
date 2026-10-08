#!/usr/bin/env python3
"""Tests for svg_to_icon.py.

Usage:
  python -m unittest boring-core/tools/tests/test_svg_to_icon.py -v
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import svg_to_icon  # noqa: E402

REPO = TOOLS.parents[1]
ICONS_SVG = REPO / "design" / "v7" / "icons-full" / "icons.svg"

BACK = ('<symbol id="b-back" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M16 10H4M9.5 4.5L4 10l5.5 5.5"/></symbol>')
DOT = ('<symbol id="b-x" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
       'stroke-width="2"><path d="M3 10l7-6 7 6"/>'
       '<circle cx="10" cy="13" r="1.25" fill="currentColor" stroke="none"/></symbol>')
RELOAD = ('<symbol id="b-reload" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
          'stroke-width="2"><path d="M17 10a7 7 0 1 1-2.05-4.95L17 7"/></symbol>')
STOP = ('<symbol id="b-stop" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
        'stroke-width="2"><circle cx="10" cy="10" r="7"/>'
        '<rect x="7.25" y="7.25" width="5.5" height="5.5" rx="1.25" '
        'fill="currentColor" stroke-width="1"/></symbol>')
SMOOTH = ('<symbol id="b-s" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
          'stroke-width="2"><path d="M2 10c2-4 4-4 6 0s4 4 6 0"/></symbol>')


def lines(text):
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.startswith("//")]


class ConvertSymbolTest(unittest.TestCase):
    def test_back_arrow_is_two_subpaths_with_stroke_2(self):
        out = svg_to_icon.convert_symbol(BACK, "back")
        body = lines(out)
        self.assertIn("CANVAS_DIMENSIONS, 20,", body)
        self.assertIn("STROKE, 2,", body)
        self.assertIn("MOVE_TO, 16, 10,", body)
        self.assertIn("H_LINE_TO, 4,", body)
        self.assertEqual(sum(1 for b in body if b.startswith("MOVE_TO")), 2)

    def test_dot_is_filled_circle_without_stroke(self):
        body = lines(svg_to_icon.convert_symbol(DOT, "x"))
        i = body.index("CIRCLE, 10, 13, 1.25,")
        self.assertEqual(body[i - 1], "NEW_PATH,")
        self.assertFalse(any(b.startswith("STROKE") for b in body[i:]))

    def test_arc_command_is_converted_to_absolute_arc_to(self):
        body = lines(svg_to_icon.convert_symbol(RELOAD, "reload"))
        arcs = [b for b in body if b.startswith("ARC_TO")]
        self.assertEqual(len(arcs), 1)
        self.assertEqual(arcs[0], "ARC_TO, 7, 7, 0, 1, 1, 14.95, 5.05,")
        self.assertFalse(any(b.startswith("R_ARC_TO") for b in body))

    def test_filled_rect_with_radius_becomes_round_rect_after_stroked_circle(self):
        body = lines(svg_to_icon.convert_symbol(STOP, "stop"))
        self.assertIn("CIRCLE, 10, 10, 7,", body)
        self.assertIn("ROUND_RECT, 7.25, 7.25, 5.5, 5.5, 1.25,", body)
        i = body.index("ROUND_RECT, 7.25, 7.25, 5.5, 5.5, 1.25,")
        self.assertEqual(body[i - 1], "NEW_PATH,")

    def test_smooth_cubic_reflects_previous_control_point(self):
        body = lines(svg_to_icon.convert_symbol(SMOOTH, "s"))
        cubics = [b for b in body if b.startswith("CUBIC_TO")]
        self.assertEqual(len(cubics), 2)
        # c2-4 4-4 6 0 from (2,10): ends (8,10), second control (6,6).
        # s reflects it: first control (10,14), then s 4 4 6 0 gives (14,10).
        self.assertEqual(cubics[1], "CUBIC_TO, 10, 14, 12, 14, 14, 10,")

    def test_plain_icons_do_not_flip_in_rtl(self):
        # Chromium's buttons already mirror the whole canvas in RTL, so an
        # icon that flips itself points the wrong way. Only *_flippable
        # icons carry the command, and we map none of those.
        self.assertNotIn("FLIPS_IN_RTL,", lines(svg_to_icon.convert_symbol(BACK, "back")))
        self.assertNotIn("FLIPS_IN_RTL,",
                         lines(svg_to_icon.convert_symbol(BACK, "arrow_back_old")))

    def test_scale_transform_scales_coordinates_and_stroke(self):
        sym = ('<symbol id="b-s" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
               'stroke-width="2"><path transform="scale(.5)" stroke-width="4" '
               'd="M10 10L20 20"/></symbol>')
        body = lines(svg_to_icon.convert_symbol(sym, "s"))
        self.assertIn("STROKE, 2,", body)
        self.assertIn("MOVE_TO, 5, 5,", body)
        self.assertIn("LINE_TO, 10, 10,", body)

    def test_attribute_it_cannot_honour_raises(self):
        sym = ('<symbol id="b-s" viewBox="0 0 20 20" fill="none" stroke="currentColor" '
               'stroke-width="2"><path opacity="0.5" d="M1 1L2 2"/></symbol>')
        with self.assertRaises(ValueError):
            svg_to_icon.convert_symbol(sym, "s")

    def test_canvas_argument_keeps_the_original_icon_size(self):
        body = lines(svg_to_icon.convert_symbol(BACK, "x", canvas=24))
        self.assertIn("CANVAS_DIMENSIONS, 24,", body)
        self.assertIn("STROKE, 2.4,", body)
        self.assertIn("MOVE_TO, 19.2, 12,", body)


class ConvertFileTest(unittest.TestCase):
    def test_all_44_symbols_convert(self):
        with tempfile.TemporaryDirectory() as out:
            paths = svg_to_icon.convert_file(str(ICONS_SVG), out)
            self.assertEqual(len(paths), 44)
            for p in paths:
                text = Path(p).read_text(encoding="utf-8")
                self.assertTrue(text.startswith("// Copyright 2026 boring."), p)
                self.assertIn("CANVAS_DIMENSIONS, 20,", text, p)
                self.assertRegex(Path(p).name, r"^[a-z0-9_]+\.icon$")
                self.assertIsNone(re.search(r"\d\s*e\d", text), p)

    def test_every_coordinate_is_inside_the_canvas(self):
        with tempfile.TemporaryDirectory() as out:
            for p in svg_to_icon.convert_file(str(ICONS_SVG), out):
                for ln in lines(Path(p).read_text(encoding="utf-8")):
                    name, *nums = [t.strip() for t in ln.split(",") if t.strip()]
                    n = [float(x) for x in nums]
                    if name in ("MOVE_TO", "LINE_TO", "H_LINE_TO", "V_LINE_TO", "CUBIC_TO"):
                        vals = n
                    elif name == "ARC_TO":
                        vals = n[5:7]
                    elif name == "CIRCLE":
                        vals = [n[0] - n[2], n[0] + n[2], n[1] - n[2], n[1] + n[2]]
                    elif name == "ROUND_RECT":
                        vals = [n[0], n[0] + n[2], n[1], n[1] + n[3]]
                    else:
                        continue
                    for v in vals:
                        self.assertTrue(-0.01 <= v <= 20.01, "%s: %s" % (Path(p).name, ln))

    def test_only_filters_by_id(self):
        with tempfile.TemporaryDirectory() as out:
            paths = svg_to_icon.convert_file(str(ICONS_SVG), out, only={"b-back"})
            self.assertEqual([Path(p).name for p in paths], ["back.icon"])


if __name__ == "__main__":
    unittest.main()
