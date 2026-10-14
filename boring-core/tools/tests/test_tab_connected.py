#!/usr/bin/env python3
"""The open tab is joined to the toolbar, with no strip of frame between.

Chromium paints the open tab with feet that flare into the toolbar
(PathType::kActiveTab) and outlines it with PathType::kBorder. An older
patch of ours swapped both for the detached rounded card (kHighlight),
which leaves a band of the frame colour under the open tab. This patch
puts them back for the open tab only; the other tabs stay detached.

Usage:
  python -m unittest boring-core/tools/tests/test_tab_connected.py -v
"""

import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PATCH = CORE / "patches" / "tab-connected.patch"
SERIES = CORE / "patches" / "series"


def lines(prefix):
    return [ln[1:] for ln in PATCH.read_text(encoding="utf-8").splitlines()
            if ln.startswith(prefix) and not ln.startswith(prefix * 3)]


class TabConnectedTest(unittest.TestCase):
    def test_patch_is_in_the_series_after_the_tab_patches_it_undoes(self):
        names = [ln.strip() for ln in SERIES.read_text().splitlines()]
        self.assertIn("tab-connected.patch", names)
        for older in ("tab-underline.patch", "tab-mock-metrics.patch"):
            self.assertLess(names.index(older), names.index("tab-connected.patch"))

    def test_the_open_tab_fill_uses_the_connected_shape(self):
        added = "\n".join(lines("+"))
        self.assertIn("TabStyle::PathType::kActiveTab", added)
        self.assertIn("TabStyle::TabSelectionState::kActive", added)

    def test_the_outline_uses_the_border_shape_again(self):
        added = "\n".join(lines("+"))
        self.assertIn("TabStyle::PathType::kBorder", added)

    def test_inactive_tabs_keep_the_detached_shape(self):
        added = "\n".join(lines("+"))
        self.assertIn("TabStyle::PathType::kHighlight", added)

    def test_only_the_horizontal_tab_style_file_changes(self):
        files = [ln for ln in PATCH.read_text(encoding="utf-8").splitlines()
                 if ln.startswith("+++ ")]
        self.assertEqual(files, ["+++ b/chrome/browser/ui/views/tabs/horizontal_tab_style_views.cc"])


if __name__ == "__main__":
    unittest.main()
