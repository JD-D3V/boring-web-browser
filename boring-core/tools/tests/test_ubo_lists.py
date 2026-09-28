#!/usr/bin/env python3
"""Offline tests for uBO's lists, the cookie list, regional lists and
the scriptlet resources.

Nothing here touches the network or needs node. Every builder gets its
own fetch, and the resource builder gets its dump as data.

Usage: python -m unittest discover -s boring-core/tools/tests
"""

import base64
import contextlib
import datetime
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

import get_filterlists as gf  # noqa: E402
import get_ubo_resources as gr  # noqa: E402
import publish_lists  # noqa: E402
from get_filterlists import FeedError, Fetched  # noqa: E402

NOW = datetime.datetime(2026, 9, 25, 12, 0, tzinfo=datetime.UTC)

GPL_TEXT = (
    "GNU GENERAL PUBLIC LICENSE\n Version 3, 29 June 2007\n"
    "... the terms ...\nEND OF TERMS AND CONDITIONS\n"
)


def ok(data: bytes) -> Fetched:
    return Fetched(
        url="https://x.invalid/", http_status=200, content_type="text/plain", data=data
    )


def listed(source, rules=None, body=(), tag="r") -> bytes:
    count = rules if rules is not None else source.min_rules * 2
    lines = ["! Title: pretend", source.licence_line, *body]
    lines += [f"||{tag}{i}.example.invalid^" for i in range(count)]
    return ("\n".join(lines) + "\n").encode("utf-8")


def all_answers(regional=True) -> dict:
    answers = {}
    outputs = [gf.UBO, gf.COOKIES, *gf.AGGRESSIVE, *(gf.REGIONAL if regional else ())]
    for n, output in enumerate(outputs):
        for m, source in enumerate(output.sources):
            answers[source.url] = listed(source, tag=f"o{n}s{m}x")
    for _, url in gf.LISTS:
        lines = ["[Adblock Plus 2.0]"] + [
            f"||e{i}.{url[-8:-4]}.invalid^" for i in range(2000)
        ]
        answers[url] = ("\n".join(lines) + "\n").encode("utf-8")
    for licence in (gf.GPL3_UASSETS, gf.GPL3_ADGUARD):
        answers[licence.text_url] = GPL_TEXT.encode("utf-8")
    return answers


def stub(answers):
    def fetch(url):
        answer = answers[url]
        if isinstance(answer, Exception):
            raise answer
        return ok(answer)

    return fetch


class Directives(unittest.TestCase):
    """ "!#if" resolved the way uBO resolves it for desktop Chromium."""

    def test_tokens(self):
        self.assertTrue(gf.eval_expr("env_chromium"))
        self.assertFalse(gf.eval_expr("env_firefox"))
        self.assertTrue(gf.eval_expr("!env_mobile"))
        self.assertFalse(gf.eval_expr("cap_html_filtering"))
        # Our engine has no $ipaddress, unlike uBO in Chromium.
        self.assertFalse(gf.eval_expr("cap_ipaddress"))
        self.assertFalse(gf.eval_expr("ext_abp"))
        self.assertTrue(gf.eval_expr("ext_ublock"))
        # A cap_ token uBO does not know is false; anything else unknown.
        self.assertFalse(gf.eval_expr("cap_something_new"))
        self.assertIsNone(gf.eval_expr("env_something_new"))

    def test_left_to_right_without_precedence(self):
        # uBO reads this as (true || false) && false.
        self.assertFalse(gf.eval_expr("env_chromium || env_firefox && env_mobile"))
        self.assertTrue(gf.eval_expr("(env_chromium && !env_mobile)"))

    def test_blocks(self):
        lines = [
            "keep1",
            "!#if env_firefox",
            "drop1",
            "!#else",
            "keep2",
            "!#endif",
            "!#if env_chromium",
            "!#if env_mobile",
            "drop2",
            "!#endif",
            "keep3",
            "!#endif",
            "!#if env_unknown_thing",
            "keep4",
            "!#endif",
        ]
        out = gf.prune_directives(lines)
        rules = [ln for ln in out if not ln.startswith("!")]
        self.assertEqual(rules, ["keep1", "keep2", "keep3", "keep4"])

    def test_stray_endif_is_ignored(self):
        self.assertEqual(
            [ln for ln in gf.prune_directives(["!#endif", "a"]) if ln == "a"], ["a"]
        )


