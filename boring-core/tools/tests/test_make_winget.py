#!/usr/bin/env python3
"""Offline tests for make_winget.py.

Usage:
  python -m pytest boring-core/tools/tests/test_make_winget.py
"""

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[1]
sys.path.insert(0, str(TOOLS))

import make_winget  # noqa: E402

PACKAGE = REPO / "packaging" / "winget" / "manifests" / "j" / "JD-D3V" / "BoringBrowser"
TEMPLATE = PACKAGE / "157.0.8103.38.1"
NEW = "158.0.8200.10.1"
NAME = f"BoringBrowser_{NEW}_installer_x64.exe"


def field(text, key):
    """The value of the one `key:` line in a manifest."""
    values = [
        line.split(":", 1)[1].strip()
        for line in text.splitlines()
        if line.strip().startswith(key + ":")
    ]
    assert len(values) == 1, (key, values)
    return values[0]


class MakeWingetTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.manifests = root / "manifests"
        self.package = self.manifests / "j" / "JD-D3V" / "BoringBrowser"
        shutil.copytree(TEMPLATE, self.package / TEMPLATE.name)
        self.release = root / "release"
        self.release.mkdir()
        self.payload = b"not a real installer"
        self.sha = hashlib.sha256(self.payload).hexdigest()
        (self.release / NAME).write_bytes(self.payload)
        (self.release / "SHA256SUMS.txt").write_text(f"{self.sha}  {NAME}\n")

    def run_tool(self, *extra):
        args = ["--release-dir", str(self.release), "--manifests", str(self.manifests)]
        return make_winget.main(args + list(extra))

    def read(self, version, suffix):
        name = f"JD-D3V.BoringBrowser{suffix}.yaml"
        return (self.package / version / name).read_text(encoding="utf-8")

    def test_new_version_gets_its_own_folder_with_url_and_hash(self):
        self.assertEqual(self.run_tool(), 0)
        installer = self.read(NEW, ".installer")
        self.assertEqual(field(installer, "PackageVersion"), NEW)
        self.assertEqual(field(installer, "InstallerSha256"), self.sha.upper())
        self.assertEqual(
            field(installer, "InstallerUrl"),
            "https://github.com/JD-D3V/boring-web-browser/releases/download/"
            f"v{NEW}/{NAME}",
        )
        # The uninstall entry carries Chromium's version only.
        self.assertEqual(field(installer, "DisplayVersion"), "158.0.8200.10")
        locale = self.read(NEW, ".locale.en-US")
        self.assertEqual(field(locale, "PackageVersion"), NEW)
        self.assertEqual(
            field(locale, "ReleaseNotesUrl"),
            f"https://github.com/JD-D3V/boring-web-browser/releases/tag/v{NEW}",
        )
        self.assertEqual(field(self.read(NEW, ""), "PackageVersion"), NEW)
        # Comments in the template survive.
        self.assertIn("# Per-user install", installer)
        # The template folder is left as it was.
        old = self.read(TEMPLATE.name, ".installer")
        self.assertEqual(field(old, "PackageVersion"), TEMPLATE.name)

    def test_rebuilt_release_refills_only_the_hash(self):
        name = f"BoringBrowser_{TEMPLATE.name}_installer_x64.exe"
        (self.release / NAME).rename(self.release / name)
        (self.release / "SHA256SUMS.txt").write_text(f"{self.sha}  {name}\n")
        before = self.read(TEMPLATE.name, ".installer")
        self.assertEqual(self.run_tool(), 0)
        after = self.read(TEMPLATE.name, ".installer")
        self.assertEqual(field(after, "InstallerSha256"), self.sha.upper())
        changed = [
            (a, b)
            for a, b in zip(before.splitlines(), after.splitlines(), strict=True)
            if a != b
        ]
        self.assertEqual(len(changed), 1, changed)

    def test_release_date_is_written_when_given(self):
        self.assertEqual(self.run_tool("--release-date", "2026-11-20"), 0)
        self.assertEqual(
            field(self.read(NEW, ".installer"), "ReleaseDate"), "2026-11-20"
        )
        # Given again, it replaces the date rather than adding a second one.
        self.assertEqual(self.run_tool("--release-date", "2026-11-21"), 0)
        self.assertEqual(
            field(self.read(NEW, ".installer"), "ReleaseDate"), "2026-11-21"
        )

    def test_refuses_a_hash_that_disagrees_with_sha256sums(self):
        (self.release / "SHA256SUMS.txt").write_text(f"{'0' * 64}  {NAME}\n")
        self.assertNotEqual(self.run_tool(), 0)
        self.assertFalse((self.package / NEW).exists())

    def test_refuses_two_installers(self):
        other = "BoringBrowser_158.0.8200.11.1_installer_x64.exe"
        (self.release / other).write_bytes(b"x")
        self.assertNotEqual(self.run_tool(), 0)

    def test_refuses_a_bad_release_date(self):
        self.assertNotEqual(self.run_tool("--release-date", "20 Nov"), 0)


class CommittedManifestTest(unittest.TestCase):
    def test_folder_name_matches_package_version(self):
        for folder in PACKAGE.iterdir():
            for path in folder.glob("*.yaml"):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(field(text, "PackageVersion"), folder.name, path)

    def test_url_names_the_same_version(self):
        text = (TEMPLATE / "JD-D3V.BoringBrowser.installer.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"/v{TEMPLATE.name}/", field(text, "InstallerUrl"))
        self.assertRegex(field(text, "InstallerSha256"), r"^[0-9A-F]{64}$")


if __name__ == "__main__":
    unittest.main()
