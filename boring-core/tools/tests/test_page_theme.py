#!/usr/bin/env python3
"""Our pages take their colours from the compiled design.

The new tab page reads its surfaces, lines, text and accent from the
window (chrome://theme/colors.css, set by boring_color_mixer.cc), so it
follows the Look and the accent; the TOKENS rows of the design (light and
dark) are the fallbacks and the colours no Look changes.

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

# Colours no Look changes: the TOKENS rows of the compiled design, light
# and dark, written into the page.
PALETTE = ("hover", "ok", "bad", "bad-tint", "solid", "solid-ink")
# The window's colours the page reads, with the TOKENS rows as fallbacks:
# token -> (CSS variable, colour id, what the mixer sets it from).
TOKENS = {
    "--page": ("--color-new-tab-page-background", "kColorNewTabPageBackground",
               "page"),
    "--surface": ("--color-toolbar", "kColorToolbar", "p.toolbar"),
    "--field": ("--color-location-bar-background",
                "kColorLocationBarBackground", "p.field"),
    "--line": ("--color-toolbar-separator", "kColorToolbarSeparator", "p.line"),
    "--edge": ("--color-boring-edge", "kColorBoringEdge", "p.edge"),
    "--ink": ("--color-toolbar-text", "kColorToolbarText", "p.ink"),
    "--ink2": ("--color-toolbar-button-icon-inactive",
               "kColorToolbarButtonIconInactive", "p.muted"),
    "--accent": ("--color-sys-primary", "kColorSysPrimary", "p.accent"),
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

    def test_the_look_and_accent_are_the_windows_with_fallbacks(self):
        css = page_css()
        for token, (var, _, _) in TOKENS.items():
            self.assertRegex(
                css,
                rf"{re.escape(token)}:\s*var\({re.escape(var)},\s*light-dark\(#[0-9a-f]{{6}},\s*#[0-9a-f]{{6}}\)\);",
                token,
            )

    def test_the_mixer_sets_every_colour_the_page_reads(self):
        src = MIXER.read_text(encoding="utf-8")
        for token, (_, color_id, field) in TOKENS.items():
            self.assertRegex(
                src,
                rf"mixer\[(ui::)?{color_id}\]\s*=\s*\{{{re.escape(field)}\}}",
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
