r"""Find strings the Chromium branded build uses but does not define.

Chromium keeps two sets of branded strings: google_chrome_strings.grd
for Chrome, chromium_strings.grd for everything else. Code reads them
through one header, so a string added to only the Chrome file still
compiles for Google and fails for us, with an undeclared identifier
thousands of targets into a build.

Three of them were waiting in Chromium 153.0.8010.47, in
chrome/browser/win/installer_downloader, far enough into the build that
finding them by compiling costs the better part of a day each. This
answers the question in about ten minutes of reading instead.

It reads both .grd files from git rather than from the working tree, on
purpose. rebrand.py rewrites chromium_strings.grd in place, so the
working copy is ours. That matters more than it sounds: a run of this
check against a working tree that held the wrong Chromium version's
string file produced a confident, wrong answer, and the wrong answer
was acted on.

What it does:

  1. reads the message names out of both .grd files
  2. takes the ones only Chrome defines
  3. finds every use of those names in the source
  4. reports a use only when it is not inside a
     #if BUILDFLAG(GOOGLE_CHROME_BRANDING) block, because one that is
     guarded is never compiled for us

The guard test tracks #if nesting properly rather than searching for
the word nearby, so a use guarded three levels up still counts as
guarded. It does not evaluate the preprocessor, so a use behind
#if !BUILDFLAG(GOOGLE_CHROME_BRANDING) is reported; that is the right
way round, because a false report costs a minute and a miss costs a
build.

A second job lives here too, run with --leftovers: the opposite
question. rebrand.py renames the product, so the question is whether
"Chromium" still shows anywhere a person looks at the installer or the
download. It reads:

  - the installer string resources the build generated
    (gen\chrome\installer\**\*.rc, UTF-16 for the string table), and
    checks that the English product name and publisher are the ones in
    product_name.py and that setup.exe was built after them
  - the files in a release folder, which rename_release.py fills: their
    names, and the name of every entry inside each zip

Credit and licence text may keep naming the project: "The Chromium
Authors", "Chromium project", chromium.org, NOTICES-* and LICENSE*
files, and the folder of the vendored Chromium Web Store extension,
which is the extension's own name. Anything else is a failure.

Usage:
  python branded_string_check.py --src E:\ung-153-47\build\src
  python branded_string_check.py --src ... --json out.json
  python branded_string_check.py --leftovers --out E:\ung-154\build\src\out\Default
  python branded_string_check.py --leftovers --release-dir E:\tmp\dist
"""

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

MESSAGE_NAME = re.compile(r'<message\s+name\s*=\s*"([A-Z0-9_]+)"')

CHROME_GRD = "chrome/app/google_chrome_strings.grd"
CHROMIUM_GRD = "chrome/app/chromium_strings.grd"

# Where code that reads branded strings lives. Walking the whole tree
# would mean reading a few hundred thousand files to find a handful.
SEARCH_ROOTS = ["chrome", "components", "ui"]

SOURCE_SUFFIXES = (".cc", ".h", ".mm")

GUARD = "BUILDFLAG(GOOGLE_CHROME_BRANDING)"


def grd_text(src: Path, rel: str) -> tuple[str, str]:
    """The .grd as upstream wrote it, and where that came from.

    Read from git rather than from the working tree, and this is the
    whole point of the function. `rebrand.py` rewrites
    chromium_strings.grd in place, so the working copy is ours, not
    upstream's. Worse, when it once read a pristine store belonging to a
    different Chromium version it wrote *that version's* string file
    over the tree, and a check reading the working copy then compared
    151's strings against 153's and reported a missing string that was
    never missing. Asking git removes the whole class of mistake.
    """
    result = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=src,
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout, "git HEAD"

    path = src / rel
    if not path.exists():
        sys.exit(f"no such file: {path}")
    print(
        f"WARNING: {rel} could not be read from git, so this is comparing\n"
        "         the working tree, which our own tooling rewrites. A result\n"
        "         from here is a hint, not an answer.",
        file=sys.stderr,
    )
    return path.read_text(encoding="utf-8", errors="replace"), "working tree"


def message_names(text: str) -> set[str]:
    return set(MESSAGE_NAME.findall(text))


