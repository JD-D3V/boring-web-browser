#!/usr/bin/env python3
r"""Read a packaged build and say whether it is fit to hand to someone.

Packaging is where a build stops being ours and starts being a download.
This checks the things that go wrong there: something needed is
missing, something that should never have left the machine is in the
package, the version claimed does not match the version built, nobody
can tell whether a binary is signed, and a dependency that came in
through Cargo rather than through Chromium's own third-party manifest
has no notice at all.

Three ways to point it at a candidate:
  --zip PATH        a packaged zip (Chromium's own layout, one top folder)
  --installer PATH  a mini_installer.exe; its embedded chrome.7z payload
                     is extracted with 7z and inspected the same way
  --dir PATH        a raw build output directory such as out\Default,
                     for when no zip has been produced yet. Only the
                     files that packaging actually stages (top level,
                     plus boring/, locales/ and Dictionaries/) are
                     inspected, because
                     the rest of a build directory (obj/, gen/, *.pdb
                     next to every binary, unit test binaries) is never
                     part of a real package and scanning all of it would
                     bury real findings under expected noise. Say so in
                     the report rather than silently narrowing scope.

Any combination of the three can be given; each is checked on its own
terms and the report says plainly which candidate produced which line.

Also checks, beyond the original content/secret/version checks:
  - Authenticode signature status of every shipped binary found, via
    Get-AuthenticodeSignature. Unsigned is reported as fact, not failure;
    there is no certificate yet, and pretending otherwise would be the
    dishonest result this tool exists to prevent.
  - SHA-256 of the final bytes of every candidate file and every binary
    inspected inside it, so a report can be checked against by hand.
  - Presence of a supplemental notice for the Rust dependencies pulled
    in by boring-core/rust (the `adblock` crate and its transitive
    dependencies). Chromium's generated NOTICES.html is built from
    Chromium's own third_party manifest and does not know this Cargo
    workspace exists, so its presence is never accepted as covering it.

Usage:
  python check_package.py --zip E:\ung\build\..._windows_x64.zip
                          [--installer E:\ung\build\..._installer_x64.exe]
                          [--dir E:\ung\build\src\out\Default]
                          [--expect-version 151.0.7922.173]
"""

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

# Without these the browser does not start.
REQUIRED = [
    "chrome.exe",
    "chrome.dll",
    "chrome_elf.dll",
    "resources.pak",
    "icudtl.dat",
    "v8_context_snapshot.bin",
    "locales/en-US.pak",
]

# Without these it starts, and protects nobody, which is worse.
REQUIRED_PROTECTION = [
    "boring_adblock.dll",
    "boring/easylist.txt",
    # The browser updater. Without it an installed copy never hears of a
    # security fix, which is the same failure in slower motion.
    "WinSparkle.dll",
]

# v1 ships no scam blocklist: no feed grants permission to redistribute
# one (see boring-core/tools/get_scamlist.py), and the browser says as
# much on its Protection page. A package holding one would either be
# stale data nobody may pass on, or a file the browser refuses to use
# while the page says the feature is off. Either way it must not ship,
# so its presence is a failure rather than something to check.
MUST_NOT_SHIP = [
    "boring/scamlist.txt",
]

# What we owe the projects this is built from.
REQUIRED_NOTICES = [
    "LICENSE",
    "NOTICES.html",
    # Our own code's licence (MIT), beside Chromium's LICENSE.
    "LICENSE-BoringBrowser.txt",
    # WinSparkle's MIT licence and the expat and OpenSSL notices it
    # carries.
    "NOTICES-WinSparkle.txt",
    # Chromium Web Store's MIT licence, and the one for the XML parser
    # inside it. See tools/get_chromium_web_store.py.
    "NOTICES-chromium-web-store.txt",
    # The en-US spelling dictionary's notice (SCOWL). NOTICES.html names
    # the hunspell dictionaries with a licence for the other languages.
    "NOTICES-hunspell-en-US.txt",
]

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The en-US Hunspell dictionary, so spelling works with no download.
# In Dictionaries beside chrome.dll, which is DIR_APP_DICTIONARIES with
# the spellcheck-dictionary-dir patch.
DICTIONARY = "Dictionaries/en-US-10-1.bdic"

