#!/usr/bin/env python3
"""Offline tests for the two cleared scam feeds and their notice.

Nothing here touches the network. The shapes are the ones the real feeds
send, measured 2026-10-28: CERT Polska's domains.txt is one bare domain
per line with no trailer and no final newline, and DurableNapkin's
hosts.txt is a hostfile whose "# Domains: N" header is not a trailer.

Usage: python -m unittest discover -s boring-core/tools/tests
"""

import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import apply  # noqa: E402
import check_package  # noqa: E402
import get_scamlist  # noqa: E402
from get_filterlists import FeedError, Fetched  # noqa: E402


SUFFIX_FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "listdata", "public_suffix_test.dat"
)
TOP_FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "listdata", "top_domains_test.list"
)
VENDORED_SUFFIXES = os.path.join(get_scamlist.DATA_DIR, "effective_tld_names.dat")
VENDORED_TOP = os.path.join(get_scamlist.DATA_DIR, "domains.list")
_suffix_patch = mock.patch.object(get_scamlist, "PUBLIC_SUFFIX_FILE", SUFFIX_FIXTURE)
_top_patch = mock.patch.object(get_scamlist, "TOP_DOMAINS_FILE", TOP_FIXTURE)


def setUpModule():
    _suffix_patch.start()
    _top_patch.start()


def tearDownModule():
    _top_patch.stop()
    _suffix_patch.stop()


NAPKIN_N = get_scamlist.DURABLENAPKIN_MIN_HOSTS


def cert_text(count: int, start: int = 0, trailing_newline: bool = False) -> str:
    text = "\n".join(f"scam{i:06d}.example.invalid" for i in range(start, start + count))
    return text + ("\n" if trailing_newline else "")


def napkin_text(count: int = NAPKIN_N) -> str:
    lines = ["# Scam Blocklist by DurableNapkin", f"# Domains: {count}", "# -"]
    lines += [f"0.0.0.0 napkin{i:03d}.example.invalid" for i in range(count)]
    return "\n".join(lines) + "\n"


def stub_fetch(answers: dict):
    def fetch(url: str) -> Fetched:
        answer = answers[url]
        if isinstance(answer, Exception):
            raise answer
        return Fetched(
            url=url,
            data=answer.encode("utf-8"),
            http_status=200,
            content_type="text/plain",
        )

    return fetch


