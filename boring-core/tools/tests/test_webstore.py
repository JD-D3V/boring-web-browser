#!/usr/bin/env python3
"""Offline tests for the Web Store and spellcheck packaging (features 12, 14).

Usage:
  python -m unittest discover -s boring-core/tools/tests
"""

import base64
import configparser
import glob
import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
CORE = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import check_package  # noqa: E402
import get_chromium_web_store as cws  # noqa: E402

WEBSTORE = CORE / "components" / "boring" / "webstore"
EXTENSION = WEBSTORE / "chromium-web-store"
PATCHES = [
    CORE / "patches" / "package-boring-files.patch",
    CORE / "patches" / "153" / "package-boring-files.patch",
]

# The real key from the 1.5.5.4 manifest, which fixes the extension ID.
REAL_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqF/d41Q7agjkUzYq8ZGb"
    "Qr8XW8mmEIMXOnR1uCTnYLL+Dm9Z+LO50xZukOISNy6zFxpI8ts/OGLsm+I2x9+U"
    "prUU4/EVdmxuwegFE6NBoEhHoRNYY0gbXZkaU8YY/XwzjVY/k18DDhl5NYPEnF6u"
    "q4Oyidg+xtd3W4+iGYczuOLER1Tp5y614zOTphcvFYhvUkCijQ6HT1TtRq/34SlF"
    "oRQqo4SFiLriK451xWIcfwiMLIekWrdoQa1v8dqIlMA3r6CKc0QykJpSYbiyormW"
    "iZ0hl2HLpkZ85mD9V0eDQ5RCtb6vkybK7INcq4yKQV4YkXhr9NpX9U4re4dlFQjE"
    "JQIDAQAB"
)


def varint(n):
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def field(number, payload):
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def make_crx(zip_bytes, key_der, crx_id=None):
    """A CRX3 with the layout Chromium writes. The signature is filler."""
    if crx_id is None:
        crx_id = hashlib.sha256(key_der).digest()[:16]
    proof = field(1, key_der) + field(2, b"not a real signature")
    header = field(2, proof) + field(10000, field(1, crx_id))
    return b"Cr24" + struct.pack("<II", 3, len(header)) + header + zip_bytes


def fake_extension(update_url=True, version=cws.VERSION, key=REAL_KEY):
    """A zip shaped like the release, with every line the script edits."""
    manifest = (
        "{\n"
        f'    "version": "{version}",\n'
        f'    "key": "{key}",\n'
        '    "permissions": ["management"],\n'
        + (
            '    "update_url": "https://raw.githubusercontent.com/x/updates.xml",\n'
            if update_url
            else ""
        )
        + '    "name": "Chromium Web Store"\n'
        "}\n"
    )
    files = {
        "manifest.json": manifest.encode(),
        "scripts/util.js": (
            b"const X = {\r\n    update_period_in_minutes: 60,\r\n};\r\n"
        ),
        "options.html": (
            b"<input id='update_period_in_minutes' type='number' value='60'/>\n"
        ),
        "scripts/options.js": (
            b'const val = parseInt(e.target.value) || 60;\nnode.value = "60";\n'
        ),
        "managed_storage.json": b'{"description": "Default is 60"}\n',
        "_locales/en/messages.json": b"{}\n",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


class CrxReadingTest(unittest.TestCase):
    def test_id_from_the_real_key(self):
        self.assertEqual(cws.id_from_key(base64.b64decode(REAL_KEY)), cws.EXTENSION_ID)

    def test_reads_zip_id_and_keys(self):
        key = base64.b64decode(REAL_KEY)
        zip_bytes = fake_extension()
        body, crx_id, keys = cws.read_crx3(make_crx(zip_bytes, key))
        self.assertEqual(body, zip_bytes)
        self.assertEqual(crx_id, hashlib.sha256(key).digest()[:16])
        self.assertEqual(keys, [key])

    def test_refuses_what_is_not_crx3(self):
        with self.assertRaises(cws.CrxError):
            cws.read_crx3(b"PK\x03\x04 a plain zip")
        with self.assertRaises(cws.CrxError):
            cws.read_crx3(b"Cr24" + struct.pack("<II", 2, 0))
        with self.assertRaises(cws.CrxError):
            cws.read_crx3(b"Cr24" + struct.pack("<II", 3, 999) + b"short")


class PrepareTest(unittest.TestCase):
    def prepare(self, **kwargs):
        key = base64.b64decode(REAL_KEY)
        crx_id = kwargs.pop("crx_id", None)
        data = make_crx(fake_extension(**kwargs), key, crx_id)
        return cws.prepare(*cws.read_crx3(data))

    def test_takes_update_url_out_and_nothing_else_from_the_manifest(self):
        files, public_key = self.prepare()
        manifest = json.loads(files["manifest.json"])
        self.assertNotIn("update_url", manifest)
        self.assertEqual(manifest["permissions"], ["management"])
        self.assertEqual(public_key, REAL_KEY)

    def test_update_checks_every_300_minutes(self):
        files, _ = self.prepare()
        self.assertIn(b"update_period_in_minutes: 300,", files["scripts/util.js"])
        self.assertIn(b"value='300'", files["options.html"])
        self.assertNotIn(b"60", files["scripts/options.js"])
        # Line endings are the release's own.
        self.assertIn(b"\r\n", files["scripts/util.js"])

    def test_refuses_a_manifest_without_update_url(self):
        # The release always had one; its absence means the file moved.
        with self.assertRaises(cws.CrxError):
            self.prepare(update_url=False)

    def test_refuses_the_wrong_version(self):
        with self.assertRaises(cws.CrxError):
            self.prepare(version="9.9.9.9")

    def test_refuses_a_crx_id_that_is_not_the_manifest_key(self):
        with self.assertRaises(cws.CrxError):
            self.prepare(crx_id=b"\x00" * 16)

    def test_refuses_an_edit_that_no_longer_matches(self):
        key = base64.b64decode(REAL_KEY)
        buf = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(fake_extension())) as src,
            zipfile.ZipFile(buf, "w") as dst,
        ):
            for info in src.infolist():
                body = src.read(info)
                if info.filename == "scripts/util.js":
                    body = body.replace(b"60", b"30")
                dst.writestr(info.filename, body)
        with self.assertRaises(cws.CrxError):
            cws.prepare(*cws.read_crx3(make_crx(buf.getvalue(), key)))

    def test_refuses_unsafe_paths(self):
        key = base64.b64decode(REAL_KEY)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../evil.js", b"x")
        with self.assertRaises(cws.CrxError):
            cws.prepare(*cws.read_crx3(make_crx(buf.getvalue(), key)))


