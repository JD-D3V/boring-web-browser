#!/usr/bin/env python3
"""Offline tests for the blocking list tools.

Nothing here touches the network. Every test hands the builders their
own fetch, so what is being tested is our handling of a feed rather
than whether a feed happens to be up today.

The question all of this exists to answer: can a refresh that failed
ever look like one that worked? It must not, because the answer people
see is "you are protected".

Usage: python -m unittest discover -s boring-core/tools/tests
"""

import base64
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import get_filterlists  # noqa: E402
import get_scamlist  # noqa: E402
import publish_lists  # noqa: E402
from get_filterlists import FeedError, Fetched  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "listdata")

FILTER_URLS = [url for _, url in get_filterlists.LISTS]
EASYLIST_URL, EASYPRIVACY_URL = FILTER_URLS
URLHAUS_URL = get_scamlist.URLHAUS_URL
OPENPHISH_URL = get_scamlist.OPENPHISH_URL


def fixture(name: str) -> bytes:
    with open(os.path.join(DATA, name), "rb") as f:
        return f.read()


def ok(data: bytes, content_type: str = "text/plain; charset=utf-8") -> Fetched:
    return Fetched(
        url="https://feed.example.invalid/",
        http_status=200,
        content_type=content_type,
        data=data,
    )


def stub_fetch(answers: dict):
    """A fetch that answers from a table. A FeedError value is raised."""

    def fetch(url: str) -> Fetched:
        answer = answers[url]
        if isinstance(answer, Exception):
            raise answer
        return ok(answer) if isinstance(answer, bytes) else answer

    return fetch