# Chromium Web Store, installed into each profile from this folder. The
# files and the version are the ones tools/get_chromium_web_store.py
# wrote into the .gni the build copies them from.
WEB_STORE_DIR = "boring/chromium-web-store"
WEB_STORE_GNI = os.path.join(
    CORE, "components", "boring", "webstore", "chromium_web_store.gni"
)


def web_store_expected(gni_path=WEB_STORE_GNI):
    """(version, [package paths]) from the .gni, or (None, []) if absent."""
    if not os.path.isfile(gni_path):
        return None, []
    with open(gni_path, encoding="utf-8") as f:
        text = f.read()
    version = re.search(r'chromium_web_store_version\s*=\s*"([^"]+)"', text)
    names = re.findall(r'"chromium-web-store/([^"]+)"', text)
    return (
        version.group(1) if version else None,
        [f"{WEB_STORE_DIR}/{name}" for name in names],
    )


def bdic_problem(data):
    """Why Chromium would refuse this .bdic, or None if it would load.

    The same checks as hunspell::BDict::Verify: the signature, a major
    version it can read, offsets inside the file, and the MD5 of the
    data against the one in the header. A dictionary that fails this is
    deleted by Chromium on first use and spelling quietly stops.
    """
    if len(data) <= 32:
        return "too short"
    signature, major, _minor, aff_offset, dic_offset = struct.unpack(
        "<IHHII", data[:16]
    )
    if signature != 0x63694442:
        return "not a BDic file"
    if major > 2:
        return f"major version {major}, Chromium reads up to 2"
    if aff_offset > len(data) or dic_offset > len(data):
        return "offsets past the end of the file"
    if major >= 2 and hashlib.md5(data[aff_offset:]).digest() != data[16:32]:
        return "MD5 does not match the header"
    return None


def web_store_manifest_problem(data, expected_version):
    """Why the shipped manifest is not the one we meant to ship, or None."""
    try:
        manifest = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        return f"does not parse: {e}"
    if "update_url" in manifest:
        return (
            "still has an update_url, so it would update itself from "
            "outside our releases"
        )
    if expected_version and manifest.get("version") != expected_version:
        return f"is version {manifest.get('version')}, expected {expected_version}"
    return None


def check_feature_contents(relative, reader, report, label):
    """Reads the files whose content, not just presence, matters."""
    if relative.lower() == DICTIONARY.lower():
        problem = bdic_problem(reader())
        if problem:
            report.fail(f"[{label}] {relative}: {problem}")
        else:
            report.note(f"[{label}] {relative} is a dictionary Chromium will load")
    elif relative.lower() == f"{WEB_STORE_DIR}/manifest.json":
        version, _ = web_store_expected()
        problem = web_store_manifest_problem(reader(), version)
        if problem:
            report.fail(f"[{label}] Chromium Web Store manifest {problem}")
        else:
            report.note(
                f"[{label}] Chromium Web Store {version} manifest has no update_url"
            )


# Names this tool will accept as the supplemental notice for the Cargo
# dependencies (the `adblock` crate and everything Cargo.lock pulls in
# with it). None of these exist yet as of this check; the list is here
# so the day one is added under any of these names, the check finds it
# without editing this tool again. Absence is reported as a real
# problem, not a warning, because one of those dependencies (adblock
# itself) is MPL-2.0, which carries a source-availability obligation
# that NOTICES.html does not discharge. See DEPENDENCY_INVENTORY.md.
RUST_NOTICE_CANDIDATES = [
    # What we actually ship, beside LICENSE and NOTICES.html, written by
    # tools/make_rust_notices.py and placed by //components/boring/notices.
    "NOTICES-rust.html",
    # Names an earlier draft of this tool expected. Kept so a package
    # built from an older tree is still recognised rather than failed.
    "boring/RUST_NOTICES.txt",
    "boring/RUST_THIRD_PARTY_NOTICES.txt",
    "boring/NOTICES-rust.txt",
    "boring/NOTICES-rust.html",
    "RUST_NOTICES.txt",
    "THIRD_PARTY_NOTICES.rust",
]