class DomainListParser(unittest.TestCase):
    def test_a_list_without_a_final_newline_parses(self):
        # CERT's real file ends like this, so a newline check would
        # refuse every good download.
        hosts = get_scamlist.parse_domain_list(cert_text(50))
        self.assertEqual(len(hosts), 50)

    def test_lowercases_trims_and_dedupes(self):
        hosts = get_scamlist.parse_domain_list(
            "Evil.Example.com\n  evil.example.com  \nEVIL.EXAMPLE.COM.\n# note\n\nb.example.org\n"
        )
        self.assertEqual(hosts, {"evil.example.com", "b.example.org"})

    def test_addresses_are_rejected(self):
        text = "".join(f"scam{i}.example.com\n" for i in range(30))
        text += "192.0.2.7\n10.0.0.1\n"
        hosts = get_scamlist.parse_domain_list(text)
        self.assertEqual(len(hosts), 30)
        self.assertNotIn("192.0.2.7", hosts)
        self.assertNotIn("10.0.0.1", hosts)

    def test_a_list_that_is_mostly_addresses_is_refused(self):
        text = "".join(f"192.0.2.{i}\n" for i in range(1, 100)) + "a.example.com\n"
        with self.assertRaises(FeedError) as caught:
            get_scamlist.parse_domain_list(text)
        self.assertIn("domains", str(caught.exception))

    def test_nothing_in_it_is_refused(self):
        with self.assertRaises(FeedError):
            get_scamlist.parse_domain_list("# only a comment\n\n")

    def test_a_last_line_that_is_not_a_domain_looks_truncated(self):
        text = cert_text(60, trailing_newline=True) + "scam-cut-off-mid-na"
        with self.assertRaises(FeedError) as caught:
            get_scamlist.parse_domain_list(text)
        self.assertIn("truncated", str(caught.exception))

    def test_too_few_domains_is_refused(self):
        with self.assertRaises(FeedError) as caught:
            get_scamlist.parse_domain_list(cert_text(10), min_hosts=11)
        self.assertIn("at least 11", str(caught.exception))

    def test_too_many_domains_is_refused(self):
        with self.assertRaises(FeedError) as caught:
            get_scamlist.parse_domain_list(cert_text(10), max_hosts=9)
        self.assertIn("more than", str(caught.exception))

    def test_cert_list_is_held_to_its_known_size(self):
        whole = get_scamlist.parse_cert_list(cert_text(get_scamlist.CERT_MIN_HOSTS))
        self.assertEqual(len(whole), get_scamlist.CERT_MIN_HOSTS)
        # A download that stopped part way parses perfectly line by
        # line and still has to be refused.
        with self.assertRaises(FeedError):
            get_scamlist.parse_cert_list(cert_text(get_scamlist.CERT_MIN_HOSTS // 2))
        with self.assertRaises(FeedError):
            get_scamlist.parse_cert_list(
                cert_text(get_scamlist.CERT_MAX_HOSTS + 1)
            )


class HostChecks(unittest.TestCase):
    def test_dotted_quads_are_not_hosts(self):
        for host in ("192.0.2.7", "10.0.0.1", "1.2.3.4.5", "999.1.1.1"):
            self.assertFalse(get_scamlist.is_blockable_host(host), host)

    def test_real_names_are_hosts(self):
        for host in ("a.example.com", "xn--e1afmkfd.xn--p1ai", "my-site.example.co.uk", "3m.com"):
            self.assertTrue(get_scamlist.is_blockable_host(host), host)

    def test_hostfile_drops_addresses_too(self):
        text = "".join(f"0.0.0.0 h{i}.example.com\n" for i in range(30))
        text += "0.0.0.0 192.0.2.9\n"
        hosts = get_scamlist.parse_hostfile(text)
        self.assertEqual(len(hosts), 30)
        self.assertNotIn("192.0.2.9", hosts)

    def test_durablenapkin_shape_parses(self):
        hosts = get_scamlist.parse_hostfile(napkin_text(40))
        self.assertEqual(len(hosts), 40)


class PublicSuffixes(unittest.TestCase):
    def test_suffixes_are_dropped_and_sites_under_them_kept(self):
        hosts = {
            "co.uk", "com.pl", "github.io", "blogspot.co.uk", "foo.ck",
            "www.ck", "evil.co.uk", "evil.github.io", "scam.example.com",
        }
        kept, dropped = get_scamlist.drop_public_suffixes(hosts)
        self.assertEqual(
            dropped, {"co.uk", "com.pl", "github.io", "blogspot.co.uk", "foo.ck"}
        )
        self.assertEqual(kept, {"www.ck", "evil.co.uk", "evil.github.io", "scam.example.com"})

    def test_a_feed_line_that_is_a_suffix_never_reaches_the_list(self):
        answers = {
            get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS)
            + "\nco.uk\ngithub.io",
            get_scamlist.DURABLENAPKIN_URL: napkin_text(),
        }
        built = get_scamlist.build_scam_list(fetch=stub_fetch(answers))
        self.assertEqual(built.failed, [])
        lines = built.text.splitlines()
        self.assertNotIn("co.uk", lines)
        self.assertNotIn("github.io", lines)
        self.assertEqual(built.entries, get_scamlist.CERT_MIN_HOSTS + NAPKIN_N)

    def test_a_feed_full_of_suffixes_is_refused(self):
        many = "\n".join(f"{c}.pl" for c in "abcdefg")
        suffixes = "\n".join(f"{c}.ck" for c in "abcdefg")
        answers = {
            get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS)
            + "\n" + suffixes,
            get_scamlist.DURABLENAPKIN_URL: napkin_text(),
        }
        built = get_scamlist.build_scam_list(fetch=stub_fetch(answers))
        self.assertEqual([s.name for s in built.failed], ["cert-polska"])
        self.assertIn("public suffix", built.failed[0].reason)
        self.assertTrue(many)

    def test_a_missing_suffix_file_stops_the_build(self):
        with mock.patch.object(get_scamlist, "PUBLIC_SUFFIX_FILE", SUFFIX_FIXTURE + ".gone"):
            with self.assertRaises(OSError):
                get_scamlist.build_scam_list(fetch=stub_fetch({
                    get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS),
                    get_scamlist.DURABLENAPKIN_URL: napkin_text(),
                }))

    def test_the_real_list_knows_the_usual_suffixes(self):
        with mock.patch.object(get_scamlist, "PUBLIC_SUFFIX_FILE", VENDORED_SUFFIXES):
            _, dropped = get_scamlist.drop_public_suffixes(
                {"co.uk", "com.pl", "github.io", "azurewebsites.net", "example.co.uk"}
            )
        self.assertEqual(dropped, {"co.uk", "com.pl", "github.io", "azurewebsites.net"})


