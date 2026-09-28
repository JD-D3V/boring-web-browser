#!/usr/bin/env python3
"""Checks that staging reads the node_modules pin out of Chromium's DEPS.

Offline. Run with: python -m unittest discover -s boring-core/tools/tests
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage_upstream import (  # noqa: E402
    GENERATED_HEADERS,
    NODE_MODULES_DEP,
    _gcs_pin,
    fix_header_guards,
)

# Shaped like Chromium 154's DEPS: the pinned entry sits between two
# other GCS deps with the same keys, so a loose match would pick theirs.
DEPS = """
deps = {
  'src/build/linux/debian_bullseye_amd64-sysroot': {
    'bucket': 'chrome-linux-sysroot',
    'condition': 'checkout_linux and checkout_x64 and non_git_source',
    'dep_type': 'gcs',
    'objects': [
      {
        'object_name': 'sysroot-object',
        'sha256sum': 'sysroot-sha',
        'output_file': 'sysroot.tar.xz',
      },
    ],
  },
  # Pull down NPM dependencies for WebUI toolchain.
  'src/third_party/node/node_modules': {
    'bucket': 'chromium-nodejs',
    'dep_type': 'gcs',
    'condition': 'non_git_source',
    'objects': [
      {
        'object_name': 'faaf73cc8ff7b0b2f0d984d6cedcf758e006f57a',
        'sha256sum': 'a298af5fafd358179d6aec9a42f667902dbcdb03a42ee4a87a1bff83515e96b9',
        'size_bytes': 11320770,
        'output_file': 'node_modules.tar.gz',
      },
    ],
  },
  'src/third_party/chromium-bidi/node_modules': {
    'dep_type': 'gcs',
    'bucket': 'chromium-nodejs',
    'objects': [
      {
        'object_name': 'chromium-bidi/e7aab7e5',
        'sha256sum': 'e7aab7e5',
        'output_file': 'node_modules.tar.gz',
      },
    ],
  },
}
"""


class GcsPinTest(unittest.TestCase):
    def test_reads_only_the_named_entry(self):
        self.assertEqual(
            _gcs_pin(DEPS, NODE_MODULES_DEP),
            {
                "bucket": "chromium-nodejs",
                "object_name": "faaf73cc8ff7b0b2f0d984d6cedcf758e006f57a",
                "sha256sum": (
                    "a298af5fafd358179d6aec9a42f667902dbcdb03a42ee4a87a1bff83515e96b9"
                ),
                "output_file": "node_modules.tar.gz",
            },
        )

    def test_missing_entry_is_an_error(self):
        with self.assertRaises(RuntimeError):
            _gcs_pin(DEPS, "src/third_party/nothing")


class HeaderGuardTest(unittest.TestCase):
    def test_drive_letter_guard_is_replaced_and_good_ones_kept(self):
        bad = "E:_UNG-154_BUILD_SRC_SKIA_EXT_SKIA_COMMIT_HASH_H_"
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)
            for relative in GENERATED_HEADERS:
                (src / relative).parent.mkdir(parents=True, exist_ok=True)
                (src / relative).write_text(
                    "#ifndef GOOD_H_\n#define GOOD_H_\n#endif  // GOOD_H_\n"
                )
            skia = src / "skia/ext/skia_commit_hash.h"
            skia.write_text(
                f"#ifndef {bad}\n#define {bad}\n"
                '#define SKIA_COMMIT_HASH "abc"\n'
                f"#endif  // {bad}\n"
            )
            fix_header_guards(src)
            text = skia.read_text()
            self.assertNotIn("E:", text)
            self.assertEqual(text.count("SKIA_EXT_SKIA_COMMIT_HASH_H_"), 3)
            self.assertIn('#define SKIA_COMMIT_HASH "abc"', text)
            dawn = (src / "gpu/webgpu/dawn_commit_hash.h").read_text()
            self.assertIn("#ifndef GOOD_H_", dawn)


if __name__ == "__main__":
    unittest.main()