class CommittedExtensionTest(unittest.TestCase):
    """What is in the repository is what the script would write."""

    def setUp(self):
        if not EXTENSION.is_dir():
            self.skipTest("run tools/get_chromium_web_store.py first")

    def committed_files(self):
        return sorted(
            p.relative_to(EXTENSION).as_posix()
            for p in EXTENSION.rglob("*")
            if p.is_file()
        )

    def test_manifest_has_no_update_url_and_the_pinned_version(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_bytes())
        self.assertNotIn("update_url", manifest)
        self.assertEqual(manifest["version"], cws.VERSION)
        self.assertIn("management", manifest["permissions"])
        self.assertEqual(
            cws.id_from_key(base64.b64decode(manifest["key"])), cws.EXTENSION_ID
        )

    def test_gni_lists_exactly_the_files_there(self):
        version, listed = check_package.web_store_expected(
            str(WEBSTORE / "chromium_web_store.gni")
        )
        self.assertEqual(version, cws.VERSION)
        self.assertEqual(
            sorted(p[len("boring/chromium-web-store/") :] for p in listed),
            self.committed_files(),
        )

    def test_header_matches_the_manifest(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_bytes())
        header = (WEBSTORE / "chromium_web_store_version.h").read_text()
        self.assertIn(f'kBundledVersion[] = "{cws.VERSION}"', header)
        self.assertIn(f'kBundledId[] = "{cws.EXTENSION_ID}"', header)
        joined = "".join(
            line.strip().strip('";').strip('"')
            for line in header.split("kBundledPublicKey[] =", 1)[1].splitlines()[1:8]
        )
        self.assertTrue(joined.startswith(manifest["key"]))

    def test_licences_travel_with_it(self):
        self.assertIn(b"MIT License", (EXTENSION / "LICENSE").read_bytes())
        notice = (
            CORE
            / "components"
            / "boring"
            / "notices"
            / "NOTICES-chromium-web-store.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("Copyright (c) 2019 NeverDecaf", notice)
        self.assertIn("Yusuke Kawasaki", notice)

    def test_matches_a_fresh_run_when_the_download_is_cached(self):
        crx = Path(cws.CACHE) / f"Chromium.Web.Store-{cws.VERSION}.crx"
        licences = {name: Path(cws.CACHE) / name for name in cws.LICENCES}
        if not crx.exists() or not all(p.exists() for p in licences.values()):
            self.skipTest("no cached download")
        self.assertEqual(hashlib.sha256(crx.read_bytes()).hexdigest(), cws.SHA256)
        wanted = cws.outputs(
            crx.read_bytes(), {n: p.read_bytes() for n, p in licences.items()}
        )
        for path, body in wanted.items():
            with self.subTest(path=os.path.relpath(path, CORE)):
                self.assertTrue(cws.same_content(path, Path(path).read_bytes(), body))


def recase(c):
    return f"[{c.lower()}{c.upper()}]" if c.isalpha() else c


def added_lines(patch, path_suffix):
    lines = []
    current = None
    for line in patch.read_text(encoding="utf-8").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("+") and current and current.endswith(path_suffix):
            lines.append(line[1:])
    return lines


class PackagingPatchTest(unittest.TestCase):
    """Both packaging patches ship every file, and only files.

    A pattern that matches a folder breaks the installer build (a folder
    cannot be copied as a file) and the zip build (the fixed timestamp
    path opens it as a file). A file no pattern matches is silently left
    out of the package.
    """

    def setUp(self):
        _, self.web_store = check_package.web_store_expected()
        if not self.web_store:
            self.skipTest("run tools/get_chromium_web_store.py first")
        self.expected = set(self.web_store) | {
            check_package.DICTIONARY,
            "NOTICES-chromium-web-store.txt",
            "NOTICES-hunspell-en-US.txt",
        }
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.out = Path(self._dir.name)
        for name in self.expected:
            path = self.out / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

    def test_chrome_release(self):
        for patch in PATCHES:
            with self.subTest(patch=patch.name):
                text = "[GENERAL]\n" + "\n".join(
                    line
                    for line in added_lines(patch, "chrome.release")
                    if not line.startswith("#")
                )
                config = configparser.ConfigParser(
                    {"VersionDir": "V", "ChromeDir": "C"}
                )
                config.read_string(text)
                staged = set()
                for option in config.options("GENERAL"):
                    if option.endswith("dir"):
                        continue
                    # As create_installer_archive.py does it: the option
                    # comes back lowercased and is globbed without case.
                    # Relative, as the real script's src_dir is: a
                    # drive letter cannot be globbed.
                    pattern = option.replace("\\", os.sep)
                    found = [
                        self.out / p
                        for p in glob.glob(
                            "".join(map(recase, pattern)), root_dir=self.out
                        )
                    ]
                    dest = config.get("GENERAL", option).replace("\\", "/")
                    for path in found:
                        self.assertTrue(path.is_file(), f"{option} matches a folder")
                        self.assertTrue(dest.startswith("V/"))
                        staged.add(dest[2:] + path.name)
                missing = {
                    name
                    for name in self.expected
                    if name.lower() not in {s.lower() for s in staged}
                }
                self.assertEqual(missing, set())

    def test_files_cfg(self):
        for patch in PATCHES:
            with self.subTest(patch=patch.name):
                text = "\n".join(added_lines(patch, "FILES.cfg"))
                scope = {"__builtins__": None}
                exec("FILES = [\n" + text + "\n]", scope)
                staged = set()
                for spec in scope["FILES"]:
                    self.assertIn("official", spec["buildtype"])
                    for path in self.out.glob(spec["filename"]):
                        self.assertTrue(
                            path.is_file(), f"{spec['filename']} matches a folder"
                        )
                        staged.add(path.relative_to(self.out).as_posix())
                self.assertEqual(self.expected - staged, set())


class CheckPackageFeatureTest(unittest.TestCase):
    def test_bdic_checks(self):
        body = b"A" * 40
        header = struct.pack("<IHHII", 0x63694442, 2, 0, 32, 36)
        good = header + hashlib.md5(body).digest() + body
        self.assertIsNone(check_package.bdic_problem(good))
        self.assertIsNotNone(check_package.bdic_problem(good[:-1] + b"B"))
        self.assertIsNotNone(check_package.bdic_problem(b"XXXX" + good[4:]))
        self.assertIsNotNone(check_package.bdic_problem(b"short"))

    def test_the_tree_dictionary_loads(self):
        tree = Path(
            r"E:\ung-153-47\build\src\third_party\hunspell_dictionaries"
            r"\en-US-10-1.bdic"
        )
        if not tree.exists():
            self.skipTest("no Chromium tree here")
        self.assertIsNone(check_package.bdic_problem(tree.read_bytes()))

    def test_manifest_checks(self):
        ok = json.dumps({"version": "1.2.3.4"}).encode()
        self.assertIsNone(check_package.web_store_manifest_problem(ok, "1.2.3.4"))
        self.assertIn(
            "update_url",
            check_package.web_store_manifest_problem(
                json.dumps({"version": "1.2.3.4", "update_url": "x"}).encode(),
                "1.2.3.4",
            ),
        )
        self.assertIsNotNone(check_package.web_store_manifest_problem(ok, "2.0"))
        self.assertIsNotNone(check_package.web_store_manifest_problem(b"{", None))

    def test_missing_web_store_and_dictionary_fail(self):
        report = check_package.Report()
        check_package.check_required_sets(set(), report, "empty")
        text = "\n".join(report.problems)
        self.assertIn(check_package.DICTIONARY, text)
        self.assertIn("NOTICES-chromium-web-store.txt", text)
        self.assertIn("NOTICES-hunspell-en-US.txt", text)
        if check_package.web_store_expected()[1]:
            self.assertIn("Chromium Web Store file(s) missing", text)


class ExtensionInstallPatchTest(unittest.TestCase):
    def test_default_is_prompt_and_explicit_choices_still_win(self):
        patch = (CORE / "patches" / "extension-install-defaults.patch").read_text()
        self.assertIn(
            '+  if (!command_line.HasSwitch("extension-mime-request-handling") ||',
            patch,
        )
        # The "always prompt" value still returns true; any other value
        # (download-as-regular-file) falls through to the normal rules.
        self.assertIn('"always-prompt-for-install"', patch)
        self.assertIn("boring::webstore::MaybeInstallBundledWebStore(profile_);", patch)


if __name__ == "__main__":
    unittest.main()
