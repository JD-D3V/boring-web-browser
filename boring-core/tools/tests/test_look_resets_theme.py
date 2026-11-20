#!/usr/bin/env python3
"""Picking a Look puts the browser back on our own colours (ledger item 46).

Settings has no Theme row, so a store theme would otherwise stay on for
good. The reset happens browser side, where the Look pref is watched
(ThemeService, cui-colours.patch), not in the page's script.
smoke_settings_appearance.py (check_theme_reset) runs it in the browser.

Usage:
  python -m unittest boring-core/tools/tests/test_look_resets_theme.py -v
"""

import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PATCH = CORE / "patches" / "157" / "cui-colours.patch"


def look_observer():
    """The added lines that register the Look pref's observer."""
    text = PATCH.read_text(encoding="utf-8")
    start = text.index("+  // boring: a new Look in Settings, Appearance repaints at once")
    end = text.index("+  // boring: so does a new accent.", start)
    return text[start:end]


class LookResetsThemeTest(unittest.TestCase):
    def test_the_look_observer_resets_a_theme_that_is_not_ours(self):
        block = look_observer()
        self.assertIn("kBoringLookPref", block)
        self.assertIn("!service->UsingDefaultTheme()", block)
        self.assertIn("service->UseDefaultTheme();", block)

    def test_a_policy_theme_is_left_alone_and_the_look_still_repaints(self):
        block = look_observer()
        self.assertIn("!service->UsingPolicyTheme()", block)
        self.assertIn("service->NotifyThemeChanged();", block)

    def test_it_is_in_theme_service(self):
        text = PATCH.read_text(encoding="utf-8")
        hunk = text[text.index("+++ b/chrome/browser/themes/theme_service.cc"):]
        self.assertIn("UseDefaultTheme", hunk[: hunk.index("diff --git")])


if __name__ == "__main__":
    unittest.main()
