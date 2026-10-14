#!/usr/bin/env python3
"""The tab strip is back at Chrome's own sizes and shape.

tab-chrome-sizes.patch runs last and undoes the metric overrides of the
older tab patches (tab-shape, tab-mock-metrics, tab-separator-pinned), so
those patches' own tests still describe them but the tree ends at stock.
What stays is colour, icons, the semibold open-tab title, the washes and the
content centring.

Usage:
  python -m unittest boring-core/tools/tests/test_tab_chrome_sizes.py -v
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
SERIES = CORE / "patches" / "series"
SETS = {
    "154": CORE / "patches" / "tab-chrome-sizes.patch",
    "153": CORE / "patches" / "153" / "tab-chrome-sizes.patch",
}

# Chrome's own values (chrome/browser/ui/tabs/tab_style.cc, layout_constants.cc).
STOCK_ADDED = [
    "constexpr int kSeparatorThickness = 2;",
    "constexpr int kSeparatorHorizontalMargin = 2;",
    "constexpr int kSeparatorHeight = 16;",
    "constexpr int kTabWidth = 232;",
    "constexpr int kTabPinnedContentWidth = 24;",
    "return 10;",
    "return 12;",
    "return 34 +",
]


def lines(path, marks):
    return [ln[1:] for ln in path.read_text(encoding="utf-8").splitlines()
            if ln[:1] in marks and not ln.startswith(("+++", "---"))]


class TabChromeSizesTest(unittest.TestCase):
    def test_runs_last_in_the_tab_series(self):
        names = [ln.strip() for ln in SERIES.read_text().splitlines() if ln.strip()]
        for older in ("tab-shape.patch", "tab-underline.patch", "tab-mock-metrics.patch",
                      "tab-connected.patch", "tab-center-content.patch",
                      "tab-separator-pinned.patch"):
            self.assertLess(names.index(older), names.index("tab-chrome-sizes.patch"))

    def test_restores_chromes_numbers(self):
        for name, path in SETS.items():
            added = "\n".join(l.strip() for l in lines(path, "+"))
            for want in STOCK_ADDED:
                self.assertIn(want, added, "%s: %s" % (name, want))

    def test_drops_the_mock_numbers(self):
        for name, path in SETS.items():
            added = "\n".join(lines(path, "+"))
            for gone in ("kTabWidth = 190", "standard_pinned_width = 44", "set_left(12)",
                         "set_right(30)", "kContentInsetLeft", "return 42 +", "return 44 +"):
                self.assertNotIn(gone, added, "%s: %s" % (name, gone))

    def test_rounded_bottom_corners_come_back_for_the_detached_shape(self):
        for name, path in SETS.items():
            added = "\n".join(lines(path, "+"))
            self.assertIn("if (path_type == TabStyle::PathType::kHitTest) {", added, name)

    def test_keeps_the_content_centring(self):
        # It is in tab-center-content.patch, which this patch must not undo.
        for name, path in SETS.items():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("set_bottom", text, name)

    def test_touches_only_the_three_style_files(self):
        for name, path in SETS.items():
            files = re.findall(r"^\+\+\+ b/(\S+)", path.read_text(encoding="utf-8"), re.M)
            self.assertEqual(sorted(files), [
                "chrome/browser/ui/layout_constants.cc",
                "chrome/browser/ui/tabs/tab_style.cc",
                "chrome/browser/ui/views/tabs/horizontal_tab_style_views.cc",
            ], name)


if __name__ == "__main__":
    unittest.main()