class Includes(unittest.TestCase):
    BASE = "https://lists.example.invalid/filters/main.txt"

    def resolve(self, text, answers):
        skipped = []
        lines = gf.resolve_list(self.BASE, text, stub(answers), {self.BASE}, skipped)
        return lines, skipped

    def test_include_is_put_in_with_markers(self):
        sub = "https://lists.example.invalid/filters/part.txt"
        lines, _ = self.resolve("a\n!#include part.txt\nb\n", {sub: b"c\n"})
        self.assertEqual(
            lines,
            [
                "a",
                "!#include part.txt",
                f"! >>>>>>>> {sub}",
                "c",
                f"! <<<<<<<< {sub}",
                "b",
            ],
        )

    def test_excluded_include_is_not_fetched(self):
        lines, _ = self.resolve("!#if env_mobile\n!#include m.txt\n!#endif\n", {})
        self.assertFalse(any("m.txt" in ln for ln in lines))

    def test_full_address_and_dotdot_are_not_followed(self):
        text = "!#include https://evil.invalid/x.txt\n!#include ../x.txt\n"
        _, skipped = self.resolve(text, {})
        self.assertEqual(len(skipped), 2)

    def test_include_stays_on_the_same_site(self):
        # A path that looks like another host is still a path here.
        url = gf.include_url(self.BASE, "//evil.invalid/x.txt")
        self.assertTrue(url.startswith("https://lists.example.invalid/"))
        self.assertEqual(
            gf.include_url(self.BASE, "sub/x.txt"),
            "https://lists.example.invalid/filters/sub/x.txt",
        )

    def test_nesting_is_limited(self):
        answers = {}
        for depth in range(gf.MAX_INCLUDE_DEPTH + 2):
            answers[f"https://lists.example.invalid/filters/d{depth}.txt"] = (
                f"!#include d{depth + 1}.txt\n".encode()
            )
        with self.assertRaises(FeedError):
            self.resolve("!#include d0.txt\n", answers)

    def test_each_file_is_included_once(self):
        sub = "https://lists.example.invalid/filters/part.txt"
        lines, _ = self.resolve(
            "!#include part.txt\n!#include part.txt\n", {sub: b"c\n"}
        )
        self.assertEqual(lines.count("c"), 1)

    def test_a_broken_include_fails_the_list(self):
        sub = "https://lists.example.invalid/filters/part.txt"
        with self.assertRaises(FeedError) as caught:
            self.resolve("!#include part.txt\n", {sub: FeedError("HTTP 404")})
        self.assertIn("part.txt", str(caught.exception))


class Headers(unittest.TestCase):
    def test_changed_licence_is_refused(self):
        source = gf.UBO.sources[0]
        text = listed(source).decode().replace(source.licence_line, "! License: MIT")
        with self.assertRaises(FeedError) as caught:
            gf.check_header(text, source)
        self.assertIn("licence", str(caught.exception))

    def test_every_list_has_a_licence_and_a_safe_id(self):
        for output in gf.REGIONAL:
            self.assertRegex(output.regional_id, r"^[a-z0-9][a-z0-9-]{0,31}$")
            self.assertEqual(output.path, f"regional/{output.regional_id}.txt")
            self.assertTrue(output.notice.startswith("NOTICES-regional-"))
        for output in (gf.UBO, gf.COOKIES, *gf.AGGRESSIVE, *gf.REGIONAL):
            for source in output.sources:
                self.assertTrue(source.licence_line.startswith("! "))

    def test_aggressive_lists_are_named_as_the_browser_reads_them(self):
        # components/boring/lists/list_paths.cc: kAggressiveUbo and
        # kAggressiveFanboy, directly in the boring folder.
        self.assertEqual(
            [o.path for o in gf.AGGRESSIVE],
            ["aggressive-ubo.txt", "aggressive-fanboy.txt"],
        )
        for output in gf.AGGRESSIVE:
            self.assertTrue(output.notice.startswith("NOTICES-aggressive-"))
            self.assertIsNone(output.regional_id)
        # Fanboy's lists only from the host whose header names CC BY 3.0.
        for source in gf.AGGRESSIVE[1].sources:
            self.assertTrue(source.url.startswith("https://secure.fanboy.co.nz/"))
            self.assertEqual(source.licence_line, gf.FANBOY_LICENCE_LINE)


