#!/usr/bin/env python3
"""Source checks for the Passport's safety rules (ledger item 13).

The Passport shows facts about a page's site. These read the real files and
check what a review would: nothing in it can send anything, it never touches
password or card values, the mark it keeps never reaches a protection, the
host it shows is the committed origin's, and its test hook needs a switch.
No Chromium tree and no browser.
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
VIEWS = CORE / "chromium_src" / "chrome" / "browser" / "ui" / "views" / "boring"
PASSPORT = [
    VIEWS / "boring_passport_tab_helper.cc",
    VIEWS / "boring_passport_tab_helper.h",
    VIEWS / "boring_passport_chip.cc",
    VIEWS / "boring_passport_bubble.cc",
    CORE / "components" / "boring" / "passport" / "passport_words.cc",
]
PATCH = CORE / "patches" / "157" / "passport.patch"


def text(path):
    return path.read_text(encoding="utf-8")


def code(path):
    """The file without // comments, so a word in a comment does not count."""
    return re.sub(r"//[^\n]*", "", text(path))


class PassportSourceTest(unittest.TestCase):
    def test_nothing_is_sent(self):
        for path in PASSPORT:
            body = code(path)
            for word in ("URLLoader", "SimpleURLLoader", "NetworkTrafficAnnotation",
                         "url_loader_factory", "UMA_HISTOGRAM", "base::UmaHistogram"):
                self.assertNotIn(word, body, f"{path.name} names {word}")

    def test_no_password_or_card_values(self):
        for path in PASSPORT:
            body = code(path)
            for word in ("password_value", "username_value", "FormFieldData",
                         "FormData", ".value()", "GetLoginsWithAffiliations"):
                if word == ".value()" and path.name == "boring_passport_tab_helper.cc":
                    # base::expected's value(): the list of entries, of which
                    # only two flags are read below.
                    continue
                self.assertNotIn(word, body, f"{path.name} names {word}")
        helper = code(VIEWS / "boring_passport_tab_helper.cc")
        consumer = helper[helper.index("OnGetPasswordStoreResultsOrErrorFrom("):]
        consumer = consumer[: consumer.index("\n}\n")]
        fields = set(re.findall(r"credential\.(\w+)", consumer))
        self.assertEqual(fields, {"blocked_by_user", "match_type"})

    def test_card_fact_reads_only_predicted_types(self):
        # Card details: the page asks if a field is predicted to be a card
        # number or a security code. Nothing a person types is read.
        helper = code(VIEWS / "boring_passport_tab_helper.cc")
        start = helper.index("::OnFieldTypesDetermined(")
        body = helper[start: helper.index("\n}\n", start)]
        self.assertIn("field->Type().GetTypes()", body)
        self.assertIn("CREDIT_CARD_NUMBER", body)
        self.assertIn("CREDIT_CARD_VERIFICATION_CODE", body)
        # The only thing taken from a field is its predicted type.
        self.assertEqual(set(re.findall(r"field->(\w+)", body)), {"Type"})
        for path in PASSPORT:
            for word in ("LOG(", "DLOG(", "VLOG(", "DVLOG(", "base::debug"):
                self.assertNotIn(word, code(path), f"{path.name} names {word}")

    def test_chip_is_drawn_to_the_design_size(self):
        # Window.dc.html: 28 high, padding 0 10, 7px dot, 7px gap, radius 6.
        chip = text(VIEWS / "boring_passport_chip.cc")
        for line in ("kChipHeight = 28;", "kChipPadding = 10;", "kChipGap = 7;",
                     "kDotSize = 7;", "kChipRadius = 6;"):
            self.assertIn(line, chip)
        self.assertIn("SEMIBOLD", chip)

    def test_mark_never_reaches_a_protection(self):
        for folder in ("scam", "adblock", "privacy", "guards"):
            for path in (CORE / "components" / "boring" / folder).rglob("*.cc"):
                self.assertNotIn("kPassportKnownSites", text(path), path.name)
        for path in (CORE / "components" / "boring" / "scam").rglob("*.h"):
            self.assertNotIn("kPassportKnownSites", text(path), path.name)
        bubble = code(VIEWS / "boring_passport_bubble.cc")
        for word in ("AllowHostForSession", "AllowLookalike", "kLookalikeAllowedSites"):
            self.assertNotIn(word, bubble)

    def test_host_is_the_committed_origin_never_page_text(self):
        bubble = code(VIEWS / "boring_passport_bubble.cc")
        self.assertIn("FormatUrlForSecurityDisplay", bubble)
        self.assertIn("GetLastCommittedURL", bubble)
        self.assertIn("ELIDE_HEAD", bubble)
        for path in PASSPORT:
            body = code(path)
            for word in ("GetTitle(", "GetFavicon", "ExecuteJavaScript", "GetVisibleURL()"
                         if path.name != "boring_passport_tab_helper.cc" else "GetTitle("):
                self.assertNotIn(word, body, f"{path.name} names {word}")

    def test_chip_only_for_the_committed_page(self):
        helper = code(VIEWS / "boring_passport_tab_helper.cc")
        self.assertRegex(helper, r"GetVisibleURL\(\) != url")
        for check in ("HostStringIsLocalhost", "HostIsIPAddress", "IsHostnameNonUnique",
                      "SchemeIsHTTPOrHTTPS"):
            self.assertIn(check, helper)

    def test_chip_steps_aside_unless_secure_and_normal(self):
        # Item 52: anything but SECURE keeps Chromium's own indicator, and an
        # error page or Chromium's interstitial is never eligible.
        chip = code(VIEWS / "boring_passport_chip.cc")
        inputs = chip[chip.index("InputsFor("):]
        inputs = inputs[:inputs.index("helper->Inputs(")]
        self.assertRegex(inputs, r"GetSecurityLevel\(\)\s*!=\s*security_state::SECURE")
        helper = code(VIEWS / "boring_passport_tab_helper.cc")
        eligible = helper[helper.index("::Eligible() const"):]
        eligible = eligible[:eligible.index("\n}\n")]
        self.assertRegex(eligible, r"GetPageType\(\)\s*!=\s*content::PAGE_TYPE_NORMAL\s*&&\s*!BlockedPage\(\)")
        words = code(CORE / "components" / "boring" / "passport" / "passport_words.cc")
        decide = words[words.index("Chip DecideChip("):words.index("Chip DecideLayout(")]
        # The field's own state is checked before either soft chip is chosen.
        self.assertLess(decide.index("in.chromium_text"), decide.index("Chip::kKnown"))
        self.assertLess(decide.index("in.pending"), decide.index("Chip::kKnown"))

    def test_facts_are_held_per_origin_not_per_address(self):
        # Item 53: replaceState, pushState or a fragment cannot drop facts.
        for name in ("boring_passport_tab_helper.cc", "boring_passport_bubble.cc"):
            body = code(VIEWS / name)
            self.assertNotRegex(body, r"facts_?\.url\s*==", name)
            self.assertIn("FactsAreFor(", body, name)
        helper = code(VIEWS / "boring_passport_tab_helper.cc")
        self.assertRegex(helper, r"IsSameOriginWith\(url\)")
        self.assertRegex(helper, r"in\.pending\s*=\s*!same_page\s*\|\|\s*facts_\.pending > 0")

    def test_test_hook_needs_its_switch(self):
        newtab = text(CORE / "components" / "boring" / "newtab" / "newtab_ui.cc")
        at = newtab.index('"passportTest"')
        self.assertIn("kPassportTestSwitch", newtab[at - 300: at])
        bubble = code(VIEWS / "boring_passport_bubble.cc")
        run = bubble[bubble.index("base::Value RunPassportTestCommand("):]
        self.assertIn("HasSwitch(kPassportTestSwitch)", run[:400])

    def test_scam_list_offers_no_mark(self):
        words = text(CORE / "components" / "boring" / "passport" / "passport_words.cc")
        scam = words[words.index("case Chip::kScamList:\n      // Not"):]
        self.assertIn("return {kLeaveThisSite};", scam[:200])

    def test_patch_hunks_are_marked(self):
        hunks = text(PATCH).split("\n@@")[1:]
        self.assertTrue(hunks)
        for hunk in hunks:
            added = [l for l in hunk.splitlines() if l.startswith("+")]
            if added:
                self.assertTrue(any("boring" in l for l in added), hunk[:200])

    def test_no_em_dashes_or_browser_names_in_words(self):
        for path in PASSPORT:
            for literal in re.findall(r'u"([^"]*)"', text(path)):
                self.assertNotIn("—", literal)
                self.assertNotIn("Chrom", literal)


if __name__ == "__main__":
    unittest.main()
