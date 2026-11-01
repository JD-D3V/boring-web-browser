#!/usr/bin/env python3
"""Redirect and AMP skipping: the rule files, the wiring and the credit.

Source-level checks only: nothing here needs the built browser. The rules
are applied in C++ (components/boring/privacy/debounce.cc), so the sample
address tests live in debounce_test.cc and run in the real build; the
smoke test for the whole thing is smoke_debounce.py, which also runs that
program.

Usage:
  python -m unittest boring-core/tools/tests/test_debounce.py -v
"""

import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
CORE = TOOLS.parent
PRIVACY = CORE / "components" / "boring" / "privacy"
BRAVE_INC = PRIVACY / "debounce_brave.inc"
BORING_INC = PRIVACY / "debounce_boring.inc"

ACTIONS = {"redirect", "base64,redirect", "regex-path", "regex-path-template"}
PATTERN = re.compile(r"^(\*|https?)://(\*\.)?[a-z0-9][a-z0-9.-]*/.*$")


def read(p):
    return p.read_text(encoding="utf-8")


def load_get_debounce():
    spec = importlib.util.spec_from_file_location(
        "get_debounce", TOOLS / "get_debounce.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rules_of(path):
    text = read(path)
    start = text.index('R"JSON(') + len('R"JSON(')
    end = text.rindex(')JSON"')
    return json.loads(text[start:end])


class BraveFileTest(unittest.TestCase):
    def test_the_rules_are_brave_s_bytes_unchanged(self):
        tool = load_get_debounce()
        have = tool.unwrap(BRAVE_INC.read_bytes())
        self.assertIsNotNone(have)
        self.assertEqual(hashlib.sha256(have).hexdigest(), tool.SHA256)

    def test_the_header_carries_licence_and_credit(self):
        head = read(BRAVE_INC).split('R"JSON(')[0]
        self.assertIn("Mozilla Public", head)
        self.assertIn("mozilla.org/MPL/2.0", head)
        self.assertIn("Brave Authors", head)
        self.assertIn("github.com/brave/adblock-lists", head)

    def test_the_file_is_only_included_by_debounce_cc(self):
        for path in (CORE / "components").rglob("*"):
            if path.suffix in {".cc", ".h"} and path.name != "debounce.cc":
                self.assertNotIn(
                    '#include "components/boring/privacy/debounce_brave.inc"',
                    read(path),
                    str(path),
                )


class OurRulesTest(unittest.TestCase):
    def setUp(self):
        self.rules = rules_of(BORING_INC)

    def test_every_rule_has_the_parts_the_reader_needs(self):
        for rule in self.rules:
            self.assertIn(rule["action"], ACTIONS)
            self.assertTrue(rule["param"])
            self.assertTrue(rule["include"])
            for pattern in rule["include"] + rule.get("exclude", []):
                self.assertRegex(pattern, PATTERN)

    def test_no_rule_covers_every_site(self):
        for rule in self.rules:
            for pattern in rule["include"]:
                self.assertNotRegex(pattern, r"^[^:]*://\*/")

    def test_the_redirectors_we_were_asked_for_are_covered(self):
        patterns = " ".join(p for r in self.rules for p in r["include"])
        for wanted in (
            "l.facebook.com/l.php",
            "l.instagram.com/",
            "www.google.com/url",
            "www.youtube.com/redirect",
            "out.reddit.com/",
            "cdn.ampproject.org/v/s/",
        ):
            self.assertIn(wanted, patterns)

    def test_a_plain_shortener_is_not_a_rule(self):
        # t.co carries its target in the page it serves, not in the address.
        patterns = " ".join(p for r in self.rules for p in r["include"])
        self.assertNotIn("//t.co/", patterns)


class WiringTest(unittest.TestCase):
    def test_the_pref_is_on_by_default(self):
        self.assertIn(
            "RegisterBooleanPref(prefs::kSkipRedirects, true)",
            read(CORE / "components" / "boring" / "core" / "boring_prefs.cc"),
        )

    def test_the_throttle_is_added_and_reads_the_pref(self):
        patch = read(CORE / "patches" / "chrome-browser-navigation-throttles.patch")
        self.assertIn("boring::DebounceThrottle::MaybeCreateAndAdd(registry);", patch)
        self.assertIn("debounce_throttle.h", patch)
        self.assertIn("kSkipRedirects", read(PRIVACY / "debounce_throttle.cc"))

    def test_only_the_page_itself_is_looked_at(self):
        text = read(PRIVACY / "debounce_throttle.cc")
        self.assertIn("IsInPrimaryMainFrame()", text)
        self.assertIn("IsHistory()", text)
        self.assertIn("GetReloadType()", text)
        self.assertIn("IsPost()", text)

    def test_every_target_goes_through_one_gate(self):
        text = read(PRIVACY / "debounce.cc")
        self.assertIn("SchemeIsHTTPOrHTTPS()", text)
        self.assertIn("has_username()", text)
        # Each of the four actions builds its address through it, and
        # nothing else makes a GURL from rule data.
        self.assertEqual(len(re.findall(r"= MakeTarget\(|return MakeTarget\(", text)), 4)
        self.assertEqual(len(re.findall(r"\bGURL\s+\w+\(|\bGURL\(", text)), 2)

    def test_the_build_file_lists_every_source(self):
        gn = read(PRIVACY / "BUILD.gn")
        for name in (
            "debounce.cc",
            "debounce.h",
            "debounce_boring.inc",
            "debounce_brave.inc",
            "debounce_throttle.cc",
            "debounce_throttle.h",
            "debounce_test.cc",
        ):
            self.assertIn(f'"{name}"', gn)
        self.assertIn('executable("debounce_test")', gn)


class ProtectionRowTest(unittest.TestCase):
    def setUp(self):
        self.text = read(CORE / "components" / "boring" / "protection" / "protection_ui.cc")

    def test_one_switch_in_each_of_the_places_it_has_to_be(self):
        for needle in (
            'id="skip-redirects"',
            "el('skip-redirects').checked = s.skipRedirects",
            "chrome.send('setSkipRedirects'",
            '"setSkipRedirects"',
            'out.Set("skipRedirects"',
            "HandleSetSkipRedirects",
            "prefs::kSkipRedirects",
        ):
            self.assertIn(needle, self.text)

    def test_the_row_is_a_labelled_checkbox_like_the_others(self):
        self.assertRegex(
            self.text,
            r'(?s)<label class="setting-row" for="skip-redirects">.*?'
            r'<input class="switch" type="checkbox" id="skip-redirects">\s*</label>',
        )


class CreditTest(unittest.TestCase):
    def test_the_shipped_licence_file_names_the_rules(self):
        apply_py = read(TOOLS / "apply.py")
        self.assertIn("debounce_brave.inc", apply_py)
        self.assertIn("Brave", apply_py)

    def test_the_readme_lists_the_licence(self):
        self.assertIn("debounce_brave.inc", read(CORE.parent / "README.md"))


class NoEmDashTest(unittest.TestCase):
    def test_none_of_our_files_have_one(self):
        files = [p for p in PRIVACY.glob("debounce*") if p != BRAVE_INC]
        files += [TOOLS / "get_debounce.py", TOOLS / "smoke_debounce.py", Path(__file__)]
        for path in files:
            if path.exists():
                self.assertNotIn(chr(0x2014), read(path), str(path))


if __name__ == "__main__":
    unittest.main()
