#!/usr/bin/env python3
"""Tests for ninja_guard.py. Fake ninjas and temp folders only, no real tree.

Usage:
  python -m unittest boring-core/tools/tests/test_ninja_guard.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import ninja_guard  # noqa: E402

TREE_NAME = "ninja.exe" if sys.platform == "win32" else "ninja"


def make_fake_ninja(path: Path, version: str) -> Path:
    """A stand in that prints a version for --version and nothing else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        path = path.with_suffix(".bat")
        path.write_text(f"@echo {version}\r\n", encoding="ascii")
    else:
        path.write_text(f"#!/bin/sh\necho {version}\n", encoding="ascii")
        path.chmod(0o755)
    return path


class Tree:
    """A temp tree: <root>/src/out/Default, optional own ninja and log."""

    def __init__(self, root: Path):
        self.src = root / "src"
        self.out = self.src / "out" / "Default"
        self.out.mkdir(parents=True)

    def add_tree_ninja(self, version: str) -> Path:
        return make_fake_ninja(self.src / "third_party" / "ninja" / "fake", version)

    def write_log(self, header: str) -> None:
        (self.out / ".ninja_log").write_text(header + "\n1\t2\t3\tobj\tabc\n")


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

    def finder_sees(self, exe: Path):
        """Make choose_ninja treat this fake as the tree's own ninja."""
        return mock.patch.object(ninja_guard, "tree_ninja", return_value=exe)

    def test_matching_versions_allowed(self):
        exe = self.tree.add_tree_ninja("1.12.1")
        self.tree.write_log("# ninja log v6")
        with self.finder_sees(exe):
            self.assertEqual(ninja_guard.guard(self.tree.out), exe)

    def test_mismatch_refused_with_one_line(self):
        exe = make_fake_ninja(self.tree.src / "bin" / "ninja", "1.13.2")
        self.tree.write_log("# ninja log v6")
        with (
            mock.patch.object(ninja_guard, "tree_ninja", return_value=None),
            mock.patch.object(ninja_guard.shutil, "which", return_value=str(exe)),
            self.assertRaises(ninja_guard.GuardError) as ctx,
        ):
            ninja_guard.guard(self.tree.out)
        message = str(ctx.exception)
        self.assertNotIn("\n", message)
        self.assertIn("version 7", message)
        self.assertIn("version 6", message)

    def test_refusal_leaves_the_log_alone(self):
        exe = make_fake_ninja(self.tree.src / "bin" / "ninja", "1.13.2")
        self.tree.write_log("# ninja log v6")
        before = (self.tree.out / ".ninja_log").read_bytes()
        with (
            mock.patch.object(ninja_guard, "tree_ninja", return_value=None),
            mock.patch.object(ninja_guard.shutil, "which", return_value=str(exe)),
            self.assertRaises(ninja_guard.GuardError),
        ):
            ninja_guard.guard(self.tree.out)
        self.assertEqual((self.tree.out / ".ninja_log").read_bytes(), before)

    def test_no_log_allowed_even_with_newer_ninja(self):
        exe = make_fake_ninja(self.tree.src / "bin" / "ninja", "1.13.2")
        with (
            mock.patch.object(ninja_guard, "tree_ninja", return_value=None),
            mock.patch.object(ninja_guard.shutil, "which", return_value=str(exe)),
        ):
            self.assertEqual(ninja_guard.guard(self.tree.out), exe)

    def test_prefers_the_tree_ninja_over_path(self):
        own = self.tree.add_tree_ninja("1.12.1")
        path_one = make_fake_ninja(self.tree.src / "bin" / "ninja", "1.13.2")
        self.tree.write_log("# ninja log v6")
        with (
            self.finder_sees(own),
            mock.patch.object(ninja_guard.shutil, "which", return_value=str(path_one)),
        ):
            self.assertEqual(ninja_guard.choose_ninja(self.tree.out), own)
            self.assertEqual(ninja_guard.guard(self.tree.out), own)

    def test_falls_back_to_path_without_a_tree_ninja(self):
        path_one = make_fake_ninja(self.tree.src / "bin" / "ninja", "1.12.1")
        self.tree.write_log("# ninja log v6")
        # No third_party/ninja in the temp tree, so the real finder says None.
        self.assertIsNone(ninja_guard.tree_ninja(self.tree.out))
        with mock.patch.object(ninja_guard.shutil, "which", return_value=str(path_one)):
            self.assertEqual(ninja_guard.guard(self.tree.out), path_one)

    def test_real_finder_sees_a_tree_ninja(self):
        placed = self.tree.src / "third_party" / "ninja" / TREE_NAME
        placed.parent.mkdir(parents=True)
        placed.write_text("")
        self.assertEqual(
            ninja_guard.tree_ninja(self.tree.out).resolve(), placed.resolve()
        )

    def test_nothing_anywhere(self):
        with (
            mock.patch.object(ninja_guard.shutil, "which", return_value=None),
            self.assertRaises(ninja_guard.GuardError),
        ):
            ninja_guard.choose_ninja(self.tree.out)


class MainTest(unittest.TestCase):
    def test_exit_codes(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMP")) as raw:
            tree = Tree(Path(raw))
            exe = make_fake_ninja(tree.src / "bin" / "ninja", "1.13.2")
            tree.write_log("# ninja log v6")
            with (
                mock.patch.object(ninja_guard, "tree_ninja", return_value=None),
                mock.patch.object(ninja_guard.shutil, "which", return_value=str(exe)),
            ):
                self.assertEqual(ninja_guard.main([str(tree.out)]), 1)
                (tree.out / ".ninja_log").unlink()
                self.assertEqual(ninja_guard.main([str(tree.out)]), 0)
            self.assertEqual(ninja_guard.main([]), 2)


if __name__ == "__main__":
    unittest.main()
