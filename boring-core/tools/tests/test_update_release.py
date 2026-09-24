#!/usr/bin/env python3
"""Offline tests for release naming, update signing and the update harness.

Nothing here needs a build, a browser or the network. The winsparkle-tool
tests run only where get_winsparkle.py has fetched the tool, and are
skipped elsewhere; the rest fake it.

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
import urllib.request
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import make_appcast  # noqa: E402
import rename_release  # noqa: E402
import test_update_local as harness  # noqa: E402

SPARKLE = "{http://www.andymatuschak.org/xml-namespaces/sparkle}"
SIGNATURE = base64.b64encode(bytes(range(64))).decode()
PUBLIC_KEY = base64.b64encode(bytes(range(32))).decode()
UNG = "ungoogled-chromium_153.0.8010.52-1.1"

VERSION_FILE = "MAJOR=153\nMINOR=0\nBUILD=8010\nPATCH=52\n"
RELEASE_HEADER = """// comment mentioning kBoringRelease = 9 in prose
namespace boring {
inline constexpr int kBoringRelease = 3;
}
"""


def quietly(fn, *args, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        result = fn(*args, **kwargs)
    return result, out.getvalue()


class RenameReleaseTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)
        self.build = self.root / "build"
        self.build.mkdir()
        self.out = self.root / "dist"
        self.version_file = self.root / "VERSION"
        self.version_file.write_text(VERSION_FILE, encoding="utf-8")
        self.header = self.root / "boring_release.h"
        self.header.write_text(RELEASE_HEADER, encoding="utf-8")
        self.installer = self.build / f"{UNG}_installer_x64.exe"
        self.installer.write_bytes(b"installer bytes")
        self.zip = self.build / f"{UNG}_windows_x64.zip"
        self.zip.write_bytes(b"zip bytes")

    def _argv(self, **over):
        values = {
            "--installer": str(self.installer),
            "--zip": str(self.zip),
            "--version-file": str(self.version_file),
            "--release-header": str(self.header),
            "--out": str(self.out),
        }
        values.update(over)
        argv = []
        for key, value in values.items():
            if value is not None:
                argv += [key, value]
        return argv

    def test_reads_the_chromium_version(self):
        self.assertEqual(
            rename_release.read_chromium_version(self.version_file), "153.0.8010.52"
        )

    def test_a_broken_version_file_is_refused(self):
        self.version_file.write_text("MAJOR=153\nMINOR=x\n", encoding="utf-8")
        with self.assertRaises(rename_release.ReleaseError):
            rename_release.read_chromium_version(self.version_file)

    def test_reads_the_release_number_from_its_one_line(self):
        self.assertEqual(rename_release.read_boring_release(self.header), 3)

    def test_the_real_release_header_parses(self):
        self.assertGreaterEqual(
            rename_release.read_boring_release(rename_release.DEFAULT_RELEASE_HEADER),
            1,
        )

    def test_two_release_lines_are_refused(self):
        self.header.write_text(
            RELEASE_HEADER + "inline constexpr int kBoringRelease = 4;\n",
            encoding="utf-8",
        )
        with self.assertRaises(rename_release.ReleaseError):
            rename_release.read_boring_release(self.header)

    def test_release_zero_is_refused(self):
        self.header.write_text(
            "inline constexpr int kBoringRelease = 0;\n", encoding="utf-8"
        )
        with self.assertRaises(rename_release.ReleaseError):
            rename_release.read_boring_release(self.header)

    def test_names(self):
        self.assertEqual(
            rename_release.release_names("153.0.8010.52", 3),
            (
                "BoringBrowser_153.0.8010.52.3_installer_x64.exe",
                "BoringBrowser_153.0.8010.52.3_windows_x64.zip",
            ),
        )

    def test_copies_names_and_sums(self):
        env_file = self.root / "github_env"
        code, printed = quietly(
            rename_release.main, self._argv(**{"--env-out": str(env_file)})
        )
        self.assertEqual(code, 0, printed)
        installer = self.out / "BoringBrowser_153.0.8010.52.3_installer_x64.exe"
        zip_path = self.out / "BoringBrowser_153.0.8010.52.3_windows_x64.zip"
        self.assertEqual(installer.read_bytes(), b"installer bytes")
        self.assertEqual(zip_path.read_bytes(), b"zip bytes")
        # Copied, not moved.
        self.assertTrue(self.installer.exists())
        self.assertTrue(self.zip.exists())
        self.assertEqual(
            sorted(p.name for p in self.out.iterdir()),
            sorted([installer.name, zip_path.name, "SHA256SUMS.txt"]),
        )

        sums = (self.out / "SHA256SUMS.txt").read_text(encoding="ascii")
        self.assertEqual(
            sums,
            f"{rename_release.sha256_of(installer)}  {installer.name}\n"
            f"{rename_release.sha256_of(zip_path)}  {zip_path.name}\n",
        )
        env = env_file.read_text(encoding="ascii")
        self.assertIn("BORING_VERSION=153.0.8010.52.3\n", env)
        self.assertIn("BORING_RELEASE=3\n", env)
        self.assertIn("CHROMIUM_VERSION=153.0.8010.52\n", env)
        self.assertIn(f"RELEASE_INSTALLER={installer}\n", env)

    def test_the_checksums_describe_the_copies(self):
        # sha256sum -c reads this format; check it against the copies.
        quietly(rename_release.main, self._argv())
        for line in (self.out / "SHA256SUMS.txt").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(rename_release.sha256_of(self.out / name), digest)

    def test_a_chromium_version_mismatch_is_refused(self):
        other = self.build / "ungoogled-chromium_153.0.8010.47-1.1_installer_x64.exe"
        other.write_bytes(b"old")
        code, printed = quietly(
            rename_release.main, self._argv(**{"--installer": str(other)})
        )
        self.assertEqual(code, 2)
        self.assertIn("153.0.8010.47", printed)
        self.assertFalse(self.out.exists() and any(self.out.iterdir()))

    def test_files_from_two_package_runs_are_refused(self):
        other = self.build / "ungoogled-chromium_153.0.8010.52-1.2_windows_x64.zip"
        other.write_bytes(b"zip")
        code, printed = quietly(
            rename_release.main, self._argv(**{"--zip": str(other)})
        )
        self.assertEqual(code, 2)
        self.assertIn("same package run", printed)

    def test_swapped_files_are_refused(self):
        code, _ = quietly(
            rename_release.main,
            self._argv(**{"--installer": str(self.zip), "--zip": str(self.installer)}),
        )
        self.assertEqual(code, 2)

    def test_an_unknown_name_is_refused(self):
        odd = self.build / "setup.exe"
        odd.write_bytes(b"x")
        code, printed = quietly(
            rename_release.main, self._argv(**{"--installer": str(odd)})
        )
        self.assertEqual(code, 2)
        self.assertIn("not a name package.py writes", printed)

    def test_a_missing_file_is_refused(self):
        self.zip.unlink()
        code, _ = quietly(rename_release.main, self._argv())
        self.assertEqual(code, 2)

    def test_an_existing_release_file_is_never_replaced(self):
        self.out.mkdir()
        existing = self.out / "BoringBrowser_153.0.8010.52.3_installer_x64.exe"
        existing.write_bytes(b"someone else's")
        code, printed = quietly(rename_release.main, self._argv())
        self.assertEqual(code, 2)
        self.assertIn("already there", printed)
        self.assertEqual(existing.read_bytes(), b"someone else's")

    def test_the_expected_version_must_match(self):
        code, _ = quietly(
            rename_release.main, self._argv(**{"--expect-version": "153.0.8010.52.3"})
        )
        self.assertEqual(code, 0)

    def test_the_expected_version_may_carry_a_suffix(self):
        code, _ = quietly(
            rename_release.main,
            self._argv(**{"--expect-version": "153.0.8010.52.3-beta"}),
        )
        self.assertEqual(code, 0)

    def test_a_different_expected_version_is_refused(self):
        for asked in ("153.0.8010.52.2", "153.0.8010.52.31", "153.0.8010.52"):
            with self.subTest(asked=asked):
                code, printed = quietly(
                    rename_release.main, self._argv(**{"--expect-version": asked})
                )
                self.assertEqual(code, 2)
                self.assertIn("kBoringRelease 3", printed)


class FakeTool:
    """Stands in for winsparkle-tool through subprocess.run."""

    def __init__(self, sign_out=SIGNATURE, sign_rc=0, verify_rc=0, stderr=""):
        self.sign_out = sign_out
        self.sign_rc = sign_rc
        self.verify_rc = verify_rc
        self.stderr = stderr
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[1] == "sign":
            return subprocess.CompletedProcess(
                command, self.sign_rc, self.sign_out + "\n", self.stderr
            )
        if command[1] == "verify":
            said = "Valid signature." if self.verify_rc == 0 else "Failed"
            return subprocess.CompletedProcess(command, self.verify_rc, said, "")
        raise AssertionError(command)


class UpdateSigningTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.folder = Path(self._dir.name)
        self.installer = self.folder / "BoringBrowser_153.0.8010.52.1_installer_x64.exe"
        self.installer.write_bytes(b"installer")
        self.tool = self.folder / "winsparkle-tool.exe"
        self.tool.write_bytes(b"")
        self.key = self.folder / "secret-place" / "update.key"
        self.key.parent.mkdir()
        self.key.write_text("private")
        self.out = self.folder / "appcast.xml"
        self.source = self.folder / "browser_updater.cc"
        self.source.write_text(
            f'constexpr char kUpdateKey[] = "{PUBLIC_KEY}";\n', encoding="utf-8"
        )
        patch = mock.patch.dict(os.environ, {make_appcast.KEY_FILE_ENV: ""})
        patch.start()
        self.addCleanup(patch.stop)

    def _argv(self, *extra):
        return [
            "--installer",
            str(self.installer),
            "--version",
            "153.0.8010.52",
            "--release",
            "1",
            "--base-url",
            "https://github.com/JD-D3V/boring-web-browser/releases/download/v1",
            "--feed-url",
            make_appcast.FEED_URL,
            "--out",
            str(self.out),
            "--winsparkle-tool",
            str(self.tool),
            *extra,
        ]

    def _run(self, fake, *extra):
        with mock.patch.object(make_appcast.subprocess, "run", fake):
            return quietly(make_appcast.main, self._argv(*extra))

    def _enclosure(self):
        return ElementTree.parse(self.out).getroot().find("./channel/item/enclosure")

    def test_signs_with_the_key_file_and_puts_the_signature_in_the_feed(self):
        fake = FakeTool()
        code, printed = self._run(
            fake, "--private-key-file", str(self.key), "--require-signature"
        )
        self.assertEqual(code, 0, printed)
        self.assertEqual(
            fake.calls[0],
            [
                str(self.tool),
                "sign",
                "--private-key-file",
                str(self.key),
                str(self.installer),
            ],
        )
        self.assertEqual(self._enclosure().get(SPARKLE + "edSignature"), SIGNATURE)
        self.assertEqual(self._enclosure().get(SPARKLE + "version"), "153.0.8010.52.1")

    def test_the_key_file_can_come_from_the_environment(self):
        fake = FakeTool()
        with mock.patch.dict(os.environ, {make_appcast.KEY_FILE_ENV: str(self.key)}):
            code, printed = self._run(fake, "--require-signature")
        self.assertEqual(code, 0, printed)
        self.assertEqual(fake.calls[0][3], str(self.key))

    def test_the_key_path_is_never_printed(self):
        fake = FakeTool(sign_rc=1, stderr=f"cannot open {self.key}")
        code, printed = self._run(fake, "--private-key-file", str(self.key))
        self.assertEqual(code, 2)
        self.assertNotIn(str(self.key), printed)
        self.assertNotIn("secret-place", printed)
        self.assertIn("***", printed)

        code, printed = self._run(FakeTool(), "--private-key-file", str(self.key))
        self.assertEqual(code, 0)
        self.assertNotIn("secret-place", printed)

    def test_a_missing_key_file_is_refused_without_naming_it(self):
        missing = self.folder / "secret-place" / "gone.key"
        code, printed = self._run(FakeTool(), "--private-key-file", str(missing))
        self.assertEqual(code, 2)
        self.assertNotIn("gone.key", printed)
        self.assertFalse(self.out.exists())

    def test_output_that_is_not_a_signature_is_refused(self):
        code, printed = self._run(
            FakeTool(sign_out="Public key: nope"), "--private-key-file", str(self.key)
        )
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists())

    def test_a_malformed_given_signature_is_refused(self):
        code, _ = self._run(FakeTool(), "--ed-signature", "dGVzdA==")
        self.assertEqual(code, 2)

    def test_signature_and_key_file_together_are_refused(self):
        with self.assertRaises(SystemExit):
            quietly(
                make_appcast.main,
                self._argv("--ed-signature", SIGNATURE, "--private-key-file", "k"),
            )

    def test_checks_the_signature_against_the_built_in_key(self):
        fake = FakeTool()
        code, printed = self._run(
            fake,
            "--private-key-file",
            str(self.key),
            "--require-signature",
            "--check-key-from",
            str(self.source),
        )
        self.assertEqual(code, 0, printed)
        verify = fake.calls[1]
        self.assertEqual(verify[1], "verify")
        self.assertIn(PUBLIC_KEY, verify)
        self.assertIn(SIGNATURE, verify)

    def test_a_signature_the_browser_would_reject_is_refused(self):
        code, printed = self._run(
            FakeTool(verify_rc=1),
            "--private-key-file",
            str(self.key),
            "--check-key-from",
            str(self.source),
        )
        self.assertEqual(code, 2)
        self.assertIn("would refuse", printed)
        self.assertFalse(self.out.exists())

    def test_a_placeholder_built_in_key_is_refused(self):
        self.source.write_text(
            'constexpr char kUpdateKey[] = "REPLACE-WITH-THE-REAL-UPDATE-KEY";\n',
            encoding="utf-8",
        )
        code, printed = self._run(
            FakeTool(),
            "--private-key-file",
            str(self.key),
            "--check-key-from",
            str(self.source),
        )
        self.assertEqual(code, 2)
        self.assertIn("placeholder", printed)

    def test_the_real_updater_source_has_one_key_line(self):
        source = (
            TOOLS.parent / "components" / "boring" / "update" / "browser_updater.cc"
        )
        if not source.exists():
            self.skipTest("no browser_updater.cc")
        try:
            make_appcast.read_update_key(str(source))
        except make_appcast.SigningError as error:
            # Today it is a placeholder; either way there is exactly one.
            self.assertIn("placeholder", str(error))

    def test_installer_arguments_are_for_the_harness_only_and_escaped(self):
        xml = make_appcast.render_feed(
            installer=str(self.installer),
            version="153.0.8010.52",
            base_url="http://127.0.0.1:1/files/",
            feed_url="http://127.0.0.1:1/appcast.xml",
            release=2,
            ed_signature=SIGNATURE,
            installer_arguments='/c echo ran> "C:\\t\\m.txt"',
        )
        enclosure = ElementTree.fromstring(xml).find("./channel/item/enclosure")
        self.assertEqual(
            enclosure.get(SPARKLE + "installerArguments"), '/c echo ran> "C:\\t\\m.txt"'
        )
        self.assertEqual(
            enclosure.get("url"), "http://127.0.0.1:1/files/" + self.installer.name
        )
        self.assertNotIn(
            "installerArguments",
            make_appcast.render_feed(
                installer=str(self.installer),
                version="1.2.3.4",
                base_url="https://x.invalid",
                feed_url=make_appcast.FEED_URL,
            ),
        )


def _real_tool() -> Path | None:
    tool = make_appcast.DEFAULT_TOOL
    return tool if sys.platform == "win32" and tool.is_file() else None


@unittest.skipUnless(_real_tool(), "winsparkle-tool not fetched here")
class RealWinsparkleToolTest(unittest.TestCase):
    """The same checks against the real tool, with throwaway keys."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.folder = Path(self._dir.name)
        self.tool = str(_real_tool())
        self.file = self.folder / "payload.exe"
        self.file.write_bytes(b"payload" * 100)

    def test_sign_then_verify_and_tamper(self):
        key = self.folder / "a.key"
        public = harness.generate_key(Path(self.tool), key)
        signature = make_appcast.sign_installer(self.tool, str(key), str(self.file))
        self.assertTrue(make_appcast.is_ed25519_signature(signature))
        make_appcast.verify_signature(self.tool, public, signature, str(self.file))

        other = self.folder / "b.key"
        other_public = harness.generate_key(Path(self.tool), other)
        with self.assertRaises(make_appcast.SigningError):
            make_appcast.verify_signature(
                self.tool, other_public, signature, str(self.file)
            )

        with open(self.file, "ab") as f:
            f.write(b"tampered")
        with self.assertRaises(make_appcast.SigningError):
            make_appcast.verify_signature(self.tool, public, signature, str(self.file))

    def test_generate_key_never_overwrites(self):
        key = self.folder / "a.key"
        key.write_text("precious")
        with self.assertRaises(harness.SetupError):
            harness.generate_key(Path(self.tool), key)
        self.assertEqual(key.read_text(), "precious")


