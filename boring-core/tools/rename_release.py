#!/usr/bin/env python3
"""Give the packaged browser its release names, and write the checksums.

ungoogled-chromium's package.py names its output after itself:

  ungoogled-chromium_<chromium>-<rev>.<packrev>_installer_x64.exe
  ungoogled-chromium_<chromium>-<rev>.<packrev>_windows_x64.zip

What people download is called

  BoringBrowser_<chromium>.<release>_installer_x64.exe
  BoringBrowser_<chromium>.<release>_windows_x64.zip

where <release> is kBoringRelease from
components/boring/core/boring_release.h, the same number the updater
appends to the Chromium version. So the name on the download, the
version in the update feed and the version the browser compares are one
number.

The package files are copied, never moved, so the build folder keeps
what package.py made. The copy is refused when the Chromium version in
the file names is not the one in chrome/VERSION, when the two files do
not come from the same package run, or when a file of the release name
is already there. SHA256SUMS.txt is written last, from the bytes of the
copies, so it describes exactly what gets uploaded.

Authenticode signing of the installer, when there is a certificate,
happens before this step, on package.py's output. Signing changes the
bytes, and the checksums have to describe the signed file.

Usage:
  cd /d E:\\ung\\build
  python rename_release.py --version-file src\\chrome\\VERSION \\
      --installer ungoogled-chromium_153.0.8010.52-1.1_installer_x64.exe \\
      --zip ungoogled-chromium_153.0.8010.52-1.1_windows_x64.zip \\
      --out E:\\tmp\\release
"""

import argparse
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import NamedTuple

TOOLS = Path(__file__).resolve().parent
CORE = TOOLS.parent
DEFAULT_RELEASE_HEADER = CORE / "components" / "boring" / "core" / "boring_release.h"

PRODUCT = "BoringBrowser"
SUMS_NAME = "SHA256SUMS.txt"

CONFIG_ERROR = 2

_VERSION_PARTS = ("MAJOR", "MINOR", "BUILD", "PATCH")
_RELEASE_LINE = re.compile(
    r"^\s*inline\s+constexpr\s+int\s+kBoringRelease\s*=\s*(\d+)\s*;", re.MULTILINE
)
_PACKAGE_NAME = re.compile(
    r"^ungoogled-chromium_(?P<chromium>\d+\.\d+\.\d+\.\d+)-(?P<revision>\d+\.\d+)"
    r"_(?P<kind>installer_x64\.exe|windows_x64\.zip)$"
)


class ReleaseError(RuntimeError):
    """Something about the inputs means this is not a release to name."""


class PackageName(NamedTuple):
    chromium: str
    revision: str
    kind: str


def read_chromium_version(path: Path) -> str:
    """The four part version from Chromium's chrome/VERSION file."""
    parts = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = raw.strip().partition("=")
        if sep:
            parts[key.strip()] = value.strip()
    missing = [p for p in _VERSION_PARTS if not parts.get(p, "").isdigit()]
    if missing:
        raise ReleaseError(f"{path} has no usable {', '.join(missing)}")
    return ".".join(parts[p] for p in _VERSION_PARTS)


def read_boring_release(path: Path) -> int:
    """kBoringRelease from boring_release.h, which keeps it on one line."""
    found = _RELEASE_LINE.findall(path.read_text(encoding="utf-8"))
    if len(found) != 1:
        raise ReleaseError(
            f"expected one kBoringRelease line in {path}, found {len(found)}"
        )
    release = int(found[0])
    if release < 1:
        raise ReleaseError(f"kBoringRelease is {release}, it starts at 1")
    return release


def parse_package_name(name: str) -> PackageName:
    match = _PACKAGE_NAME.match(name)
    if not match:
        raise ReleaseError(f"{name} is not a name package.py writes")
    return PackageName(match["chromium"], match["revision"], match["kind"])


def release_version(chromium: str, release: int) -> str:
    """What the updater compares: the Chromium version, then ours."""
    return f"{chromium}.{release}"


