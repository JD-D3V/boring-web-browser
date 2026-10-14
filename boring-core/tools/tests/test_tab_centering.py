#!/usr/bin/env python3
"""The favicon, title and close button sit on the centre of the tab body.

Chromium puts the favicon at the top of the tab's content area and centres
the title in the whole view, which only lines up when the tab is exactly as
tall as the icon needs. Our tab is taller (36 DIP body), so the icon rode
high. The patch makes the content area symmetrical about the visible tab
body and centres the icon and title in it.

Usage:
  python -m unittest boring-core/tools/tests/test_tab_centering.py -v
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PATCH = CORE / "patches" / "tab-center-content.patch"
SERIES = CORE / "patches" / "series"
METRICS = CORE / "patches" / "tab-mock-metrics.patch"

# Chromium's own layout constants for the tab strip (layout_constants.cc).
STRIP_PADDING = 6
OVERLAP = 1
VERTICAL_PADDING = 6


def patch_text():
    return PATCH.read_text(encoding="utf-8")


def tab_view_height():
    m = re.search(r"\+\s*return (\d+) \+\s*GetLayoutConstant\(LayoutConstant::kTabstripToolbarOverlap\)",
                  METRICS.read_text(encoding="utf-8"))
    return int(m.group(1)) + OVERLAP


class TabCenteringTest(unittest.TestCase):
    def test_patch_is_in_the_series_after_the_metrics_patch(self):
        names = [ln.strip() for ln in SERIES.read_text().splitlines()]
        self.assertIn("tab-center-content.patch", names)
        self.assertLess(names.index("tab-mock-metrics.patch"), names.index("tab-center-content.patch"))

    def test_content_area_is_centred_on_the_visible_tab_body(self):
        # The patch sets the bottom inset to the vertical padding; the
        # overlap is added by the caller. The top inset stays Chromium's.
        self.assertRegex(
            patch_text(),
            r"set_bottom\(\s*\+?\s*GetLayoutConstant\(LayoutConstant::kTabVerticalPadding\)\)")
        h = tab_view_height()
        top = VERTICAL_PADDING + STRIP_PADDING
        bottom = OVERLAP + VERTICAL_PADDING
        contents_centre = (top + (h - bottom)) / 2
        body_centre = (STRIP_PADDING + (h - OVERLAP)) / 2
        self.assertEqual(contents_centre, body_centre)

    def test_favicon_is_centred_in_the_content_area(self):
        self.assertIn("Center(contents_rect.height(), favicon_bounds.height())", patch_text())

    def test_title_is_centred_in_the_content_area_not_the_whole_view(self):
        text = patch_text()
        self.assertIn("title_bounds(title_left, contents_rect.y(), title_width,", text)
        self.assertIn("contents_rect.height());", text)
        self.assertNotIn("+    const gfx::Rect title_bounds(title_left, GetLocalBounds().y()", text)

    def test_only_the_two_tab_files_change(self):
        files = sorted(ln for ln in patch_text().splitlines() if ln.startswith("+++ "))
        self.assertEqual(files, [
            "+++ b/chrome/browser/ui/views/tabs/horizontal_tab_style_views.cc",
            "+++ b/chrome/browser/ui/views/tabs/tab.cc",
        ])


if __name__ == "__main__":
    unittest.main()
