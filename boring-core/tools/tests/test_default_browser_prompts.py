#!/usr/bin/env python3
"""No default browser bar and no pin to taskbar bar on any start (ledger 131,
Q56, after Q52). The patch text is checked here; check_user_launch.py checks
the real window."""

import os
import re
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
TOOLS = CORE / "tools"
PATCH = CORE / "patches" / "157" / "default-browser-prompts-off.patch"
SERIES = CORE / "patches" / "series"
sys.path.insert(0, str(TOOLS))
os.environ.setdefault("BORING_OUT", r"E:\ung-157\build\src\out\Default")

PROMPT = "chrome/browser/ui/startup/default_browser_prompt/default_browser_prompt.cc"
PIN_PREFS = (
    "chrome/browser/ui/startup/default_browser_prompt/pin_infobar/pin_infobar_prefs.cc"
)


def sections(text):
    parts = re.split(r"^diff --git ", text, flags=re.M)[1:]
    return {p.split(" b/", 1)[0].removeprefix("a/"): p for p in parts}


def added(section):
    return "\n".join(
        line[1:]
        for line in section.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def removed(section):
    return "\n".join(
        line[1:]
        for line in section.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )


class PatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        cls.files = sections(cls.text)

    def test_patch_is_in_the_series(self):
        names = [
            line.strip()
            for line in SERIES.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertIn("default-browser-prompts-off.patch", names)

    def test_touches_only_the_two_prompt_files(self):
        self.assertEqual(set(self.files), {PROMPT, PIN_PREFS})

    def test_default_browser_prompt_is_suppressed_for_the_running_version(self):
        # The same pref an installer's initial preferences set
        # (suppress_default_browser_prompt_for_version): the NOT_DEFAULT branch
        # of the startup check then shows nothing. The default follows the
        # build, so the next version needs no edit. The pref is never cleared
        # by Chromium's own reset of the decline counts.
        section = self.files[PROMPT]
        self.assertIn("kBrowserSuppressDefaultBrowserPrompt", section)
        self.assertIn("std::string(version_info::GetVersionNumber())", added(section))
        self.assertIn("std::string());", removed(section))

    def test_pin_prompt_is_at_its_maximum_from_the_start(self):
        # InfoBarShownRecentlyOrMaxTimes() ends with count >= max_prompt_count;
        # a max of 0 makes that true for every stored count, so an older
        # profile with a low count (Release 2) shows nothing either, also when
        # the browser is the default one.
        section = self.files[PIN_PREFS]
        self.assertIn("max_prompt_count = 0;", added(section))
        self.assertEqual(removed(section), "")

    def test_settings_still_sets_the_default(self):
        # Nothing here touches the settings handler, the policy, the OS
        # registration or the Welcome page link.
        for rel in self.files:
            self.assertIn("default_browser_prompt/", rel)
            self.assertNotIn("settings", rel)
            self.assertNotIn("welcome", rel)
        self.assertNotIn("kDefaultBrowserSettingEnabled", self.text)
        self.assertNotIn("SetAsDefault", self.text)


class LaunchCheckTest(unittest.TestCase):
    """check_user_launch.py fails on any default browser or pin bar."""

    @classmethod
    def setUpClass(cls):
        import check_user_launch

        cls.bad = check_user_launch.BAD

    def test_combined_bar(self):
        self.assertTrue(
            self.bad.search(
                "Set Boring Browser as your default browser and pin it to your taskbar"
            )
        )

    def test_default_bar_alone_and_its_button(self):
        self.assertTrue(self.bad.search("Set Boring Browser as your default browser"))
        self.assertTrue(self.bad.search("Set as default"))
        self.assertTrue(self.bad.search("Make default"))

    def test_pdf_viewer_bar(self):
        self.assertTrue(
            self.bad.search("Set Boring Browser as your default PDF viewer")
        )

    def test_pin_bar(self):
        self.assertTrue(self.bad.search("Pin Boring Browser to your taskbar"))

    def test_earlier_forbidden_names_still_fail(self):
        for name in ("Continue where you left off", "Restore pages?", "Vertical tabs"):
            self.assertTrue(self.bad.search(name), name)

    def test_browser_controls_and_welcome_link_do_not_match(self):
        for name in (
            "Protection",
            "Bookmarks you add show here",
            "Make Boring Browser your default browser",
            "Address and search bar",
            "New Tab",
        ):
            self.assertFalse(self.bad.search(name), name)


if __name__ == "__main__":
    unittest.main()
