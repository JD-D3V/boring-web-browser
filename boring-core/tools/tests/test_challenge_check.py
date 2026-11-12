#!/usr/bin/env python3
"""The pure parts of challenge_check.py, and the WebGL name it tests.

Nothing here starts a browser.

Usage: python -m pytest boring-core/tools/tests/test_challenge_check.py
"""

import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
PATCHES = TOOLS.parent / "patches"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import challenge_check as cc  # noqa: E402


def s(title="", url="https://x.test/", origin="1", cf=False, token=False):
    return {"title": title, "url": url, "origin": origin, "cf": cf, "token": token}


CF = "Just a moment..."


class Classify(unittest.TestCase):
    def test_no_challenge(self):
        self.assertEqual(cc.classify([s("Home"), s("Home")]), "none")

    def test_passed(self):
        self.assertEqual(cc.classify([s(CF), s(CF), s("Home", origin="2")]), "passed")

    def test_challenge_comes_back_is_a_loop(self):
        tl = [s(CF), s("Home", origin="2"), s(CF, origin="3")]
        self.assertEqual(cc.classify(tl), "looped")

    def test_challenge_page_reloading_itself_is_a_loop(self):
        tl = [s(CF, origin=str(i)) for i in range(3)]
        self.assertEqual(cc.classify(tl), "looped")

    def test_stuck(self):
        self.assertEqual(cc.classify([s(CF), s(CF), s(CF)]), "stuck")

    def test_title_only_samples_from_plain_mode(self):
        tl = [{"title": "Just a moment... - Boring Browser"}] * 3
        self.assertEqual(cc.classify(tl), "stuck")

    def test_markers_other_than_title(self):
        self.assertTrue(cc.is_challenge(s(cf=True)))
        self.assertTrue(cc.is_challenge(s(url="https://x.test/?__cf_chl_rt_tk=1")))
        self.assertFalse(cc.is_challenge(s("A moment of calm")))

    def test_failed_reads_do_not_split_an_episode(self):
        tl = [s(CF), {"t": None, "error": "navigating"}, s(CF), s("Home", origin="2")]
        self.assertEqual(cc.classify(tl), "passed")

    def test_widget(self):
        self.assertEqual(cc.classify([s(), s(token=True)], "widget"), "solved")
        self.assertEqual(cc.classify([s(), s()], "widget"), "unsolved")

    def test_empty(self):
        self.assertEqual(cc.classify([]), "no-data")


class Compare(unittest.TestCase):
    def test_noise_causes_it(self):
        on = ["looped", "stuck", "looped", "passed", "looped"]
        off = ["passed"] * 4 + ["looped"]
        self.assertEqual(cc.compare(on, off), "noise causes it")

    def test_baseline_fails_too(self):
        on = ["looped"] * 5
        off = ["looped", "looped", "stuck", "passed", "passed"]
        self.assertEqual(cc.compare(on, off), "plain Chromium fails too")

    def test_no_trouble(self):
        self.assertEqual(cc.compare(["none"] * 5, ["passed"] * 5), "no trouble")

    def test_small_difference_is_inconclusive(self):
        on = ["looped", "looped", "passed", "passed", "passed"]
        off = ["looped", "passed", "passed", "passed", "passed"]
        self.assertEqual(cc.compare(on, off), "inconclusive")

    def test_not_run(self):
        self.assertEqual(cc.compare([], ["none"]), "not run")


class Verdicts(unittest.TestCase):
    def test_creepjs(self):
        text = "0% headless: noop\n33% like headless: x\n12% stealth\nlies (3)"
        v = cc.parse_verdict("creepjs", text)
        self.assertEqual(v, {"like_headless_pct": 33.0, "headless_pct": 0.0,
                             "stealth_pct": 12.0, "lies": 3})

    def test_recaptcha(self):
        text = '{"success": true, "score": 0.9, "action": "examples/v3scores"}'
        self.assertEqual(cc.parse_verdict("recaptcha", text), {"score": 0.9})

    def test_botd(self):
        self.assertEqual(cc.parse_verdict("botd", '{"bot": false}'), {"bot": False})
        self.assertEqual(cc.parse_verdict("botd", "You are a bot"), {"bot": True})
        self.assertEqual(cc.parse_verdict("botd", "nothing"), {"bot": None})

    def test_sannysoft(self):
        v = cc.parse_verdict("sannysoft", "", {"failed": 2, "passed": 20})
        self.assertEqual(v, {"failed": 2, "passed": 20})

    def test_browserleaks(self):
        text = "Unmasked Vendor\tGoogle Inc. (Intel)\nUnmasked Renderer\tANGLE (Intel, x, D3D11)\n"
        v = cc.parse_verdict("browserleaks", text)
        self.assertEqual(v["renderer"], "ANGLE (Intel, x, D3D11)")
        self.assertIsNone(v["uniqueness"])

    def test_missing_text(self):
        self.assertEqual(cc.parse_verdict("creepjs", None)["lies"], None)

    def test_summary_medians(self):
        visits = [
            {"page": "p", "arm": "on", "outcome": "none", "verdict": {"score": 0.3}},
            {"page": "p", "arm": "on", "outcome": "none", "verdict": {"score": 0.7}},
            {"page": "p", "arm": "off", "outcome": "none", "verdict": {"score": 0.9}},
        ]
        out = cc.summarize(visits)["p"]
        self.assertEqual(out["median_verdicts"]["on"]["score"], 0.5)
        self.assertEqual(out["on_vs_off"], "no trouble")


