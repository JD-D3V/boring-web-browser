#!/usr/bin/env python3
"""Tests for ninja_guard.py and the ninja routing in joblock.py.

Fake ninja scripts and temp folders only, no real tree. The tree finder and
the PATH lookup are the real ones: the fakes sit where they look.

Usage:
  python -m unittest boring-core/tools/tests/test_ninja_guard.py -v
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import joblock  # noqa: E402
import ninja_guard  # noqa: E402


def make_fake_ninja(path: Path, version: str) -> Path:
    """A stand in that prints a version for --version and logs any other call."""
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = path.parent / "calls.txt"
    if sys.platform == "win32":
        path = path.with_suffix(".bat")
        path.write_text(
            "@echo off\r\n"
            'if "%~1"=="--version" goto ver\r\n'
            f'echo %*>>"{marker}"\r\n'
            "exit /b 0\r\n"
            f":ver\r\necho {version}\r\n",
            encoding="ascii",
        )
    else:
        path.write_text(
            f'#!/bin/sh\n[ "$1" = --version ] && {{ echo {version}; exit 0; }}\n'
            f'echo "$@" >> "{marker}"\n',
            encoding="ascii",
        )
        path.chmod(0o755)
    return path


def calls_of(fake: Path) -> list[str]:
    """The non-version calls the fake saw."""
    marker = fake.parent / "calls.txt"
    return marker.read_text().splitlines() if marker.exists() else []


class Tree:
    """A temp tree: <root>/src/out/Default, optional own ninja and log."""

    def __init__(self, root: Path):
        self.src = root / "src"
        self.out = self.src / "out" / "Default"
        self.out.mkdir(parents=True)

    def add_tree_ninja(self, version: str) -> Path:
        """The tree's own ninja, where the real finder looks for it."""
        return make_fake_ninja(self.src / "third_party" / "ninja" / "ninja", version)

    def add_path_ninja(self, version: str) -> Path:
        """A ninja on PATH, found by the real PATH lookup."""
        return make_fake_ninja(self.src / "bin" / "ninja", version)

    def write_log(self, header: str) -> None:
        (self.out / ".ninja_log").write_text(header + "\n1\t2\t3\tobj\tabc\n")

    def path_only(self, exe: Path):
        """Run with PATH holding only this fake's folder."""
        return mock.patch.dict(os.environ, {"PATH": str(exe.parent)})


