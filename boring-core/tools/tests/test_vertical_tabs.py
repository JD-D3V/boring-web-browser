#!/usr/bin/env python3
"""Side tabs are Chromium 154's own, off by default, and we do not patch them.

There is no feature flag to turn on: the switch is the vertical_tabs.enabled
pref (Settings > Appearance > Tab position, the tab right-click menu, the app
menu). Top tabs stay the default as long as no patch of ours flips that pref
or the controller. The source checks run only where a 154 tree is present.

Usage:
  python -m unittest boring-core/tools/tests/test_vertical_tabs.py -v
"""

import os
import re
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CORE / "tools"))
SRC = Path(os.environ.get("BORING_SRC_154", r"E:\ung-154\build\src"))


class VerticalTabs(unittest.TestCase):
    def test_no_patch_forces_side_tabs(self):
        for patch in (CORE / "patches").rglob("*.patch"):
            added = [
                line
                for line in patch.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ]
            for line in added:
                self.assertNotRegex(line, r"kVerticalTabsEnabled|vertical_tabs\.enabled", patch.name)

    def test_smoke_covers_both_schemes_light_and_dark(self):
        import smoke_vtabs

        names = {name for name, _ in smoke_vtabs.SCENES}
        self.assertTrue({"cool-light", "cool-dark", "green-dark"} <= names)
        self.assertEqual(smoke_vtabs.PREF, "vertical_tabs.enabled")

    @unittest.skipUnless((SRC / "chrome").is_dir(), "no 154 tree")
    def test_chromium_default_is_top_tabs_with_a_switch(self):
        prefs = (SRC / "chrome/browser/ui/tabs/tab_strip_prefs.cc").read_text(encoding="utf-8")
        self.assertRegex(prefs, r"RegisterBooleanPref\(prefs::kVerticalTabsEnabled,\s*false")
        menu = (SRC / "chrome/browser/ui/tabs/tab_menu_model.cc").read_text(encoding="utf-8")
        self.assertIn("CommandToggleVertical", menu)
        page = (SRC / "chrome/browser/resources/settings/appearance_page/appearance_page.html.ts").read_text(encoding="utf-8")
        self.assertIn('pref-key="vertical_tabs.enabled"', page)


if __name__ == "__main__":
    unittest.main()