class PopularSites(unittest.TestCase):
    """Pass 2, T2. A feed line cannot put a popular real site on the list."""

    def test_popular_sites_and_names_under_them_are_dropped(self):
        hosts = {
            "chase.com", "login.chase.com", "paypal.com", "evil.github.io",
            "scam.example.invalid", "chase.com.evil.invalid",
        }
        kept, dropped = get_scamlist.drop_popular_sites(hosts)
        self.assertEqual(dropped, {"chase.com", "login.chase.com", "paypal.com"})
        self.assertEqual(
            kept, {"evil.github.io", "scam.example.invalid", "chase.com.evil.invalid"}
        )

    def test_a_feed_line_naming_a_popular_site_never_reaches_the_list(self):
        answers = {
            get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS)
            + "\nchase.com\nwww.paypal.com",
            get_scamlist.DURABLENAPKIN_URL: napkin_text(),
        }
        built = get_scamlist.build_scam_list(fetch=stub_fetch(answers))
        self.assertEqual(built.failed, [])
        lines = built.text.splitlines()
        self.assertNotIn("chase.com", lines)
        self.assertNotIn("www.paypal.com", lines)

    def test_a_feed_full_of_popular_sites_is_refused(self):
        many = "\n".join(f"www{i}.chase.com" for i in range(8))
        answers = {
            get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS) + "\n" + many,
            get_scamlist.DURABLENAPKIN_URL: napkin_text(),
        }
        built = get_scamlist.build_scam_list(fetch=stub_fetch(answers))
        self.assertEqual([s.name for s in built.failed], ["cert-polska"])
        self.assertIn("popular sites", built.failed[0].reason)

    def test_a_missing_top_list_stops_the_build(self):
        with mock.patch.object(get_scamlist, "TOP_DOMAINS_FILE", TOP_FIXTURE + ".gone"):
            with self.assertRaises(OSError):
                get_scamlist.build_scam_list(fetch=stub_fetch({
                    get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS),
                    get_scamlist.DURABLENAPKIN_URL: napkin_text(),
                }))

    def test_a_brand_file_that_reads_as_empty_stops_the_build(self):
        gone = os.path.join(tempfile.mkdtemp(prefix="brands-"), "brands.inc")
        self.addCleanup(shutil.rmtree, os.path.dirname(gone), ignore_errors=True)
        with open(gone, "w", encoding="utf-8") as f:
            f.write('{"paypal", "paypal.com"}\n// a format the pattern no longer reads\n')
        with mock.patch.object(get_scamlist, "BRANDS_FILE", gone):
            with self.assertRaises(get_scamlist.FeedError):
                get_scamlist.load_popular_sites()

    def test_the_shipped_brand_file_clears_the_minimum(self):
        sites = get_scamlist.load_popular_sites()
        self.assertGreaterEqual(len(sites), get_scamlist.MIN_BRANDS)

    def test_the_real_top_list_is_read_and_brands_are_added(self):
        with mock.patch.object(get_scamlist, "TOP_DOMAINS_FILE", VENDORED_TOP):
            sites = get_scamlist.load_popular_sites()
        self.assertIn("google.com", sites)
        self.assertIn("paypal.com", sites)
        self.assertGreater(len(sites), 5000)


