#!/usr/bin/env python3
"""Offline tests for focus_lock.py (keeps test browsers off the foreground)
and the report in probe_focus.py (which shows whether they stayed off).

Usage:
  python -m unittest discover -s boring-core/tools/tests
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import drive  # noqa: E402
import focus_lock  # noqa: E402
import probe_focus  # noqa: E402


class FocusLockTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("BORING_WINDOW_POSITION", None)
        patched = mock.patch.object(focus_lock, "_lock")
        self.lock = patched.start()
        self.addCleanup(patched.stop)
        self.assertEqual(focus_lock._holders, 0)

    def test_locked_before_hold_returns_and_unlocked_on_release(self):
        h = focus_lock.hold()
        self.assertEqual(self.lock.call_args_list[0], mock.call(focus_lock.LSFW_LOCK))
        h.release()
        self.assertEqual(
            self.lock.call_args_list[-1], mock.call(focus_lock.LSFW_UNLOCK)
        )
        self.assertEqual(focus_lock._holders, 0)

    def test_nested_holds_unlock_once_after_the_last(self):
        a, b = focus_lock.hold(), focus_lock.hold()
        a.release()
        self.assertNotIn(mock.call(focus_lock.LSFW_UNLOCK), self.lock.call_args_list)
        b.release()
        unlocks = self.lock.call_args_list.count(mock.call(focus_lock.LSFW_UNLOCK))
        self.assertEqual(unlocks, 1)

    def test_releasing_twice_is_harmless(self):
        a, b = focus_lock.hold(), focus_lock.hold()
        a.release()
        a.release()
        self.assertEqual(focus_lock._holders, 1)
        b.release()
        self.assertEqual(focus_lock._holders, 0)

    def test_with_block_releases_when_the_body_fails(self):
        with self.assertRaises(ValueError), focus_lock.hold():
            raise ValueError("boom")
        self.assertEqual(focus_lock._holders, 0)

    def test_asked_again_while_held_because_a_click_drops_the_lock(self):
        with (
            mock.patch.object(focus_lock, "REASSERT_SECONDS", 0.01),
            focus_lock.hold(),
        ):
            time.sleep(0.15)
            locks = self.lock.call_args_list.count(mock.call(focus_lock.LSFW_LOCK))
        self.assertGreater(locks, 3)

    def test_watching_on_purpose_locks_nothing(self):
        os.environ["BORING_WINDOW_POSITION"] = "40,40"
        with focus_lock.hold():
            pass
        self.lock.assert_not_called()
        self.assertEqual(focus_lock._holders, 0)


class BrowserHoldsTheForegroundTest(unittest.TestCase):
    """drive.Browser must give the foreground back however it ends."""

    def setUp(self):
        patched = mock.patch.object(focus_lock, "_lock")
        patched.start()
        self.addCleanup(patched.stop)

    def test_a_browser_that_fails_to_start_does_not_leave_the_lock_held(self):
        with (
            mock.patch.object(drive, "free_port", side_effect=OSError("no port")),
            self.assertRaises(OSError),
        ):
            drive.Browser()
        self.assertEqual(focus_lock._holders, 0)

    def test_quit_gives_the_foreground_back_even_if_the_session_delete_fails(self):
        b = drive.Browser.__new__(drive.Browser)
        b._focus = focus_lock.hold()
        b.sid, b.proc = "s", mock.Mock()
        with (
            mock.patch.object(b, "_req", side_effect=RuntimeError("gone")),
            self.assertRaises(RuntimeError),
        ):
            b.quit()
        self.assertEqual(focus_lock._holders, 0)
        b.proc.terminate.assert_called_once()


class ProbeReportTest(unittest.TestCase):
    def test_a_run_that_never_fronts_our_window_leaves_the_foreground_unchanged(self):
        changes = [probe_focus.Change(1.2, "Mail", "mail.exe", False)]
        text, took = probe_focus.report("'Claude'", changes, "'Mail'", 0)
        self.assertFalse(took)
        self.assertIn("foreground unchanged", text)

    def test_a_run_that_fronts_our_window_is_reported_as_taking_the_focus(self):
        changes = [
            probe_focus.Change(0.4, "New Tab - Boring Browser", "chrome.exe", True)
        ]
        text, took = probe_focus.report("'Claude'", changes, "'Claude'", 0)
        self.assertTrue(took)
        self.assertIn("took the focus", text)
        self.assertIn("OURS", text)

    def test_no_changes_at_all(self):
        text, took = probe_focus.report("'Claude'", [], "'Claude'", 0)
        self.assertFalse(took)
        self.assertIn("none", text)


if __name__ == "__main__":
    unittest.main()
