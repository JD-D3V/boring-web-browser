#!/usr/bin/env python3
"""Tests for the Passport's decisions and words.

components/boring/passport/passport_words.cc decides which chip the address
field shows and how each fact on the Passport is said. It is plain standard
C++, so this compiles the real file into a small program (passport_probe.cc)
with the Visual Studio compiler and asks it a table of questions. No
Chromium tree and no browser.

Usage: python -m unittest tools.tests.test_passport_words (from boring-core)
"""

import os
import shutil
import subprocess
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(os.path.dirname(TESTS))
WORDS = os.path.join(CORE, "components", "boring", "passport", "passport_words.cc")
VCVARS = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Community"
    r"\VC\Auxiliary\Build\vcvars64.bat"
)

NONE, KNOWN, NEW, BLOCKED, SCAM = range(5)


def inputs(eligible=1, blocked=0, scam=0, text=0, marked=0, visited=0, lookalike=0, pending=0):
    return f"{eligible} {blocked} {scam} {text} {marked} {visited} {lookalike} {pending}"


class PassportWordsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(VCVARS):
            raise unittest.SkipTest("Visual Studio 2022 is not installed here")
        cls.workdir = tempfile.mkdtemp(prefix="passport-", dir=os.environ.get("TMP"))
        cls.exe = os.path.join(cls.workdir, "passport_probe.exe")
        bat = os.path.join(cls.workdir, "build.bat")
        with open(bat, "w") as f:
            f.write(
                "@echo off\n"
                f'call "{VCVARS}" >nul\n'
                f'cd /d "{cls.workdir}"\n'
                "cl /nologo /EHsc /std:c++20 /W3 /O1 "
                f'/I "{CORE}" /Fe"{cls.exe}" '
                f'"{os.path.join(TESTS, "passport_probe.cc")}" "{WORDS}"\n'
            )
        done = subprocess.run(["cmd", "/c", bat], capture_output=True, text=True, timeout=300)
        if done.returncode != 0 or not os.path.exists(cls.exe):
            raise AssertionError("probe did not build:\n" + done.stdout + done.stderr)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def ask(self, *questions):
        done = subprocess.run(
            [self.exe], input="\n".join(questions) + "\n",
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def chip(self, op="chip", **kw):
        number, text, verdict, buttons = self.ask(f"{op} {inputs(**kw)}")[0].split("|")
        return int(number), text, verdict, [b for b in buttons.split(";") if b]

    # Section 2 of the spec, first match wins.
    def test_not_eligible_is_no_chip_whatever_else_holds(self):
        self.assertEqual(self.chip(eligible=0, blocked=1, scam=1, marked=1)[0], NONE)
        self.assertEqual(self.chip(op="layout", eligible=0, blocked=1)[0], NONE)

    def test_blocked_beats_everything(self):
        n, text, _, buttons = self.chip(blocked=1, scam=1, text=1, marked=1, visited=2)
        self.assertEqual((n, text), (BLOCKED, "Blocked"))
        self.assertEqual(buttons, [])  # Pressing it opens page info (Q7).

    def test_scam_list_beats_the_mark_and_history(self):
        n, text, verdict, buttons = self.chip(scam=1, text=1, marked=1, visited=2)
        self.assertEqual((n, text), (SCAM, "Scam list"))
        self.assertEqual(verdict, "This site is on the scam list.")
        self.assertEqual(buttons, ["Leave this site"])  # Q4: no "I know this site".

    def test_chromium_text_keeps_its_words_but_the_passport_opens(self):
        self.assertEqual(self.chip(text=1, visited=2)[0], NONE)
        self.assertEqual(self.chip(op="layout", text=1, visited=2)[0], KNOWN)
        self.assertEqual(self.chip(op="layout", text=1)[0], NEW)

    def test_known_by_history_or_mark(self):
        n, text, verdict, buttons = self.chip(visited=2)
        self.assertEqual((n, text, verdict), (KNOWN, "Known site", "A site you know"))
        self.assertEqual(buttons, ["Site settings", "Forget this site"])
        self.assertEqual(self.chip(marked=1)[0], KNOWN)

    def test_one_earlier_day_is_no_chip_two_is_known(self):
        self.assertEqual(self.chip(visited=0)[0], NEW)
        self.assertEqual(self.chip(visited=1)[0], NONE)
        self.assertEqual(self.chip(op="layout", visited=1)[0], NONE)
        self.assertEqual(self.chip(visited=2)[0], KNOWN)
        self.assertEqual(self.chip(visited=9)[0], KNOWN)
        # The mark is Known at once, whatever history says.
        self.assertEqual(self.chip(marked=1, visited=0)[0], KNOWN)
        self.assertEqual(self.chip(marked=1, visited=1)[0], KNOWN)
        # A look-alike with one earlier day stays New; the red chips win.
        self.assertEqual(self.chip(visited=1, lookalike=1)[0], NEW)
        self.assertEqual(self.chip(visited=1, scam=1)[0], SCAM)
        self.assertEqual(self.chip(visited=1, blocked=1)[0], BLOCKED)
        self.assertEqual(self.chip(visited=1, pending=1)[0], NONE)

    def test_lookalike_is_new_even_with_history_unless_marked(self):
        self.assertEqual(self.chip(visited=2, lookalike=1)[0], NEW)
        self.assertEqual(self.chip(visited=2, lookalike=1, marked=1)[0], KNOWN)

    def test_pending_answers_show_no_soft_chip(self):
        # History is in, the look-alike answer is not: never "Known site".
        self.assertEqual(self.chip(visited=2, pending=1)[0], NONE)
        self.assertEqual(self.chip(marked=1, pending=1)[0], NONE)
        self.assertEqual(self.chip(pending=1)[0], NONE)
        self.assertEqual(self.chip(op="layout", visited=2, pending=1)[0], NONE)
        # The red chips do not wait.
        self.assertEqual(self.chip(blocked=1, pending=1)[0], BLOCKED)
        self.assertEqual(self.chip(scam=1, pending=1)[0], SCAM)

    def test_new_to_you(self):
        n, text, verdict, buttons = self.chip()
        self.assertEqual((n, text, verdict), (NEW, "New to you", "New to you. Take a moment."))
        self.assertEqual(buttons, ["Leave this site", "I know this site"])

    # Section 4.3: visits.
    def test_visit_words(self):
        first, today, month, year, floor = self.ask(
            "visits 0 1 2026 1 2026 March",
            "visits 4 5 2026 1 2026 March",
            "visits 13 14 2026 0 2026 March",
            "visits 2 3 2025 0 2026 December",
            "visits 1 0 2026 0 2026 May",
        )
        self.assertEqual(first, "This is the first time you have visited this site.")
        self.assertEqual(today, "You have visited this site 5 times today.")
        self.assertEqual(month, "You have visited this site 14 times since March.")
        self.assertEqual(year, "You have visited this site 3 times since December 2025.")
        # This page counts too: never "1 times", even if history lags behind.
        self.assertEqual(floor, "You have visited this site 2 times since May.")

    def test_twin_and_connection_words(self):
        used, brand, priv, not_priv = self.ask(
            "twin royalpost.example 1", "twin paypal.com 0", "connection 1", "connection 0"
        )
        self.assertEqual(
            used, "It looks like royalpost.example, a site you use, but it is not the same."
        )
        self.assertEqual(brand, "It looks like paypal.com, but it is not the same.")
        self.assertEqual(priv, "The connection is private.")
        self.assertEqual(not_priv, "The connection is not private.")

    # Footer joins and plurals.
    def test_footer(self):
        zero, one, two, many = self.ask(
            "footer 0 0 0 0 0", "footer 0 3 0 0 0", "footer 0 4 0 0 1", "footer 1 2 1 2 3"
        )
        self.assertEqual(zero, "Nothing blocked on this page.")
        self.assertEqual(one, "Blocked on this page: 3 trackers.")
        self.assertEqual(two, "Blocked on this page: 4 trackers and 1 pop-up.")
        self.assertEqual(
            many,
            "Blocked on this page: 1 ad, 2 trackers, 1 cookie banner, 2 scripts"
            " and 3 pop-ups.",
        )

    # Section 4.4: rows and their order.
    def test_known_rows(self):
        plain, all_rows = self.ask(f"facts {KNOWN} 0 1 1 0", f"facts {KNOWN} 1 1 0 1")
        # A known shop asking for a card is normal: no card row (Q5).
        self.assertEqual(plain, "visits;connection;")
        self.assertEqual(all_rows, "visits;twin;connection;password;")

    def test_new_rows_never_reassure(self):
        private, everything = self.ask(f"facts {NEW} 0 0 1 0", f"facts {NEW} 1 1 0 1")
        self.assertEqual(private, "visits;")
        self.assertEqual(everything, "visits;twin;card;connection;password;")

    def test_scam_rows(self):
        (rows,) = self.ask(f"facts {SCAM} 1 1 1 1")
        self.assertEqual(rows, "scam;visits;twin;card;")

    def test_blocked_and_none_have_no_rows(self):
        self.assertEqual(self.ask(f"facts {BLOCKED} 1 1 0 1", f"facts {NONE} 1 1 0 1"), ["", ""])

    def test_no_em_dashes_or_browser_names(self):
        with open(WORDS, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("\u2014", text)
        self.assertNotIn("Chrome", text)
        self.assertNotIn("Chromium", text)


if __name__ == "__main__":
    unittest.main()
