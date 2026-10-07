#!/usr/bin/env python3
"""Offline tests for the page assistance script embedder.

Usage:
  python -m unittest discover -s boring-core/tools/tests
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BORING_CORE = Path(__file__).resolve().parents[2]
ASSISTANCE = BORING_CORE / "components" / "boring" / "assistance"
EMBED = ASSISTANCE / "embed_scripts.py"

PAGE = 'const title = "界面";\n' + r"const path = 'a\b';" + "\n"
PROTOCOL = 'const quote = "say \\"hi\\"";\n'


def raw_string(header, name):
    tag = f'inline constexpr char {name}[] = R"BORINGJS('
    start = header.index(tag) + len(tag)
    end = header.index(')BORINGJS";', start)
    return header[start:end]


class EmbedScriptsTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory(dir=os.environ.get("TMP"))
        self.addCleanup(self._dir.cleanup)
        self.dir = Path(self._dir.name)

    def run_embed(self, *args):
        return subprocess.run(
            [sys.executable, str(EMBED), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def write_js(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def test_writes_each_script_verbatim(self):
        page = self.write_js("page_context.js", PAGE)
        protocol = self.write_js("protocol.js", PROTOCOL)
        out = self.dir / "assistance_scripts.h"

        result = self.run_embed(
            str(out),
            f"kAssistancePageScript={page}",
            f"kAssistanceProtocolScript={protocol}",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        raw = out.read_bytes()
        self.assertNotIn(b"\r", raw)
        header = raw.decode("utf-8")
        self.assertIn(
            "#ifndef COMPONENTS_BORING_ASSISTANCE_ASSISTANCE_SCRIPTS_H_", header
        )
        self.assertIn("namespace boring {", header)
        self.assertLess(
            header.index("kAssistancePageScript"),
            header.index("kAssistanceProtocolScript"),
        )
        self.assertEqual(raw_string(header, "kAssistancePageScript"), PAGE)
        self.assertEqual(raw_string(header, "kAssistanceProtocolScript"), PROTOCOL)

    def test_rejects_delimiter_in_script(self):
        bad = self.write_js("bad.js", 'const x = "a";  // )BORINGJS"\n')
        out = self.dir / "assistance_scripts.h"

        result = self.run_embed(str(out), f"kAssistancePageScript={bad}")

        self.assertEqual(result.returncode, 1)
        self.assertFalse(out.exists())

    def test_rejects_bad_name(self):
        js = self.write_js("x.js", "1;\n")
        out = self.dir / "assistance_scripts.h"

        result = self.run_embed(str(out), f"name={js}")

        self.assertEqual(result.returncode, 1)
        self.assertFalse(out.exists())

    def test_real_scripts_embed(self):
        out = self.dir / "assistance_scripts.h"

        result = self.run_embed(
            str(out),
            f"kAssistancePageScript={ASSISTANCE / 'page_context.js'}",
            f"kAssistanceProtocolScript={ASSISTANCE / 'protocol.js'}",
            f"kAssistanceGeminiScript={ASSISTANCE / 'gemini_adapter.js'}",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        header = out.read_text(encoding="utf-8")
        for name in (
            "kAssistancePageScript",
            "kAssistanceProtocolScript",
            "kAssistanceGeminiScript",
        ):
            self.assertIn(f"inline constexpr char {name}[]", header)


if __name__ == "__main__":
    unittest.main()
