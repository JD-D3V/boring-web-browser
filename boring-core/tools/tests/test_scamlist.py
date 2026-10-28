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
import shutil
import sys
import tempfile
import unittest
from unittest import mock

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import get_scamlist  # noqa: E402
from get_filterlists import FeedError, Fetched  # noqa: E402


def cert_text(count: int, start: int = 0, trailing_newline: bool = False) -> str:
    text = "\n".join(f"scam{i:06d}.example.invalid" for i in range(start, start + count))
    return text + ("\n" if trailing_newline else "")


def napkin_text(count: int = 40) -> str:
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


class Assembly(unittest.TestCase):
    def answers(self, **overrides):
        answers = {
            get_scamlist.CERT_URL: cert_text(get_scamlist.CERT_MIN_HOSTS),
            get_scamlist.DURABLENAPKIN_URL: napkin_text(40),
        }
        answers.update(overrides)
        return answers

    def test_both_feeds_are_merged(self):
        built = get_scamlist.build_scam_list(fetch=stub_fetch(self.answers()))
        self.assertEqual(built.failed, [])
        self.assertEqual(built.entries, get_scamlist.CERT_MIN_HOSTS + 40)
        self.assertEqual(
            [s.name for s in built.sources], ["cert-polska", "durablenapkin"]
        )
        self.assertEqual(
            get_scamlist.count_real_hosts(built.text), built.entries
        )

    def test_overlap_counts_once(self):
        answers = self.answers(
            **{get_scamlist.DURABLENAPKIN_URL: "0.0.0.0 scam000001.example.invalid\n" * 1
               + napkin_text(40)}
        )
        built = get_scamlist.build_scam_list(fetch=stub_fetch(answers))
        self.assertEqual(built.entries, get_scamlist.CERT_MIN_HOSTS + 40)

    def test_a_truncated_cert_download_is_a_failed_source(self):
        built = get_scamlist.build_scam_list(
            fetch=stub_fetch(self.answers(**{get_scamlist.CERT_URL: cert_text(500)}))
        )
        self.assertEqual([s.name for s in built.failed], ["cert-polska"])
        self.assertEqual(built.entries, 40)
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
                get_scamlist.CERT_MIN_HOSTS + 40,
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


if __name__ == "__main__":
    unittest.main()
