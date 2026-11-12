#!/usr/bin/env python3
"""Offline tests for "block page annoyances".

What can be checked without a browser: the list it ships (source,
licence, notice, no cookie rules let in through an include), that the
bundle and the package carry it, the pref's name and default, the
Protection page row, and that the ad blocker reads the pref and keeps
the per-site off. That pages are really cleaned up is
smoke_annoyances.py, in the built browser.

Usage: python -m unittest discover -s boring-core/tools/tests
"""

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
BORING_CORE = TOOLS.parent
COMPONENTS = BORING_CORE / "components" / "boring"
sys.path.insert(0, str(TOOLS))

import check_package  # noqa: E402
import get_filterlists as gf  # noqa: E402
import publish_lists  # noqa: E402


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def fake_fetch(pages: dict):
    def fetch(url):
        if url not in pages:
            raise gf.FeedError(f"no such page {url}")
        data = pages[url].encode("utf-8")
        return gf.Fetched(url=url, http_status=200, content_type="text/plain", data=data)

    return fetch


NEWSLETTER = gf.FANBOY + "fanboy-newsletter.txt"


def newsletter(include: str = "") -> str:
    rules = "".join(f"##.nl-{i}\n" for i in range(2100))
    head = f"[Adblock Plus 2.0]\n! Title: Fanboy's Newsletter List\n{gf.FANBOY_LICENCE_LINE}\n"
    return head + (f"!#include {include}\n" if include else "") + rules


class TheList(unittest.TestCase):
    def test_it_is_fanboys_newsletter_list_under_cc_by(self):
        self.assertEqual(gf.ANNOYANCES.path, "annoyances.txt")
        self.assertEqual(gf.ANNOYANCES.notice, "NOTICES-annoyances.txt")
        self.assertIs(gf.ANNOYANCES.licence, gf.CC_BY_3)
        (only,) = gf.ANNOYANCES.sources
        self.assertEqual(only.url, "https://secure.fanboy.co.nz/fanboy-newsletter.txt")
        self.assertEqual(
            only.licence_line, "! License: http://creativecommons.org/licenses/by/3.0/"
        )
        self.assertIn("Fanboy", gf.ANNOYANCES.attribution)

    def test_no_list_that_carries_cookie_or_social_rules(self):
        for output in (gf.ANNOYANCES, gf.AGGRESSIVE[0]):
            for src in output.sources:
                self.assertNotIn("annoyance.txt", src.url)  # Fanboy's Annoyance List
                self.assertNotIn("social", src.url)
                self.assertNotIn("cookie", src.url)
                self.assertIn("cookie", src.refuse_includes)

    def test_it_is_built_and_bundled(self):
        self.assertIn(gf.ANNOYANCES, publish_lists.BUNDLED_OUTPUTS)
        self.assertNotIn(gf.ANNOYANCES.path, publish_lists.TRUSTED_NAMES)
        self.assertEqual(publish_lists.bundle_name(gf.ANNOYANCES), "annoyances.txt")

    def test_a_cookie_include_stops_the_build(self):
        fetch = fake_fetch(
            {
                NEWSLETTER: newsletter("easylist_cookie_specific_uBO.txt"),
                gf.FANBOY + "easylist_cookie_specific_uBO.txt": "##.cookie\n",
            }
        )
        build = gf.build_output_list(gf.ANNOYANCES, fetch)
        self.assertFalse(build.complete)
        self.assertIn("easylist_cookie_specific_uBO.txt", build.result.sources[0].reason)

    def test_an_ordinary_include_still_builds(self):
        fetch = fake_fetch(
            {
                NEWSLETTER: newsletter("fanboy_newsletter_specific_uBO.txt"),
                gf.FANBOY + "fanboy_newsletter_specific_uBO.txt": "example.com##.nl\n",
            }
        )
        build = gf.build_output_list(gf.ANNOYANCES, fetch)
        self.assertTrue(build.complete, build.result.sources[0].reason)
        self.assertIn("example.com##.nl", build.result.text)

    def test_the_notice_credits_the_list(self):
        fetch = fake_fetch({NEWSLETTER: newsletter()})
        build = gf.build_output_list(gf.ANNOYANCES, fetch)
        text = gf.notice_text(build, "2026-11-11T00:00:00Z", None)
        self.assertIn("Fanboy's Newsletter List", text)
        self.assertIn("Fanboy and the EasyList authors (https://easylist.to/)", text)
        self.assertIn(gf.FANBOY_LICENCE_LINE, text)
        self.assertIn(gf.CC_BY_3.url, text)