class ToolRun(unittest.TestCase):
    """get_filterlists.main as the build runs it, network stubbed."""

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="boring-ubo-test-")
        self.addCleanup(shutil.rmtree, self.out, ignore_errors=True)

    def run_tool(self, answers, extra=()):
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            code = gf.main(["--out", self.out, *extra], fetch=stub(answers), now=NOW)
        return code, log.getvalue()

    def path(self, *parts):
        return os.path.join(self.out, *parts)

    def test_healthy_run_writes_everything(self):
        code, log = self.run_tool(all_answers())
        self.assertEqual(code, 0, log)
        for name in ("easylist.txt", "ubo.txt", "cookies.txt", "sources.json"):
            self.assertTrue(os.path.exists(self.path("boring", name)), name)
        with open(self.path("boring", "regional", "index.json"), encoding="utf-8") as f:
            index = json.load(f)
        self.assertEqual([e["id"] for e in index], [o.regional_id for o in gf.REGIONAL])
        self.assertEqual(set(index[0]), {"id", "title", "locales", "licence", "source"})
        for output in (gf.UBO, gf.COOKIES, *gf.AGGRESSIVE, *gf.REGIONAL):
            self.assertTrue(os.path.exists(self.path(output.notice)), output.notice)
        for output in gf.AGGRESSIVE:
            self.assertTrue(os.path.exists(self.path("boring", output.path)))
        with open(self.path("NOTICES-aggressive-fanboy.txt"), encoding="utf-8") as f:
            self.assertIn(gf.FANBOY_LICENCE_LINE, f.read())
        with open(self.path("NOTICES-uAssets.txt"), encoding="utf-8") as f:
            notice = f.read()
        self.assertIn("END OF TERMS AND CONDITIONS", notice)
        self.assertIn("2026-09-25T12:00:00Z", notice)
        self.assertNotIn(chr(0x2014), notice)
        with open(self.path("NOTICES-easylist-cookie.txt"), encoding="utf-8") as f:
            self.assertIn("The EasyList authors", f.read())
        with open(self.path("boring", "sources.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["generated"], "2026-09-25T12:00:00Z")
        self.assertEqual(len(manifest["lists"]["ubo.txt"]["sources"]), 4)

    def test_easylist_is_as_served(self):
        answers = all_answers()
        self.run_tool(answers)
        with open(self.path("boring", "easylist.txt"), "rb") as f:
            written = f.read()
        joined = b"\n".join(answers[url] for _, url in gf.LISTS)
        self.assertEqual(written, joined)

    def test_one_failed_ubo_source_keeps_ubo_out_and_fails(self):
        answers = all_answers()
        answers[gf.UBO.sources[1].url] = FeedError("HTTP 503")
        code, log = self.run_tool(answers)
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.path("boring", "ubo.txt")))
        # The others still land.
        self.assertTrue(os.path.exists(self.path("boring", "cookies.txt")))
        self.assertIn("not writing ubo.txt", log)

    def test_missing_gpl_text_keeps_those_lists_out(self):
        answers = all_answers()
        answers[gf.GPL3_ADGUARD.text_url] = b"MIT License\n"
        code, _ = self.run_tool(answers)
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.path("boring", "regional", "ja.txt")))
        self.assertTrue(os.path.exists(self.path("boring", "regional", "de.txt")))

    def test_a_list_no_longer_written_is_removed(self):
        self.run_tool(all_answers())
        answers = all_answers()
        answers[gf.REGIONAL[0].sources[0].url] = FeedError("HTTP 404")
        self.run_tool(answers)
        self.assertFalse(os.path.exists(self.path("boring", "regional", "de.txt")))
        self.assertFalse(os.path.exists(self.path("NOTICES-regional-de.txt")))
        with open(self.path("boring", "regional", "index.json"), encoding="utf-8") as f:
            self.assertNotIn("de", [e["id"] for e in json.load(f)])

    def test_no_regional_leaves_regional_alone(self):
        self.run_tool(all_answers())
        code, _ = self.run_tool(all_answers(regional=False), ["--no-regional"])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(self.path("boring", "regional", "de.txt")))