def filter_bytes(rules: int = 6000, tag: str = "a") -> bytes:
    lines = ["[Adblock Plus 2.0]", "! Title: a pretend list"]
    lines += [f"||ads{tag}{i}.example.invalid^" for i in range(rules)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def hostfile_bytes(count: int = 300, start: int = 0) -> bytes:
    lines = ["# a pretend hostfile"]
    lines += [
        f"127.0.0.1\thost{i:05d}.example.invalid" for i in range(start, start + count)
    ]
    lines.append(f"# Number of entries: {count}")
    return "\n".join(lines).encode("utf-8")


def url_feed_bytes(count: int = 150, start: int = 90000) -> bytes:
    return "".join(
        f"https://phish{i:05d}.example.invalid/login\n"
        for i in range(start, start + count)
    ).encode("utf-8")


URLHAUS_SOURCE = ("urlhaus", URLHAUS_URL, get_scamlist.parse_hostfile)


@contextlib.contextmanager
def permitted(*sources):
    """Runs a block with those scam feeds treated as cleared to use.

    v1 clears none, so build_scam_list does nothing at all. The
    assembly, the floors and the parsers still have to work for the day
    permission arrives, and this is how they stay tested without any of
    it running for real.
    """
    before = get_scamlist.PERMITTED_SOURCES
    get_scamlist.PERMITTED_SOURCES = sources
    try:
        yield
    finally:
        get_scamlist.PERMITTED_SOURCES = before


def healthy_answers() -> dict:
    return {
        EASYLIST_URL: filter_bytes(tag="a"),
        EASYPRIVACY_URL: filter_bytes(tag="b"),
        URLHAUS_URL: hostfile_bytes(),
        OPENPHISH_URL: url_feed_bytes(),
    }


def snapshot(directory: str) -> dict:
    """Every file in a folder with its bytes, for "nothing moved" checks."""
    out = {}
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                out[name] = f.read()
    return out


class PayloadChecks(unittest.TestCase):
    """The checks that apply to any feed, before format comes into it."""

    def test_empty_is_refused(self):
        with self.assertRaises(FeedError):
            get_filterlists.decode_payload(ok(b""))
        with self.assertRaises(FeedError):
            get_filterlists.decode_payload(ok(b"   \n  \n"))

    def test_html_error_page_is_refused(self):
        page = fixture("error_page.html")
        with self.assertRaises(FeedError) as caught:
            get_filterlists.decode_payload(ok(page, "text/html"))
        self.assertIn("content type", str(caught.exception))
        # A host that serves the page as text/plain is still not a list.
        with self.assertRaises(FeedError) as caught:
            get_filterlists.decode_payload(ok(page, "text/plain"))
        self.assertIn("HTML", str(caught.exception))

    def test_non_text_is_refused(self):
        with self.assertRaises(FeedError):
            get_filterlists.decode_payload(ok(b"\x1f\x8b\x08\x00binary"))


class FilterListChecks(unittest.TestCase):
    def test_healthy_list_parses(self):
        text = filter_bytes(1200).decode("utf-8")
        self.assertEqual(get_filterlists.parse_filter_list(text), 1200)

    def test_missing_header_is_refused(self):
        text = fixture("easylist_no_header.txt").decode("utf-8")
        with self.assertRaises(FeedError) as caught:
            get_filterlists.parse_filter_list(text)
        self.assertIn("header", str(caught.exception))

    def test_truncated_list_is_refused(self):
        text = filter_bytes(1200).decode("utf-8").rstrip("\n")
        with self.assertRaises(FeedError) as caught:
            get_filterlists.parse_filter_list(text)
        self.assertIn("truncated", str(caught.exception))

    def test_too_few_rules_is_refused(self):
        text = fixture("easylist_small.txt").decode("utf-8")
        with self.assertRaises(FeedError) as caught:
            get_filterlists.parse_filter_list(text)
        self.assertIn("rules", str(caught.exception))

    def test_prose_wearing_a_header_is_refused(self):
        lines = ["[Adblock Plus 2.0]"]
        count = get_filterlists.MIN_FILTER_RULES + 10
        lines += [f"line {i} of prose, not a filter rule" for i in range(count)]
        with self.assertRaises(FeedError) as caught:
            get_filterlists.parse_filter_list("\n".join(lines) + "\n")
        self.assertIn("filter rules", str(caught.exception))


class HostfileChecks(unittest.TestCase):
    def test_healthy_hostfile_parses(self):
        hosts = get_scamlist.parse_hostfile(
            fixture("urlhaus_good.txt").decode("utf-8")
        )
        self.assertEqual(len(hosts), 40)
        # No trailing newline, which is what the real feed sends.
        self.assertFalse(fixture("urlhaus_good.txt").endswith(b"\n"))

    def test_no_entries_is_refused(self):
        with self.assertRaises(FeedError) as caught:
            get_scamlist.parse_hostfile(
                fixture("urlhaus_no_entries.txt").decode("utf-8")
            )
        self.assertIn("no host lines", str(caught.exception))

    def test_missing_middle_is_caught_by_the_trailer(self):
        with self.assertRaises(FeedError) as caught:
            get_scamlist.parse_hostfile(
                fixture("urlhaus_short_of_trailer.txt").decode("utf-8")
            )
        self.assertIn("claims 390", str(caught.exception))

    def test_cut_mid_record_is_refused(self):
        with self.assertRaises(FeedError) as caught:
            get_scamlist.parse_hostfile(
                fixture("urlhaus_cut_midline.txt").decode("utf-8")
            )
        self.assertIn("truncated", str(caught.exception))

    def test_url_feed_parses(self):
        hosts = get_scamlist.parse_url_feed(
            fixture("openphish_good.txt").decode("utf-8")
        )
        self.assertEqual(len(hosts), 40)

    def test_url_feed_without_its_last_newline_is_refused(self):
        with self.assertRaises(FeedError) as caught:
            get_scamlist.parse_url_feed(fixture("openphish_cut.txt").decode("utf-8"))
        self.assertIn("truncated", str(caught.exception))


class ScamListBuild(unittest.TestCase):
    """v1 builds no scam list, and the builder still works underneath."""

    def test_no_feed_is_permitted(self):
        # The state this version ships in. If this ever fails, someone
        # has added a feed, and that needs a written permission behind
        # it, not a passing test.
        self.assertEqual(get_scamlist.PERMITTED_SOURCES, ())

    def test_nothing_is_fetched_and_there_is_no_coverage(self):
        requested = []

        def fetch(url):
            requested.append(url)
            raise AssertionError("no scam feed may be fetched in this version")

        built = get_scamlist.build_scam_list(fetch=fetch)
        self.assertEqual(requested, [])
        self.assertEqual(built.sources, [])
        self.assertEqual(built.entries, 0)
        self.assertEqual(get_scamlist.count_real_hosts(built.text), 0)

    def test_the_tool_refuses_to_write_a_list(self):
        work = tempfile.mkdtemp(prefix="boring-scam-test-")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = get_scamlist.main(["--out", work])
        self.assertEqual(code, 2)
        self.assertIn("cleared for redistribution", out.getvalue())
        self.assertFalse(os.path.exists(os.path.join(work, "boring")))

    def test_a_permitted_source_that_is_down_means_no_coverage(self):
        with permitted(URLHAUS_SOURCE):
            built = get_scamlist.build_scam_list(
                fetch=stub_fetch({URLHAUS_URL: FeedError("TimeoutError: timed out")})
            )
        self.assertEqual(built.entries, 0)
        self.assertEqual(len(built.failed), 1)
        self.assertFalse(built.healthy)
        # The test entry is still written so the smoke tests can find
        # it, and it still counts for nothing.
        self.assertIn(get_scamlist.TEST_HOSTS[0], built.text)
        self.assertEqual(get_scamlist.count_real_hosts(built.text), 0)

    def test_a_feed_holding_only_the_test_entry_is_zero_coverage(self):
        only_test = (
            "# a pretend hostfile\n"
            f"127.0.0.1\t{get_scamlist.TEST_HOSTS[0]}\n"
            "# Number of entries: 1"
        ).encode("utf-8")
        with permitted(URLHAUS_SOURCE):
            built = get_scamlist.build_scam_list(
                fetch=stub_fetch({URLHAUS_URL: only_test})
            )
        self.assertEqual(built.entries, 0)
        self.assertEqual(get_scamlist.count_real_hosts(built.text), 0)

    def test_openphish_is_never_used_as_fallback(self):
        with permitted(URLHAUS_SOURCE):
            built = get_scamlist.build_scam_list(
                fetch=stub_fetch(
                    {
                        URLHAUS_URL: FeedError("HTTP 503"),
                        OPENPHISH_URL: url_feed_bytes(),
                    }
                )
            )
        self.assertEqual(built.entries, 0)
        self.assertEqual(built.failed[0].name, "urlhaus")
        self.assertFalse(built.healthy)

    def test_only_permitted_urls_are_requested(self):
        requested = []
        answers = stub_fetch(healthy_answers())

        def fetch(url):
            requested.append(url)
            return answers(url)

        with permitted(URLHAUS_SOURCE):
            built = get_scamlist.build_scam_list(fetch=fetch)
        self.assertEqual(requested, [URLHAUS_URL])
        self.assertEqual([source.name for source in built.sources], ["urlhaus"])
        self.assertEqual(built.entries, 300)

    def test_status_carries_what_happened(self):
        with permitted(URLHAUS_SOURCE):
            built = get_scamlist.build_scam_list(fetch=stub_fetch(healthy_answers()))
        urlhaus = built.sources[0]
        self.assertTrue(urlhaus.ok)
        self.assertEqual(urlhaus.http_status, 200)
        self.assertEqual(urlhaus.entries, 300)
        self.assertGreater(urlhaus.bytes, 0)
        self.assertIsNone(urlhaus.reason)

    def test_real_hosts_and_test_hosts_stay_apart_in_the_file(self):
        with permitted(URLHAUS_SOURCE):
            built = get_scamlist.build_scam_list(fetch=stub_fetch(healthy_answers()))
        lines = built.text.splitlines()
        marker = lines.index(get_scamlist.TEST_MARKER)
        self.assertNotIn(get_scamlist.TEST_HOSTS[0], lines[:marker])
        self.assertIn(get_scamlist.TEST_HOSTS[0], lines[marker:])
        self.assertEqual(get_scamlist.count_real_hosts(built.text), built.entries)


class CoveragePolicy(unittest.TestCase):
    def build(self, entries, sources_ok):
        statuses = [
            get_filterlists.SourceStatus(name=f"s{i}", url="x", ok=state)
            for i, state in enumerate(sources_ok)
        ]
        return get_filterlists.BuildResult(text="", entries=entries, sources=statuses)

    def test_all_sources_failed_is_refused(self):
        with self.assertRaises(publish_lists.RefusedError):
            publish_lists.check_coverage(
                publish_lists.SCAM_POLICY, self.build(0, [False, False]), 900
            )

    def test_first_run_needs_real_coverage(self):
        policy = publish_lists.SCAM_POLICY
        with self.assertRaises(publish_lists.RefusedError):
            publish_lists.check_coverage(
                policy, self.build(policy.first_run_floor - 1, [True, True]), None
            )
        publish_lists.check_coverage(
            policy, self.build(policy.first_run_floor, [True, True]), None
        )

    def test_healthy_shrink_floor(self):
        policy = publish_lists.SCAM_POLICY
        publish_lists.check_coverage(policy, self.build(500, [True, True]), 1000)
        with self.assertRaises(publish_lists.RefusedError):
            publish_lists.check_coverage(policy, self.build(400, [True, True]), 1000)

    def test_a_failed_source_buys_a_lower_floor_but_not_no_floor(self):
        policy = publish_lists.SCAM_POLICY
        publish_lists.check_coverage(policy, self.build(400, [True, False]), 1000)
        with self.assertRaises(publish_lists.RefusedError):
            publish_lists.check_coverage(policy, self.build(300, [True, False]), 1000)


class PublishPath(unittest.TestCase):
    """The tool as it is actually run, files on disk and exit codes."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="boring-list-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.out = os.path.join(self.work, "dist")
        os.makedirs(self.out)

    def run_publish(self, answers, extra=None, previous=None):
        fetch = stub_fetch(answers)
        argv = ["--out", self.out, "--unsigned", *(extra or [])]
        if previous:
            argv += ["--previous", previous]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = publish_lists.main(argv, fetch_filters=fetch, fetch_scam=fetch)
        return code, out.getvalue() + err.getvalue()

    def read_manifest(self):
        with open(
            os.path.join(self.out, publish_lists.MANIFEST_NAME), encoding="utf-8"
        ) as f:
            return json.load(f)

    def seed_previous(self, answers=None, version=100):
        code, _ = self.run_publish(
            answers or healthy_answers(), extra=["--version", str(version)]
        )
        self.assertEqual(code, 0)
        return snapshot(self.out)

    def test_healthy_run_publishes_a_correct_bundle(self):
        code, log = self.run_publish(healthy_answers(), extra=["--version", "500"])
        self.assertEqual(code, 0)

        manifest = self.read_manifest()
        self.assertEqual(manifest["version"], 500)
        self.assertFalse(manifest["degraded"])
        self.assertEqual({f["name"] for f in manifest["files"]}, {"easylist.txt"})

        for entry in manifest["files"]:
            with open(os.path.join(self.out, entry["name"]), "rb") as f:
                data = f.read()
            self.assertEqual(len(data), entry["size"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])

        self.assertEqual(len(manifest["sources"]), 2)
        self.assertTrue(all(s["ok"] for s in manifest["sources"]))
        self.assertIn("without a signature", log)

    def test_no_scam_list_is_published_even_though_the_feeds_answer(self):
        # The fetch here would happily hand over both scam feeds. No
        # provider has given permission to pass their data on, so none
        # of it may end up in the bundle or in the manifest.
        code, _ = self.run_publish(healthy_answers(), extra=["--version", "500"])
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(os.path.join(self.out, "scamlist.txt")))
        manifest = self.read_manifest()
        self.assertNotIn("scamlist.txt", [f["name"] for f in manifest["files"]])
        self.assertNotIn("scamlist.txt", [s["list"] for s in manifest["sources"]])
        self.assertNotIn("urlhaus", [s["name"] for s in manifest["sources"]])

    def test_every_filter_source_down_refuses_and_keeps_the_old_bundle(self):
        before = self.seed_previous()

        answers = healthy_answers()
        answers[EASYLIST_URL] = FeedError("TimeoutError: timed out")
        answers[EASYPRIVACY_URL] = FeedError("HTTP 503")
        code, log = self.run_publish(answers, extra=["--version", "101"])

        self.assertEqual(code, 1)
        self.assertIn("every source failed", log)
        self.assertEqual(snapshot(self.out), before)
        self.assertEqual(self.read_manifest()["version"], 100)

    def test_one_filter_source_down_publishes_against_a_previous_bundle(self):
        self.seed_previous()
        answers = healthy_answers()
        answers[EASYLIST_URL] = FeedError("HTTP 503")
        code, _ = self.run_publish(answers, extra=["--version", "101"])

        self.assertEqual(code, 0)
        manifest = self.read_manifest()
        self.assertTrue(manifest["degraded"])
        easylist = next(f for f in manifest["files"] if f["name"] == "easylist.txt")
        self.assertEqual(easylist["entries"], 6000)

    def test_an_html_error_page_refuses_the_run(self):
        before = self.seed_previous()
        answers = healthy_answers()
        answers[EASYLIST_URL] = fixture("error_page.html")
        answers[EASYPRIVACY_URL] = fixture("error_page.html")
        code, log = self.run_publish(answers, extra=["--version", "101"])

        self.assertEqual(code, 1)
        self.assertIn("HTML", log)
        self.assertEqual(snapshot(self.out), before)

    def test_an_empty_feed_refuses_the_run(self):
        before = self.seed_previous()
        answers = healthy_answers()
        answers[EASYLIST_URL] = b""
        answers[EASYPRIVACY_URL] = b"\n\n"
        code, log = self.run_publish(answers, extra=["--version", "101"])

        self.assertEqual(code, 1)
        self.assertIn("empty", log)
        self.assertEqual(snapshot(self.out), before)

    def test_a_truncated_filter_list_refuses_the_run(self):
        before = self.seed_previous()
        answers = healthy_answers()
        answers[EASYLIST_URL] = filter_bytes(tag="a").rstrip(b"\n")
        answers[EASYPRIVACY_URL] = filter_bytes(tag="b").rstrip(b"\n")
        code, log = self.run_publish(answers, extra=["--version", "101"])

        self.assertEqual(code, 1)
        self.assertIn("truncated", log)
        self.assertEqual(snapshot(self.out), before)

    def test_a_dramatic_shrink_is_refused(self):
        before = self.seed_previous()
        answers = healthy_answers()
        # Both sources answer, healthily, with two thirds of the rules
        # the published bundle has. Each one clears its own floor, so
        # the only thing that can refuse this is the shrink policy.
        answers[EASYLIST_URL] = filter_bytes(rules=4000, tag="a")
        answers[EASYPRIVACY_URL] = filter_bytes(rules=4000, tag="b")
        code, log = self.run_publish(answers, extra=["--version", "101"])

        self.assertEqual(code, 1)
        self.assertIn("below the", log)
        self.assertEqual(snapshot(self.out), before)

    def test_a_previous_bundle_in_another_folder_is_compared_against(self):
        previous_dir = os.path.join(self.work, "previous")
        os.makedirs(previous_dir)
        with open(
            os.path.join(previous_dir, publish_lists.MANIFEST_NAME),
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "version": 400,
                    "files": [
                        {"name": "easylist.txt", "entries": 900_000},
                    ],
                },
                f,
            )
        code, log = self.run_publish(
            healthy_answers(), extra=["--version", "500"], previous=previous_dir
        )
        self.assertEqual(code, 1)
        self.assertIn("easylist.txt", log)
        self.assertFalse(os.path.exists(os.path.join(self.out, "easylist.txt")))

    def test_a_version_behind_the_published_one_is_refused(self):
        before = self.seed_previous(version=900)
        code, log = self.run_publish(healthy_answers(), extra=["--version", "800"])
        self.assertEqual(code, 1)
        self.assertIn("below the published", log)
        self.assertEqual(snapshot(self.out), before)

    def test_a_refused_run_leaves_nothing_half_written(self):
        self.seed_previous()
        answers = healthy_answers()
        answers[EASYLIST_URL] = FeedError("HTTP 503")
        answers[EASYPRIVACY_URL] = FeedError("HTTP 503")
        self.run_publish(answers, extra=["--version", "101"])
        self.assertFalse([n for n in os.listdir(self.out) if n.endswith(".new")])

    def test_unsigned_writes_no_signature(self):
        code, log = self.run_publish(healthy_answers(), extra=["--version", "500"])
        self.assertEqual(code, 0)
        self.assertFalse(
            os.path.exists(os.path.join(self.out, publish_lists.SIGNATURE_NAME))
        )
        self.assertIn("WARNING", log)

    def test_a_missing_signing_key_refuses_rather_than_publishing(self):
        fetch = stub_fetch(healthy_answers())
        missing = os.path.join(self.work, "not-a-key.pem")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = publish_lists.main(
                ["--out", self.out, "--sign-key", missing, "--version", "500"],
                fetch_filters=fetch,
                fetch_scam=fetch,
            )
        self.assertEqual(code, 1)
        self.assertIn("no signing key", err.getvalue())
        self.assertFalse(
            os.path.exists(os.path.join(self.out, publish_lists.MANIFEST_NAME))
        )


@unittest.skipUnless(shutil.which("openssl"), "openssl is not on PATH")
class Signing(unittest.TestCase):
    """The signature is only worth having if it is over the real bytes."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="boring-sign-test-")
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.out = os.path.join(self.work, "dist")
        self.keys = os.path.join(self.work, "keys")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(publish_lists.main(["--gen-test-key", self.keys]), 0)
        self.gen_log = out.getvalue()
        self.key = os.path.join(self.keys, "key.pem")

    def test_gen_test_key_says_what_it_is(self):
        self.assertIn("LOCAL TESTING ONLY", self.gen_log)
        self.assertIn("never install it into any trust store", self.gen_log)
        self.assertTrue(os.path.exists(os.path.join(self.keys, "pub.der")))

    def test_a_signed_bundle_has_the_signature_file_the_browser_expects(self):
        fetch = stub_fetch(healthy_answers())
        with contextlib.redirect_stdout(io.StringIO()):
            code = publish_lists.main(
                ["--out", self.out, "--sign-key", self.key, "--version", "500"],
                fetch_filters=fetch,
                fetch_scam=fetch,
            )
        self.assertEqual(code, 0)

        with open(
            os.path.join(self.out, publish_lists.SIGNATURE_NAME), encoding="utf-8"
        ) as f:
            signature = json.load(f)
        self.assertEqual(signature["alg"], publish_lists.SIGNATURE_ALG)
        self.assertEqual(len(signature["key"]), 16)
        self.assertTrue(signature["sig"])

        with open(os.path.join(self.keys, "pub.der"), "rb") as f:
            spki = f.read()
        self.assertEqual(signature["key"], publish_lists.key_id_for(spki))

        # The key id has to be the one the browser will look up, and the
        # signature has to be over the manifest exactly as written.
        manifest_path = os.path.join(self.out, publish_lists.MANIFEST_NAME)
        pub_pem = os.path.join(self.work, "pub.pem")
        sig_der = os.path.join(self.work, "sig.der")
        with open(pub_pem, "wb") as f:
            f.write(publish_lists.openssl(["pkey", "-in", self.key, "-pubout"]))
        with open(sig_der, "wb") as f:
            f.write(base64.b64decode(signature["sig"]))
        publish_lists.openssl(
            [
                "dgst",
                "-sha256",
                "-verify",
                pub_pem,
                "-signature",
                sig_der,
                manifest_path,
            ]
        )

    def test_the_signing_key_can_come_from_the_environment(self):
        with open(self.key, encoding="utf-8") as f:
            pem = f.read()
        fetch = stub_fetch(healthy_answers())
        os.environ[publish_lists.SIGNING_KEY_ENV] = pem
        self.addCleanup(os.environ.pop, publish_lists.SIGNING_KEY_ENV, None)
        with contextlib.redirect_stdout(io.StringIO()):
            code = publish_lists.main(
                ["--out", self.out, "--version", "500"],
                fetch_filters=fetch,
                fetch_scam=fetch,
            )
        self.assertEqual(code, 0)
        self.assertTrue(
            os.path.exists(os.path.join(self.out, publish_lists.SIGNATURE_NAME))
        )


if __name__ == "__main__":
    unittest.main()
