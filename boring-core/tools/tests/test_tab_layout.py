#!/usr/bin/env python3
"""The tab strip is Chromium's, with the tab contents centred and a bold open tab.

Seven tab patches (tab-shape, tab-underline, tab-mock-metrics, tab-connected,
tab-center-content, tab-separator-pinned, tab-chrome-sizes) used to rewrite
each other's lines, and the last one put Chromium's sizes back. What they
left behind together is one patch, tab-layout.patch: the content area sits
on the centre of the visible tab body, the favicon and title are centred in
it, and the open tab's title is semibold. Sizes, shape and colours are
Chromium's (colours come from our ColorMixer, boring_color_mixer.cc).

Usage:
  python -m unittest boring-core/tools/tests/test_tab_layout.py -v
"""

import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PATCHES = CORE / "patches"
PATCH = PATCHES / "157" / "tab-layout.patch"
SERIES = PATCHES / "series"

# Chromium's own layout constants for the tab strip (layout_constants.cc).
TAB_HEIGHT = 34 + 1
STRIP_PADDING = 6
OVERLAP = 1
VERTICAL_PADDING = 6

GONE = (
    "tab-shape.patch",
    "tab-underline.patch",
    "tab-mock-metrics.patch",
    "tab-connected.patch",
    "tab-center-content.patch",
    "tab-separator-pinned.patch",
    "tab-chrome-sizes.patch",
)


def patch_text():
    return PATCH.read_text(encoding="utf-8")


def added():
    return "\n".join(
        ln[1:] for ln in patch_text().splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    )


class TabLayoutTest(unittest.TestCase):
    def test_one_tab_patch_in_the_series(self):
        names = [ln.strip() for ln in SERIES.read_text().splitlines()]
        self.assertIn("tab-layout.patch", names)
        for old in GONE:
            self.assertNotIn(old, names)
            for d in ("", "153", "154", "157"):
                self.assertFalse((PATCHES / d / old).exists(), f"{d}/{old}")

    def test_only_the_two_tab_files_change(self):
        files = sorted(ln for ln in patch_text().splitlines() if ln.startswith("+++ "))
        self.assertEqual(
            files,
            [
                "+++ b/chrome/browser/ui/views/tabs/common/horizontal_tab_style_views.cc",
                "+++ b/chrome/browser/ui/views/tabs/tab.cc",
            ],
        )

    def test_no_sizes_or_colours_in_the_tab_patch(self):
        text = added()
        for gone in ("kTabWidth", "CornerRadius", "kSeparator", "SkColor", "kColor"):
            self.assertNotIn(gone, text)

    def test_content_area_is_centred_on_the_visible_tab_body(self):
        # The bottom inset is the vertical padding; the overlap is added by
        # the caller. The top inset stays Chromium's.
        self.assertIn(
            "set_bottom(\n      GetLayoutConstant(LayoutConstant::kTabVerticalPadding));",
            added(),
        )
        top = VERTICAL_PADDING + STRIP_PADDING
        bottom = OVERLAP + VERTICAL_PADDING
        contents_centre = (top + (TAB_HEIGHT - bottom)) / 2
        body_centre = (STRIP_PADDING + (TAB_HEIGHT - OVERLAP)) / 2
        self.assertEqual(contents_centre, body_centre)

    def test_favicon_and_title_are_centred_in_the_content_area(self):
        text = added()
        self.assertIn("Center(contents_rect.height(), favicon_bounds.height())", text)
        self.assertIn("title_bounds(title_left, contents_rect.y(), title_width,", text)

    def test_open_tab_title_is_semibold(self):
        self.assertIn(
            "IsActive() ? gfx::Font::Weight::SEMIBOLD : gfx::Font::Weight::NORMAL",
            added(),
        )


if __name__ == "__main__":
    unittest.main()
