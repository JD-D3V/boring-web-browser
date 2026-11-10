#!/usr/bin/env python3
"""Source-level checks for the Release 3 security review fixes.

Nothing here needs the built browser: each test reads the source and pins
the shape of a fix. The real behaviour is run by the smoke tests named in
each docstring, in the next integration build.

Usage: python -m pytest boring-core/tools/tests/test_r3_security.py
"""

import re
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


if __name__ == "__main__":
    unittest.main()
