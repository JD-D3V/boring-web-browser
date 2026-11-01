#!/usr/bin/env python3
"""Offline tests for cookie banner blocking and auto-reject.

What can be checked without a browser: the pref's name and default, that
the ad blocker and the renderer read it, that the reject script is built
into the page script the way the agent starts it, and (when node is on
PATH) the flows in cookie_reject.js. That the banners are really hidden
and answered is smoke_cookies.py, in the built browser.

Usage: python -m unittest discover -s boring-core/tools/tests
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BORING_CORE = Path(__file__).resolve().parents[2]
COMPONENTS = BORING_CORE / "components" / "boring"
COSMETIC = COMPONENTS / "adblock" / "cosmetic"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class CookiePref(unittest.TestCase):
    def test_pref_is_named_and_on_by_default(self):
        header = source(COMPONENTS / "core" / "boring_prefs.h")
        self.assertRegex(
            header,
            r'kBoringBlockCookieBanners\[\]\s*=\s*"boring\.privacy\.block_cookie_banners";',
        )
        registry = source(COMPONENTS / "core" / "boring_prefs.cc")
        self.assertIn(
            "RegisterBooleanPref(prefs::kBoringBlockCookieBanners, true)", registry
        )

    def test_the_protection_page_has_a_row_for_it(self):
        page = source(COMPONENTS / "protection" / "protection_ui.cc")
        self.assertRegex(
            page,
            r'<label class="setting-row" for="hide-cookies">\s*<span><strong>Block cookie banners</strong>',
        )
        self.assertIn("prefs->SetBoolean(prefs::kBoringBlockCookieBanners", page)
        self.assertIn("prefs->GetBoolean(prefs::kBoringBlockCookieBanners)", page)
        # The old pref name is gone everywhere.
        self.assertNotIn("kBoringHideCookieNotices", page)
        self.assertNotIn(
            "kBoringHideCookieNotices", source(COMPONENTS / "core" / "boring_prefs.h")
        )

    def test_the_cookie_list_follows_the_pref(self):
        service = source(COMPONENTS / "adblock" / "adblock_service.cc")
        self.assertIn(
            "lists.cookie_notices = prefs->GetBoolean(prefs::kBoringBlockCookieBanners)",
            service,
        )
        # The cookie engine is only in use for a profile that wants it, and
        # auto-reject is only offered to such a profile.
        self.assertRegex(service, r"if \(lists\.cookie_notices\) \{\s*if \(cookies_\)")
        self.assertIn("result->auto_reject_cookies = lists.cookie_notices;", service)

    def test_the_renderer_asks_for_it_in_the_main_frame_only(self):
        mojom = source(COMPONENTS / "adblock" / "mojom" / "adblock.mojom")
        self.assertIn("bool auto_reject_cookies;", mojom)
        agent = source(COSMETIC / "cosmetic_filter_agent.cc")
        self.assertIn("resources->auto_reject_cookies && !frame->Parent()", agent)
        self.assertIn('config.Set("cookies", reject_cookies);', agent)


class EmbeddedScript(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory(dir=os.environ.get("TMP"))
        self.addCleanup(self._dir.cleanup)
        self.dir = Path(self._dir.name)

    def embed(self) -> str:
        out = self.dir / "cosmetic_scripts.h"
        subprocess.run(
            [
                sys.executable,
                str(COSMETIC / "embed_scripts.py"),
                str(out),
                str(COSMETIC / "procedural_filters.js"),
                str(COSMETIC / "cosmetic_filters.js"),
                str(COSMETIC / "cookie_reject.js"),
            ],
            check=True,
        )
        return out.read_text(encoding="utf-8")

    def test_the_reject_script_is_in_the_page_script_and_started_by_config(self):
        header = self.embed()
        self.assertIn("function startCookieReject(doc, win)", header)
        self.assertIn("const COOKIE_REJECT_RULES = [", header)
        self.assertRegex(
            header,
            r"if \(config\.cookies\) \{\s*startCookieReject\(document, window\);\s*\}",
        )
        # The cosmetic filters still start first and unchanged.
        self.assertLess(
            header.index(
                "startCosmeticFilters(sendClassIds, config, document, window)"
            ),
            header.index("startCookieReject(document, window)"),
        )

    @unittest.skipUnless(shutil.which("node"), "node is not on PATH")
    def test_the_whole_page_script_is_valid_javascript(self):
        header = self.embed()
        match = re.search(r'R"BORINGJS\((.*)\)BORINGJS"', header, re.S)
        self.assertIsNotNone(match)
        path = self.dir / "page_script.js"
        path.write_text(
            "const fn = " + match.group(1).strip() + ";\n", encoding="utf-8"
        )
        result = subprocess.run(
            ["node", "--check", str(path)], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_script_missing_is_refused(self):
        result = subprocess.run(
            [sys.executable, str(COSMETIC / "embed_scripts.py"), "out.h", "a", "b"],
            capture_output=True,
            text=True,
            cwd=self.dir,
        )
        self.assertNotEqual(result.returncode, 0)


@unittest.skipUnless(shutil.which("node"), "node is not on PATH")
class RejectFlows(unittest.TestCase):
    def test_node_tests_pass(self):
        result = subprocess.run(
            ["node", "--test", str(COSMETIC / "test_cookie_reject.js")],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class NoEmDashes(unittest.TestCase):
    def test_none_in_what_this_feature_wrote(self):
        for path in (
            COSMETIC / "cookie_reject.js",
            COSMETIC / "test_cookie_reject.js",
            BORING_CORE / "tools" / "smoke_cookies.py",
        ):
            self.assertNotIn(chr(0x2014), source(path), path.name)


if __name__ == "__main__":
    unittest.main()
