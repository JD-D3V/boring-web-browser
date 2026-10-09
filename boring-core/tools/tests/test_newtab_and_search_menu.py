#!/usr/bin/env python3
"""New tab wording, the Colours link, and the search engine popup's look.

Usage:
  python -m unittest boring-core/tools/tests/test_newtab_and_search_menu.py -v
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
NEWTAB = CORE / "components" / "boring" / "newtab" / "newtab_ui.cc"
BRIDGE_H = CORE / "components" / "boring" / "newtab" / "search_engine_menu.h"
MENU = CORE / "chromium_src" / "chrome" / "browser" / "ui" / "views" / "boring" / "boring_search_engine_menu.cc"
MIXER = CORE / "chromium_src" / "chrome" / "browser" / "ui" / "color" / "boring_color_mixer.cc"
SMOKE = CORE / "tools" / "smoke_newtab.py"


def read(p):
    return p.read_text(encoding="utf-8")


class NewTabTextTest(unittest.TestCase):
    def test_tagline_is_looking_for(self):
        text = read(NEWTAB)
        self.assertIn("Find what you&rsquo;re looking for.", text)
        self.assertNotIn("Find what you came for", text)

    def test_the_smoke_test_checks_the_new_tagline(self):
        text = read(SMOKE)
        self.assertNotIn("you came for", text)
        self.assertIn("looking for", text)


class ColoursLinkTest(unittest.TestCase):
    def test_page_has_a_colours_button_that_asks_the_browser(self):
        text = read(NEWTAB)
        self.assertRegex(text, r'<button[^>]*id="colours"[^>]*>Colours</button>')
        self.assertIn("chrome.send('openColours')", text)

    def test_handler_is_registered_and_calls_the_bridge(self):
        text = read(NEWTAB)
        self.assertRegex(text, r'"openColours",\s*base::BindRepeating\(&NewTabMessageHandler::HandleOpenColours')
        self.assertIn("OpenColourPickerForPage(web_ui()->GetWebContents())", text)

    def test_bridge_is_declared_for_the_page_and_defined_in_the_browser_ui(self):
        self.assertIn("bool OpenColourPickerForPage(content::WebContents* page);", read(BRIDGE_H))
        menu = read(MENU)
        self.assertIn("bool OpenColourPickerForPage(content::WebContents* page)", menu)
        self.assertIn("IDC_CUSTOMIZE_CHROME", menu)
        self.assertIn("GlobalBrowserCollection::GetInstance()->FindBrowserWithTab(page)", menu)


class SearchMenuLookTest(unittest.TestCase):
    def test_make_default_and_done_are_quiet_text_links_not_pills(self):
        text = read(MENU)
        self.assertNotIn("MdTextButton", text)
        self.assertEqual(text.count("std::make_unique<views::LabelButton>("), 2)
        self.assertGreaterEqual(text.count("SetEnabledTextColors(ui::kColorLinkForeground)"), 2)

    def test_rows_and_links_hover_with_rounded_corners_like_the_main_menu(self):
        text = read(MENU)
        self.assertIn("views::InstallRoundRectHighlightPathGenerator(pick, gfx::Insets(), 10);", text)
        self.assertIn("views::InstallRoundRectHighlightPathGenerator(make_default, gfx::Insets(), 8);", text)

    def test_row_hover_is_a_see_through_accent_wash_so_the_text_stays_visible(self):
        self.assertRegex(read(MIXER), r"mixer\[kColorHoverButtonBackgroundHovered\]\s*=\s*\{SkColorSetA\(p\.accent,\s*0x[0-9a-fA-F]+\)\}")

    def test_the_bubble_corners_match_the_main_menu(self):
        self.assertIn("delegate_->set_corner_radius(14);", read(MENU))

    def test_the_redundant_tooltip_is_gone(self):
        self.assertNotIn('SetTooltipText(u"Search with "', read(MENU))


if __name__ == "__main__":
    unittest.main()
