#!/usr/bin/env python3
"""Checks that staging reads the node_modules pin out of Chromium's DEPS.

Offline. Run with: python -m unittest discover -s boring-core/tools/tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stage_upstream import NODE_MODULES_DEP, _gcs_pin  # noqa: E402

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
                "sha256sum": "a298af5fafd358179d6aec9a42f667902dbcdb03a42ee4a87a1bff83515e96b9",
                "output_file": "node_modules.tar.gz",
            },
        )

    def test_missing_entry_is_an_error(self):
        with self.assertRaises(RuntimeError):
            _gcs_pin(DEPS, "src/third_party/nothing")


if __name__ == "__main__":
    unittest.main()
