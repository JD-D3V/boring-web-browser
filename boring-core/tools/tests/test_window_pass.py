#!/usr/bin/env python3
"""The real-window pass lists what it must, and its dry run starts nothing."""

import datetime
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import capture_r3_pass  # noqa: E402
import run_window_pass  # noqa: E402
import smoke_all  # noqa: E402

OUT = Path("E:/tmp/r3-window-pass-test")


def steps():
    return run_window_pass.build_steps(OUT, 90)


def scripts(step):
    return [Path(argv[0]).name for argv in step.commands]


class PlanTest(unittest.TestCase):
    def test_every_script_exists(self):
        for step in steps():
            for argv in step.commands:
                self.assertTrue(Path(argv[0]).exists(), argv[0])

    def test_ids_are_unique(self):
        ids = [s.id for s in steps()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_seven_real_window_smokes_are_all_in_the_pass(self):
        planned = {name for s in steps() for name in scripts(s)}
        self.assertEqual(smoke_all.NATIVE_CHECKS - planned, set())

    def test_takeover_net_audit_and_apps_rows_are_in_the_pass(self):
        planned = {name for s in steps() for name in scripts(s)}
        for name in ("smoke_takeover.py", "smoke_apps_rows.py", "net_audit.py"):
            self.assertIn(name, planned)

    def test_net_audit_runs_every_scenario(self):
        (step,) = [s for s in steps() if s.id.startswith("4-")]
        self.assertIn("--all", step.commands[0])

    def test_update_test_is_not_run_on_this_machine(self):
        (step,) = [s for s in steps() if s.id.startswith("6b-")]
        self.assertTrue(step.info_only)
        self.assertEqual(step.commands[0][1:], ["--list"])

    def test_only_the_takeover_step_is_marked_fullscreen(self):
        self.assertEqual([s.id for s in steps() if s.takeover], ["2-takeover"])

    def test_tools_that_get_help_parse_arguments(self):
        # `--help` on a smoke without argparse would start the test.
        for name in run_window_pass.ARGPARSE_TOOLS:
            text = (TOOLS / name).read_text(encoding="utf-8")
            self.assertIn("argparse", text, name)


class PicturesTest(unittest.TestCase):
    def test_both_schemes_for_every_picture(self):
        files = [name for _, name in capture_r3_pass.plan(capture_r3_pass.GROUPS)]
        self.assertEqual(len(files), len(set(files)))
        for name in files:
            self.assertTrue(name.endswith(("-light.png", "-dark.png")), name)
        self.assertEqual(
            len([f for f in files if f.endswith("-light.png")]),
            len([f for f in files if f.endswith("-dark.png")]),
        )

    def test_the_tab_states_cover_shape_underline_and_pinned_separator(self):
        names = {name for name, *_ in capture_r3_pass.TAB_STATES}
        self.assertIn("tabs-plain", names)
        self.assertIn("tabs-pinned-plain-active", names)
        self.assertIn("tabs-pinned-pinned-active", names)

    def test_every_settings_page_named_in_the_patch_notes_is_taken(self):
        urls = {url for _, url, _ in capture_r3_pass.WEBUI_PAGES}
        for page in (
            "protection",
            "reading",
            "summaries",
            "autofill",
            "payments",
            "onStartup",
            "searchEngines",
            "performance",
            "appearance",
        ):
            self.assertIn(f"chrome://settings/{page}", urls)


class RunStepTest(unittest.TestCase):
    """The runner's own bookkeeping, with steps that start no browser."""

    def run_fake(self, code, timeout=60, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "logs").mkdir()
            step = run_window_pass.Step("t", "fake", [["-c", code]], timeout, "", **kw)
            ctx = {
                "logs": out / "logs",
                "build": out,
                "env": dict(os.environ),
                "probe": False,
                "current": None,
                "version": "x",
                "started": datetime.datetime.now(),
                "tools": "t",
                "all_steps": [step],
                "out": out,
            }
            result = run_window_pass.run_step(step, ctx)
            run_window_pass.write_summary(out / "S.txt", ctx, [result], "test")
            return result, (out / "S.txt").read_text(encoding="utf-8")

    def test_exit_zero_is_a_pass(self):
        result, _ = self.run_fake("print('PASS: a')")
        self.assertEqual(result.status, "PASS")

    def test_a_skip_is_said_in_the_word_and_kept_in_the_summary(self):
        result, text = self.run_fake(
            "print('PASS: a'); print('SKIP: b')", detail=(r"^SKIP",)
        )
        self.assertEqual(result.status, "PASS+SKIP")
        self.assertIn("SKIP: b", text)

    def test_a_non_zero_exit_is_a_fail(self):
        result, _ = self.run_fake("import sys; print('FAIL: a'); sys.exit(1)")
        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.counts, "0 pass, 1 fail, 0 skip")

    def test_a_stuck_step_is_killed_at_its_limit(self):
        result, _ = self.run_fake("import time; time.sleep(60)", timeout=2)
        self.assertEqual(result.status, "TIMEOUT")

    def test_an_info_step_is_never_a_pass(self):
        result, _ = self.run_fake("print('case: x')", info_only=True)
        self.assertEqual(result.status, "NOT RUN")


class DryRunTest(unittest.TestCase):
    def test_dry_run_prints_every_step_and_starts_nothing(self):
        r = subprocess.run(
            [
                sys.executable,
                str(TOOLS / "run_window_pass.py"),
                "--dry-run",
                "--out",
                str(OUT),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for step in steps():
            self.assertIn(f"[{step.id}]", r.stdout)
        self.assertFalse(OUT.exists(), "a dry run must not create the results folder")


if __name__ == "__main__":
    unittest.main()