class Setup(unittest.TestCase):
    def test_profile_prefs(self):
        self.assertEqual(cc.profile_prefs("off"), {"boring": {"fingerprint_noise": False}})
        self.assertIsNone(cc.profile_prefs("on"))
        self.assertIsNone(cc.profile_prefs("on-realgl"))
        with self.assertRaises(ValueError):
            cc.profile_prefs("maybe")

    def test_spoof_feature_escapes_commas_and_slashes(self):
        value = cc.spoof_feature("A, B", "C/D (E)")
        self.assertTrue(value.startswith("SpoofWebGLInfo:vendor/"))
        self.assertNotIn(",", value)
        _, params = value.split(":", 1)
        parts = params.split("/")
        self.assertEqual(parts[0::2], ["vendor", "renderer"])
        self.assertEqual([urllib.parse.unquote(p) for p in parts[1::2]],
                         ["A, B", "C/D (E)"])
        self.assertNotIn("%20", value)

    def test_arm_switches(self):
        self.assertEqual(cc.arm_switches("on"), [])
        self.assertEqual(cc.arm_switches("off"), [])
        self.assertEqual(len(cc.arm_switches("on-realgl")), 1)
        self.assertEqual(cc.arm_switches("only-rects"),
                         ["--fingerprinting-client-rects-noise"])

    def test_isolation_arms_start_with_the_pref_off(self):
        for arm in cc.ONE_SWITCH:
            self.assertEqual(cc.profile_prefs(arm), cc.profile_prefs("off"), arm)
            self.assertEqual(len(cc.arm_switches(arm)), 1, arm)

    def test_isolation_switches_are_the_ones_the_pref_adds(self):
        patch = (PATCHES / "157" / "privacy-defaults.patch").read_text(encoding="utf-8")
        for name in ("kFingerprintingClientRectsNoise",
                     "kFingerprintingCanvasMeasureTextNoise",
                     "kFingerprintingCanvasImageDataNoise"):
            self.assertIn(name, patch)
        self.assertEqual(len(cc.ONE_SWITCH), 3)

    def test_arm_order_alternates(self):
        self.assertEqual(cc.arm_order(0, ["on", "off"]), ["on", "off"])
        self.assertEqual(cc.arm_order(1, ["on", "off"]), ["off", "on"])

    def test_robots(self):
        robots = "User-agent: *\nDisallow: /private\n"
        self.assertTrue(cc.robots_allows(robots, "https://x.test/"))
        self.assertFalse(cc.robots_allows(robots, "https://x.test/private/a"))
        self.assertTrue(cc.robots_allows("", "https://x.test/"))

    def test_pages_are_https_and_named_once(self):
        names = [p["name"] for p in cc.PAGES]
        self.assertEqual(len(names), len(set(names)))
        for p in cc.PAGES:
            self.assertTrue(p["url"].startswith("https://"), p["name"])
            self.assertIn(p["group"], ("challenge", "detector", "ordinary", "needs-click"))

    def test_tool_never_sends_input(self):
        src = (TOOLS / "challenge_check.py").read_text(encoding="utf-8")
        for banned in ("dispatchMouseEvent", "dispatchKeyEvent", "SendInput",
                       "keybd_event", "mouse_event", ".click(", ".submit(",
                       "/element/", "ImageGrab"):
            self.assertNotIn(banned, src)


class FakeResponse:
    def __init__(self, status, body=""):
        self.status = status
        self._body = body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def fetch_giving(outcome):
    def fetch(req, timeout=None):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return fetch


def http_error(code):
    return urllib.error.HTTPError("https://x.test/robots.txt", code, "x", {}, None)


