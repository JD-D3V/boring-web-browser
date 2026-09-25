#!/usr/bin/env python3
"""Offline tests for the release tools.

Usage:
  python -m unittest discover -s boring-core/tools/tests
"""

import base64
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import joblock  # noqa: E402
import make_appcast  # noqa: E402
import sign_windows  # noqa: E402

SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"


class JobLockTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.lock_path = Path(self._dir.name) / "build.lock"

    def test_acquires_and_reports_its_holder(self):
        with joblock.JobLock("nightly build", path=self.lock_path):
            holder = joblock.read_holder(self.lock_path)
            self.assertIsNotNone(holder)
            self.assertEqual(holder["job"], "nightly build")
            self.assertEqual(holder["pid"], os.getpid())
            self.assertIn("nightly build", joblock.describe(holder))

    def test_second_acquirer_is_refused(self):
        with joblock.JobLock("first", path=self.lock_path):
            second = joblock.JobLock("second", path=self.lock_path)
            with self.assertRaises(joblock.TreeBusy) as caught:
                second.acquire()
            self.assertIn("first", str(caught.exception))

    def test_free_again_once_the_first_holder_releases(self):
        first = joblock.JobLock("first", path=self.lock_path)
        first.acquire()
        first.release()
        with joblock.JobLock("second", path=self.lock_path):
            pass

    def test_released_when_the_holding_process_exits(self):
        # The operating system drops the lock with the handle, so a build
        # killed half way through does not wedge the tree for ever.
        script = (
            "import sys, os;"
            f"sys.path.insert(0, {str(TOOLS)!r});"
            "import joblock;"
            f"joblock.JobLock('crasher', path={str(self.lock_path)!r}).acquire();"
            "os._exit(0)"
        )
        done = subprocess.run([sys.executable, "-c", script], check=False)
        self.assertEqual(done.returncode, 0)
        with joblock.JobLock("after the crash", path=self.lock_path):
            pass

    def test_a_live_lease_keeps_other_owners_out(self):
        claim = joblock.JobLock(
            "release run", path=self.lock_path, owner="gh-1", lease=600
        )
        claim.acquire()
        claim.release()

        same_job = joblock.JobLock("release step 2", path=self.lock_path, owner="gh-1")
        with same_job:
            pass

        stranger = joblock.JobLock("manual build", path=self.lock_path, owner="jd")
        with self.assertRaises(joblock.TreeBusy) as caught:
            stranger.acquire()
        self.assertIn("gh-1", str(caught.exception))

    def test_an_expired_lease_does_not_block(self):
        stale = joblock.JobLock("old run", path=self.lock_path, owner="gh-0", lease=-1)
        stale.acquire()
        stale.release()
        with joblock.JobLock("next run", path=self.lock_path, owner="gh-2"):
            pass

    def test_cli_runs_the_command_and_returns_its_exit_code(self):
        code = joblock.main(
            [
                "--lock-file",
                str(self.lock_path),
                "--job",
                "cli test",
                "--",
                sys.executable,
                "-c",
                "raise SystemExit(7)",
            ]
        )
        self.assertEqual(code, 7)

    def test_cli_reports_busy_with_a_distinct_exit_code(self):
        with joblock.JobLock("holder", path=self.lock_path):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = joblock.main(
                    [
                        "--lock-file",
                        str(self.lock_path),
                        "--job",
                        "latecomer",
                        "--",
                        sys.executable,
                        "-c",
                        "pass",
                    ]
                )
            self.assertEqual(code, joblock.BUSY_EXIT)
            self.assertIn("holder", stderr.getvalue())


