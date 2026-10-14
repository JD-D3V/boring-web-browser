#!/usr/bin/env python3
"""The tab strip matches the approved mock, and the open tab has no underline.

The mock is the "In context" tab strip in design/v7/icons-dotted. Its numbers
are read from that page's CSS and the patch is checked against them.

Usage:
  python -m unittest boring-core/tools/tests/test_tab_style.py -v
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
REPO = CORE.parent
PATCH = CORE / "patches" / "tab-mock-metrics.patch"
SERIES = CORE / "patches" / "series"
MOCK = REPO / "design" / "v7" / "icons-dotted" / "src" / "template.html"

# Chromium's tab height is the visible tab plus the strip padding and the
# overlap with the toolbar; the strip padding is 6 (layout_constants.cc).
STRIP_PADDING = 6


def mock_tab():
    text = MOCK.read_text(encoding="utf-8")
    return re.search(r"\n  \.tab\{(.*?)\n  \}", text, re.S).group(1)


def added():
    return [ln[1:] for ln in PATCH.read_text(encoding="utf-8").splitlines()
            if ln.startswith("+") and not ln.startswith("+++")]


def after():
    """The patched text as the build sees it: added and untouched lines."""
    return [ln[1:] for ln in PATCH.read_text(encoding="utf-8").splitlines()
            if ln[:1] in ("+", " ") and not ln.startswith("+++")]


def removed():
    return [ln[1:] for ln in PATCH.read_text(encoding="utf-8").splitlines()
            if ln.startswith("-") and not ln.startswith("---")]


class TabStyleTest(unittest.TestCase):
    def test_patch_is_in_the_series_after_the_older_tab_patches(self):
        names = [ln.strip() for ln in SERIES.read_text().splitlines()]
        self.assertIn("tab-mock-metrics.patch", names)
        for older in ("tab-shape.patch", "tab-underline.patch"):
            self.assertLess(names.index(older), names.index("tab-mock-metrics.patch"))

    def test_the_open_tab_has_no_underline(self):
        gone = "\n".join(removed())
        self.assertIn("kUnderlineHeight", gone)
        self.assertIn("kColorSysPrimary", gone)
        self.assertNotIn("kUnderlineHeight", "\n".join(added()))

    def test_tab_height_is_the_mocks_36(self):
        height = int(re.search(r"height:(\d+)px", mock_tab()).group(1))
        m = re.search(r"return (\d+) \+\s*GetLayoutConstant\(LayoutConstant::kTabstripToolbarOverlap\)",
                      "\n".join(added()))
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)) - STRIP_PADDING, height)

    def test_top_corner_radius_is_the_mocks(self):
        radius = int(re.search(r"border-radius:(\d+)px \d+px 0 0", mock_tab()).group(1))
        text = "\n".join(after())
        m = re.search(r"GetTopCornerRadius\(\) const \{.*?return (\d+);", text, re.S)
        self.assertEqual(int(m.group(1)), radius)

    def test_content_insets_are_the_mocks(self):
        left = int(re.search(r"padding:0 \d+px 0 (\d+)px", mock_tab()).group(1))
        text = "\n".join(added())
        self.assertIn("set_left(%d)" % left, text)
        # 6 px padding plus the 24 px close button.
        self.assertIn("set_right(30)", text)

    def test_icon_to_title_gap_is_the_mocks(self):
        gap = int(re.search(r"gap:(\d+)px", mock_tab()).group(1))
        text = "\n".join(after())
        m = re.search(r"kTabPreTitlePadding:.*?return (\d+);", text, re.S)
        self.assertEqual(int(m.group(1)), gap)

    def test_tab_width_is_the_mocks(self):
        width = int(re.search(r"flex:0 1 (\d+)px", mock_tab()).group(1))
        self.assertIn("kTabWidth = %d;" % width, "\n".join(added()))


if __name__ == "__main__":
    unittest.main()