def dump(**extra):
    """A small dump in the shape ubo_resources_dump.mjs prints."""
    scriptlets = [
        {"name": "safe-self.fn", "fn": "function safeSelf() { return {}; }"},
        {
            "name": "set-constant.js",
            "aliases": ["set.js"],
            "fn": "function setConstant(a, b) { safeSelf(); }",
            "dependencies": ["safe-self.fn"],
        },
        {
            "name": "trusted-set-cookie.js",
            "fn": "function trustedSetCookie() {}",
            "requiresTrust": True,
            "world": "ISOLATED",
        },
    ]
    redirects = [
        ["noop.js", {"alias": "noopjs", "data": "text"}],
        ["1x1.gif", {"alias": ["1x1-transparent.gif"], "data": "blob"}],
        ["click2load.html", {"params": ["aliasURL", "url"]}],
    ]
    return {"scriptlets": scriptlets, "redirects": redirects, **extra}


class Resources(unittest.TestCase):
    def setUp(self):
        self.war = tempfile.mkdtemp(prefix="boring-war-test-")
        self.addCleanup(shutil.rmtree, self.war, ignore_errors=True)
        with open(os.path.join(self.war, "noop.js"), "wb") as f:
            f.write(b"(function() {\r\n})();\r\n")
        with open(os.path.join(self.war, "1x1.gif"), "wb") as f:
            f.write(b"GIF89a\x01\x00")

    def test_scriptlets_map_to_adblock_rust_resources(self):
        out = gr.scriptlet_resources(dump()["scriptlets"])
        helper, constant, trusted = out
        self.assertEqual(helper["kind"], {"mime": "fn/javascript"})
        self.assertEqual(constant["kind"], {"mime": "application/javascript"})
        self.assertEqual(constant["aliases"], ["set.js"])
        self.assertEqual(constant["dependencies"], ["safe-self.fn"])
        self.assertNotIn("permission", constant)
        self.assertEqual(trusted["permission"], gr.TRUSTED_PERMISSION)
        self.assertEqual(
            base64.b64decode(constant["content"]).decode(),
            "function setConstant(a, b) { safeSelf(); }",
        )
        # serde leaves empty dependency lists out; so do we.
        self.assertNotIn("dependencies", helper)

    def test_redirects(self):
        out, skipped = gr.redirect_resources(dump()["redirects"], self.war)
        self.assertEqual(skipped, ["click2load.html"])
        noop, gif = out
        self.assertEqual(noop["kind"], {"mime": "application/javascript"})
        self.assertEqual(noop["aliases"], ["noopjs"])
        self.assertEqual(base64.b64decode(noop["content"]), b"(function() {\n})();\n")
        self.assertEqual(gif["kind"], {"mime": "image/gif"})
        self.assertEqual(base64.b64decode(gif["content"]), b"GIF89a\x01\x00")

    def test_new_fields_stop_the_run(self):
        entries = dump()["scriptlets"]
        entries[0]["newThing"] = 1
        with self.assertRaises(gr.FormatError):
            gr.scriptlet_resources(entries)

    def test_arrow_function_scriptlet_stops_the_run(self):
        entries = [{"name": "x.js", "fn": "() => {}"}]
        with self.assertRaises(gr.FormatError):
            gr.scriptlet_resources(entries)

    def test_missing_redirect_file_stops_the_run(self):
        with self.assertRaises(gr.FormatError):
            gr.redirect_resources([["gone.js", {}]], self.war)

    def test_names_must_be_unique_and_dependencies_present(self):
        resources = gr.scriptlet_resources(dump()["scriptlets"])
        clash = gr.resource("other.js", ["set.js"], "application/javascript", b"")
        with self.assertRaises(gr.FormatError):
            gr.check_resources(resources + [clash])
        broken = [r for r in resources if r["name"] != "safe-self.fn"]
        with self.assertRaises(gr.FormatError):
            gr.check_resources(broken)

    def test_tarball_pin(self):
        with self.assertRaises(FeedError):
            gr.verify_tarball(b"not the tarball")


class PublishExtras(unittest.TestCase):
    def test_incomplete_ubo_refuses_the_bundle(self):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import test_lists  # noqa: PLC0415

        work = tempfile.mkdtemp(prefix="boring-pub-test-")
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        answers = test_lists.healthy_answers()
        answers[gf.UBO.sources[3].url] = FeedError("HTTP 503")
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = publish_lists.main(
                ["--out", work, "--unsigned", "--version", "5"],
                fetch_filters=test_lists.stub_fetch(answers),
                check_parse=test_lists.stub_check,
            )
        self.assertEqual(code, 1)
        self.assertIn("ubo.txt", err.getvalue())
        self.assertFalse(os.path.exists(os.path.join(work, "lists.json")))


if __name__ == "__main__":
    unittest.main()