class PopularSitesPrivateSuffixes(unittest.TestCase):
    """Ledger 102. A blog on a hosting platform is not the platform."""

    def setUp(self):
        for name, path in (
            ("PUBLIC_SUFFIX_FILE", VENDORED_SUFFIXES),
            ("TOP_DOMAINS_FILE", VENDORED_TOP),
        ):
            patcher = mock.patch.object(get_scamlist, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_name_on_a_hosting_platform_is_kept(self):
        hosts = {
            "scam-blog.wordpress.com", "store.scam-blog.wordpress.com",
            "scam-shop.tumblr.com", "scam.github.io", "scam.pages.dev",
        }
        kept, dropped = get_scamlist.drop_popular_sites(hosts)
        self.assertEqual(dropped, set())
        self.assertEqual(kept, hosts)

    def test_the_platform_and_real_popular_sites_are_dropped(self):
        hosts = {
            "wordpress.com", "tumblr.com", "paypal.com", "login.paypal.com",
            "scam-blog.wordpress.com",
        }
        kept, dropped = get_scamlist.drop_popular_sites(hosts)
        self.assertEqual(
            dropped, {"wordpress.com", "tumblr.com", "paypal.com", "login.paypal.com"}
        )
        self.assertEqual(kept, {"scam-blog.wordpress.com"})

    def test_a_feed_of_blogs_on_a_platform_is_not_refused(self):
        blogs = "\n".join(f"scam{i}.wordpress.com" for i in range(12))
        answers = {
            get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS) + "\n" + blogs,
            get_scamlist.DURABLENAPKIN_URL: napkin_text(),
        }
        built = get_scamlist.build_scam_list(fetch=stub_fetch(answers))
        self.assertEqual(built.failed, [])
        self.assertIn("scam11.wordpress.com", built.text.splitlines())

    def test_more_than_five_popular_entries_still_refuse_the_feed(self):
        count = get_scamlist.MAX_POPULAR_DROPS + 1
        popular = "\n".join(f"www{i}.paypal.com" for i in range(count))
        answers = {
            get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS) + "\n" + popular,
            get_scamlist.DURABLENAPKIN_URL: napkin_text(),
        }
        built = get_scamlist.build_scam_list(fetch=stub_fetch(answers))
        self.assertEqual([s.name for s in built.failed], ["cert-polska"])
        self.assertIn("popular sites", built.failed[0].reason)