class RobotsFailsClosed(unittest.TestCase):
    """Only a readable robots.txt that allows it, or none at all (404, 410),
    lets a visit go ahead."""

    def decide(self, outcome, url="https://x.test/page"):
        return cc.robots_decision(url, fetch=fetch_giving(outcome))

    def test_allowed_and_disallowed(self):
        ok = self.decide(FakeResponse(200, "User-agent: *\nDisallow: /private\n"))
        self.assertTrue(ok[0])
        no = self.decide(FakeResponse(200, "User-agent: *\nDisallow: /page\n"))
        self.assertFalse(no[0])

    def test_no_robots_txt_is_allowed(self):
        for code in (404, 410):
            self.assertTrue(self.decide(http_error(code))[0], code)

    def test_cannot_read_it_skips_the_page_and_says_why(self):
        for outcome, word in (
            (http_error(403), "403"),
            (http_error(500), "500"),
            (http_error(503), "503"),
            (http_error(429), "429"),
            (TimeoutError("timed out"), "TimeoutError"),
            (urllib.error.URLError("refused"), "URLError"),
            (FakeResponse(204), "204"),
        ):
            go, why = self.decide(outcome)
            self.assertFalse(go, word)
            self.assertIn(word, why)


class FakeBrowser:
    launches = []

    def __init__(self, user_data_dir=None, args=None, keep_switches=None, *, headful=False):
        self.profile = Path(user_data_dir)
        self.args = list(args or ())
        self.existed = self.profile.is_dir()
        self.quit_called = False
        FakeBrowser.launches.append(self)

    def get(self, url):
        self.url = url

    def run(self, js):
        if js is cc.PROBE_JS:
            return {"probe": True}
        return {"title": "t", "url": self.url, "origin": "1", "cf": False,
                "token": False, "text": "", "counts": {}}

    def screenshot(self, path):
        pass

    def quit(self):
        self.quit_called = True


class FreshProfiles(unittest.TestCase):
    def setUp(self):
        FakeBrowser.launches = []
        self.fake_drive = types.SimpleNamespace(Browser=FakeBrowser)
        self.out = Path(tempfile.mkdtemp(prefix="cc-test-"))
        self.addCleanup(cc.shutil.rmtree, self.out, True)

    def visit(self, probe=False, arm="on", seconds=0):
        page = {"url": "https://x.test/", "name": "x", "group": "ordinary",
                "kind": "interstitial"}
        drive = {"drive": self.fake_drive}
        with mock.patch.dict(sys.modules, drive), mock.patch.object(cc.time, "sleep"):
            return cc.visit_webdriver(page, arm, self.out, "chrome.exe", seconds,
                                      False, probe)

    def test_each_profile_is_new_and_outside_out(self):
        a = cc._new_profile("on")
        b = cc._new_profile("on")
        self.addCleanup(cc._drop_profile, a)
        self.addCleanup(cc._drop_profile, b)
        self.assertNotEqual(a, b)
        self.assertTrue((a / "Default").is_dir())
        self.assertNotIn(self.out, a.parents)

    def test_an_old_profile_folder_under_out_is_never_reused(self):
        old = self.out / "r0" / "x" / "on" / "profile" / "Default"
        old.mkdir(parents=True)
        (old / "Cookies").write_text("cf_clearance")
        self.visit()
        used = FakeBrowser.launches[0].profile
        self.assertFalse((used / "Default" / "Cookies").exists())
        self.assertTrue((old / "Cookies").exists())  # not ours to touch

    def test_profile_is_deleted_after_the_visit(self):
        self.visit(probe=True)
        self.assertEqual(len(FakeBrowser.launches), 2)
        for b in FakeBrowser.launches:
            self.assertTrue(b.existed)
            self.assertTrue(b.quit_called)
            self.assertFalse(b.profile.exists())

    def test_profile_is_deleted_when_the_visit_fails(self):
        with mock.patch.object(FakeBrowser, "get", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                self.visit()
        self.assertFalse(FakeBrowser.launches[0].profile.exists())

    def test_swiftshader_only_on_the_local_probe(self):
        self.visit(probe=True)
        probe, public = FakeBrowser.launches
        self.assertIn("--enable-unsafe-swiftshader", probe.args)
        self.assertEqual(probe.url, "about:blank")
        self.assertNotIn("--enable-unsafe-swiftshader", public.args)
        self.assertEqual(public.url, "https://x.test/")


class WebGlName(unittest.TestCase):
    """The patch reports the same Chrome-shaped name the tool tests with."""

    def test_patch_uses_the_realistic_name(self):
        patch = (PATCHES / "fingerprint-uniform.patch").read_text(encoding="utf-8")
        self.assertIn(f'String("{cc.REAL_GL_RENDERER}")', patch)
        self.assertIn(f'String("{cc.REAL_GL_VENDOR}")', patch)
        self.assertNotIn("ANGLE (generic)", patch)
        self.assertNotIn('String("Google Inc.")', patch)

    def test_smoke_expects_the_same_name(self):
        import smoke_fingerprint
        self.assertEqual(smoke_fingerprint.RENDERER, cc.REAL_GL_RENDERER)
        self.assertEqual(smoke_fingerprint.VENDOR, cc.REAL_GL_VENDOR)


if __name__ == "__main__":
    unittest.main()
