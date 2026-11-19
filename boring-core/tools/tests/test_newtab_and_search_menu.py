#!/usr/bin/env python3
"""New tab wording, the Colours link, and the search engine popup's look.

Usage:
  python -m unittest boring-core/tools/tests/test_newtab_and_search_menu.py -v
"""

import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
NEWTAB = CORE / "components" / "boring" / "newtab" / "newtab_ui.cc"
BRIDGE_H = CORE / "components" / "boring" / "newtab" / "search_engine_menu.h"
MENU = (
    CORE
    / "chromium_src"
    / "chrome"
    / "browser"
    / "ui"
    / "views"
    / "boring"
    / "boring_search_engine_menu.cc"
)
MIXER = (
    CORE
    / "chromium_src"
    / "chrome"
    / "browser"
    / "ui"
    / "color"
    / "boring_color_mixer.cc"
)
SMOKE = CORE / "tools" / "smoke_newtab.py"


def read(p):
    return p.read_text(encoding="utf-8")


class NewTabPageTest(unittest.TestCase):
    """The page as drawn (screens C01 and C02): no search box."""

    def test_the_drawn_sections_and_words_are_there(self):
        text = read(NEWTAB)
        for words in (
            "Pinned sites",
            "Pick up where you left off",
            'id="accounts"',
            "Protection is on. ",
            "chrome://settings/protection",
        ):
            self.assertIn(words, text)

    def test_the_old_page_is_gone(self):
        text = read(NEWTAB)
        for gone in (
            'type="search"',
            'id="engine"',
            'id="colours"',
            "Just a Browser",
            "openColours",
            "showEngineMenu",
            "Find what you",
        ):
            self.assertNotIn(gone, text)

    def test_a_title_only_ever_goes_in_as_text(self):
        text = read(NEWTAB)
        self.assertNotIn("innerHTML", text)
        self.assertIn("node('span', 'title', item.title || item.host)", text)

    def test_the_two_bridges_nothing_calls_are_gone(self):
        for path in (BRIDGE_H, MENU):
            text = read(path)
            self.assertNotIn("OpenColourPickerForPage", text)
            self.assertNotIn("ShowSearchEngineMenuForPage", text)

    def test_the_smoke_test_checks_the_new_page(self):
        text = read(SMOKE)
        self.assertIn("no search box", text)
        self.assertIn("Pick up where you left off", text)


class WelcomePageTest(unittest.TestCase):
    WELCOME = CORE / "components" / "boring" / "welcome" / "welcome_ui.cc"

    def test_switch_rows_explain_themselves_without_em_dash(self):
        text = read(self.WELCOME)
        self.assertIn("Takes away the continue anyway link on a scam", text)
        self.assertNotIn("—", text)
        self.assertNotIn("&mdash;", text)

    def test_logo_and_heading_are_centred(self):
        text = read(self.WELCOME)
        self.assertRegex(text, r"\.brand \{[^}]*margin: 0 auto 24px")
        self.assertRegex(text, r"h1 \{[^}]*text-align: center")


class SearchMenuLookTest(unittest.TestCase):
    def test_make_default_and_done_are_quiet_text_links_not_pills(self):
        text = read(MENU)
        self.assertNotIn("MdTextButton", text)
        self.assertEqual(text.count("std::make_unique<views::LabelButton>("), 2)
        self.assertGreaterEqual(
            text.count("SetEnabledTextColors(ui::kColorLinkForeground)"), 2
        )

    def test_rows_and_links_hover_with_rounded_corners_like_the_main_menu(self):
        text = read(MENU)
        self.assertIn(
            "views::InstallRoundRectHighlightPathGenerator(pick, gfx::Insets(), 10);",
            text,
        )
        self.assertIn(
            "views::InstallRoundRectHighlightPathGenerator(make_default, gfx::Insets(), 8);",
            text,
        )

    def test_row_hover_is_a_see_through_accent_wash_so_the_text_stays_visible(self):
        self.assertRegex(
            read(MIXER),
            r"mixer\[kColorHoverButtonBackgroundHovered\]\s*=\s*\{SkColorSetA\(p\.accent,\s*0x[0-9a-fA-F]+\)\}",
        )

    def test_the_bubble_corners_match_the_main_menu(self):
        self.assertIn("delegate_->set_corner_radius(14);", read(MENU))

    def test_the_redundant_tooltip_is_gone(self):
        self.assertNotIn('SetTooltipText(u"Search with "', read(MENU))


if __name__ == "__main__":
    unittest.main()
