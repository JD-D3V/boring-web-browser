#!/usr/bin/env python3
"""Pick the right ninja for a Chromium tree, and refuse a log version clash.

The Chromium 157 trees are built with the ninja inside the tree
(third_party/ninja/ninja.exe, 1.12.x), which writes a version 6
out/Default/.ninja_log. A newer ninja on PATH (1.13 and up) needs version 7
and deletes a version 6 log on any run, even a dry run, which forces a full
rebuild that takes hours.

Usage:
  python ninja_guard.py <out dir>

Prints the path of the ninja to run on stdout and exits 0. When that ninja
would wreck the existing log, prints one line on stderr and exits 1.
It never runs a build and never touches the log.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

# Ninja 1.12 and older write log version 6; 1.13 and newer write version 7.
FIRST_VERSION_7 = (1, 13)
LOG_HEADER = re.compile(r"^# ninja log v(\d+)\s*$")


class GuardError(Exception):
    """The chosen ninja must not be run against this tree."""


def log_version_for(version: tuple[int, int]) -> int:
    """The .ninja_log version a ninja of this (major, minor) writes."""
    return 7 if version >= FIRST_VERSION_7 else 6


def parse_version(text: str) -> tuple[int, int]:
    """(major, minor) from `ninja --version` output such as '1.12.1.git'."""
    found = re.match(r"\s*(\d+)\.(\d+)", text)
    if not found:
        raise GuardError(f"cannot read the ninja version from {text.strip()!r}")
    return int(found.group(1)), int(found.group(2))


def read_log_version(log: Path) -> int | None:
    """The version in the first line of a .ninja_log, or None for no file.

    An empty file counts as no log: there is nothing in it to lose.
    """
    if not log.is_file():
        return None
    with log.open("rb") as handle:
        first = handle.readline().decode("utf-8", errors="replace")
    if not first.strip():
        return None
    found = LOG_HEADER.match(first)
    if not found:
        raise GuardError(f"cannot read the log version from the first line of {log}")
    return int(found.group(1))


def tree_ninja(out: Path) -> Path | None:
    """The ninja inside the tree that owns this out dir, if it has one."""
    name = "ninja.exe" if sys.platform == "win32" else "ninja"
    candidate = out.resolve().parent.parent / "third_party" / "ninja" / name
    return candidate if candidate.is_file() else None


def choose_ninja(out: Path) -> Path:
    """The tree's own ninja, else the one on PATH."""
    own = tree_ninja(out)
    if own is not None:
        return own
    on_path = shutil.which("ninja")
    if on_path is None:
        raise GuardError("no ninja in the tree and none on PATH")
    return Path(on_path)


def ninja_version(exe: Path) -> tuple[int, int]:
    """Ask a ninja for its version. Runs `--version` only."""
    try:
        done = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as err:
        raise GuardError(f"cannot run {exe} --version: {err}") from err
    return parse_version(done.stdout)


def guard(out: Path) -> Path:
    """The ninja to run for this out dir, or GuardError if it would wreck the log."""
    exe = choose_ninja(out)
    log = out / ".ninja_log"
    have = read_log_version(log)
    if have is None:
        return exe
    version = ninja_version(exe)
    wants = log_version_for(version)
    if wants != have:
        raise GuardError(
            f"refusing to run: {exe} (ninja {version[0]}.{version[1]}) writes "
            f"log version {wants} but {log} is version {have}, "
            f"and it would delete the log and force a full rebuild"
        )
    return exe


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: ninja_guard.py <out dir>", file=sys.stderr)
        return 2
    try:
        print(guard(Path(args[0])))
    except GuardError as err:
        print(str(err), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