def already_handled() -> set[str]:
    """Names rebrand.py puts back, so a fixed one stops being reported."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from rebrand import MISSING_BRANDED_MESSAGES
    except ImportError:
        return set()
    return {name for name, _desc, _body in MISSING_BRANDED_MESSAGES}


def write_report(path: str, by_name: dict) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(by_name, indent=2), encoding="utf-8")
    print("\nwrote", out)


def guarded_lines(text: str) -> list[bool]:
    """For each line, whether it sits inside a Chrome branding guard.

    Tracks the #if stack so a use nested inside other conditionals is
    still known to be guarded by an outer one.
    """
    inside: list[bool] = []
    stack: list[bool] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#if"):
            stack.append(GUARD in stripped and not stripped.startswith("#if !"))
        elif stripped.startswith("#elif"):
            if stack:
                stack[-1] = GUARD in stripped and "!" not in stripped
        elif stripped.startswith("#else"):
            if stack:
                # The other half of a branding guard is the half that is
                # ours, so it is not guarded.
                stack[-1] = False
        elif stripped.startswith("#endif") and stack:
            stack.pop()
        inside.append(any(stack))
    return inside


def uses(src: Path, names: set[str]) -> list[dict]:
    """Every unguarded use of a Chrome only string, with its line."""
    if not names:
        return []
    found = []
    for root_name in SEARCH_ROOTS:
        root = src / root_name
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # Nothing in a test or a third party tree ends up in the
            # browser we ship, and both are enormous.
            dirnames[:] = [
                d for d in dirnames if d not in ("third_party", "test", "tests")
            ]
            for filename in filenames:
                if not filename.endswith(SOURCE_SUFFIXES):
                    continue
                path = Path(dirpath) / filename
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if "IDS_" not in text:
                    continue
                hits = [n for n in names if n in text]
                if not hits:
                    continue
                guards = guarded_lines(text)
                for number, line in enumerate(text.splitlines()):
                    for name in hits:
                        if name not in line:
                            continue
                        if guards[number]:
                            continue
                        found.append(
                            {
                                "name": name,
                                "file": str(path.relative_to(src)).replace("\\", "/"),
                                "line": number + 1,
                                "text": line.strip()[:120],
                            }
                        )
    return found


LEFTOVER = re.compile(r"chromium", re.IGNORECASE)

# Text that has to keep naming the project: the copyright holder, the
# credit to the project, and links to it.
CREDIT = re.compile(
    r"The Chromium Authors|Chromium Authors|Chromium project|chromium\.org",
    re.IGNORECASE,
)

# A file or folder name that may keep the word: a notice travels with the
# thing it is the notice for, and the Chromium Web Store is a third party
# extension that goes by that name.
ALLOWED_NAME = re.compile(r"^(NOTICES[-.]|LICENSE)|^chromium-web-store$", re.IGNORECASE)

INSTALLER_RESOURCES = Path("gen") / "chrome" / "installer"
STRINGS_RC = "installer_util_strings.rc"


def read_resource(path: Path) -> str:
    """A generated .rc as text. The string table is UTF-16, the rest ASCII."""
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def text_leftovers(text: str) -> list[tuple[int, str]]:
    """Lines that say Chromium once the credit phrases are taken out."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        if LEFTOVER.search(CREDIT.sub("", line)):
            found.append((number, line.strip()[:140]))
    return found


def name_leftovers(path: str) -> bool:
    """Whether a file path still says Chromium outside the allowed names."""
    parts = [p for p in re.split(r"[\\/]", path) if p]
    return any(LEFTOVER.search(p) and not ALLOWED_NAME.match(p) for p in parts)


def string_value(text: str, name: str) -> str | None:
    match = re.search(rf'^\s*{re.escape(name)}\s+"(.*)"\s*$', text, re.MULTILINE)
    return match.group(1) if match else None