class HarnessVerdictTest(unittest.TestCase):
    Obs = harness.Observation

    def test_older_not_offered(self):
        v = harness.verdict_older_not_offered
        self.assertTrue(v(self.Obs(feed_requests=1, browser_alive=True)).passed)
        self.assertFalse(v(self.Obs(feed_requests=0, browser_alive=True)).passed)
        self.assertFalse(
            v(self.Obs(feed_requests=1, dialog_seen=True, browser_alive=True)).passed
        )
        self.assertFalse(v(self.Obs(feed_requests=1, browser_alive=False)).passed)

    def test_feed_unreachable(self):
        v = harness.verdict_feed_unreachable
        self.assertTrue(v(self.Obs(browser_alive=True)).passed)
        self.assertFalse(v(self.Obs(browser_alive=False)).passed)
        self.assertFalse(v(self.Obs(browser_alive=True, dialog_seen=True)).passed)

    def test_non_local_http_ignored(self):
        v = harness.verdict_non_local_http_ignored
        self.assertTrue(v(self.Obs(browser_alive=True)).passed)
        self.assertFalse(v(self.Obs(browser_alive=True, feed_requests=1)).passed)
        inconclusive = v(self.Obs(browser_alive=True, probe_reached=False))
        self.assertFalse(inconclusive.passed)
        self.assertIn("inconclusive", inconclusive.reason)

    def test_refused(self):
        v = harness.verdict_refused
        good = self.Obs(
            feed_requests=1,
            dialog_seen=True,
            download_started=True,
            download_complete=True,
            browser_alive=True,
        )
        self.assertTrue(v(good).passed)
        ran = self.Obs(**{**good.__dict__, "installer_ran": True})
        self.assertIn("RAN", v(ran).reason)
        self.assertFalse(v(ran).passed)
        no_click = self.Obs(feed_requests=1, dialog_seen=True, browser_alive=True)
        self.assertIn("inconclusive", v(no_click).reason)
        self.assertFalse(v(self.Obs(browser_alive=True)).passed)

    def test_newer_offered(self):
        v = harness.verdict_newer_offered
        good = self.Obs(
            feed_requests=1,
            dialog_seen=True,
            download_started=True,
            download_complete=True,
            installer_ran=True,
        )
        self.assertTrue(v(good).passed)
        self.assertFalse(
            v(self.Obs(**{**good.__dict__, "installer_ran": False})).passed
        )
        self.assertFalse(v(self.Obs(**{**good.__dict__, "dialog_seen": False})).passed)

    def test_every_case_has_a_verdict_and_a_method(self):
        for case in harness.CASES:
            self.assertIn(case.name, harness.VERDICTS)
            self.assertTrue(callable(getattr(harness.Harness, case.name)))

    def test_click_cases_are_marked(self):
        clicks = {c.name for c in harness.CASES if c.needs_click}
        self.assertEqual(
            clicks,
            {"tampered_refused", "wrong_key_refused", "newer_offered", "update_a_to_b"},
        )
        case = next(c for c in harness.CASES if c.name == "newer_offered")
        line = harness.result_line(case, harness.Verdict(False, "no"))
        self.assertTrue(line.startswith("FAIL newer_offered [click]: "))

    def test_no_interactive_skips_the_click_cases(self):
        args = harness.build_parser().parse_args(["--no-interactive"])
        chosen = dict((c.name, skip) for c, skip in harness.selected_cases(args))
        self.assertEqual(chosen["older_not_offered"], "")
        self.assertIn("click", chosen["newer_offered"])
        self.assertIn("--real-installer", chosen["update_a_to_b"])