# Anything matching these has no business in a download. Globs, matched
# against the path inside the archive with the top folder stripped.
FORBIDDEN = [
    # Google's CDM is not ours to redistribute, and it is installed into
    # a user data folder, so its presence here means something leaked in
    # from a development profile.
    "WidevineCdm/*",
    "widevinecdm.dll",
    # Debug symbols are large and tell an attacker more than they need.
    "*.pdb",
    # A developer's profile, test output or key material.
    "User Data/*",
    "*-profile/*",
    "*.pem",
    "*.pfx",
    "*.p12",
    "*.key",
    "*.env",
    "*id_rsa*",
    "*.log",
    "testprofile*/*",
]

# Files whose text is read looking for something that should not be in a
# download. Only small text files, so this stays quick.
SECRET_SCAN_MAX_BYTES = 1 << 20
SECRET_PATTERNS = [
    (re.compile(rb"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"), "a private key"),
    (re.compile(rb"ghp_[A-Za-z0-9]{20,}"), "a GitHub token"),
    (re.compile(rb"sk-[A-Za-z0-9]{20,}"), "an API key"),
    (re.compile(rb"AKIA[0-9A-Z]{16}"), "an AWS key id"),
]

# Binaries worth an Authenticode check and a hash when they turn up in
# whatever is being inspected, matched case-insensitively by basename.
SIGNATURE_CANDIDATES = {
    "chrome.exe",
    "chrome.dll",
    "chrome_elf.dll",
    "boring_adblock.dll",
    "mini_installer.exe",
    "setup.exe",
    "chrome_proxy.exe",
    "chrome_pwa_launcher.exe",
    "notification_helper.exe",
}

# Only these subpaths of a raw build output directory are ever staged
# into a real package (see chrome/tools/build/win/FILES.cfg and
# boring-core/patches/package-boring-files.patch). Scanning the rest of
# a build directory for FORBIDDEN patterns would flag thousands of
# expected .pdb/obj/gen/test files that were never going to ship.
DIR_SCAN_SUBPATHS = ["", "boring", "locales", "Dictionaries"]


# At the top level of a build output directory, hundreds of files exist
# that FILES.cfg never stages (build tool binaries, unit test binaries,
# and a .pdb beside each of those, none of which is a packaging
# candidate). Checking all of them for FORBIDDEN patterns would flag
# things like torque.exe.pdb that were never going to ship, so the top
# level is narrowed to the names this tool otherwise cares about: what
# must be present, and what would be a binary worth a hash and a
# signature check. This is a real narrowing of scope, not a full audit
# of the directory; the installer/zip payload checks are the ones that
# see the actual staged file set.
def _top_level_known_names():
    names = set()
    for wanted in REQUIRED + REQUIRED_NOTICES:
        if "/" not in wanted:
            names.add(wanted)
    for wanted in RUST_NOTICE_CANDIDATES:
        if "/" not in wanted:
            names.add(wanted)
    names |= SIGNATURE_CANDIDATES
    return names


class Report:
    """Collects what was found so every check runs before anything fails."""

    def __init__(self):
        self.problems = []
        self.notes = []

    def fail(self, message):
        self.problems.append(message)

    def note(self, message):
        self.notes.append(message)

    def finish(self):
        for note in self.notes:
            print("  " + note)
        if not self.problems:
            print("\npackage looks shippable")
            return 0
        print()
        for problem in self.problems:
            print("PROBLEM:", problem)
        print(f"\n{len(self.problems)} problem(s)")
        return 1


