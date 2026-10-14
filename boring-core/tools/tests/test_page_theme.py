#!/usr/bin/env python3
"""Our pages take their colours from the browser's theme.

The new tab page used to carry its own teal. It now reads the colours the
window already uses (boring_color_mixer.cc sets them for Cool and Beige,
light and dark) from chrome://theme/colors.css, so the page and the window
are one design and follow the colour picker. The old teal stays as the
fallback if the stylesheet ever fails to load.

Usage:
  python -m unittest boring-core/tools/tests/test_page_theme.py -v
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PAGE = CORE / "components" / "boring" / "newtab" / "newtab_ui.cc"
MIXER = CORE / "chromium_src" / "chrome" / "browser" / "ui" / "color" / "boring_color_mixer.cc"

# Page token -> the theme colour it reads, which the mixer sets from the
# palette field named on the right.
TOKENS = {
    "--surface": ("--color-location-bar-background", "kColorLocationBarBackground", "field"),
    "--paper": ("--color-dialog-background", "kColorDialogBackground", "paper"),
    "--ink": ("--color-dialog-foreground", "kColorDialogForeground", "ink"),
    "--muted": ("--color-label-foreground-secondary", "kColorLabelForegroundSecondary", "muted"),
    "--line": ("--color-bubble-border", "kColorBubbleBorder", "line"),
    "--accent": ("--color-sys-primary", "kColorSysPrimary", "accent"),
    "--soft": ("--color-sys-primary-container", "kColorSysPrimaryContainer", "tint"),
}


def page_css():
    text = PAGE.read_text(encoding="utf-8")
    return re.search(r"<style>(.*?)</style>", text, re.S).group(1)


class PageThemeTest(unittest.TestCase):
    def test_page_loads_the_theme_stylesheet_before_its_own(self):
        text = PAGE.read_text(encoding="utf-8")
        link = text.index('href="chrome://theme/colors.css?sets=ui,chrome"')
        self.assertLess(link, text.index("<style>"))

    def test_each_token_reads_its_theme_colour_with_the_old_teal_as_fallback(self):
        css = page_css()
        for token, (var, _, _) in TOKENS.items():
            self.assertRegex(css, r"%s:\s*var\(%s,\s*light-dark\(#[0-9a-f]{6},\s*#[0-9a-f]{6}\)\);" %
                             (re.escape(token), re.escape(var)))

    def test_field_edge_is_derived_so_it_keeps_its_contrast_in_every_scheme(self):
        self.assertRegex(page_css(), r"--field:\s*color-mix\(in srgb,\s*var\(--ink\)\s*\d+%,\s*var\(--surface\)\);")

    def test_the_mixer_sets_every_colour_the_page_reads(self):
        src = MIXER.read_text(encoding="utf-8")
        for token, (_, color_id, field) in TOKENS.items():
            self.assertRegex(src, r"mixer\[ui::%s\]\s*=\s*\{p\.%s\}|mixer\[%s\]\s*=\s*\{p\.%s\}" %
                             (color_id, field, color_id, field), token)


    def test_settings_always_loads_the_theme_stylesheet(self):
        # Upstream only adds colors.css when a webui-refresh flag is on, which
        # it is not here, so --boring-* silently stayed on their fallbacks.
        for sub in ("", "153/", "154/"):
            text = (CORE / "patches" / sub / "settings-restyle.patch").read_text(encoding="utf-8")
            self.assertIn("-    const enableThemedColors =", text, sub)
            self.assertIn("+    this.addThemedColors_();", text, sub)
            self.assertNotIn("+    if (enableThemedColors)", text, sub)


if __name__ == "__main__":
    unittest.main()
