#!/usr/bin/env python3
"""Syntax-check one C++ file with the flags of an existing Chromium object.

Usage:
  python boring-core/tools/check_compile.py <source.cc> --like <object path>
      [--out E:/ung-154/build/src/out/Default] [--gen-include DIR]

Takes the compile command ninja already has for --like (a path relative to
the out dir), points it at <source.cc>, puts boring-core's include roots
before Chromium's, and runs it with /Zs. Writes nothing, and runs no gn gen
or build.
"""

import argparse
import ctypes
import shlex
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
BORING_CORE = TOOLS.parent
DEFAULT_OUT = Path("E:/ung-154/build/src/out/Default")

SOURCE_FLAGS = ("/c", "-c")
# Options that name an output file or a listing. The check must write nothing.
OUTPUT_OPTIONS = ("Fo", "Fd", "Fa", "FA", "Fp", "FR", "showIncludes")
# Plain diagnostics, so the captured output has no terminal color codes.
PLAIN_DIAGNOSTICS = ("-fcolor-diagnostics",)


class CheckError(Exception):
    """A problem with the request itself, not a compile error."""


def split_command(line: str) -> list[str]:
    """Split a command line the way Windows programs read their arguments."""
    if sys.platform != "win32":
        return shlex.split(line)
    shell32 = ctypes.WinDLL("shell32")
    kernel32 = ctypes.WinDLL("kernel32")
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argc = ctypes.c_int()
    argv = shell32.CommandLineToArgvW(line, ctypes.byref(argc))
    if not argv:
        raise CheckError("could not split the ninja command line")
    try:
        return [argv[i] for i in range(argc.value)]
    finally:
        kernel32.LocalFree(argv)


def is_dropped(arg: str) -> bool:
    """True for options that would write output or are not wanted here."""
    if arg in PLAIN_DIAGNOSTICS:
        return True
    return arg[:1] in ("/", "-") and arg[1:].startswith(OUTPUT_OPTIONS)


def ninja_command(out: Path, obj: str) -> list[str]:
    """Return the compile command ninja uses for obj, as an argument list."""
    try:
        done = subprocess.run(
            ["ninja", "-C", str(out), "-t", "commands", "-s", obj],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as err:
        raise CheckError("ninja is not on PATH") from err
    if done.returncode != 0:
        raise CheckError((done.stderr or done.stdout).strip())
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    if not lines:
        raise CheckError(f"ninja printed no compile command for {obj}")
    return split_command(lines[-1])


def retarget(command: list[str], source: Path, gen_include: Path | None) -> list[str]:
    """Point a compile command at source and make it a syntax-only check."""
    cut = 0
    if command[1:3] == ["-t", "msvc"] and "--" in command:
        cut = command.index("--") + 1
    wrapper, compiler = command[:cut], command[cut:]

    src = next((i + 1 for i, arg in enumerate(compiler) if arg in SOURCE_FLAGS), None)
    if src is None or src >= len(compiler):
        raise CheckError("the compile command has no '/c <source>'")

    # /Zs replaces /c here; clang warns when both are given.
    kept = []
    for i, arg in enumerate(compiler):
        if i == src:
            kept.append(source.as_posix())
        elif arg in SOURCE_FLAGS or is_dropped(arg):
            continue
        else:
            kept.append(arg)

    added = [
        f"/I{(BORING_CORE / 'chromium_src').as_posix()}",
        f"/I{BORING_CORE.as_posix()}",
    ]
    if gen_include is not None:
        added.append(f"/I{gen_include.as_posix()}")
    # Our roots go before the first include path, so they win the lookup.
    first = next(
        (i for i, arg in enumerate(kept) if arg.startswith(("-I", "/I"))),
        len(kept),
    )
    kept[first:first] = added
    kept.append("/Zs")
    return wrapper + kept


def run_check(source: Path, like: str, out: Path, gen_include: Path | None) -> int:
    """Run the check and print the compiler's output; returns its exit code."""
    source = source.resolve()
    if not source.is_file():
        raise CheckError(f"no such source file: {source}")
    if not (out / "build.ninja").is_file():
        raise CheckError(f"no build.ninja in {out}; point --out at a built out dir")

    command = retarget(ninja_command(out, Path(like).as_posix()), source, gen_include)
    if "/" in command[0] or "\\" in command[0]:
        command[0] = str((out / command[0]).resolve())

    started = time.monotonic()
    done = subprocess.run(
        command,
        cwd=out,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    seconds = time.monotonic() - started

    text = done.stdout + done.stderr
    if text.strip():
        sys.stderr.write(text if text.endswith("\n") else text + "\n")
    if done.returncode == 0:
        print(f"{source.name}: compiles (syntax only, {seconds:.1f} s)")
    else:
        print(f"{source.name}: does not compile ({seconds:.1f} s)", file=sys.stderr)
    return done.returncode


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the check."""
    parser = argparse.ArgumentParser(
        description="Syntax-check one C++ file with an existing object's flags."
    )
    parser.add_argument("source", type=Path, help="C++ source file to check")
    parser.add_argument(
        "--like",
        required=True,
        metavar="OBJ",
        help="object path relative to the out dir, e.g. obj/chrome/.../x.obj",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="built out dir (default: %(default)s)",
    )
    parser.add_argument(
        "--gen-include",
        type=Path,
        metavar="DIR",
        help="extra include dir holding generated headers",
    )
    args = parser.parse_args(argv)
    try:
        return run_check(args.source, args.like, args.out, args.gen_include)
    except CheckError as err:
        print(f"check_compile: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