def strip_root(names):
    """Drops the single top folder the zip wraps everything in."""
    roots = {name.split("/", 1)[0] for name in names if "/" in name}
    if len(roots) != 1:
        return {name: name for name in names}
    root = roots.pop() + "/"
    return {
        name: (name[len(root) :] if name.startswith(root) else name) for name in names
    }


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_required_sets(present, report, label):
    # Chromium's own packaging mixes case ("Locales\en-US.pak" inside a
    # mini_installer payload vs "locales/en-US.pak" in a zip), and
    # Windows paths are not case sensitive to begin with, so every
    # comparison here is done on lowercased paths.
    present_lower = {p.lower() for p in present}
    for wanted in REQUIRED:
        if wanted.lower() not in present_lower:
            report.fail(f"[{label}] {wanted} is missing")
    for wanted in REQUIRED_PROTECTION:
        if wanted.lower() not in present_lower:
            report.fail(f"[{label}] {wanted} is missing, so protection would be off")
    for wanted in REQUIRED_NOTICES:
        if wanted.lower() not in present_lower:
            report.fail(
                f"[{label}] {wanted} is missing, so the package ships no notices"
            )
    if DICTIONARY.lower() not in present_lower:
        report.fail(
            f"[{label}] {DICTIONARY} is missing, so spelling has no "
            "dictionary where Windows has no English spelling data"
        )
    version, web_store = web_store_expected()
    if not web_store:
        report.fail(
            f"[{label}] cannot tell which Chromium Web Store files should "
            f"ship: {WEB_STORE_GNI} is missing. Run "
            "tools/get_chromium_web_store.py"
        )
    missing = [name for name in web_store if name.lower() not in present_lower]
    if missing:
        report.fail(
            f"[{label}] {len(missing)} Chromium Web Store file(s) missing, "
            f"so it would not install: {', '.join(missing[:5])}"
            + (" and more" if len(missing) > 5 else "")
        )
    elif web_store:
        report.note(
            f"[{label}] Chromium Web Store {version}: "
            f"all {len(web_store)} files present"
        )
    if not any(name.lower() in present_lower for name in RUST_NOTICE_CANDIDATES):
        report.fail(
            f"[{label}] no supplemental Rust dependency notice found "
            f"(looked for {', '.join(RUST_NOTICE_CANDIDATES)}); "
            "NOTICES.html is Chromium's own third_party manifest and does "
            "not cover boring-core/rust's Cargo dependencies, one of which "
            "(adblock, MPL-2.0) has a source-availability obligation. "
            "See docs/release/DEPENDENCY_INVENTORY.md"
        )


def check_forbidden_and_secrets(relative, size, reader, report, label):
    for pattern in FORBIDDEN:
        if fnmatch.fnmatch(relative, pattern):
            report.fail(f"[{label}] {relative} should not be in a download")
            return
    if size <= SECRET_SCAN_MAX_BYTES and relative.endswith(
        (".txt", ".json", ".cfg", ".ini", ".xml", ".html", ".js")
    ):
        body = reader()
        for pattern, what in SECRET_PATTERNS:
            if pattern.search(body):
                report.fail(f"[{label}] {relative} looks like it contains {what}")


def check_not_shipped(present, report, label):
    """Nothing in MUST_NOT_SHIP may be in the package.

    Exact paths, kept apart from FORBIDDEN below, which holds glob
    patterns for a different question: FORBIDDEN is about things that
    should never be in any package of ours, this is about a file that
    is fine in principle and not permitted in this version.

    A list we are not allowed to hand on is worse than no list: it
    contradicts what the browser tells the person using it, and it
    redistributes somebody else's data without their permission.
    """
    have = {name.replace("\\", "/") for name in present}
    for name in MUST_NOT_SHIP:
        if name in have:
            report.fail(
                f"[{label}] {name} is in the package. This version ships no "
                "scam list: no feed grants permission to redistribute one, "
                "and the browser says scam blocking is off. Rebuild without "
                "it rather than shipping it"
            )
        else:
            report.note(f"[{label}] {name} correctly absent")