def release_names(chromium: str, release: int) -> tuple[str, str]:
    stem = f"{PRODUCT}_{release_version(chromium, release)}"
    return f"{stem}_installer_x64.exe", f"{stem}_windows_x64.zip"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_inputs(installer: Path, zip_path: Path, chromium: str) -> None:
    """Refuse package files that are not this build's pair."""
    for path in (installer, zip_path):
        if not path.is_file():
            raise ReleaseError(f"no file at {path}")
    got_installer = parse_package_name(installer.name)
    got_zip = parse_package_name(zip_path.name)
    if got_installer.kind != "installer_x64.exe":
        raise ReleaseError(f"{installer.name} is not the installer")
    if got_zip.kind != "windows_x64.zip":
        raise ReleaseError(f"{zip_path.name} is not the zip")
    for got, path in ((got_installer, installer), (got_zip, zip_path)):
        if got.chromium != chromium:
            raise ReleaseError(
                f"{path.name} says Chromium {got.chromium}, "
                f"but chrome/VERSION says {chromium}"
            )
    if got_installer.revision != got_zip.revision:
        raise ReleaseError(
            f"the installer is revision {got_installer.revision} and the zip "
            f"{got_zip.revision}, so they are not from the same package run"
        )


def copy_exactly(source: Path, destination: Path) -> str:
    """Copy through a .part file, check the copy, return its sha256."""
    if destination.exists():
        raise ReleaseError(f"{destination} is already there, refusing to replace it")
    partial = destination.with_name(destination.name + ".part")
    shutil.copyfile(source, partial)
    copied = sha256_of(partial)
    if copied != sha256_of(source):
        partial.unlink()
        raise ReleaseError(f"the copy of {source.name} does not match the original")
    os.replace(partial, destination)
    return copied


def write_sums(folder: Path, names: list[str]) -> Path:
    """SHA256SUMS.txt in the format sha256sum -c reads, from the final bytes."""
    lines = [f"{sha256_of(folder / name)}  {name}\n" for name in sorted(names)]
    sums = folder / SUMS_NAME
    with open(sums, "w", encoding="ascii", newline="\n") as f:
        f.writelines(lines)
    return sums


def rename_release(
    installer: Path,
    zip_path: Path,
    version_file: Path,
    release_header: Path,
    out: Path,
    expect_version: str | None = None,
) -> dict[str, str]:
    """Copy the pair to their release names and write the checksums.

    Returns what the release steps after this one need to know.
    """
    chromium = read_chromium_version(version_file)
    release = read_boring_release(release_header)
    version = release_version(chromium, release)
    if expect_version is not None and not (
        expect_version == version or expect_version.startswith(version + "-")
    ):
        raise ReleaseError(
            f"asked to release {expect_version}, but the source says {version} "
            f"(Chromium {chromium}, kBoringRelease {release})"
        )
    check_inputs(installer, zip_path, chromium)

    installer_name, zip_name = release_names(chromium, release)
    out.mkdir(parents=True, exist_ok=True)
    if (out / SUMS_NAME).exists():
        raise ReleaseError(f"{out / SUMS_NAME} is already there, use a clean folder")
    copy_exactly(installer, out / installer_name)
    copy_exactly(zip_path, out / zip_name)
    sums = write_sums(out, [installer_name, zip_name])
    return {
        "CHROMIUM_VERSION": chromium,
        "BORING_RELEASE": str(release),
        "BORING_VERSION": version,
        "RELEASE_INSTALLER": str(out / installer_name),
        "RELEASE_ZIP": str(out / zip_name),
        "RELEASE_SUMS": str(sums),
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Copy the packaged browser to its release names."
    )
    ap.add_argument("--installer", required=True, type=Path)
    ap.add_argument("--zip", required=True, type=Path, dest="zip_path")
    ap.add_argument(
        "--version-file",
        required=True,
        type=Path,
        help="chrome/VERSION of the tree the packages were built from",
    )
    ap.add_argument(
        "--release-header",
        type=Path,
        default=DEFAULT_RELEASE_HEADER,
        help="boring_release.h the browser was built with (default: ours)",
    )
    ap.add_argument("--out", required=True, type=Path, help="release folder")
    ap.add_argument(
        "--expect-version",
        default=None,
        help=(
            "refuse unless the release is this version, or this version "
            "with a -suffix, for example 153.0.8010.52.1-beta"
        ),
    )
    ap.add_argument(
        "--env-out",
        type=Path,
        default=None,
        help="append NAME=value lines here, for example $GITHUB_ENV",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = rename_release(
            args.installer,
            args.zip_path,
            args.version_file,
            args.release_header,
            args.out,
            args.expect_version,
        )
    except (ReleaseError, OSError) as error:
        print(f"rename_release: {error}", file=sys.stderr)
        return CONFIG_ERROR

    print(f"release {result['BORING_VERSION']}")
    print(Path(result["RELEASE_SUMS"]).read_text(encoding="ascii"), end="")
    if args.env_out:
        with open(args.env_out, "a", encoding="ascii", newline="\n") as f:
            for key, value in result.items():
                f.write(f"{key}={value}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
