#!/usr/bin/env python3
"""Three plain switches replaced Senior Safe Mode.

Source-level checks only: nothing here needs the built browser. The
migration itself is run in the real build by smoke_switches.py.

Usage:
  python -m unittest boring-core/tools/tests/test_switches.py -v
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
BORING = CORE / "components" / "boring"
PATCHES = CORE / "patches"
PREFS_H = BORING / "core" / "boring_prefs.h"
PREFS_CC = BORING / "core" / "boring_prefs.cc"
PROTECTION = BORING / "protection" / "protection_ui.cc"
WELCOME = BORING / "welcome" / "welcome_ui.cc"

# The one place the old name may still appear: the pref that migration
# reads once and clears.
OLD_PREF = "boring.senior_safe_mode"

LINES = {
    "Stop screen takeovers": "Stops a page from locking your screen or keyboard "
    "with fake alerts.",
    "No way past scam warnings": "Takes away the continue anyway link on a scam "
    "warning.",
    "Hide sponsored results": "Removes paid results from Google and Bing searches.",
}


def read(p):
    return p.read_text(encoding="utf-8")


def flat(text):
    """Page source with its line breaks and indents folded to single spaces."""
    return re.sub(r"\s+", " ", text)


class NamedModeIsGoneTest(unittest.TestCase):
    def test_no_browser_source_names_the_old_mode(self):
        for path in BORING.rglob("*"):
            if path.suffix not in {".cc", ".h", ".gn", ".html", ".ts", ".js"}:
                continue
            text = read(path).replace(OLD_PREF, "")
            self.assertNotRegex(text, r"(?i)senior", str(path))

    def test_no_patch_set_names_the_old_mode(self):
        for path in PATCHES.rglob("*.patch"):
            self.assertNotRegex(read(path), r"(?i)senior", str(path))

    def test_the_command_line_switch_is_gone(self):
        self.assertNotIn("senior-safe-mode", read(PREFS_CC))
        self.assertNotIn("IsSeniorSafeMode", read(PREFS_H))


class DefaultsTest(unittest.TestCase):
    def test_pref_names(self):
        text = read(PREFS_H)
        self.assertIn('kStopTakeovers[] = "boring.protection.stop_takeovers"', text)
        self.assertIn('kNoScamBypass[] = "boring.protection.no_scam_bypass"', text)
        self.assertIn(
            'kHideSponsoredResults[] = "boring.hide_sponsored_results"', text
        )

    def test_takeovers_on_the_other_two_off(self):
        text = read(PREFS_CC)
        self.assertIn("RegisterBooleanPref(prefs::kStopTakeovers, true)", text)
        self.assertIn("RegisterBooleanPref(prefs::kNoScamBypass, false)", text)
        self.assertIn("RegisterBooleanPref(prefs::kHideSponsoredResults, false)", text)

    def test_one_pref_for_hiding_sponsored_results(self):
        # The existing setting is kept; no second pref for the same thing.
        defined = re.findall(r"constexpr char k\w*Sponsored\w*\[\]", read(PREFS_H))
        self.assertEqual(len(defined), 1)


class MigrationTest(unittest.TestCase):
    def body(self):
        text = read(PREFS_CC)
        start = text.index("void MigrateObsoleteProfilePrefs(")
        return text[start : text.index("\n}\n", start)]

    def test_old_pref_on_turns_every_switch_on(self):
        body = self.body()
        self.assertRegex(body, r"if \(prefs->GetBoolean\(kObsoleteModePref\)\)")
        for pref in ("kStopTakeovers", "kNoScamBypass", "kHideSponsoredResults"):
            self.assertIn(f"prefs->SetBoolean(prefs::{pref}, true);", body)

    def test_old_pref_is_cleared_either_way(self):
        body = self.body()
        # After the if block, not inside it.
        self.assertRegex(body, r"\}\n  prefs->ClearPref\(kObsoleteModePref\);")

    def test_old_pref_is_the_old_name(self):
        text = read(PREFS_CC)
        self.assertIn(f'kObsoleteModePref[] = "{OLD_PREF}"', text)
        self.assertIn("RegisterBooleanPref(kObsoleteModePref, false)", text)

    def test_chromium_runs_it_for_every_profile(self):
        for path in (
            PATCHES / "chrome-browser-prefs.patch",
            PATCHES / "154" / "chrome-browser-prefs.patch",
        ):
            text = read(path)
            self.assertIn("+  boring::MigrateObsoleteProfilePrefs(profile_prefs);", text)
            self.assertRegex(
                text, r"BEGIN_MIGRATE_OBSOLETE_PROFILE_PREFS\n[^\n]*\n\+\n\+  // boring"
            )


class PagesTest(unittest.TestCase):
    def test_protection_page_has_the_three_switches_with_their_lines(self):
        text = flat(read(PROTECTION))
        for label, line in LINES.items():
            self.assertIn(f"<strong>{label}</strong> <p>{line}</p>", text)

    def test_protection_page_asks_before_turning_off_the_bypass_switch(self):
        text = read(PROTECTION)
        self.assertIn("Nobody from a bank or tech company will ever ask", text)
        self.assertIn("chrome.send('setNoScamBypass', [true]);", text)
        self.assertIn("chrome.send('setNoScamBypass', [false]);", text)
        # Only the turn off button sends the off message.
        self.assertEqual(text.count("setNoScamBypass', [false]"), 1)

    def test_welcome_offers_only_the_two_that_start_off(self):
        text = flat(read(WELCOME))
        self.assertIn("No way past scam warnings", text)
        self.assertIn("Hide sponsored results", text)
        self.assertNotIn("screen takeovers", text.lower())
        for line in list(LINES.values())[1:]:
            self.assertIn(line, text)

    def test_no_em_dash_in_either_page(self):
        for path in (PROTECTION, WELCOME):
            self.assertNotIn("—", read(path))
            self.assertNotIn("&mdash;", read(path))

    def test_settings_page_binds_the_same_prefs(self):
        for path in (PATCHES / "settings-boring-pages.patch", PATCHES / "154" / "settings-boring-pages.patch"):
            text = read(path)
            for pref in (
                "boring.protection.stop_takeovers",
                "boring.protection.no_scam_bypass",
                "boring.hide_sponsored_results",
            ):
                self.assertIn(f'(*s_allowlist)["{pref}"]', text)
                self.assertIn("pref=\"{{prefs." + pref + "}}\"", text)


if __name__ == "__main__":
    unittest.main()
