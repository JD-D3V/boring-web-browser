#!/usr/bin/env python3
"""Source-level checks for the Release 3 security review fixes.

Nothing here needs the built browser: each test reads the source and pins
the shape of a fix. The real behaviour is run by the smoke tests named in
each docstring, in the next integration build.

Usage: python -m pytest boring-core/tools/tests/test_r3_security.py
"""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
BORING = CORE / "components" / "boring"
PATCHES = CORE / "patches"
TOOLS = CORE / "tools"


def read(p):
    return p.read_text(encoding="utf-8")


class WebGpuAdapterInfo(unittest.TestCase):
    """Item 54. smoke_fingerprint.py reads navigator.gpu in the build."""

    def test_patch_blanks_vendor_and_architecture(self):
        patch = read(PATCHES / "fingerprint-uniform.patch")
        self.assertIn("modules/webgpu/gpu_adapter.cc", patch)
        self.assertIn("generic ? g_empty_string : vendor_", patch)
        self.assertIn("generic ? g_empty_string : architecture_", patch)
        self.assertIn("FingerprintingClientRectsNoiseEnabled", patch)

    def test_smoke_checks_the_adapter_info(self):
        smoke = read(TOOLS / "smoke_fingerprint.py")
        self.assertIn("navigator.gpu", smoke)
        self.assertIn("webgpu: vendor and architecture are blank", smoke)


class GuardTestHooks(unittest.TestCase):
    """Item 61. smoke_scam_guards.py checks a non-localhost page."""

    def test_hooks_only_act_on_localhost_pages(self):
        for name in ("guard_infobar.cc", "clipboard_guard.cc"):
            text = read(BORING / "guards" / name)
            self.assertIn("net::IsLocalhost(", text, name)
            self.assertIn('#include "net/base/url_util.h"', text, name)
        # The check sits in the same condition as the switch, so a switch
        # alone is not enough.
        bar = read(BORING / "guards" / "guard_infobar.cc")
        self.assertRegex(
            bar,
            r"HasSwitch\(kTestAnswerSwitch\)\s*&&\s*net::IsLocalhost\(",
        )
        clip = read(BORING / "guards" / "clipboard_guard.cc")
        after_switch = clip.split("kTestClipboardSwitch)) {", 1)[1]
        self.assertLess(
            after_switch.index("IsLocalhost"), after_switch.index("CheckClipboardCopy")
        )

    def test_smoke_drives_a_remote_page(self):
        smoke = read(TOOLS / "smoke_scam_guards.py")
        self.assertIn("not localhost: nothing answers the bar", smoke)


class NativeLaunchPath(unittest.TestCase):
    """Item 62. The launch-from-native path asks the same delegate check."""

    def test_patch_asks_the_delegate_before_launching(self):
        patch = read(PATCHES / "native-hosts-launch.patch")
        files = re.findall(r"^\+\+\+ b/(\S+)", patch, re.M)
        self.assertEqual(
            files,
            ["chrome/browser/extensions/api/messaging/native_messaging_launch_from_native.cc"],
        )
        self.assertIn("ChromeMessagingDelegate().IsNativeMessagingHostAllowed(", patch)
        self.assertIn("PolicyPermission::DISALLOW", patch)
        # The check comes before the host is created.
        self.assertLess(patch.index("DISALLOW"), patch.index("const extensions::PortId"))

    def test_patch_is_in_the_series_after_the_delegate_patch(self):
        series = read(PATCHES / "series").split()
        self.assertEqual(series.count("native-hosts-launch.patch"), 1)
        self.assertLess(
            series.index("native-hosts-check.patch"),
            series.index("native-hosts-launch.patch"),
        )


class ScamClickThrough(unittest.TestCase):
    """Item 65. smoke_scam.py clicks through, turns the switch on, reloads."""

    def test_the_switch_wins_over_the_session_allow_list(self):
        cc = read(BORING / "scam" / "scam_service.cc")
        body = cc.split("bool ScamService::ShouldBlock(", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("kNoScamBypass", body)
        # Read before the allow-list is used.
        self.assertLess(body.index("kNoScamBypass"), body.index("hosts.count(host)"))
        self.assertIn("hosts.clear()", body)

    def test_smoke_checks_it(self):
        self.assertIn(
            "turning the switch on clears an earlier Continue anyway",
            read(TOOLS / "smoke_scam.py"),
        )


class TakeoverSiteName(unittest.TestCase):
    """Item 66. smoke_takeover.py reads the page with a host and with text."""

    def script(self):
        cc = read(BORING / "scam" / "takeover" / "takeover_ui.cc")
        return cc.split('R"SCRIPT(', 1)[1].split(')SCRIPT"', 1)[0]

    def test_only_a_host_is_shown(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("no node here")
        script = self.script()
        # Run the page's own lines against a fake page for each address.
        harness = """
const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = input.cases.map(function(q) {
  const el = {hidden: true, textContent: ''};
  const location = {search: '?site=' + encodeURIComponent(q)};
  const document = {getElementById: function(id) {
    return id === 'site' ? el : {addEventListener: function() {}}; }};
  const chrome = {send: function() {}};
  new Function('location', 'document', 'chrome', input.src)(location, document, chrome);
  return !el.hidden;
});
console.log(JSON.stringify(out));
"""
        shown = ["example.com", "a-b.co.uk", "192.168.0.1", "[::1]", "[2001:db8::1]", "xn--e1afmkfd.xn--p1ai"]
        hidden = [
            "Call Microsoft on 0800 123 456",
            "call-now.example.com/ ",
            "x" * 254,
            "<b>hi</b>",
            "example.com:8080",
            "",
        ]
        cases = shown + hidden
        done = subprocess.run(
            [node, "-e", harness],
            input=json.dumps({"src": script, "cases": cases}),
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        got = json.loads(done.stdout)
        self.assertEqual(got, [True] * len(shown) + [False] * len(hidden))

    def test_smoke_checks_it(self):
        self.assertIn("free text in ?site= is not shown", read(TOOLS / "smoke_takeover.py"))


if __name__ == "__main__":
    unittest.main()