def check_contents_zip(zip_path, report):
    label = os.path.basename(zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        inner = strip_root(names)
        present = set(inner.values())

        check_required_sets(present, report, label)

        for outer, relative in inner.items():
            info = archive.getinfo(outer)
            check_forbidden_and_secrets(
                relative,
                info.file_size,
                lambda outer=outer: archive.read(outer),
                report,
                label,
            )
            check_feature_contents(
                relative, lambda outer=outer: archive.read(outer), report, label
            )
            if relative in SIGNATURE_CANDIDATES or os.path.basename(
                relative
            ).lower() in {n.lower() for n in SIGNATURE_CANDIDATES}:
                report.note(
                    f"[{label}] {relative}: sha256 {sha256_of(archive.read(outer))} "
                    f"({info.file_size} bytes) (extract to check signature; a "
                    "zip entry has no Authenticode signature of its own to read)"
                )

        report.note(f"[{label}] {len(present)} files in the zip")
        check_not_shipped(inner.values(), report, label)


def check_version_zip(zip_path, expect, report):
    """Compares the version in the file name with the one expected.

    A release whose file name and binary disagree is the one nobody
    notices until someone reports a bug against the wrong build.
    """
    label = os.path.basename(zip_path)
    found = re.search(r"(\d+\.\d+\.\d+\.\d+)", os.path.basename(zip_path))
    named = found.group(1) if found else None
    if expect and named and named != expect:
        report.fail(f"[{label}] the zip is named {named} but {expect} was expected")
    if named:
        report.note(f"[{label}] zip name says version {named}")
    elif expect:
        report.fail(f"[{label}] the zip name holds no version to check")


def file_version(path):
    """The Windows FileVersion of an executable, or None."""
    script = (
        "$ErrorActionPreference='Stop';"
        "(Get-Item -LiteralPath $env:BORING_FILE).VersionInfo.FileVersion"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        env={**os.environ, "BORING_FILE": os.path.abspath(path)},
    )
    return result.stdout.strip() if result.returncode == 0 else None


def authenticode_status(path):
    """('Status', 'Signer' or None) from Get-AuthenticodeSignature.

    Returns (None, None) if PowerShell itself could not be run. A
    Status of NotSigned is a normal, honest result to report here: this
    project has no certificate yet. Anything other than Valid or
    NotSigned (HashMismatch, NotTrusted, and so on) is a real problem.
    """
    script = (
        "$ErrorActionPreference='Stop';"
        "$s = Get-AuthenticodeSignature -LiteralPath $env:BORING_FILE;"
        "$signer = if ($s.SignerCertificate) "
        "{ $s.SignerCertificate.Subject } else { '' };"
        "Write-Output ($s.Status.ToString() + '|' + $signer)"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        env={**os.environ, "BORING_FILE": os.path.abspath(path)},
    )
    if result.returncode != 0:
        return None, None
    line = result.stdout.strip()
    if "|" not in line:
        return None, None
    status, signer = line.split("|", 1)
    return status, (signer or None)


def read_version_file(path):
    """Turns a chrome/VERSION file into a dotted version string."""
    parts = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, _, value = line.strip().partition("=")
                parts[key.strip()] = value.strip()
    try:
        return f"{parts['MAJOR']}.{parts['MINOR']}.{parts['BUILD']}.{parts['PATCH']}"
    except KeyError:
        return None


def find_7z():
    for candidate in ("7z", "7z.exe"):
        found = shutil.which(candidate)
        if found:
            return found
    fallback = r"C:\Program Files\7-Zip\7z.exe"
    return fallback if os.path.isfile(fallback) else None


def find_installer_payload(installer_path, work_dir):
    """Extracts mini_installer.exe with 7z and returns the inner archive path.

    mini_installer.exe embeds its payload as a PE resource holding a 7z
    archive (observed here as .rsrc\\B7\\CHROME.PACKED.7Z; the exact
    resource id is not load-bearing and is not checked). Returns None if
    7z is missing or nothing extractable was found, so callers degrade
    to "not verified" instead of crashing.
    """
    seven_zip = find_7z()
    if not seven_zip:
        return None, "7z was not found on PATH or at the usual install location"
    result = subprocess.run(
        [seven_zip, "x", "-y", f"-o{work_dir}", installer_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None, f"7z could not extract {installer_path}: {result.stdout[-500:]}"
    for root, _dirs, files in os.walk(work_dir):
        for name in files:
            if name.lower().endswith(".7z"):
                return os.path.join(root, name), None
    return None, "7z extracted the installer but no inner .7z payload turned up"


def list_7z(archive_path):
    """Returns [(path-with-backslashes, size)] from `7z l` output."""
    seven_zip = find_7z()
    if not seven_zip:
        return None, "7z was not found"
    result = subprocess.run(
        [seven_zip, "l", archive_path], capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, f"7z could not list {archive_path}"
    entries = []
    for line in result.stdout.splitlines():
        if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line):
            fields = line.split(None, 5)
            if len(fields) == 6 and fields[2] != "D....":
                try:
                    size = int(fields[3])
                except ValueError:
                    continue
                entries.append((fields[5], size))
    return entries, None


def check_installer(installer_path, expect, report):
    label = os.path.basename(installer_path)
    version = file_version(installer_path)
    if version is None:
        report.fail(f"[{label}] could not read the file version")
    else:
        report.note(f"[{label}] file version {version}")
        if expect and not version.startswith(expect):
            report.fail(f"[{label}] says {version} but {expect} was expected")

    report.note(f"[{label}] sha256 {sha256_of_file(installer_path)}")
    status, signer = authenticode_status(installer_path)
    if status is None:
        report.note(
            f"[{label}] Authenticode status: not verified (PowerShell check failed)"
        )
    else:
        report.note(
            f"[{label}] Authenticode status: {status}"
            + (f", signer: {signer}" if signer else "")
        )
        if status not in ("NotSigned", "Valid"):
            report.fail(
                f"[{label}] Authenticode status is {status}, not NotSigned or Valid"
            )

    with tempfile.TemporaryDirectory(prefix="boring_check_pkg_") as work_dir:
        inner, err = find_installer_payload(installer_path, work_dir)
        if inner is None:
            report.fail(f"[{label}] could not inspect installer payload: {err}")
            return
        entries, err = list_7z(inner)
        if entries is None:
            report.fail(f"[{label}] could not list installer payload: {err}")
            return

        # Paths inside come out as Chrome-bin\<version>\... or
        # Chrome-bin\<top-level exe>; normalise the same way the zip
        # check does, dropping the Chrome-bin\<version> prefix where
        # present so the same REQUIRED lists apply.
        present = set()
        by_relative_size = {}
        for raw, size in entries:
            parts = raw.split("\\")
            if (
                len(parts) >= 3
                and parts[0] == "Chrome-bin"
                and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[1])
            ):
                relative = "/".join(parts[2:])
            elif len(parts) >= 2 and parts[0] == "Chrome-bin":
                relative = "/".join(parts[1:])
            else:
                relative = "/".join(parts)
            present.add(relative)
            by_relative_size[relative] = size

        report.note(f"[{label}] installer payload holds {len(present)} files")
        check_required_sets(present, report, label + " payload")
        # The listing from 7z gives names and sizes only, not bytes, so
        # only the FORBIDDEN filename-pattern half of this check runs
        # here; the reader always returns empty, so the secret-content
        # scan is a no-op for the payload. That scan already ran for
        # real, on file content, in check_dir() against the same build
        # output these binaries were packed from, so this is not a gap,
        # just not repeated work.
        for relative in present:
            check_forbidden_and_secrets(
                relative,
                by_relative_size.get(relative, 0),
                lambda: b"",
                report,
                label + " payload",
            )
            base = os.path.basename(relative).lower()
            if base in {n.lower() for n in SIGNATURE_CANDIDATES}:
                report.note(
                    f"[{label} payload] {relative}: "
                    f"{by_relative_size.get(relative)} bytes (size only; "
                    "hashing/signing the payload copy requires unpacking it to "
                    "disk, not done here since --dir already covers the same "
                    "binaries built from the same output directory)"
                )


def check_dir(dir_path, report):
    """Checks a raw build output directory as a stand-in for a package.

    Only DIR_SCAN_SUBPATHS are scanned; see the module docstring for why.
    This is not equivalent to checking a real zip; it is the best
    available check when no zip has been produced yet, and it says so.
    """
    label = os.path.basename(os.path.normpath(dir_path)) or dir_path
    report.note(
        f"[{label}] this is a raw build output directory, not a packaged "
        "zip. boring/, locales/ and Dictionaries/ were scanned in full; the top level "
        "was narrowed to the specific files this tool checks for "
        "(required files, notices, and known binaries), not the "
        "hundreds of build-tool binaries, .pdb files and test binaries "
        "that also sit there and were never going to be staged into a "
        "package. This is not a full audit of the directory."
    )

    present = set()
    file_paths = {}
    for sub in DIR_SCAN_SUBPATHS:
        base = os.path.join(dir_path, sub) if sub else dir_path
        if not os.path.isdir(base):
            continue
        if sub == "":
            known = _top_level_known_names()
            names = [
                n
                for n in os.listdir(base)
                if os.path.isfile(os.path.join(base, n)) and n in known
            ]
        else:
            names = []
            for root, _dirs, files in os.walk(base):
                for name in files:
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, dir_path).replace("\\", "/")
                    names.append(rel)
            for rel in names:
                present.add(rel)
                file_paths[rel] = os.path.join(dir_path, rel.replace("/", os.sep))
            continue
        for name in names:
            present.add(name)
            file_paths[name] = os.path.join(base, name)

    check_required_sets(present, report, label)

    for relative, full_path in file_paths.items():
        try:
            size = os.path.getsize(full_path)
        except OSError:
            continue

        def reader(full_path=full_path):
            with open(full_path, "rb") as f:
                return f.read()

        check_forbidden_and_secrets(relative, size, reader, report, label)
        check_feature_contents(relative, reader, report, label)

        base_name = os.path.basename(relative).lower()
        if base_name in {n.lower() for n in SIGNATURE_CANDIDATES}:
            digest = sha256_of_file(full_path)
            status, signer = authenticode_status(full_path)
            status_text = status if status is not None else "not verified"
            report.note(
                f"[{label}] {relative}: {size} bytes, sha256 {digest}, "
                f"Authenticode {status_text}" + (f", signer {signer}" if signer else "")
            )
            if status is not None and status not in ("NotSigned", "Valid"):
                report.fail(
                    f"[{label}] {relative} Authenticode status is {status}, "
                    "not NotSigned or Valid"
                )

    check_not_shipped(file_paths.keys(), report, label)


def check_version_dir(dir_path, expect, report):
    label = os.path.basename(os.path.normpath(dir_path)) or dir_path
    chrome_exe = os.path.join(dir_path, "chrome.exe")
    if not os.path.isfile(chrome_exe):
        return
    version = file_version(chrome_exe)
    if version is None:
        report.fail(f"[{label}] could not read chrome.exe's file version")
        return
    report.note(f"[{label}] chrome.exe file version {version}")
    if expect and not version.startswith(expect):
        report.fail(f"[{label}] chrome.exe says {version} but {expect} was expected")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="a packaged zip to inspect")
    ap.add_argument("--installer", help="a mini_installer.exe to inspect")
    ap.add_argument(
        "--dir",
        help="a raw build output directory (e.g. out\\Default) to inspect "
        "when no zip exists yet",
    )
    ap.add_argument("--expect-version", help="e.g. 151.0.7922.173")
    ap.add_argument(
        "--version-file",
        help="a chrome/VERSION file; if given and --expect-version is not, "
        "the expected version is read from here",
    )
    args = ap.parse_args()

    if not (args.zip or args.installer or args.dir):
        sys.exit("give at least one of --zip, --installer, --dir")

    expect = args.expect_version
    if not expect and args.version_file:
        if not os.path.isfile(args.version_file):
            sys.exit("no VERSION file at " + args.version_file)
        expect = read_version_file(args.version_file)
        if not expect:
            sys.exit(args.version_file + " did not parse as a VERSION file")
        print("expected version from", args.version_file, "is", expect)

    report = Report()

    if args.zip:
        print("reading", args.zip)
        if not os.path.isfile(args.zip):
            report.fail("no zip at " + args.zip)
        else:
            check_contents_zip(args.zip, report)
            check_version_zip(args.zip, expect, report)
            report.note(
                f"{os.path.basename(args.zip)}: sha256 {sha256_of_file(args.zip)}"
            )

    if args.dir:
        print("reading", args.dir)
        if not os.path.isdir(args.dir):
            report.fail("no directory at " + args.dir)
        else:
            check_dir(args.dir, report)
            check_version_dir(args.dir, expect, report)

    if args.installer:
        print("reading", args.installer)
        if not os.path.isfile(args.installer):
            report.fail("no installer at " + args.installer)
        else:
            check_installer(args.installer, expect, report)

    return report.finish()


if __name__ == "__main__":
    sys.exit(main())