class VendoredData(unittest.TestCase):
    """The two Chromium data files travel with the repo."""

    def test_the_vendored_files_are_there_and_are_the_real_ones(self):
        with open(VENDORED_SUFFIXES, encoding="utf-8") as f:
            self.assertIn("Mozilla Public", f.read(400))
        self.assertGreater(os.path.getsize(VENDORED_SUFFIXES), 300_000)
        self.assertGreater(os.path.getsize(VENDORED_TOP), 100_000)

    def test_the_default_is_the_vendored_copy(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("BORING_SRC", None)
            self.assertEqual(
                get_scamlist._data_file("domains.list", "a", "b"), VENDORED_TOP
            )

    def test_boring_src_overrides_it(self):
        with mock.patch.dict(os.environ, {"BORING_SRC": "T"}):
            self.assertEqual(
                get_scamlist._data_file("domains.list", "a", "b"),
                os.path.join("T", "a", "b"),
            )


class SourceFloors(unittest.TestCase):
    """Ledger 102. Each permitted source has its own minimum."""

    def build(self, napkin_count):
        answers = {
            get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS),
            get_scamlist.DURABLENAPKIN_URL: napkin_text(napkin_count),
        }
        return get_scamlist.build_scam_list(fetch=stub_fetch(answers))

    def test_durablenapkin_cut_to_30_hosts_is_a_failed_source(self):
        built = self.build(30)
        self.assertEqual([s.name for s in built.failed], ["durablenapkin"])
        self.assertIn("at least 500", built.failed[0].reason)

    def test_durablenapkin_at_its_floor_passes(self):
        built = self.build(get_scamlist.DURABLENAPKIN_MIN_HOSTS)
        self.assertEqual(built.failed, [])

    def test_the_real_floors_fit_the_feeds_as_measured(self):
        # Measured 2026-11-10: CERT 124,920 and DurableNapkin 2,165 after
        # the filters. A floor above either would refuse a healthy feed.
        self.assertLess(get_scamlist.SOURCE_MIN_HOSTS["cert-polska"], 124_920 // 2)
        self.assertLess(get_scamlist.SOURCE_MIN_HOSTS["durablenapkin"], 2_165 // 2)

    def test_a_source_without_its_own_floor_uses_the_generic_one(self):
        self.assertNotIn("unnamed", get_scamlist.SOURCE_MIN_HOSTS)
        self.assertEqual(get_scamlist.MIN_SOURCE_HOSTS, 25)


class Assembly(unittest.TestCase):
    def answers(self, **overrides):
        answers = {
            get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS),
            get_scamlist.DURABLENAPKIN_URL: napkin_text(),
        }
        answers.update(overrides)
        return answers

    def test_both_feeds_are_merged(self):
        built = get_scamlist.build_scam_list(fetch=stub_fetch(self.answers()))
        self.assertEqual(built.failed, [])
        self.assertEqual(built.entries, get_scamlist.CERT_MIN_HOSTS + NAPKIN_N)
        self.assertEqual(
            [s.name for s in built.sources], ["cert-polska", "durablenapkin"]
        )
        self.assertEqual(
            get_scamlist.count_real_hosts(built.text), built.entries
        )

    def test_overlap_counts_once(self):
        answers = self.answers(
            **{get_scamlist.DURABLENAPKIN_URL: "0.0.0.0 scam000001.example.invalid\n" * 1
               + napkin_text()}
        )
        built = get_scamlist.build_scam_list(fetch=stub_fetch(answers))
        self.assertEqual(built.entries, get_scamlist.CERT_MIN_HOSTS + NAPKIN_N)

    def test_a_truncated_cert_download_is_a_failed_source(self):
        built = get_scamlist.build_scam_list(
            fetch=stub_fetch(self.answers(**{get_scamlist.CERT_URL: cert_text(500)}))
        )
        self.assertEqual([s.name for s in built.failed], ["cert-polska"])
        self.assertEqual(built.entries, NAPKIN_N)
        self.assertTrue(built.degraded)

    def test_big_shared_hosts_are_never_blocked(self):
        cert = cert_text(get_scamlist.CERT_MIN_HOSTS) + "\ngithub.io\nPages.dev\nbad.pages.dev"
        built = get_scamlist.build_scam_list(
            fetch=stub_fetch(self.answers(**{get_scamlist.CERT_URL: cert}))
        )
        lines = built.text.splitlines()
        self.assertNotIn("github.io", lines)
        self.assertNotIn("pages.dev", lines)
        # A scam page under one of them is still blocked.
        self.assertIn("bad.pages.dev", lines)

    def test_main_writes_the_list_and_the_notice(self):
        work = tempfile.mkdtemp(prefix="boring-scam-test-")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        real = get_scamlist.build_scam_list
        out = io.StringIO()
        with mock.patch.object(
            get_scamlist,
            "build_scam_list",
            lambda: real(fetch=stub_fetch(self.answers())),
        ), contextlib.redirect_stdout(out):
            code = get_scamlist.main(["--out", work])
        self.assertEqual(code, 0)
        listed = os.path.join(work, "boring", "scamlist.txt")
        self.assertTrue(os.path.isfile(listed))
        with open(listed, encoding="utf-8") as f:
            self.assertEqual(
                get_scamlist.count_real_hosts(f.read()),
                get_scamlist.CERT_MIN_HOSTS + NAPKIN_N,
            )
        self.assertTrue(os.path.isfile(os.path.join(work, get_scamlist.NOTICE_NAME)))

    def test_main_writes_nothing_when_no_feed_answers(self):
        work = tempfile.mkdtemp(prefix="boring-scam-test-")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        down = {
            get_scamlist.CERT_URL: FeedError("HTTP 503"),
            get_scamlist.DURABLENAPKIN_URL: FeedError("HTTP 503"),
        }
        real = get_scamlist.build_scam_list
        with mock.patch.object(
            get_scamlist, "build_scam_list", lambda: real(fetch=stub_fetch(down))
        ), contextlib.redirect_stdout(io.StringIO()):
            code = get_scamlist.main(["--out", work])
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(os.path.join(work, "boring")))


