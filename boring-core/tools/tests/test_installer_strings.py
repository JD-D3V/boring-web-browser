#!/usr/bin/env python3
"""The product name lives in one file, and "Chromium" does not leak past it.

Offline. Covers product_name.py (the one place), who reads it, and the
--leftovers mode of branded_string_check.py, which looks for the word in
the generated installer resources and in the names of a release folder.

Usage:
  python -m unittest discover -s boring-core/tools/tests
"""

import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
CORE = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import branded_string_check as check  # noqa: E402
import make_appcast  # noqa: E402
import rebrand  # noqa: E402
import rename_release  # noqa: E402
from product_name import ID, NAME, PUBLISHER  # noqa: E402


def quietly(fn, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        result = fn(*args, **kwargs)
    return result, out.getvalue()


class ProductNameTest(unittest.TestCase):
    def test_nothing_in_it_says_chromium(self):
        for value in (NAME, ID, PUBLISHER):
            self.assertNotRegex(value, re.compile("chromium", re.IGNORECASE))

    def test_the_id_is_the_name_without_spaces(self):
        self.assertEqual(ID, NAME.replace(" ", ""))

    def test_rebrand_reads_it(self):
        self.assertEqual(rebrand.NAME, NAME)
        self.assertEqual(rebrand.ID, ID)
        self.assertEqual(rebrand.PUBLISHER, PUBLISHER)
        self.assertEqual(rebrand.BRANDING["PRODUCT_FULLNAME"], NAME)
        self.assertEqual(rebrand.BRANDING["COMPANY_FULLNAME"], PUBLISHER)
        self.assertEqual(
            rebrand.BRANDING["PRODUCT_INSTALLER_FULLNAME"], NAME + " Installer"
        )

    def test_the_download_names_are_built_from_the_id(self):
        installer, archive = rename_release.release_names("154.0.8037.57", 3)
        self.assertEqual(installer, f"{ID}_154.0.8037.57.3_installer_x64.exe")
        self.assertEqual(archive, f"{ID}_154.0.8037.57.3_windows_x64.zip")

    def test_the_update_feed_reads_the_name(self):
        self.assertIn("{name}", make_appcast.TEMPLATE)
        self.assertNotIn(NAME, make_appcast.TEMPLATE)

    def test_the_licence_file_name_matches_the_id(self):
        # These spell LICENSE-<ID>.txt out because a patch cannot import
        # Python, so a name change that misses one fails here.
        for path in (
            TOOLS / "apply.py",
            TOOLS / "check_package.py",
            CORE / "patches" / "package-boring-files.patch",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn(f"LICENSE-{ID}.txt", text, path.name)
            others = set(re.findall(r"LICENSE-([A-Za-z]+)\.txt", text))
            self.assertEqual(others, {ID}, path.name)

    def test_only_display_strings_follow_the_name(self):
        """Release 2 installs keep updating: ids and paths do not move with NAME."""
        modes = dict(rebrand.INSTALL_MODES)
        # The install and profile folder is the id, as it was in release 1.
        self.assertEqual(
            modes['kProductPathName[] = L"Chromium";'],
            f'kProductPathName[] = L"{ID}";',
        )
        # These are registered with Windows and survive a rename of the
        # product, on purpose: changing them drops the default browser
        # choice of anyone who updates.
        self.assertEqual(
            modes['.browser_prog_id_prefix = L"ChromiumHTM",'],
            '.browser_prog_id_prefix = L"BoringHTM",',
        )
        self.assertEqual(
            modes['.pdf_prog_id_prefix = L"ChromiumPDF",'],
            '.pdf_prog_id_prefix = L"BoringPDF",',
        )
        self.assertEqual(
            modes['.direct_launch_url_scheme = "chromium",'],
            '.direct_launch_url_scheme = "boringbrowser",',
        )
        # What a person reads follows the name.
        self.assertEqual(
            modes['.base_app_name = L"Chromium",'], f'.base_app_name = L"{NAME}",'
        )


def write_rc(path, text, utf16=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-16") if utf16 else text.encode("utf-8"))


def make_out(root, *, strings_extra="", product=NAME, publisher=PUBLISHER, setup=NAME):
    """A build output folder shaped like the parts of out\\Default we read."""
    installer = root / "gen" / "chrome" / "installer"
    write_rc(
        installer / "util" / "installer_util_strings.rc",
        '#include "installer_util_strings.h"\n\nSTRINGTABLE\nBEGIN\n'
        f'  IDS_PRODUCT_NAME_EN_US "{product}"\n'
        f'  IDS_ABOUT_VERSION_COMPANY_NAME_EN_US "{publisher}"\n'
        f"{strings_extra}END\n",
        utf16=True,
    )
    write_rc(
        installer / "setup" / "setup_exe_version.rc",
        "// Copyright 2014 The Chromium Authors\n"
        f'VALUE "ProductName", "{NAME} Installer"\n'
        'VALUE "LegalCopyright", "Copyright 2026 The Chromium Authors."\n',
    )
    (root / "setup.exe").write_bytes(b"MZ\0\0" + setup.encode("utf-16-le"))
    return root


class LeftoverResourceTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def problems(self):
        return check.resource_problems(self.root)

    def test_a_clean_build_passes(self):
        make_out(self.root)
        self.assertEqual(quietly(self.problems)[0], [])

    def test_a_chromium_in_the_string_table_fails_with_its_line(self):
        make_out(self.root, strings_extra='  IDS_SHORTCUT_NAME_EN_US "Chromium"\n')
        problems, _ = quietly(self.problems)
        self.assertEqual(len(problems), 1)
        self.assertIn("installer_util_strings.rc:7", problems[0])
        self.assertIn("IDS_SHORTCUT_NAME_EN_US", problems[0])

    def test_any_language_counts(self):
        make_out(self.root, strings_extra='  IDS_PRODUCT_NAME_FR "Chromium"\n')
        self.assertEqual(len(quietly(self.problems)[0]), 1)

    def test_credit_and_licence_text_may_name_the_project(self):
        extra = (
            '  IDS_CREDIT_EN_US "Made by The Chromium Authors."\n'
            '  IDS_PROJECT_EN_US "Built on the Chromium project, see chromium.org"\n'
        )
        make_out(self.root, strings_extra=extra)
        self.assertEqual(quietly(self.problems)[0], [])

    def test_a_credit_does_not_hide_a_product_name_on_the_same_line(self):
        make_out(
            self.root,
            strings_extra='  IDS_X_EN_US "Chromium, by The Chromium Authors"\n',
        )
        self.assertEqual(len(quietly(self.problems)[0]), 1)

    def test_a_version_resource_is_read_too(self):
        make_out(self.root)
        rc = self.root / "gen/chrome/installer/setup/setup_exe_version.rc"
        rc.write_text(rc.read_text() + 'VALUE "ProductName", "Chromium Installer"\n')
        problems, _ = quietly(self.problems)
        self.assertEqual(len(problems), 1)
        self.assertIn("setup_exe_version.rc", problems[0])

    def test_the_publisher_must_be_ours(self):
        make_out(self.root, publisher="The Chromium Authors")
        problems, _ = quietly(self.problems)
        self.assertTrue(
            any("IDS_ABOUT_VERSION_COMPANY_NAME_EN_US" in p for p in problems)
        )

    def test_the_product_name_must_be_ours(self):
        make_out(self.root, product="Something Else")
        problems, _ = quietly(self.problems)
        self.assertTrue(any("IDS_PRODUCT_NAME_EN_US" in p for p in problems))

    def test_a_setup_built_before_the_strings_changed_fails(self):
        make_out(self.root, setup="Old Name")
        problems, _ = quietly(self.problems)
        self.assertEqual(len(problems), 1)
        self.assertIn("setup.exe", problems[0])

    def test_no_generated_strings_fails_rather_than_passing(self):
        problems, _ = quietly(self.problems)
        self.assertEqual(len(problems), 1)
        self.assertIn("installer_util_strings.rc", problems[0])


def write_zip(path, root, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for entry in entries:
            archive.writestr(f"{root}/{entry}", b"x")


PACKAGE_ENTRIES = [
    "chrome.exe",
    "chrome.dll",
    "LICENSE",
    f"LICENSE-{ID}.txt",
    "NOTICES.html",
    "NOTICES-chromium-web-store.txt",
    "boring/easylist.txt",
    "boring/chromium-web-store/managed_storage.json",
]


class LeftoverNameTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_a_release_with_our_names_passes(self):
        stem = f"{ID}_154.0.8037.57.1"
        (self.root / f"{stem}_installer_x64.exe").write_bytes(b"i")
        write_zip(
            self.root / f"{stem}_windows_x64.zip",
            f"{stem}_windows_x64",
            PACKAGE_ENTRIES,
        )
        (self.root / "SHA256SUMS.txt").write_text("0  x\n")
        problems, _ = quietly(check.release_problems, self.root)
        self.assertEqual(problems, [])

    def test_package_py_names_fail(self):
        ung = "ungoogled-chromium_154.0.8037.57-1.1"
        (self.root / f"{ung}_installer_x64.exe").write_bytes(b"i")
        write_zip(
            self.root / f"{ung}_windows_x64.zip", f"{ung}_windows_x64", PACKAGE_ENTRIES
        )
        problems, _ = quietly(check.release_problems, self.root)
        self.assertTrue(any("installer_x64.exe: the file name" in p for p in problems))
        self.assertTrue(any("windows_x64.zip: the file name" in p for p in problems))
        self.assertTrue(any("entry ungoogled-chromium" in p for p in problems))

    def test_an_entry_that_names_the_project_fails(self):
        stem = f"{ID}_154.0.8037.57.1_windows_x64"
        write_zip(self.root / f"{stem}.zip", stem, ["chrome.exe", "Chromium Setup.lnk"])
        problems, _ = quietly(check.release_problems, self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("Chromium Setup.lnk", problems[0])

    def test_an_empty_folder_fails_rather_than_passing(self):
        problems, _ = quietly(check.release_problems, self.root)
        self.assertEqual(len(problems), 1)

    def test_a_missing_folder_fails(self):
        problems, _ = quietly(check.release_problems, self.root / "nope")
        self.assertEqual(len(problems), 1)

    def test_the_allow_list_is_narrow(self):
        allowed = [
            "NOTICES-chromium-web-store.txt",
            "boring/chromium-web-store/_locales/de/messages.json",
            "LICENSE",
        ]
        refused = [
            "chromium.dll",
            "chromium-web-store.exe",
            "boring/chromium/x.txt",
            "Chromium.lnk",
            "docs/chromium-notes.txt",
        ]
        for name in allowed:
            self.assertFalse(check.name_leftovers(name), name)
        for name in refused:
            self.assertTrue(check.name_leftovers(name), name)

    def test_what_rename_release_writes_passes(self):
        """package.py's own names fail; the copies rename_release makes pass."""
        ung = "ungoogled-chromium_154.0.8037.57-1.1"
        build = self.root / "build"
        build.mkdir()
        (build / f"{ung}_installer_x64.exe").write_bytes(b"installer")
        write_zip(
            build / f"{ung}_windows_x64.zip", f"{ung}_windows_x64", PACKAGE_ENTRIES
        )
        version = self.root / "VERSION"
        version.write_text("MAJOR=154\nMINOR=0\nBUILD=8037\nPATCH=57\n")
        header = self.root / "boring_release.h"
        header.write_text("inline constexpr int kBoringRelease = 1;\n")
        dist = self.root / "dist"

        before, _ = quietly(check.release_problems, build)
        self.assertTrue(before)
        quietly(
            rename_release.rename_release,
            build / f"{ung}_installer_x64.exe",
            build / f"{ung}_windows_x64.zip",
            version,
            header,
            dist,
        )
        after, _ = quietly(check.release_problems, dist)
        self.assertEqual(after, [])


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def test_exit_codes(self):
        out = make_out(self.root / "out")
        code, printed = quietly(check.main, ["--leftovers", "--out", str(out)])
        self.assertEqual(code, 0, printed)
        self.assertIn("no leftover", printed)

        make_out(self.root / "bad", strings_extra='  IDS_X_EN_US "Chromium"\n')
        code, printed = quietly(
            check.main, ["--leftovers", "--out", str(self.root / "bad")]
        )
        self.assertEqual(code, 1)
        self.assertIn("1 leftover", printed)

    def test_leftovers_needs_something_to_read(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("BORING_OUT", None)
            with self.assertRaises(SystemExit):
                quietly(check.main, ["--leftovers"])

    def test_the_original_mode_still_wants_a_source_tree(self):
        with self.assertRaises(SystemExit):
            quietly(check.main, [])


if __name__ == "__main__":
    unittest.main()
