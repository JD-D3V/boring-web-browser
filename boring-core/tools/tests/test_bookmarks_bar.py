#!/usr/bin/env python3
"""Bookmarks bar on by default, matching the toolbar, and the focus hook.

Source-level checks only: nothing here needs the built browser.

Usage:
  python -m unittest boring-core/tools/tests/test_bookmarks_bar.py -v
"""

import re
import sys
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PATCHES = CORE / "patches"
SERIES = PATCHES / "series"
MIXER = (
    CORE
    / "chromium_src"
    / "chrome"
    / "browser"
    / "ui"
    / "color"
    / "boring_color_mixer.cc"
)
HOOK = PATCHES / "location-bar-test-hook.patch"
TOOLS = CORE / "tools"

sys.path.insert(0, str(TOOLS))


def added(text):
    return "\n".join(ln[1:] for ln in text.splitlines() if ln.startswith("+"))


class DefaultOnTest(unittest.TestCase):
    def test_every_engine_set_keeps_the_pref_default_true(self):
        for sub in ("", "154", "153"):
            p = PATCHES / sub / "shell-defaults.patch"
            text = p.read_text(encoding="utf-8")
            self.assertRegex(
                text,
                r"(?m)^ +prefs::kShowBookmarkBar, true,",
                f"{p} must leave the pref default true",
            )
            self.assertNotRegex(
                text,
                r"(?m)^\+\s+prefs::kShowBookmarkBar, false",
                f"{p} turns the bar off in a new profile",
            )

    def test_no_patch_turns_the_pref_default_off(self):
        for p in PATCHES.rglob("*.patch"):
            text = p.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)^\+.*kShowBookmarkBar,\s*false", str(p))

    def test_toggle_command_is_left_alone(self):
        # Ctrl+Shift+B is Chromium's IDC_SHOW_BOOKMARK_BAR; no patch of ours
        # may remove it or the controller's pref handling.
        for p in PATCHES.rglob("*.patch"):
            text = p.read_text(encoding="utf-8")
            for ln in text.splitlines():
                if ln.startswith("-") and not ln.startswith("---"):
                    self.assertNotIn("IDC_SHOW_BOOKMARK_BAR", ln, str(p))
                    self.assertNotIn("ToggleBookmarkBar", ln, str(p))


class StyleTest(unittest.TestCase):
    def setUp(self):
        self.mixer = MIXER.read_text(encoding="utf-8")

    def test_bar_is_the_toolbar_surface(self):
        self.assertRegex(
            self.mixer, r"mixer\[kColorBookmarkBarBackground\]\s*=\s*\{p\.toolbar\}"
        )

    def test_text_and_icons_use_the_toolbar_ink(self):
        for cid in (
            "kColorBookmarkBarForeground",
            "kColorBookmarkButtonIcon",
            "kColorBookmarkFolderIcon",
        ):
            self.assertRegex(self.mixer, rf"mixer\[{cid}\]\s*=\s*\{{p\.ink\}}")

    def test_separator_is_the_hairline(self):
        self.assertRegex(
            self.mixer,
            r"mixer\[kColorBookmarkBarSeparatorChromeRefresh\]\s*=\s*\{p\.line\}",
        )


class FocusHookTest(unittest.TestCase):
    def setUp(self):
        self.text = HOOK.read_text(encoding="utf-8")

    def test_in_series_after_the_glow(self):
        names = [ln.strip() for ln in SERIES.read_text().splitlines()]
        self.assertIn("location-bar-test-hook.patch", names)
        self.assertLess(
            names.index("location-bar-focus-glow.patch"),
            names.index("location-bar-test-hook.patch"),
        )

    def test_only_runs_with_the_switch(self):
        body = added(self.text)
        self.assertIn('HasSwitch(\n          "boring-focus-omnibox")', body)
        self.assertIn("FocusLocation(", body)

    def test_hunk_counts_are_consistent(self):
        # git apply rejects a hunk whose header disagrees with its body.
        hunks = []
        for ln in self.text.splitlines():
            if ln.startswith("@@"):
                hunks.append((ln, []))
            elif hunks:
                hunks[-1][1].append(ln)
        self.assertTrue(hunks)
        for head, lines in hunks:
            m = re.match(r"@@ -\d+,(\d+) \+\d+,(\d+) @@", head)
            old = sum(1 for ln in lines if ln[:1] in (" ", "-") or ln == "")
            new = sum(1 for ln in lines if ln[:1] in (" ", "+") or ln == "")
            self.assertEqual((old, new), (int(m.group(1)), int(m.group(2))), head)

    def test_capture_tool_passes_the_switch(self):
        import capture_native

        self.assertEqual(capture_native.FOCUS_HOOK, "--boring-focus-omnibox")
        self.assertIn("boring-focus-omnibox", self.text)
        src = (TOOLS / "capture_native.py").read_text(encoding="utf-8")
        self.assertIn("--focus-omnibox", src)
        self.assertIn("chrome_args.append(FOCUS_HOOK)", src)


if __name__ == "__main__":
    unittest.main()