class SignWindowsTest(unittest.TestCase):
    def setUp(self):
        # A real certificate in this shell's environment would change the
        # command line the dry run prints.
        cleared = dict.fromkeys(sign_windows.CREDENTIAL_SOURCES, "")
        cleared["BORING_SIGN_TIMESTAMP_URL"] = ""
        patch = mock.patch.dict(os.environ, cleared)
        patch.start()
        self.addCleanup(patch.stop)

    def test_dry_run_prints_the_command_it_would_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = sign_windows.main(
                [
                    "--dry-run",
                    "--signtool",
                    r"C:\sdk\signtool.exe",
                    r"out\chrome.exe",
                    r"out\boring_adblock.dll",
                ]
            )
        self.assertEqual(code, 0)
        printed = out.getvalue()
        self.assertIn(
            r"C:\sdk\signtool.exe sign /fd sha256 "
            "/tr http://timestamp.digicert.com /td sha256 "
            r"/sha1 <BORING_SIGN_THUMBPRINT> /s My "
            r"out\chrome.exe out\boring_adblock.dll",
            printed,
        )

    def test_dry_run_needs_no_certificate(self):
        self.assertIsNone(sign_windows.credential_from_env({}))

    def test_conflicting_credential_sources_are_refused(self):
        with self.assertRaises(sign_windows.CredentialError) as caught:
            sign_windows.credential_from_env(
                {"BORING_SIGN_THUMBPRINT": "AABB", "BORING_SIGN_PFX": r"E:\c.pfx"}
            )
        message = str(caught.exception)
        self.assertIn("BORING_SIGN_THUMBPRINT", message)
        self.assertIn("BORING_SIGN_PFX", message)

    def test_a_pfx_password_is_never_printed(self):
        credential = sign_windows.credential_from_env(
            {"BORING_SIGN_PFX": r"E:\c.pfx", "BORING_SIGN_PFX_PASSWORD": "hunter2"}
        )
        command = sign_windows.build_sign_command(
            "signtool.exe", ["a.exe"], credential, sign_windows.DEFAULT_TIMESTAMP_URL
        )
        self.assertIn("hunter2", command)
        self.assertNotIn("hunter2", sign_windows.show(command, credential.secrets))

    def test_the_signing_service_gets_its_own_timestamp_authority(self):
        credential = sign_windows.credential_from_env(
            {"BORING_SIGN_DLIB": r"C:\acs\dlib.dll", "BORING_SIGN_DMDF": r"C:\acs.json"}
        )
        self.assertEqual(
            sign_windows.timestamp_url_for(credential, None, {}),
            sign_windows.ARTIFACT_SIGNING_TIMESTAMP_URL,
        )

    def test_the_timestamp_authority_can_come_from_the_environment(self):
        chosen = "http://timestamp.example.invalid"
        self.assertEqual(
            sign_windows.timestamp_url_for(
                None, None, {"BORING_SIGN_TIMESTAMP_URL": chosen}
            ),
            chosen,
        )
        self.assertEqual(
            sign_windows.timestamp_url_for(None, "http://asked.invalid", {}),
            "http://asked.invalid",
        )

    def test_verify_checks_the_whole_chain(self):
        command = sign_windows.build_verify_command("signtool.exe", ["a.exe"])
        self.assertEqual(command, ["signtool.exe", "verify", "/pa", "/all", "a.exe"])

    def test_manifest_skips_blanks_and_comments(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "sign-list.txt"
            manifest.write_text(
                "# what we ship\n\nchrome.exe\n  boring_adblock.dll  \n",
                encoding="utf-8",
            )
            self.assertEqual(
                sign_windows.read_manifest(manifest),
                ["chrome.exe", "boring_adblock.dll"],
            )


class MakeAppcastTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.folder = Path(self._dir.name)
        self.out = self.folder / "appcast.xml"

    def _installer(self) -> Path:
        path = self.folder / "boring-151.0.7922.173-beta.1-installer.exe"
        path.write_bytes(b"not really an installer")
        return path

    def _run(self, installer: Path, version: str, extra: list[str] | None = None):
        argv = [
            "--installer",
            str(installer),
            "--version",
            version,
            "--base-url",
            "https://example.invalid/downloads/",
            "--feed-url",
            "https://example.invalid/updates/appcast.xml",
            "--out",
            str(self.out),
        ]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = make_appcast.main(argv + (extra or []))
        return code, out.getvalue()

    def test_a_missing_installer_is_refused(self):
        code, printed = self._run(self.folder / "not-there.exe", "151.0.7922.173")
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists())
        self.assertIn("no installer at", printed)

    def test_writes_well_formed_xml_with_the_exact_version(self):
        installer = self._installer()
        code, _ = self._run(installer, "151.0.7922.173-beta.1")
        self.assertEqual(code, 0)

        root = ElementTree.parse(self.out).getroot()
        enclosure = root.find("./channel/item/enclosure")
        self.assertIsNotNone(enclosure)
        self.assertEqual(enclosure.get(SPARKLE + "version"), "151.0.7922.173-beta.1")
        self.assertEqual(enclosure.get("length"), str(installer.stat().st_size))
        self.assertEqual(
            enclosure.get("url"),
            "https://example.invalid/downloads/" + installer.name,
        )
        self.assertEqual(enclosure.get(SPARKLE + "os"), "windows")

    def test_the_feed_address_is_fixed(self):
        # A feed whose own address carries the version is no feed: the
        # browser it is meant for is the one that cannot reach it.
        code, printed = self._run(
            self._installer(),
            "151.0.7922.173",
            [],
        )
        self.assertEqual(code, 0)
        root = ElementTree.parse(self.out).getroot()
        link = root.find("./channel/link").text
        self.assertEqual(link, "https://example.invalid/updates/appcast.xml")
        self.assertNotIn("151.0.7922.173", link)

    def test_a_versioned_feed_address_is_refused(self):
        argv = [
            "--installer",
            str(self._installer()),
            "--version",
            "151.0.7922.173",
            "--base-url",
            "https://example.invalid/downloads/",
            "--feed-url",
            "https://example.invalid/v151.0.7922.173/appcast.xml",
            "--out",
            str(self.out),
        ]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = make_appcast.main(argv)
        self.assertEqual(code, 2)
        self.assertIn("nowhere to look", out.getvalue())

    def test_says_so_when_the_feed_is_unauthenticated(self):
        _, printed = self._run(self._installer(), "151.0.7922.173")
        self.assertIn("UNAUTHENTICATED", printed.upper())

    def test_the_release_number_is_part_of_the_compared_version(self):
        code, _ = self._run(self._installer(), "153.0.8010.52", ["--release", "2"])
        self.assertEqual(code, 0)
        enclosure = (
            ElementTree.parse(self.out).getroot().find("./channel/item/enclosure")
        )
        self.assertEqual(enclosure.get(SPARKLE + "version"), "153.0.8010.52.2")
        # WinSparkle shows this beside "you have <installed version>", and
        # the browser reports its version with the release on the end. The
        # Chromium version alone read as a downgrade: "153.0.8010.52 is
        # now available (you have 153.0.8010.52.1)".
        self.assertEqual(
            enclosure.get(SPARKLE + "shortVersionString"), "153.0.8010.52.2"
        )

    def test_a_release_feed_without_a_signature_is_refused(self):
        code, printed = self._run(
            self._installer(), "153.0.8010.52", ["--require-signature"]
        )
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists())
        self.assertIn("unsigned feed", printed)

    def test_carries_an_eddsa_signature_when_given_one(self):
        # 64 bytes, the size of an Ed25519 signature.
        signature = base64.b64encode(bytes(range(64))).decode()
        code, printed = self._run(
            self._installer(), "151.0.7922.173", ["--ed-signature", signature]
        )
        self.assertEqual(code, 0)
        root = ElementTree.parse(self.out).getroot()
        enclosure = root.find("./channel/item/enclosure")
        self.assertEqual(enclosure.get(SPARKLE + "edSignature"), signature)
        self.assertNotIn("UNAUTHENTICATED", printed.upper())


if __name__ == "__main__":
    unittest.main()
