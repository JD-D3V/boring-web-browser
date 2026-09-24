#!/usr/bin/env python3
"""Checks that renaming the product never renames the project.

Offline. Run with: python -m unittest discover -s boring-core/tools/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rebrand import (  # noqa: E402
    MISSING_BRANDED_MESSAGES,
    NAME,
    add_missing_messages,
    check_attribution,
    rename_product,
)

BRANDED = "chrome/app/chromium_strings.grd"

GRD = """<?xml version="1.0" encoding="UTF-8"?>
<grit latest_public_release="0" current_release="1">
  <release seq="1">
    <messages fallback_to_english="true">
      <message name="IDS_PRODUCT_NAME" desc="The name.">
        Chromium
      </message>
    </messages>
  </release>
</grit>
"""

# The About page credit, exactly as Chromium writes it.
ABOUT_CREDIT = (
    "Chromium is made possible by the "
    '<ph name="BEGIN_LINK_CHROMIUM">&lt;a target="_blank" href="$1" '
    'aria-description="$3"&gt;</ph>Chromium<ph name="END_LINK_CHROMIUM">'
    "&lt;/a&gt;</ph> open source project and other "
    '<ph name="BEGIN_LINK_OSS">&lt;a target="_blank" href="$2" '
    'aria-description="$3"&gt;</ph>open source software'
    '<ph name="END_LINK_OSS">&lt;/a&gt;</ph>.'
)

SHORT_CREDIT = (
    "Chromium is made possible by the "
    '<ph name="BEGIN_LINK_CHROMIUM">&lt;a target="_blank" href="$1"&gt;</ph>'
    'Chromium<ph name="END_LINK_CHROMIUM">&lt;/a&gt;</ph> open source project.'
)

COPYRIGHT = (
    '<message name="IDS_ABOUT_VERSION_COMPANY_NAME" desc="Company name">\n'
    "  The Chromium Authors\n"
    "</message>"
)


class RenameKeepsTheCredit(unittest.TestCase):
    def test_about_credit_names_us_and_credits_chromium(self):
        out = rename_product(ABOUT_CREDIT)
        self.assertTrue(out.startswith(f"{NAME} is made possible by the "))
        self.assertIn('</ph>Chromium<ph name="END_LINK_CHROMIUM">', out)
        self.assertIn("open source project", out)
        self.assertNotIn(f"</ph>{NAME}<ph", out)

    def test_short_credit_too(self):
        out = rename_product(SHORT_CREDIT)
        self.assertEqual(
            out,
            SHORT_CREDIT.replace("Chromium is made", f"{NAME} is made", 1),
        )

    def test_copyright_holder_is_left_alone(self):
        self.assertEqual(rename_product(COPYRIGHT), COPYRIGHT)

    def test_project_in_a_description_is_left_alone(self):
        text = 'desc="The link to the Chromium project."'
        self.assertEqual(rename_product(text), text)

    def test_chromiumos_is_not_our_product(self):
        text = "ChromiumOS is made possible by additional open source software."
        self.assertEqual(rename_product(text), text)

    def test_ordinary_product_mentions_are_renamed(self):
        self.assertEqual(
            rename_product("Relaunch Chromium? Chromium is up to date."),
            f"Relaunch {NAME}? {NAME} is up to date.",
        )

    def test_the_guard_catches_a_lost_credit(self):
        before = SHORT_CREDIT
        after = before.replace("Chromium", NAME)  # the old, wrong rename
        with self.assertRaises(SystemExit):
            check_attribution("components_chromium_strings.grd", before, after)

    def test_the_guard_passes_the_real_rename(self):
        before = ABOUT_CREDIT
        check_attribution("x", before, rename_product(before))

    def test_a_missing_branded_string_is_added_once(self):
        name = MISSING_BRANDED_MESSAGES[0][0]
        self.assertNotIn(name, GRD)
        out = add_missing_messages(BRANDED, GRD)
        self.assertEqual(out.count(f'name="{name}"'), 1)
        # Inside the messages block, not after it.
        self.assertLess(out.index(name), out.index("    </messages>"))

    def test_the_added_string_is_renamed_like_every_other(self):
        # The entries are written with the product still called Chromium
        # so the rename reaches them. Checked against whatever is in the
        # list rather than one string, because the list changes as
        # upstream fixes things.
        body = MISSING_BRANDED_MESSAGES[0][2]
        self.assertIn("Chromium", body)
        out = rename_product(add_missing_messages(BRANDED, GRD))
        self.assertIn(body.replace("Chromium", NAME), out)
        self.assertNotIn(body, out)

    def test_it_is_not_added_twice(self):
        once = add_missing_messages(BRANDED, GRD)
        twice = add_missing_messages(BRANDED, once)
        self.assertEqual(once, twice)

    def test_other_files_are_left_alone(self):
        text = "<grit>\n    </messages>\n</grit>\n"
        self.assertEqual(
            add_missing_messages("components/components_chromium_strings.grd", text),
            text,
        )

    def test_nowhere_to_put_it_is_refused_not_guessed(self):
        with self.assertRaises(SystemExit):
            add_missing_messages(BRANDED, "<grit>no messages block</grit>")

    def test_the_addition_does_not_disturb_the_credit_check(self):
        before = GRD
        after = rename_product(add_missing_messages(BRANDED, before))
        check_attribution(BRANDED, before, after)

    def test_running_it_twice_changes_nothing_more(self):
        once = rename_product(ABOUT_CREDIT)
        self.assertEqual(rename_product(once), once)


if __name__ == "__main__":
    unittest.main()
