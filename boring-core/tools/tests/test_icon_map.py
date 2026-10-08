#!/usr/bin/env python3
"""Tests for icon_map.py against the Chromium 154 tree.

Usage:
  python -m unittest boring-core/tools/tests/test_icon_map.py -v
Set BORING_TREE to use a tree other than E:/ung-154/build/src.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import icon_map  # noqa: E402

TREE = os.environ.get("BORING_TREE", r"E:\ung-154\build\src")
CHROMIUM_SRC = TOOLS.parent / "chromium_src"


@unittest.skipUnless(os.path.isdir(TREE), "Chromium 154 tree not present")
class IconMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolved = icon_map.resolve(TREE)

    def test_every_mapped_name_exists_in_the_tree(self):
        missing = [n for names in icon_map.ICON_MAP.values() for n in names
                   if not self.resolved.get(n)]
        self.assertEqual(missing, [])

    def test_no_chromium_icon_is_mapped_twice(self):
        seen = {}
        for sid, names in icon_map.ICON_MAP.items():
            for n in names:
                self.assertNotIn(n, seen, "%s and %s both map %s" % (sid, seen.get(n), n))
                seen[n] = sid

    def test_every_mapped_id_is_in_the_svg(self):
        svg = (TOOLS.parents[1] / "design" / "v7" / "icons-full" / "icons.svg").read_text(encoding="utf-8")
        for sid in icon_map.ICON_MAP:
            self.assertIn('id="%s"' % sid, svg)

    def test_generated_files_validate_with_the_chromium_aggregator(self):
        with tempfile.TemporaryDirectory() as out:
            written = icon_map.generate(TREE, out)
            self.assertGreater(len(written), 40)
            icon_map.validate(written, TREE)

    def test_validate_rejects_a_broken_icon(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.icon"
            bad.write_text("CANVAS_DIMENSIONS, 20,\nNOT_A_COMMAND, 1, 2,\n")
            with self.assertRaises(Exception):
                icon_map.validate([str(bad)], TREE)

    def test_back_arrow_files_flip_in_rtl(self):
        with tempfile.TemporaryDirectory() as out:
            icon_map.generate(TREE, out)
            text = (Path(out) / "components" / "vector_icons" / "arrow_back.icon").read_text()
            self.assertIn("FLIPS_IN_RTL,", text)

    def test_menu_icon_is_dots(self):
        text = (CHROMIUM_SRC / "chrome" / "app" / "vector_icons" / "boring_menu.icon").read_text()
        self.assertEqual(text.count("CIRCLE,"), 3)
        self.assertNotIn("LINE_TO", text)

    def test_committed_icons_match_the_generator(self):
        with tempfile.TemporaryDirectory() as out:
            for rel in icon_map.generate(TREE, out):
                rel_path = Path(rel).relative_to(out)
                committed = CHROMIUM_SRC / rel_path
                self.assertTrue(committed.exists(), str(rel_path))
                self.assertEqual(committed.read_text(), Path(rel).read_text(), str(rel_path))


if __name__ == "__main__":
    unittest.main()
