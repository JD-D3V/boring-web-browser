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


if __name__ == "__main__":
    unittest.main()
