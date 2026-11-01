#!/usr/bin/env python3
"""Offline tests for the phone number banner.

What can be checked without a browser: the detector's node tests, that the
script embeds into a header, and that the tab helper, patch and build
files are wired up. That the banner really shows is smoke_phone_banner.py,
in the built browser.

Usage: python -m unittest discover -s boring-core/tools/tests
"""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BORING_CORE = Path(__file__).resolve().parents[2]
COMPONENTS = BORING_CORE / "components" / "boring"
PHONE = COMPONENTS / "scam" / "phone"
EMBED = COMPONENTS / "assistance" / "embed_scripts.py"


def source(path):
    return path.read_text(encoding="utf-8")


class Embedding(unittest.TestCase):
    def test_the_detector_embeds_as_a_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "phone_scam_scripts.h"
            subprocess.run(
                [
                    sys.executable,
                    str(EMBED),
                    str(out),
                    f"kPhoneScamDetectScript={PHONE / 'phone_scam_detect.js'}",
                ],
                check=True,
            )
            header = out.read_text(encoding="utf-8")
        self.assertIn("kPhoneScamDetectScript[]", header)
        self.assertIn("scanDocument", header)

    def test_the_build_file_uses_the_same_name(self):
        gn = source(PHONE / "BUILD.gn")
        self.assertIn("kPhoneScamDetectScript=", gn)
        self.assertIn("kPhoneScamDetectScript", source(PHONE / "phone_scam_tab_helper.cc"))


class Wiring(unittest.TestCase):
    def test_the_patch_is_in_the_series_and_attaches_the_helper(self):
        series = source(BORING_CORE / "patches" / "series").split()
        self.assertIn("phone-banner-tab-helper.patch", series)
        patch = source(BORING_CORE / "patches" / "phone-banner-tab-helper.patch")
        self.assertIn("boring::PhoneScamTabHelper::CreateForWebContents", patch)
        self.assertNotIn("\r", patch)

    def test_chrome_links_the_helper_through_the_scam_target(self):
        gn = source(COMPONENTS / "scam" / "BUILD.gn")
        self.assertIn('"//components/boring/scam/phone"', gn)

    def test_it_reads_the_existing_switch_and_sets_the_takeover_signal(self):
        cc = source(PHONE / "phone_scam_tab_helper.cc")
        self.assertIn("guards::IsEnabled", cc)
        self.assertIn("TakeoverTabHelper::MarkLooksLikeScam", cc)
        self.assertIn("TakeoverTabHelper::LooksLikeScam", cc)
        # No new switch for this.
        for name in ("boring_prefs.cc", "boring_prefs.h"):
            self.assertNotIn("phone", source(COMPONENTS / "core" / name).lower())

    def test_the_wording_matches_what_the_smoke_test_expects(self):
        wording = "Real companies do not put phone numbers in pop-up warnings."
        self.assertIn(wording, source(PHONE / "phone_scam_tab_helper.cc"))
        self.assertIn(wording, source(BORING_CORE / "tools" / "smoke_phone_banner.py"))


class DeadBranchGone(unittest.TestCase):
    def test_protection_page_has_no_quad9_branch(self):
        text = source(COMPONENTS / "protection" / "protection_ui.cc")
        self.assertNotIn("Quad9", text)
        self.assertNotIn("no warning page", text)


@unittest.skipUnless(shutil.which("node"), "node is not on PATH")
class Detector(unittest.TestCase):
    def test_node_tests_pass(self):
        result = subprocess.run(
            ["node", "--test", str(PHONE / "test_phone_scam_detect.js")],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class NoEmDashes(unittest.TestCase):
    def test_none_in_what_this_feature_wrote(self):
        files = list(PHONE.iterdir()) + [
            BORING_CORE / "tools" / "smoke_phone_banner.py",
            BORING_CORE / "tools" / "capture_phone_banner.py",
            BORING_CORE / "tools" / "testdata" / "phone_banner.html",
            BORING_CORE / "patches" / "phone-banner-tab-helper.patch",
        ]
        for path in files:
            self.assertNotIn(chr(0x2014), source(path), path.name)


class Detector_has_no_stray_delimiter(unittest.TestCase):
    def test_raw_string_delimiter_is_absent(self):
        self.assertIsNone(re.search(r"\)BORINGJS", source(PHONE / "phone_scam_detect.js")))


if __name__ == "__main__":
    unittest.main()
