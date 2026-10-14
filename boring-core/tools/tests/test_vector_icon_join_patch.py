#!/usr/bin/env python3
"""The round stroke join patch: our icons are drawn with round joins.

Usage:
  python -m unittest boring-core/tools/tests/test_vector_icon_join_patch.py -v
"""

import os
import subprocess
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PATCH = CORE / "patches" / "vector-icon-round-joins.patch"
SERIES = CORE / "patches" / "series"
TREE = os.environ.get("BORING_TREE", r"E:\ung-154\build\src")


class RoundJoinPatchTest(unittest.TestCase):
    def test_patch_exists_and_sets_a_round_join(self):
        text = PATCH.read_text(encoding="utf-8")
        self.assertIn("setStrokeJoin(cc::PaintFlags::kRound_Join)", text)
        self.assertIn("ui/gfx/paint_vector_icon.cc", text)

    def test_patch_is_in_the_series(self):
        names = [ln.strip() for ln in SERIES.read_text().splitlines()]
        self.assertIn("vector-icon-round-joins.patch", names)

    @unittest.skipUnless(os.path.isdir(TREE), "Chromium 154 tree not present")
    def test_patch_applies_or_is_already_applied_to_the_154_tree(self):
        def check(*extra):
            return subprocess.run(["git", "apply", "--check", *extra, str(PATCH)],
                                  cwd=TREE, capture_output=True).returncode == 0
        self.assertTrue(check() or check("--reverse"))


if __name__ == "__main__":
    unittest.main()