class ThePackage(unittest.TestCase):
    def test_the_package_needs_the_list_and_its_notice(self):
        self.assertIn("boring/annoyances.txt", check_package.REQUIRED_PROTECTION)
        self.assertIn("boring/aggressive-ubo.txt", check_package.REQUIRED_PROTECTION)
        self.assertIn("NOTICES-annoyances.txt", check_package.REQUIRED_NOTICES)

    def test_the_installer_ships_both(self):
        patch = source(BORING_CORE / "patches" / "157" / "package-boring-files.patch")
        self.assertIn("+boring\\annoyances.txt: %(VersionDir)s\\boring\\", patch)
        self.assertIn("+NOTICES-annoyances.txt: %(VersionDir)s\\", patch)
        self.assertIn("+    'filename': 'boring/annoyances.txt',", patch)
        self.assertIn("+    'filename': 'NOTICES-annoyances.txt',", patch)

    def test_the_browser_knows_the_file(self):
        paths_h = source(COMPONENTS / "lists" / "list_paths.h")
        paths_cc = source(COMPONENTS / "lists" / "list_paths.cc")
        self.assertIn("ListKind::kAnnoyances,", paths_h)
        self.assertIn('kAnnoyancesFile[] = "annoyances.txt"', paths_cc)


class ThePref(unittest.TestCase):
    def test_pref_is_named_and_on_by_default(self):
        header = source(COMPONENTS / "core" / "boring_prefs.h")
        self.assertRegex(
            header, r'kBoringBlockAnnoyances\[\]\s*=\s*"boring\.block_annoyances";'
        )
        registry = source(COMPONENTS / "core" / "boring_prefs.cc")
        self.assertIn("RegisterBooleanPref(prefs::kBoringBlockAnnoyances, true)", registry)

    def test_the_protection_page_has_a_row_for_it(self):
        page = source(COMPONENTS / "protection" / "protection_ui.cc")
        self.assertRegex(
            page,
            r'<label class="setting-row" for="hide-annoyances">\s*'
            r"<span><strong>Block page annoyances</strong>",
        )
        self.assertIn("el('hide-annoyances').checked = s.hideAnnoyances;", page)
        self.assertIn("chrome.send('setBlockAnnoyances'", page)
        self.assertIn('"setBlockAnnoyances"', page)
        self.assertIn("prefs->SetBoolean(prefs::kBoringBlockAnnoyances", page)
        self.assertIn("prefs->GetBoolean(prefs::kBoringBlockAnnoyances)", page)

    def test_a_folder_copy_carries_it(self):
        settings = source(COMPONENTS / "folder_copy" / "folder_copy_settings.cc")
        self.assertIn(
            '{prefs::kBoringBlockAnnoyances, "Block page annoyances", Kind::kSwitch}',
            settings,
        )


class TheEngine(unittest.TestCase):
    def setUp(self):
        self.service = source(COMPONENTS / "adblock" / "adblock_service.cc")

    def test_the_lists_follow_the_pref(self):
        self.assertIn(
            "lists.annoyances = prefs->GetBoolean(prefs::kBoringBlockAnnoyances)",
            self.service,
        )
        load = self.service[self.service.index("void AdblockService::LoadAnnoyances()") :]
        load = load[: load.index("\n}\n")]
        self.assertIn("{GetListPath(ListKind::kAggressiveUbo), true}", load)
        self.assertIn("{GetListPath(ListKind::kAnnoyances), false}", load)

    def test_never_with_the_aggressive_engine(self):
        # Same rules twice would run every scriptlet twice.
        self.assertRegex(
            self.service,
            r"\} else if \(lists\.annoyances\) \{[^}]*if \(annoyances_\) \{\s*"
            r"engines\.push_back\(annoyances_\);",
        )

    def test_a_site_with_blocking_off_is_left_alone(self):
        # Every engine, this one too, is skipped for such a site before any
        # engine is asked: requests in the throttle, page rules in the
        # cosmetic filter host.
        throttle = source(COMPONENTS / "adblock" / "adblock_throttle.cc")
        self.assertIn("->IsOff(top_frame_url)", throttle)
        cosmetic = source(COMPONENTS / "adblock" / "cosmetic_filters_impl.cc")
        self.assertIn("return !off_sites_ || !off_sites_->IsOff(top_frame_url);", cosmetic)


class NoEmDashes(unittest.TestCase):
    def test_none_in_what_this_feature_wrote(self):
        for path in (
            TOOLS / "smoke_annoyances.py",
            Path(__file__),
            COMPONENTS / "protection" / "protection_ui.cc",
        ):
            self.assertNotIn(chr(0x2014), source(path), path.name)


if __name__ == "__main__":
    unittest.main()
