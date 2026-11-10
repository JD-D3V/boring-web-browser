#!/usr/bin/env python3
"""smoke_all.py lists every smoke_*.py, or names it as left out."""

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import smoke_all  # noqa: E402


class SmokeAllListsEverythingTest(unittest.TestCase):
    def test_every_smoke_file_is_listed_or_left_out(self):
        on_disk = {p.name for p in TOOLS.glob("smoke_*.py")}
        listed = {script for _, script in smoke_all.CHECKS}
        self.assertEqual(on_disk - listed - set(smoke_all.LEFT_OUT), set())

    def test_every_listed_check_exists(self):
        for _, script in smoke_all.CHECKS:
            self.assertTrue((TOOLS / script).exists(), script)

    def test_no_check_is_listed_twice_or_also_left_out(self):
        scripts = [script for _, script in smoke_all.CHECKS]
        self.assertEqual(len(scripts), len(set(scripts)))
        self.assertEqual(set(scripts) & set(smoke_all.LEFT_OUT), set())

    def test_left_out_files_have_a_reason(self):
        for name, reason in smoke_all.LEFT_OUT.items():
            self.assertTrue(reason.strip(), name)
