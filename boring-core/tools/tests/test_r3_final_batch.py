#!/usr/bin/env python3
"""Source-level checks for the last product batch before Release 3 (ledger 105).

Nothing here needs the built browser. The real behaviour is checked by
smoke_final_batch.py on the 157 build.

Usage: python -m pytest boring-core/tools/tests/test_r3_final_batch.py
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
BORING = CORE / "components" / "boring"
PATCHES = CORE / "patches"


def read(p):
    return p.read_text(encoding="utf-8")


class GuestSettingsLinks(unittest.TestCase):
    """P2a. In a guest session our three Settings links are hidden, as on 154."""

    def test_links_hide_when_the_guest_overrides_leave_the_key_out(self):
        patch = read(PATCHES / "157" / "settings-menu-links.patch")
        for key in ("protection", "reading", "summaries"):
            self.assertIn(
                f'+            ?hidden="${{!!this.pageVisibility_ && '
                f'!this.pageVisibility_.{key}}}"',
                patch,
                key,
            )
            # The upstream helper hides only on false, which shows the link
            # to a guest because the guest overrides have no such key.
            self.assertNotIn(
                f"shouldHideMenuItem_(this.pageVisibility_?.{key})", patch, key
            )


class OffTheRecordSharedSwitches(unittest.TestCase):
    """P2b. A guest or incognito window cannot turn off secure DNS or updates."""

    def setUp(self):
        self.src = read(BORING / "protection" / "protection_ui.cc")

    def body(self, signature):
        start = self.src.index(signature)
        return self.src[start : self.src.index("\n  }\n", start)]

    def test_only_the_two_shared_kinds_count(self):
        self.assertIn(
            'return kind == "local_state" || kind == "updater";',
            self.body("static bool IsBrowserWideKind("),
        )

    def test_apply_refuses_before_it_changes_anything(self):
        body = self.body("void ApplyConnection(")
        refuse = body.index(
            "if (IsBrowserWideKind(*kind) && context->IsOffTheRecord())"
        )
        self.assertIn("return;", body[refuse : refuse + 120])
        self.assertLess(refuse, body.index("SetSecureDnsEnabled(on)"))
        self.assertLess(refuse, body.index("BrowserUpdater::SetAutomatic(on)"))

    def test_rows_say_so_and_cannot_be_switched(self):
        body = self.body("base::ListValue OwnConnections()")
        m = re.search(
            r"if \(can_switch && IsBrowserWideKind\(\*kind\) &&\s+"
            r"context->IsOffTheRecord\(\)\) \{\s+can_switch = false;\s+"
            r'detail = "Change this in a normal window.";',
            body,
        )
        self.assertTrue(m)
        self.assertLess(m.start(), body.index('row.Set("canSwitch", can_switch)'))


class NewTabEngineMenuNumbers(unittest.TestCase):
    """C6. The engine button rectangle from the page is saturated, not cast."""

    def test_no_plain_cast_of_page_numbers(self):
        src = read(BORING / "newtab" / "newtab_ui.cc")
        start = src.index("void HandleShowEngineMenu(")
        body = src[start : src.index("\n  }\n", start)]
        self.assertNotIn("static_cast<int>", body)
        self.assertEqual(body.count("base::saturated_cast<int>(args["), 4)
        self.assertIn('#include "base/numerics/safe_conversions.h"', src)


class Quad9AnnotationPolicy(unittest.TestCase):
    """The Quad9 check's traffic annotation says how policy reaches it."""

    def test_policy_text_is_written(self):
        src = read(BORING / "scam" / "quad9_block_checker.cc")
        self.assertNotIn("Not implemented yet", src)
        self.assertIn('"No policy of its own. It follows the secure DNS setting', src)
        self.assertIn("DnsOverHttpsMode and DnsOverHttpsTemplates", src)


class FolderCopyRewriteRules(unittest.TestCase):
    """Pass 3 S6 leftover. New #%# lines and $redirect, $csp, $replace
    network rules in a folder copy are flagged in the preview."""

    def test_rules_are_flagged(self):
        src = read(BORING / "folder_copy" / "folder_copy_settings.cc")
        start = src.index("Added AddsException(")
        body = src[start : src.index("\n}\n", start)]
        self.assertIn('line.find("#%#") != std::string::npos || rewrites', body)
        self.assertIn("const size_t options = line.rfind('$');", body)
        for word in ("redirect", "csp", "replace"):
            self.assertIn(f'line.find("{word}", options)', body)
        # A comment line is never a rule.
        self.assertIn('line.rfind("!", 0) != 0', body)


class NativeLaunchUserLevelPolicy(unittest.TestCase):
    """Pass 2 S4 leftover. On 157 a host started from the native side gets
    user-level hosts only when policy allows them, as the main path does."""

    def test_launcher_follows_the_policy(self):
        patch = read(PATCHES / "157" / "native-hosts-launch.patch")
        self.assertIn(
            "+  const MessagingDelegate::PolicyPermission permission =\n"
            "+      ChromeMessagingDelegate().IsNativeMessagingHostAllowed(profile, host_id);\n"
            "+  if (permission == MessagingDelegate::PolicyPermission::DISALLOW) {",
            patch,
        )
        self.assertIn("-          /* allow_user_level_hosts= */ true,", patch)
        self.assertIn(
            "+          /* allow_user_level_hosts= */ permission ==\n"
            "+              MessagingDelegate::PolicyPermission::ALLOW_ALL,",
            patch,
        )


if __name__ == "__main__":
    unittest.main()
