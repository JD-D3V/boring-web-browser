#!/usr/bin/env python3
"""Source checks for the guards around the Quad9 block warning.

The behaviour is run in the real browser by smoke_dns_warning.py; these
keep the lines that carry it from being dropped in an edit.

Usage: python -m unittest discover -s boring-core/tools/tests
"""

import os
import unittest

CORE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def source(*parts):
    with open(os.path.join(CORE, *parts), encoding="utf-8") as f:
        return f.read()


class Quad9Guards(unittest.TestCase):
    def test_the_dns_request_refuses_redirects(self):
        text = source("components", "boring", "scam", "quad9_block_checker.cc")
        self.assertIn(
            "request->redirect_mode = network::mojom::RedirectMode::kError;", text
        )

    def test_intranet_names_are_not_sent_to_quad9(self):
        text = source("components", "boring", "scam", "quad9_block_throttle.cc")
        self.assertIn("net::IsHostnameNonUnique(url.host())", text)

    def test_the_gate_wants_secure_mode_and_quad9_alone(self):
        text = source("chromium_src", "chrome", "browser", "boring", "privacy_bridge.cc")
        for needle in (
            "net::SecureDnsMode::kSecure",
            "ManagementMode::kNoOverride",
            "servers.size() == 1",
            "!state.dns_managed",
        ):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
