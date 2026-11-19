#!/usr/bin/env python3
"""Our pages take their colours from the compiled design.

The new tab page carries the TOKENS rows of the design (light and dark)
and takes only its accent from the window (boring_color_mixer.cc sets it
from chrome://theme/colors.css), so it follows the colour picker's accent.

Usage:
  python -m unittest boring-core/tools/tests/test_page_theme.py -v
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PAGE = CORE / "components" / "boring" / "newtab" / "newtab_ui.cc"
MIXER = (
    CORE
    / "chromium_src"
    / "chrome"
    / "browser"
    / "ui"
    / "color"
    / "boring_color_mixer.cc"
)

# The page's own palette is the TOKENS rows of the compiled design, light
# and dark, written into the page. Only the accent is the window's.
PALETTE = ("page", "surface", "field", "hover", "line", "edge", "ink", "ink2",
           "ok", "bad", "bad-tint", "solid", "solid-ink")
TOKENS = {
    "--accent": ("--color-sys-primary", "kColorSysPrimary", "accent"),
}


def page_css():
    text = PAGE.read_text(encoding="utf-8")
    return re.search(r"<style>(.*?)</style>", text, re.S).group(1)


class PageThemeTest(unittest.TestCase):
    def test_page_loads_the_theme_stylesheet_before_its_own(self):
        text = PAGE.read_text(encoding="utf-8")
        link = text.index('href="chrome://theme/colors.css?sets=ui,chrome"')
        self.assertLess(link, text.index("<style>"))

    def test_the_palette_is_the_design_tokens_light_and_dark(self):
        css = page_css()
        for name in PALETTE:
            self.assertRegex(
                css,
                rf"--{re.escape(name)}:\s*light-dark\(#[0-9a-f]{{6}},\s*#[0-9a-f]{{6}}\);",
                name,
            )

    def test_the_accent_is_the_windows_with_a_fallback(self):
        self.assertRegex(
            page_css(),
            r"--accent:\s*var\(--color-sys-primary,\s*light-dark\(#[0-9a-f]{6},\s*#[0-9a-f]{6}\)\);",
        )

    def test_the_mixer_sets_every_colour_the_page_reads(self):
        src = MIXER.read_text(encoding="utf-8")
        for token, (_, color_id, field) in TOKENS.items():
            self.assertRegex(
                src,
                rf"mixer\[ui::{color_id}\]\s*=\s*\{{p\.{field}\}}|mixer\[{color_id}\]\s*=\s*\{{p\.{field}\}}",
                token,
            )

    def test_settings_always_loads_the_theme_stylesheet(self):
        # Upstream only adds colors.css when a webui-refresh flag is on, which
        # it is not here, so --boring-* silently stayed on their fallbacks.
        for sub in ("", "153/", "154/"):
            text = (CORE / "patches" / sub / "settings-restyle.patch").read_text(
                encoding="utf-8"
            )
            self.assertIn("-    const enableThemedColors =", text, sub)
            self.assertIn("+    this.addThemedColors_();", text, sub)
            self.assertNotIn("+    if (enableThemedColors)", text, sub)


if __name__ == "__main__":
    unittest.main()