class Notice(unittest.TestCase):
    def test_the_mit_notice_travels_with_the_list(self):
        notice = get_scamlist.notice_text("2026-10-28T00:00:00Z")
        self.assertIn("Copyright (c) 2019 durablenapkin", notice)
        self.assertIn("Permission is hereby granted", notice)
        self.assertIn("THE SOFTWARE IS PROVIDED", notice)
        self.assertIn("github.com/durablenapkin/scamblocklist", notice)
        self.assertNotIn("{copyright}", notice)

    def test_cert_polska_is_named_without_implying_endorsement(self):
        notice = get_scamlist.notice_text("2026-10-28T00:00:00Z")
        flat = " ".join(notice.split())
        self.assertIn("CERT Polska", flat)
        self.assertIn("Nothing here is endorsed by, or connected with, NASK or CERT Polska", flat)

    def test_no_em_dash(self):
        self.assertNotIn(chr(0x2014), get_scamlist.notice_text("x"))


class DevelopmentStandIn(unittest.TestCase):
    """What apply.py leaves in a tree that never had a scam list."""

    def setUp(self):
        self.tree = tempfile.mkdtemp(prefix="scamlist-tree-")
        self.addCleanup(shutil.rmtree, self.tree, ignore_errors=True)
        self.list_path = os.path.join(
            self.tree, "out", "Default", "boring", "scamlist.txt"
        )

    def stage(self):
        with contextlib.redirect_stdout(io.StringIO()):
            apply.stage_scam_list(self.tree)

    def test_it_holds_the_test_host_and_no_real_host(self):
        text = get_scamlist.development_list()
        self.assertIn(get_scamlist.TEST_HOSTS[0], text)
        self.assertEqual(get_scamlist.count_real_hosts(text), 0)

    def test_a_tree_with_no_list_gets_it(self):
        os.makedirs(os.path.join(self.tree, "out", "Default"))
        self.stage()
        with open(self.list_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), get_scamlist.development_list())

    def test_a_list_already_there_is_left_alone(self):
        os.makedirs(os.path.dirname(self.list_path))
        with open(self.list_path, "w", encoding="utf-8") as f:
            f.write("real.example.invalid\n")
        self.stage()
        with open(self.list_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "real.example.invalid\n")

    def test_an_older_stand_in_is_replaced(self):
        os.makedirs(os.path.dirname(self.list_path))
        with open(self.list_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(
                get_scamlist.DEV_HEADER
                + "\n"
                + get_scamlist.TEST_MARKER
                + "\nboring-scam-test.invalid\n"
            )
        self.stage()
        with open(self.list_path, encoding="utf-8", newline="") as f:
            self.assertEqual(f.read(), get_scamlist.development_list())

    def kmin_hosts(self):
        src = os.path.join(
            os.path.dirname(TOOLS), "components", "boring", "scam", "scam_service.cc"
        )
        with open(src, encoding="utf-8") as f:
            m = re.search(r"kMinHosts\s*=\s*(\d+);", f.read())
        self.assertIsNotNone(m, "kMinHosts not found in scam_service.cc")
        return int(m.group(1))

    def count_hosts(self, text):
        return len(
            [l for l in text.splitlines() if l.strip() and not l.startswith("#")]
        )

    def test_the_stand_in_is_above_the_browsers_floor(self):
        floor = self.kmin_hosts()
        self.assertGreaterEqual(
            self.count_hosts(get_scamlist.development_list()), floor
        )

    def test_the_smoke_scam_list_is_above_the_browsers_floor(self):
        import smoke_scam

        self.assertGreaterEqual(
            self.count_hosts(smoke_scam.SCAM_LIST), self.kmin_hosts()
        )

    def test_a_tree_with_no_output_folder_is_not_given_one(self):
        self.stage()
        self.assertFalse(os.path.exists(os.path.join(self.tree, "out")))

    def check(self, text):
        report = check_package.Report()
        check_package.check_feature_contents(
            "boring/scamlist.txt", lambda: text.encode("utf-8"), report, "t"
        )
        return report

    def test_a_package_will_not_ship_the_stand_in(self):
        self.assertEqual(len(self.check(get_scamlist.development_list()).problems), 1)

    def test_a_package_ships_a_real_list(self):
        text = "\n".join(
            [get_scamlist.HEADER, "scam.example.invalid", get_scamlist.TEST_MARKER]
        )
        self.assertEqual(self.check(text + "\n").problems, [])


if __name__ == "__main__":
    unittest.main()