class MappingTest(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(ninja_guard.log_version_for((1, 10)), 6)
        self.assertEqual(ninja_guard.log_version_for((1, 12)), 6)
        self.assertEqual(ninja_guard.log_version_for((1, 13)), 7)
        self.assertEqual(ninja_guard.log_version_for((2, 0)), 7)

    def test_parse_version(self):
        self.assertEqual(ninja_guard.parse_version("1.12.1\n"), (1, 12))
        self.assertEqual(ninja_guard.parse_version("1.13.2.git"), (1, 13))
        with self.assertRaises(ninja_guard.GuardError):
            ninja_guard.parse_version("not a version")


class HeaderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMP"))
        self.addCleanup(self._tmp.cleanup)
        self.log = Path(self._tmp.name) / ".ninja_log"

    def test_no_file(self):
        self.assertIsNone(ninja_guard.read_log_version(self.log))

    def test_empty_file(self):
        self.log.write_bytes(b"")
        self.assertIsNone(ninja_guard.read_log_version(self.log))

    def test_versions_read(self):
        for number in (6, 7):
            self.log.write_text(f"# ninja log v{number}\n0\t1\t2\ta\tb\n")
            self.assertEqual(ninja_guard.read_log_version(self.log), number)

    def test_crlf_header(self):
        self.log.write_bytes(b"# ninja log v6\r\n")
        self.assertEqual(ninja_guard.read_log_version(self.log), 6)

    def test_garbage_header(self):
        self.log.write_text("hello\n")
        with self.assertRaises(ninja_guard.GuardError):
            ninja_guard.read_log_version(self.log)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMP"))
        self.addCleanup(self._tmp.cleanup)
        self.tree = Tree(Path(self._tmp.name))

    def test_tree_ninja_with_a_version_6_log_passes(self):
        own = self.tree.add_tree_ninja("1.12.1")
        newer = self.tree.add_path_ninja("1.13.2")
        self.tree.write_log("# ninja log v6")
        with self.tree.path_only(newer):
            self.assertEqual(ninja_guard.guard(self.tree.out), own)

    def test_no_log_passes_even_with_a_newer_ninja(self):
        newer = self.tree.add_path_ninja("1.13.2")
        with self.tree.path_only(newer):
            self.assertEqual(ninja_guard.guard(self.tree.out), newer)

    def test_older_tree_with_a_version_7_log_and_path_ninja_passes(self):
        newer = self.tree.add_path_ninja("1.13.2")
        self.tree.write_log("# ninja log v7")
        self.assertIsNone(ninja_guard.tree_ninja(self.tree.out))
        with self.tree.path_only(newer):
            self.assertEqual(ninja_guard.guard(self.tree.out), newer)

    def test_path_ninja_against_a_version_6_log_is_refused(self):
        newer = self.tree.add_path_ninja("1.13.2")
        self.tree.write_log("# ninja log v6")
        before = (self.tree.out / ".ninja_log").read_bytes()
        with (
            self.tree.path_only(newer),
            self.assertRaises(ninja_guard.GuardError) as ctx,
        ):
            ninja_guard.guard(self.tree.out)
        message = str(ctx.exception)
        self.assertNotIn("\n", message)
        self.assertIn("version 7", message)
        self.assertIn("version 6", message)
        self.assertEqual((self.tree.out / ".ninja_log").read_bytes(), before)

    def test_old_ninja_against_a_version_7_log_is_refused(self):
        older = self.tree.add_path_ninja("1.12.1")
        self.tree.write_log("# ninja log v7")
        with self.tree.path_only(older), self.assertRaises(ninja_guard.GuardError):
            ninja_guard.guard(self.tree.out)

    def test_read_only_call_is_not_refused(self):
        newer = self.tree.add_path_ninja("1.13.2")
        self.tree.write_log("# ninja log v6")
        with self.tree.path_only(newer):
            for args in (
                ["-C", "out", "-t", "commands", "-s", "x.obj"],
                ["-t", "targets", "all"],
                ["-tgraph"],
                ["--version"],
            ):
                with self.subTest(args=args):
                    self.assertEqual(ninja_guard.guard(self.tree.out, args), newer)
            for args in (["-n"], ["-t", "clean"], ["chrome"], ["-t", "deps"]):
                with self.subTest(args=args), self.assertRaises(ninja_guard.GuardError):
                    ninja_guard.guard(self.tree.out, args)

    def test_log_older_than_6_with_an_older_ninja_is_not_refused(self):
        older = self.tree.add_path_ninja("1.9.0")
        for header in ("# ninja log v5", "# ninja log v4"):
            self.tree.write_log(header)
            with self.subTest(header=header), self.tree.path_only(older):
                self.assertEqual(ninja_guard.guard(self.tree.out), older)

    def test_log_older_than_6_with_ninja_1_13_is_refused(self):
        newer = self.tree.add_path_ninja("1.13.2")
        self.tree.write_log("# ninja log v5")
        with self.tree.path_only(newer), self.assertRaises(ninja_guard.GuardError):
            ninja_guard.guard(self.tree.out)

    def test_nothing_anywhere(self):
        with (
            mock.patch.dict(os.environ, {"PATH": str(self.tree.src)}),
            self.assertRaises(ninja_guard.GuardError),
        ):
            ninja_guard.choose_ninja(self.tree.out)


class OpensLogTest(unittest.TestCase):
    def test_calls(self):
        self.assertTrue(ninja_guard.opens_log([]))
        self.assertTrue(ninja_guard.opens_log(["-C", "out", "chrome"]))
        self.assertTrue(ninja_guard.opens_log(["-n", "chrome"]))
        self.assertTrue(ninja_guard.opens_log(["-t", "clean"]))
        self.assertFalse(ninja_guard.opens_log(["-t", "commands", "-s", "x"]))
        self.assertFalse(ninja_guard.opens_log(["-tcommands"]))
        self.assertFalse(ninja_guard.opens_log(["--version"]))


class MainTest(unittest.TestCase):
    def test_exit_codes(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMP")) as raw:
            tree = Tree(Path(raw))
            exe = tree.add_path_ninja("1.13.2")
            tree.write_log("# ninja log v6")
            with (
                tree.path_only(exe),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(ninja_guard.main([str(tree.out)]), 1)
                (tree.out / ".ninja_log").unlink()
                self.assertEqual(ninja_guard.main([str(tree.out)]), 0)
                self.assertEqual(ninja_guard.main([]), 2)


class JoblockRoutingTest(unittest.TestCase):
    """joblock.py -- ninja ... must reach the guard, not the PATH ninja."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMP"))
        self.addCleanup(self._tmp.cleanup)
        self.tree = Tree(Path(self._tmp.name))
        self.lock = str(Path(self._tmp.name) / "test.lock")

    def run_main(self, *command: str) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = joblock.main(["--lock-file", self.lock, "--", *command])
        return code, err.getvalue()

    def test_bare_ninja_is_rerouted_to_the_tree_ninja(self):
        own = self.tree.add_tree_ninja("1.12.1")
        newer = self.tree.add_path_ninja("1.13.2")
        self.tree.write_log("# ninja log v6")
        with self.tree.path_only(newer):
            code, _ = self.run_main("ninja", "-C", str(self.tree.out), "chrome")
        self.assertEqual(code, 0)
        self.assertEqual(calls_of(own), [f"-C {self.tree.out} chrome"])
        self.assertEqual(calls_of(newer), [])

    def test_bare_ninja_that_clashes_is_refused_and_not_run(self):
        newer = self.tree.add_path_ninja("1.13.2")
        self.tree.write_log("# ninja log v6")
        with self.tree.path_only(newer):
            code, err = self.run_main("ninja", "-C", str(self.tree.out), "-n", "chrome")
        self.assertEqual(code, 1)
        self.assertIn("refusing to run", err)
        self.assertEqual(calls_of(newer), [])

    def test_ninja_named_by_path_is_checked_too(self):
        newer = self.tree.add_path_ninja("1.13.2")
        self.tree.write_log("# ninja log v6")
        code, err = self.run_main(str(newer), "-C", str(self.tree.out), "chrome")
        self.assertEqual(code, 1)
        self.assertIn("refusing to run", err)
        self.assertEqual(calls_of(newer), [])

    def test_read_only_call_runs(self):
        newer = self.tree.add_path_ninja("1.13.2")
        self.tree.write_log("# ninja log v6")
        with self.tree.path_only(newer):
            code, _ = self.run_main(
                "ninja", f"-C{self.tree.out}", "-t", "commands", "x.obj"
            )
        self.assertEqual(code, 0)
        self.assertEqual(len(calls_of(newer)), 1)

    def test_other_commands_are_left_alone(self):
        self.assertEqual(joblock.route_ninja(["python", "-V"]), ["python", "-V"])
        self.assertEqual(
            joblock.route_ninja(["ninja157.bat", "x"]), ["ninja157.bat", "x"]
        )


if __name__ == "__main__":
    unittest.main()
