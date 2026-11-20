#!/usr/bin/env python3
"""Check the compiled UI's icons made it into the build, and photograph them.

Two parts. Without starting the browser: every icon tools/icon_map.py wrote
under chromium_src is in the build's generated vector_icons.cc command for
command (so the build drew ours, not Chromium's), every icon of ours is
declared in the generated header, and every Incognito icon is the ghost.
Then it starts the built browser four times (normal and Incognito, light and
dark), photographs each window by PrintWindow, and copies the matching
compiled screens beside the pictures for a person to compare: the toolbar
(back, forward, reload, the menu dots), the tab strip's new tab and close,
and in Incognito the ghost on the avatar button. Sends no mouse or keys.

    python smoke_icons.py [--out DIR]       # needs the built browser (BORING_OUT)

Compiled screens: design/v12-compiled/shots-final (c01 new tab, c07 menu,
and dark/ when present). The pictures are for eyes; what the script fails
on is the build check and a window that did not draw.
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import icon_map
from capture_native import frame_window, grab
from drive import CHROME, OUT
from smoke_local import Checks
from smoke_memory import close, launch

TOOLS = Path(__file__).resolve().parent
CHROMIUM_SRC = TOOLS.parent / "chromium_src"
SHOTS = TOOLS.parents[1] / "design" / "v12-compiled" / "shots-final"
SCREENS = ("c01-newtab.png", "c07-menuopen.png")
TOKEN = re.compile(r"[A-Z][A-Z_]+|-?\d*\.\d+|-?\d+")
# A PrintWindow of a window that never painted is one flat colour, which
# compresses to almost nothing; a drawn toolbar and tab strip do not.
DRAWN_BYTES = 10000


def tokens(text):
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("//"))
    return " ".join(TOKEN.findall(body))


def ours_written():
    """The .icon files under chromium_src that icon_map.py writes."""
    for path in sorted(CHROMIUM_SRC.rglob("*.icon")):
        if "from the rounded icon set" in path.read_text(encoding="utf-8"):
            yield path


def generated_cc(rel_dir):
    """The generated vector_icons sources for one icon directory."""
    # chrome/app and components keep theirs in a vector_icons directory;
    # omnibox, ui/views and the message centres one level up.
    gen = Path(OUT) / "gen" / rel_dir
    found = sorted(gen.glob("*.cc")) if gen.is_dir() else []
    return found or sorted(gen.parent.glob("vector_icons.cc"))


def constant(name):
    return "k" + "".join(p.capitalize() for p in name.split("_")) + "Icon"


def listed_in_build(rel_dir, name):
    """Whether a BUILD.gn beside the icon or one level up names it. Chromium
    keeps a few retired .icon files that no target builds (157:
    components/omnibox/browser/vector_icons/star_old.icon)."""
    src = Path(OUT).parents[1]
    named = re.compile(r'["/]' + re.escape(name) + '"')
    for folder in (src / rel_dir, (src / rel_dir).parent):
        for gn in folder.glob("*.gn*"):
            if named.search(gn.read_text(encoding="utf-8", errors="ignore")):
                return True
    return False


# Icons of ours that no BUILD.gn names, on purpose: Chromium keeps the file
# but builds nothing from it. Any other unnamed icon fails (a typo in a
# BUILD.gn would otherwise pass as "not built").
NOT_BUILT = {"components/omnibox/browser/vector_icons/star_old.icon"}


def check_build(checks):
    cache = {}
    missing = []
    skipped, unnamed = [], []
    for path in ours_written():
        rel_dir = path.parent.relative_to(CHROMIUM_SRC).as_posix()
        if not listed_in_build(rel_dir, path.name):
            rel = f"{rel_dir}/{path.name}"
            (skipped if rel in NOT_BUILT else unnamed).append(rel)
            continue
        if rel_dir not in cache:
            cache[rel_dir] = " ".join(
                tokens(p.read_text(encoding="utf-8", errors="ignore"))
                for p in generated_cc(rel_dir)
            )
        if tokens(path.read_text(encoding="utf-8")) not in cache[rel_dir]:
            missing.append(f"{rel_dir}/{path.name}")
    print(f"not built by this Chromium, skipped ({len(skipped)}, allowed): {', '.join(skipped)}")
    checks("every icon no BUILD.gn names is on the allowed list", not unnamed, ", ".join(unnamed[:8]))
    checks("every icon of the set is in the build as written", not missing, ", ".join(missing[:8]))

    header = Path(OUT) / "gen" / "chrome" / "app" / "vector_icons" / "vector_icons.h"
    text = header.read_text(encoding="utf-8") if header.exists() else ""
    absent = [constant(n) for n in icon_map.OURS if constant(n) not in text]
    checks("every icon of ours is declared", bool(text) and not absent, ", ".join(absent[:8]))

    ghosts = [
        f"{p.parent.relative_to(CHROMIUM_SRC).as_posix()}/{p.name}"
        for n in icon_map.ICON_MAP["c-priv"]
        for p in CHROMIUM_SRC.rglob(n + ".icon")
    ]
    # tests/test_icon_map.py checks these files are the ghost; here, that
    # the build drew them.
    checks(
        "every Incognito icon is the ghost in the build",
        len(ghosts) >= 6 and not set(ghosts) & set(missing),
        ", ".join(sorted(set(ghosts) & set(missing))),
    )


def shoot(checks, out, label, extra):
    profile = Path(tempfile.mkdtemp(prefix="smoke-icons-", dir=r"E:\tmp"))
    flags = ["--disable-features=CalculateNativeWinOcclusion", *extra]
    proc, cdp = launch(CHROME, profile, flags)
    try:
        time.sleep(4)
        hwnd = frame_window(CHROME, under=os.getpid())
        dest = out / f"{label}.png"
        grab(hwnd, str(dest))
        size = dest.stat().st_size if dest.exists() else 0
        checks(f"{label}: the window drew", size > DRAWN_BYTES, f"{size} bytes, {dest}")
    finally:
        close(proc, cdp)
        shutil.rmtree(profile, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=r"E:\tmp\smoke-icons")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    checks = Checks()

    check_build(checks)
    for label, extra in (
        ("light-normal", []),
        ("light-incognito", ["--incognito"]),
        ("dark-normal", ["--force-dark-mode"]),
        ("dark-incognito", ["--force-dark-mode", "--incognito"]),
    ):
        shoot(checks, out, label, extra)

    for name in SCREENS:
        for src, prefix in ((SHOTS / name, "compiled-light-"), (SHOTS / "dark" / name, "compiled-dark-")):
            if src.exists():
                shutil.copy(src, out / (prefix + name))
    print("pictures:", out)
    return checks.result("icons")


if __name__ == "__main__":
    sys.exit(main())
