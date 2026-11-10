"""apply.py saves the original of a patched file before the first patch.

clean_tree.py puts back only what has a copy in the pristine store. Files
that ungoogled-chromium itself changes (chrome_download_manager_delegate.cc,
app_menu.cc, tab_modal_dialog_manager.cc, prepopulated_engines.json) never
got one, because nothing saved them, and HEAD is not their original. These
tests run seed_pristine() against a small git tree.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import apply  # noqa: E402

ORIGINAL = "one\ntwo\nthree\n"
PATCH = (
    "diff --git a/a/f.cc b/a/f.cc\n"
    "--- a/a/f.cc\n"
    "+++ b/a/f.cc\n"
    "@@ -1,3 +1,3 @@\n"
    " one\n"
    "-two\n"
    "+TWO\n"
    " three\n"
)


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class SeedPristine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = os.path.join(self.tmp, "src")
        self.store = os.path.join(self.tmp, "store")
        os.makedirs(os.path.join(self.src, "a"))
        git(self.src, "init", "-q")
        git(self.src, "config", "core.autocrlf", "false")
        self.file = os.path.join(self.src, "a", "f.cc")
        self.write(self.file, ORIGINAL)
        self.patch = os.path.join(self.tmp, "p.patch")
        self.write(self.patch, PATCH)
        self.rel = os.path.join("a", "f.cc")

    def write(self, path, text):
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def read(self, path):
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()

    def test_saves_the_file_before_it_is_patched(self):
        seeded = apply.seed_pristine(self.src, [self.patch], self.store)
        self.assertEqual(seeded, [self.rel])
        self.assertEqual(self.read(os.path.join(self.store, self.rel)), ORIGINAL)

    def test_a_file_that_ungoogled_changed_is_saved_as_it_stands(self):
        # HEAD holds something else: the tree's own state is the base.
        self.write(self.file, "head\n")
        git(self.src, "add", ".")
        git(
            self.src,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-qm",
            "head",
        )
        self.write(self.file, ORIGINAL)
        apply.seed_pristine(self.src, [self.patch], self.store)
        self.assertEqual(self.read(os.path.join(self.store, self.rel)), ORIGINAL)

    def test_an_existing_copy_is_never_replaced(self):
        keep = os.path.join(self.store, self.rel)
        os.makedirs(os.path.dirname(keep))
        self.write(keep, "older original\n")
        self.assertEqual(apply.seed_pristine(self.src, [self.patch], self.store), [])
        self.assertEqual(self.read(keep), "older original\n")

    def test_a_file_already_patched_is_not_taken_for_the_original(self):
        self.write(self.file, ORIGINAL.replace("two", "TWO"))
        self.assertEqual(apply.seed_pristine(self.src, [self.patch], self.store), [])
        self.assertFalse(os.path.exists(os.path.join(self.store, self.rel)))

    def test_a_header_path_outside_the_tree_is_skipped(self):
        outside = os.path.join(os.path.dirname(self.store), "escaped.txt")
        for name in ("../escaped.txt", "a/../../escaped.txt", "/abs/escaped.txt"):
            patch = os.path.join(self.src, "evil.patch")
            self.write(
                patch,
                f"--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-x\n+y\n",
            )
            self.assertEqual(apply.seed_pristine(self.src, [patch], self.store), [])
        self.assertFalse(os.path.exists(outside))

    def test_a_file_missing_from_the_tree_is_skipped(self):
        os.remove(self.file)
        self.assertEqual(apply.seed_pristine(self.src, [self.patch], self.store), [])

    def test_apply_patches_seeds_then_patches(self):
        series = os.path.join(self.tmp, "series")
        self.write(series, "p.patch\n")
        orig_names, orig_path = apply.series_names, apply.patch_path
        apply.series_names = lambda: ["p.patch"]
        apply.patch_path = lambda name, patch_set: self.patch
        self.addCleanup(setattr, apply, "series_names", orig_names)
        self.addCleanup(setattr, apply, "patch_path", orig_path)
        apply.apply_patches(self.src, None, self.store)
        self.assertEqual(self.read(self.file), ORIGINAL.replace("two", "TWO"))
        self.assertEqual(self.read(os.path.join(self.store, self.rel)), ORIGINAL)


if __name__ == "__main__":
    unittest.main()
