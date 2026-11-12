#!/usr/bin/env python3
"""Write the winget manifests for a release from its release folder.

  python make_winget.py --release-dir E:\\tmp\\release-157 [--release-date 2026-11-20]

The release folder is what rename_release.py made: one
<ID>_<chromium>.<release>_installer_x64.exe and SHA256SUMS.txt. The
version comes from the installer's name, the hash from its bytes (and
must agree with SHA256SUMS.txt when that is there).

The three manifest files are copied from the newest version folder under
packaging/winget/manifests/j/JD-D3V/BoringBrowser (or from --template)
into a folder named after the version, with these lines filled in:
PackageVersion, InstallerUrl, InstallerSha256, DisplayVersion (Chromium's
version, which is what the uninstall entry shows), ReleaseNotesUrl and,
when given, ReleaseDate. Everything else, comments included, is kept.
Run it again on a rebuilt release and only the hash changes.

Nothing is uploaded or submitted. See SUBMIT.txt in the winget research
folder for the pull request to microsoft/winget-pkgs.
"""

import argparse
import datetime
import hashlib
import re
import sys
from pathlib import Path

from product_name import ID

REPO = Path(__file__).resolve().parents[2]
MANIFESTS = REPO / "packaging" / "winget" / "manifests"
PACKAGE_ID = "JD-D3V.BoringBrowser"
PACKAGE_DIR = Path("j", "JD-D3V", "BoringBrowser")
RELEASES = "https://github.com/JD-D3V/boring-web-browser/releases"
INSTALLER = re.compile(rf"^{ID}_(\d+\.\d+\.\d+\.\d+\.\d+)_installer_x64\.exe$")


def fail(message):
    print(f"make_winget: {message}", file=sys.stderr)
    return 1


def version_key(name):
    return tuple(int(part) for part in name.split("."))


def set_field(text, key, value, *, insert_before=None):
    """Replaces the value of the one `key:` line, keeping its indent.

    With insert_before, a missing key is added as a top-level line just
    above that top-level key instead.
    """
    pattern = re.compile(rf"^(\s*-?\s*{key}:)[ \t]*\S.*$", re.M)
    found = pattern.findall(text)
    if len(found) == 1:
        return pattern.sub(lambda m: f"{m.group(1)} {value}", text)
    if not found and insert_before:
        anchor = re.compile(rf"^{insert_before}:", re.M)
        if len(anchor.findall(text)) == 1:
            return anchor.sub(lambda m: f"{key}: {value}\n{m.group(0)}", text)
    raise ValueError(f"expected one {key}: line, found {len(found)}")


def find_installer(release_dir):
    found = [p for p in release_dir.iterdir() if INSTALLER.match(p.name)]
    if len(found) != 1:
        names = ", ".join(p.name for p in found) or "none"
        raise ValueError(
            f"expected one {ID}_<version>_installer_x64.exe, found {names}"
        )
    return found[0], INSTALLER.match(found[0].name).group(1)


def checked_sha256(installer):
    sha = hashlib.sha256(installer.read_bytes()).hexdigest()
    sums = installer.parent / "SHA256SUMS.txt"
    if sums.exists():
        listed = [
            line.split()[0].lower()
            for line in sums.read_text(encoding="utf-8").splitlines()
            if line.split()[1:] and line.split()[-1].lstrip("*") == installer.name
        ]
        if listed != [sha]:
            raise ValueError(
                f"SHA256SUMS.txt says {listed} for {installer.name}, the file is {sha}"
            )
    return sha.upper()


def fill(template_dir, out_dir, version, sha, release_date):
    chromium = version.rsplit(".", 1)[0]
    url = f"{RELEASES}/download/v{version}/{ID}_{version}_installer_x64.exe"
    texts = {}
    for suffix in ("", ".installer", ".locale.en-US"):
        name = f"{PACKAGE_ID}{suffix}.yaml"
        text = (template_dir / name).read_text(encoding="utf-8")
        text = set_field(text, "PackageVersion", version)
        if suffix == ".installer":
            text = set_field(text, "InstallerUrl", url)
            text = set_field(text, "InstallerSha256", sha)
            text = set_field(text, "DisplayVersion", chromium)
            if release_date:
                text = set_field(
                    text, "ReleaseDate", release_date, insert_before="Installers"
                )
        if suffix == ".locale.en-US":
            text = set_field(text, "ReleaseNotesUrl", f"{RELEASES}/tag/v{version}")
        texts[name] = text
    # Written only once all three filled cleanly.
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        (out_dir / name).write_text(text, encoding="utf-8", newline="\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--manifests", type=Path, default=MANIFESTS)
    parser.add_argument("--template", type=Path, help="version folder to copy from")
    parser.add_argument(
        "--release-date", help="YYYY-MM-DD, the day the release went public"
    )
    args = parser.parse_args(argv)

    try:
        if args.release_date:
            datetime.date.fromisoformat(args.release_date)
        installer, version = find_installer(args.release_dir)
        sha = checked_sha256(installer)
        package = args.manifests / PACKAGE_DIR
        out_dir = package / version
        template = args.template
        if template is None:
            folders = [p for p in package.iterdir() if p.is_dir()]
            template = (
                out_dir
                if out_dir in folders
                else max(folders, key=lambda p: version_key(p.name))
            )
        fill(template, out_dir, version, sha, args.release_date)
    except (OSError, ValueError) as error:
        return fail(error)
    print(f"{out_dir}\n  version {version}\n  sha256  {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
