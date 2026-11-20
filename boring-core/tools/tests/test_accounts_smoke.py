#!/usr/bin/env python3
"""Tests for the helpers in smoke_accounts.py and the Accounts wiring.

The smoke needs a built browser; its report reader, its seed and the places
it is wired into do not.

Usage: python -m pytest boring-core/tools/tests/test_accounts_smoke.py
"""

import os
import sys
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(TESTS)
CORE = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import net_audit  # noqa: E402
import run_window_pass  # noqa: E402
import smoke_accounts as sa  # noqa: E402
import smoke_all  # noqa: E402

REPORT = "\n".join([
    "button\tYour accounts\tP",
    "panel\t1",
    "hwnd\t1234",
    "width\t376",
    "label\tYour accounts",
    "label\tPersonal",
    "label\tGoogle account",
    "button\tMail\ton",
    "button\tCalendar\ton",
    "button\tFiles\ton",
    "label\tAdd an account",
    "button\tGoogle\ton",
    "button\tOther\toff",
    "end",
    "",
])


def read(*parts):
    with open(os.path.join(CORE, *parts), encoding="utf-8") as f:
        return f.read()


class Report(unittest.TestCase):
    def test_none_until_end(self):
        self.assertIsNone(sa.parse_report("button\tYour accounts\tP\npanel\t1\n"))

    def test_fields(self):
        r = sa.parse_report(REPORT)
        self.assertEqual(r["button"], ("Your accounts", "P"))
        self.assertTrue(r["panel"])
        self.assertEqual(r["hwnd"], 1234)
        self.assertEqual(r["width"], 376)
        self.assertEqual(r["labels"], ["Your accounts", "Personal", "Google account", "Add an account"])
        self.assertEqual(r["buttons"], [("Mail", True), ("Calendar", True), ("Files", True),
                                        ("Google", True), ("Other", False)])
        self.assertEqual(sa.links_of(r), ["Mail", "Calendar", "Files"])

    def test_closed_panel_and_glyph(self):
        r = sa.parse_report("button\tYour accounts\tglyph\npanel\t0\nend\n")
        self.assertFalse(r["panel"])
        self.assertIsNone(r["hwnd"])
        self.assertEqual(r["button"][1], "glyph")


class Seed(unittest.TestCase):
    def test_seed_is_the_pref_path(self):
        prefs = sa.seed_prefs(sa.SEED)
        self.assertEqual(prefs["boring"]["accounts"]["list"], sa.SEED)
        self.assertEqual(sa.stored_accounts(prefs), sa.SEED)
        self.assertEqual(sa.stored_accounts({}), [])
        self.assertIn('"boring.accounts.list"',
                      read("components", "boring", "accounts", "accounts_store.h"))

    def test_seed_names_known_companies_only(self):
        for entry in sa.SEED:
            self.assertIn(entry["provider"], ("google", "proton"))
            self.assertNotIn("mail", entry)

    def test_bad_text(self):
        self.assertTrue(sa.bad_text("Open in Chrome"))
        self.assertTrue(sa.bad_text("a — b"))
        self.assertFalse(sa.bad_text(sa.FOOTER))

    def test_words_match_the_browser(self):
        button = read("chromium_src", "chrome", "browser", "ui", "views", "toolbar",
                      "boring_accounts_button.cc")
        flat = " ".join(button.replace('"\n           u"', "").split())
        for text in (sa.SUBLINE, sa.FOOTER):
            self.assertIn(text.split(". ")[0], flat)
        handler = read("components", "boring", "accounts", "accounts_handler.cc")
        self.assertIn('"Use an address that starts with https://"', handler)
        self.assertIn("That does not look like a web address.", handler)


class Wiring(unittest.TestCase):
    def test_in_smoke_all_and_the_window_pass(self):
        self.assertIn("smoke_accounts.py", [s for _l, s in smoke_all.CHECKS])
        self.assertIn("smoke_accounts.py", smoke_all.NATIVE_CHECKS)
        self.assertIn("smoke_accounts.py", read("tools", "run_window_pass.py"))
        self.assertTrue(hasattr(run_window_pass, "main"))

    def test_net_audit_scenario(self):
        spec = net_audit.SCENARIOS["accounts"]
        self.assertTrue(spec["must_reach_nothing"])
        self.assertTrue(spec["seed_all_off"])
        self.assertEqual(len(spec["seed_prefs"]["boring"]["accounts"]["list"]), 2)

    def test_patch_is_last_in_series(self):
        series = [s for s in read("patches", "series").splitlines() if s.strip()]
        # Later pieces (the Passport) follow it; it stays after the Bar.
        self.assertIn("accounts.patch", series)
        self.assertGreater(series.index("accounts.patch"), series.index("bar.patch"))
        patch = read("patches", "157", "accounts.patch")
        self.assertIn("IsRegularProfile()", patch)
        self.assertIn("BoringAccountsButton", patch)
        self.assertIn("accounts: false,", patch)


if __name__ == "__main__":
    unittest.main()
