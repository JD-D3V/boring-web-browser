#!/usr/bin/env python3
"""Offline tests for smoke browser launch isolation and focus reporting."""

import ctypes
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import drive  # noqa: E402
import probe_focus  # noqa: E402
import smoke_all  # noqa: E402


class LaunchIsolationTest(unittest.TestCase):
    def setUp(self):
        patched = mock.patch.dict(os.environ)
        self.addCleanup(patched.stop)
        patched.start()
        os.environ.pop("BORING_ALLOW_HEADFUL", None)
        os.environ.pop("BORING_WINDOW_POSITION", None)
        winapi = mock.patch.object(ctypes, "windll", create=True)
        self.addCleanup(winapi.stop)
        self.lock = winapi.start().user32.LockSetForegroundWindow

    def test_webdriver_launches_headless_without_taking_global_lock(self):
        for args, env in (
            (None, {}),
            (["--headless=new"], {"BORING_WINDOW_POSITION": "40,40"}),
            (["headless=old"], {"BORING_ALLOW_HEADFUL": "1"}),
        ):
            with (
                self.subTest(args=args, env=env),
                mock.patch.dict(os.environ, env),
                mock.patch.object(drive.subprocess, "Popen") as start,
                mock.patch.object(drive.Browser, "_req") as req,
            ):
                start.return_value.poll.return_value = None
                req.return_value = {"value": {"sessionId": "test"}}
                with drive.Browser(args=args):
                    pass
                caps = next(
                    call.args[2]
                    for call in req.call_args_list
                    if call.args[:2] == ("POST", "/session")
                )
                chrome_args = caps["capabilities"]["alwaysMatch"]["goog:chromeOptions"][
                    "args"
                ]
                self.assertEqual(
                    ["--headless=new"],
                    [arg for arg in chrome_args if arg.startswith("--headless")],
                )
                self.lock.assert_not_called()

    def test_session_start_failure_terminates_the_owned_driver(self):
        with (
            mock.patch.object(drive.subprocess, "Popen") as start,
            mock.patch.object(drive.Browser, "_req") as req,
            self.assertRaisesRegex(RuntimeError, "session failed"),
        ):
            start.return_value.poll.return_value = None
            req.side_effect = [None, RuntimeError("session failed")]
            drive.Browser()
        start.return_value.terminate.assert_called_once()

    def test_session_delete_failure_terminates_the_owned_driver(self):
        with (
            mock.patch.object(drive.subprocess, "Popen") as start,
            mock.patch.object(drive.Browser, "_req") as req,
            self.assertRaisesRegex(RuntimeError, "session gone"),
        ):
            start.return_value.poll.return_value = None
            req.side_effect = [
                None,
                {"value": {"sessionId": "test"}},
                RuntimeError("session gone"),
            ]
            with drive.Browser():
                pass
        start.return_value.terminate.assert_called_once()

    def test_native_request_fails_before_starting_driver(self):
        os.environ["BORING_WINDOW_POSITION"] = "40,40"
        with (
            mock.patch.object(drive.subprocess, "Popen") as start,
            self.assertRaisesRegex(RuntimeError, "BORING_ALLOW_HEADFUL=1"),
        ):
            drive.Browser(headful=True)
        start.assert_not_called()

    def test_switch_terminator_is_rejected_before_starting_driver(self):
        with (
            mock.patch.object(drive.subprocess, "Popen") as start,
            self.assertRaisesRegex(ValueError, "switch name"),
        ):
            drive.Browser(args=["--", "--headless=new"])
        start.assert_not_called()

    def test_explicit_native_launch_preserves_visible_window_options(self):
        os.environ["BORING_ALLOW_HEADFUL"] = "1"
        os.environ["BORING_WINDOW_POSITION"] = "40,40"
        with (
            mock.patch.object(drive.subprocess, "Popen") as start,
            mock.patch.object(drive.Browser, "_req") as req,
        ):
            start.return_value.poll.return_value = None
            req.return_value = {"value": {"sessionId": "test"}}
            with drive.Browser(headful=True):
                pass
        caps = next(
            call.args[2]
            for call in req.call_args_list
            if call.args[:2] == ("POST", "/session")
        )
        chrome_args = caps["capabilities"]["alwaysMatch"]["goog:chromeOptions"]["args"]
        self.assertIn("--window-position=40,40", chrome_args)
        self.assertFalse(any(arg.startswith("--headless") for arg in chrome_args))
        self.lock.assert_not_called()

    def test_suite_reports_blocked_native_checks_as_incomplete(self):
        with (
            mock.patch.object(
                smoke_all,
                "CHECKS",
                [
                    ("native check", "smoke_tabs.py"),
                    ("headless check", "smoke_scam.py"),
                ],
            ),
            mock.patch.object(smoke_all.subprocess, "run") as run,
            mock.patch("builtins.print") as printed,
        ):
            run.return_value.returncode = 0
            self.assertEqual(smoke_all.main(), 1)
        run.assert_called_once()
        self.assertTrue(run.call_args.args[0][1].endswith("smoke_scam.py"))
        self.assertIn("blocked", str(printed.call_args_list).lower())


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