def resource_problems(out: Path) -> list[str]:
    """Leftovers in the generated installer resources, and a stale setup.exe."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from product_name import NAME, PUBLISHER

    root = out / INSTALLER_RESOURCES
    strings = root / "util" / STRINGS_RC
    if not strings.is_file():
        return [f"no {STRINGS_RC} under {root}; the build has not generated it"]

    problems = []
    files = sorted(root.rglob("*.rc"))
    for path in files:
        rel = path.relative_to(out).as_posix()
        for number, line in text_leftovers(read_resource(path)):
            problems.append(f"{rel}:{number}: {line}")

    text = read_resource(strings)
    for name, want in (
        ("IDS_PRODUCT_NAME_EN_US", NAME),
        ("IDS_ABOUT_VERSION_COMPANY_NAME_EN_US", PUBLISHER),
    ):
        got = string_value(text, name)
        if got != want:
            problems.append(
                f"{STRINGS_RC}: {name} is {got!r}, product_name.py says {want!r}"
            )

    # The .rc is only the input. setup.exe is what ships, and it is not
    # rebuilt by anything but the mini_installer target.
    setup = out / "setup.exe"
    if setup.is_file() and NAME.encode("utf-16-le") not in setup.read_bytes():
        problems.append(
            f"setup.exe does not contain {NAME!r}; it was built before the "
            "strings changed, build mini_installer"
        )
    elif not setup.is_file():
        problems.append(f"no setup.exe in {out}")
    print(f"read {len(files)} installer resource files under {root}")
    return problems


def release_problems(folder: Path) -> list[str]:
    """Leftovers in the names of a release folder's files and zip entries."""
    if not folder.is_dir():
        return [f"no folder at {folder}"]
    problems = []
    count = 0
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        count += 1
        if name_leftovers(path.name):
            problems.append(f"{folder.name}/{path.name}: the file name says Chromium")
        if path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    entries = archive.namelist()
            except zipfile.BadZipFile as error:
                problems.append(f"{path.name}: not a zip: {error}")
                continue
            bad = [e for e in entries if name_leftovers(e)]
            for entry in bad[:5]:
                problems.append(f"{path.name}: entry {entry}")
            if len(bad) > 5:
                problems.append(f"{path.name}: and {len(bad) - 5} more entries")
    if not count:
        problems.append(f"{folder} holds no files to check")
    print(f"read {count} release files in {folder}")
    return problems


def leftovers_main(args) -> int:
    if not args.out and not args.release_dir:
        sys.exit("--leftovers needs --out (or BORING_OUT) and/or --release-dir")
    problems = []
    if args.out:
        problems += resource_problems(Path(args.out))
    for folder in args.release_dir:
        problems += release_problems(Path(folder))
    if problems:
        print(f"\n{len(problems)} leftover(s):\n")
        for line in problems:
            print("  ", line)
        return 1
    print("no leftover Chromium outside credit and licence text")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="a Chromium source tree")
    ap.add_argument("--json", help="write the whole report here")
    ap.add_argument(
        "--leftovers",
        action="store_true",
        help="look for Chromium left in the built installer and the release files",
    )
    ap.add_argument(
        "--out",
        default=os.environ.get("BORING_OUT"),
        help="build output folder for --leftovers (default: BORING_OUT)",
    )
    ap.add_argument(
        "--release-dir",
        action="append",
        default=[],
        help="folder rename_release.py wrote, for --leftovers; may repeat",
    )
    args = ap.parse_args(argv)

    if args.leftovers:
        return leftovers_main(args)
    if not args.src:
        ap.error("--src is required unless --leftovers is given")

    src = Path(args.src)
    chrome_text, chrome_from = grd_text(src, CHROME_GRD)
    chromium_text, chromium_from = grd_text(src, CHROMIUM_GRD)
    print(f"branded strings read from {chrome_from} and {chromium_from}")
    chrome_only = message_names(chrome_text) - message_names(chromium_text)
    print(f"{len(chrome_only)} strings are defined for Chrome only")

    found = uses(src, chrome_only)
    if not found:
        print("none of them are used outside a Chrome branding guard")
        return 0

    by_name: dict[str, list[dict]] = {}
    for hit in found:
        by_name.setdefault(hit["name"], []).append(hit)

    # The .grd came from git, so it does not know about the strings we
    # already put back. Without this the tool would report the same
    # names for ever and could never be a gate that passes.
    handled = already_handled()
    outstanding = sorted(set(by_name) - handled)
    covered = sorted(set(by_name) & handled)

    if covered:
        print(f"\n{len(covered)} already covered by rebrand.py:\n")
        for name in covered:
            print("  ", name)

    if not outstanding:
        print(
            "\nNothing outstanding. Every Chrome only string this build "
            "reads is already put back."
        )
        if args.json:
            write_report(args.json, by_name)
        return 0

    print(f"\n{len(outstanding)} would not compile in a Chromium branded build:\n")
    for name in outstanding:
        print(" ", name)
        for hit in by_name[name]:
            print(f"      {hit['file']}:{hit['line']}")

    print("\nAdd each one to MISSING_BRANDED_MESSAGES in rebrand.py, with the")
    print("text upstream uses and the product name left as Chromium.")

    if args.json:
        write_report(args.json, by_name)
    return 1


if __name__ == "__main__":
    sys.exit(main())
