#!/usr/bin/env python3
"""Tests for check_compile.py against the Chromium 154 build.

Usage:
  TMP='E:/tmp' TEMP='E:/tmp' python -m unittest \
      boring-core/tools/tests/test_check_compile.py -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_compile  # noqa: E402

BORING_CORE = TOOLS.parent
SCRIPT = TOOLS / "check_compile.py"
OUT = check_compile.DEFAULT_OUT
LIKE = "obj/chrome/browser/ui/views/toolbar/impl/boring_reader_button.obj"
GOOD_SOURCE = (
    BORING_CORE
    / "chromium_src"
    / "chrome"
    / "browser"
    / "ui"
    / "views"
    / "toolbar"
    / "boring_reader_button.cc"
)
SCRATCH = Path(os.environ.get("TMP", "E:/tmp"))
HAS_BUILD = (OUT / "build.ninja").is_file()
SKIP_REASON = f"no build.ninja in {OUT}; these tests need the Chromium 154 build"


def run_tool(source: Path) -> subprocess.CompletedProcess:
    """Run the tool the way a person would, and capture what it prints."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--like", LIKE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@unittest.skipUnless(HAS_BUILD, SKIP_REASON)
class CheckCompileTest(unittest.TestCase):
    def object_state(self) -> tuple[int, int]:
        st = (OUT / LIKE).stat()
        return st.st_size, st.st_mtime_ns

    def test_known_good_file_passes(self):
        before = self.object_state()
        result = run_tool(GOOD_SOURCE)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        # The check must not overwrite the object it borrowed flags from.
        self.assertEqual(self.object_state(), before)

    def test_syntax_error_fails(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix="check_compile_", dir=SCRATCH))
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        bad = scratch / "bad_syntax.cc"
        bad.write_text("int x = ;\n", encoding="utf-8")

        result = run_tool(bad)
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error", output)
        self.assertIn("bad_syntax.cc", output)


if __name__ == "__main__":
    unittest.main()