class HarnessPartsTest(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(harness.newer_version("153.0.8010.52", 1), "153.0.8010.52.2")
        self.assertEqual(harness.older_version("153.0.8010.52", 1), "152.0.8010.52.1")
        self.assertEqual(
            harness.split_build_version("153.0.8010.52.2"), ("153.0.8010.52", 2)
        )

    def test_versions_compare_the_way_the_updater_should(self):
        def key(v):
            return tuple(int(p) for p in v.split("."))

        installed = harness.installed_build_version("153.0.8010.52", 1)
        self.assertGreater(
            key(harness.newer_version("153.0.8010.52", 1)), key(installed)
        )
        self.assertLess(key(harness.older_version("153.0.8010.52", 1)), key(installed))

    def test_parses_the_public_key(self):
        said = (
            f"Private key saved to k.key\nPublic key: {PUBLIC_KEY}\n\n"
            f'    EdDSAPub EDDSA {{"{PUBLIC_KEY}"}}\n'
        )
        self.assertEqual(harness.parse_public_key(said), PUBLIC_KEY)
        with self.assertRaises(harness.SetupError):
            harness.parse_public_key("Public key: short=")

    def test_the_server_serves_and_records(self):
        server = harness.FeedServer().start()
        self.addCleanup(server.stop)
        server.serve({"/appcast.xml": b"<rss/>", "/files/a.exe": b"x" * 5000})
        base = f"http://127.0.0.1:{server.port}"
        with urllib.request.urlopen(base + "/appcast.xml", timeout=5) as r:
            self.assertEqual(r.read(), b"<rss/>")
        with urllib.request.urlopen(base + "/files/a.exe", timeout=5) as r:
            self.assertEqual(len(r.read()), 5000)
        with urllib.request.urlopen(base + "/probe", timeout=5) as r:
            self.assertEqual(r.read(), b"ok")
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/nothing", timeout=5)
        self.assertEqual(server.count("/appcast.xml"), 1)
        self.assertEqual(server.fetched("/files/a.exe"), (True, True))
        self.assertEqual(server.fetched("/files/b.exe"), (False, False))
        # The script's own probe is not the browser asking.
        self.assertEqual(server.count("/probe"), 0)
        server.serve({})
        self.assertEqual(server.count(), 0)

    def test_the_closed_port_is_closed(self):
        port = harness.closed_port()
        with self.assertRaises(OSError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/appcast.xml", timeout=2)

    def test_refuses_to_run_outside_the_sandbox_unless_told(self):
        args = harness.build_parser().parse_args([])
        with (
            mock.patch.dict(os.environ, {"USERNAME": "Joseph"}),
            self.assertRaises(harness.SetupError) as caught,
        ):
            harness.check_setup(args)
        self.assertIn("--outside-sandbox", str(caught.exception))

    def test_list_prints_every_case(self):
        code, printed = quietly(harness.main, ["--list"])
        self.assertEqual(code, 0)
        for case in harness.CASES:
            self.assertIn(case.name, printed)
        self.assertIn("[click]", printed)

    def test_a_zip_copy_is_not_an_installed_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Path(folder) / "Application"
            (app / "153.0.8010.52").mkdir(parents=True)
            chrome = app / "chrome.exe"
            chrome.write_bytes(b"")
            self.assertFalse(harness.is_installed_copy(chrome))
            installer = app / "153.0.8010.52" / "Installer"
            installer.mkdir()
            (installer / "setup.exe").write_bytes(b"")
            self.assertTrue(harness.is_installed_copy(chrome))


if __name__ == "__main__":
    unittest.main()
