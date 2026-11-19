#!/usr/bin/env python3
"""Check the Look (compiled UI ledger item 2) in light and dark.

For each Look (Soft white, the default; Slate; Dusk) the profile pref
boring.appearance.look is written into a new profile before the browser
starts, and the colours the browser's own colour provider hands out are
read back as resolved CSS variables from chrome://theme/colors.css, which
comes from the same provider the native views use (as smoke_ui_polish.py
does). They must be the palettes of boring_color_mixer.cc: the frame band,
the toolbar, the address bar's fill and its edge, the ink; the edge colour
id (kColorBoringEdge) and the ok green (kColorBoringOk); and, where the
Look draws an edge of its own, text fields, outline buttons and off
switches in that edge.

Then a new Look must repaint at once: Soft white is changed to Slate the
way the Settings control writes it (chrome.settingsPrivate.setPref) and
the frame band must follow without a restart. Until Settings lists the
pref (compiled UI item 9), setPref refuses it and that check is reported
as NOT CHECKED, which fails the run.

With BORING_ALLOW_HEADFUL=1 it also photographs the new tab page of each
Look, light and dark, by PrintWindow of our own window, and puts the
matching compiled screen beside each picture (design/v12-compiled/
shots-final: c01 for light, c02 for dark). Sends no mouse or keys to the
desktop.

    python smoke_colours.py            # expects "PASS: colours"
    python smoke_colours.py --no-live  # skip the live change

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

from drive import CHROME, Browser, headful_allowed

PREF = "boring.appearance.look"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "cui-colours"
# design/ is not in git: run from the main checkout, or point BORING_DESIGN
# at the shots-final folder.
DESIGN = Path(os.environ.get(
    "BORING_DESIGN", ROOT / "design" / "v12-compiled" / "shots-final"))
SCREEN = {False: "c01-newtab.png", True: "c02-newtabdark.png"}

# Look, dark -> colour as boring_color_mixer.cc sets it. Dusk in light is
# Slate's light palette. Slate, and Dusk, have no edge of their own: their
# edge is their line, and text fields, buttons and switches keep
# Chromium's colours there.
SOFT_LIGHT = {"frame": "eceae6", "toolbar": "ffffff", "field": "f4f3ef",
              "ink": "1f1e1c", "edge": "8a867d"}
SOFT_DARK = {"frame": "111110", "toolbar": "1c1c1a", "field": "121211",
             "ink": "ecebe7", "edge": "77756d"}
SLATE_LIGHT = {"frame": "d3d6e3", "toolbar": "ffffff", "field": "eef0f6",
               "ink": "23242e", "edge": "d9dbe6"}
SLATE_DARK = {"frame": "0a0b0f", "toolbar": "1d1e28", "field": "0f1015",
              "ink": "dcdde6", "edge": "2c2d3a"}
DUSK_DARK = {"frame": "0f1017", "toolbar": "1b1d2b", "field": "262838",
             "ink": "dcdde6", "edge": "2c2d3a"}
EXPECT = {
    ("soft_white", False): SOFT_LIGHT,
    ("soft_white", True): SOFT_DARK,
    ("slate", False): SLATE_LIGHT,
    ("slate", True): SLATE_DARK,
    ("dusk", False): SLATE_LIGHT,
    ("dusk", True): DUSK_DARK,
}
OK = {False: "1a7f55", True: "4cc38a"}
DRAWN_EDGE = {"soft_white"}

# Palette field -> the CSS variables of the ids the mixer gives it.
VARS = {
    "frame": ["--color-frame-active"],
    "toolbar": ["--color-toolbar"],
    "field": ["--color-location-bar-background"],
    "ink": ["--color-omnibox-text"],
    "edge": ["--color-location-bar-border", "--color-boring-edge"],
}
EDGE_CONTROLS = [
    "--color-textfield-outline",
    "--color-button-border",
    "--color-toggle-button-track-off",
]
OK_VAR = "--color-boring-ok"

RESOLVE = r"""
  const out = {};
  const p = document.createElement('div');
  document.body.appendChild(p);
  for (const n of arguments[0]) {
    p.style.color = 'var(' + n + ')';
    out[n] = getComputedStyle(p).color;
  }
  return out;
"""


def rgb(hex6):
    return "rgb({}, {}, {})".format(*(int(hex6[i:i + 2], 16) for i in (0, 2, 4)))


def all_vars():
    names = [n for group in VARS.values() for n in group]
    return names + EDGE_CONTROLS + [OK_VAR]


def seed_profile(path, look):
    """A new profile holding the Look, as Settings would have left it."""
    if look is None:
        return
    default = Path(path) / "Default"
    default.mkdir(parents=True, exist_ok=True)
    prefs = {"boring": {"appearance": {"look": look}}}
    (default / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")


def resolve(b):
    b.get("chrome://theme/colors.css?sets=ui,chrome")
    css = b.run("return document.documentElement.innerText")
    have = set(re.findall(r"(--color-[a-z0-9-]+):", css))
    b.get("chrome://settings/help")
    time.sleep(1.0)
    return have, b.run(RESOLVE, [all_vars()])


def expect_rows(look, dark):
    want = EXPECT[(look, dark)]
    rows = [(n, want[field]) for field, names in VARS.items() for n in names]
    rows.append((OK_VAR, OK[dark]))
    if look in DRAWN_EDGE:
        rows += [(n, want["edge"]) for n in EDGE_CONTROLS]
    return rows


def check_look(look, dark, checks):
    tag = f"{look} {'dark' if dark else 'light'}"
    args = ["--window-size=1200,700"] + (["--force-dark-mode"] if dark else [])
    with tempfile.TemporaryDirectory(prefix="colours-", dir=os.environ.get("TMP")) as prof:
        # Soft white is the default: its light and dark runs write no pref.
        seed_profile(prof, None if look == "soft_white" else look)
        with Browser(user_data_dir=prof, args=args) as b:
            have, got = resolve(b)
    for name, hex6 in expect_rows(look, dark):
        checks[f"{tag}: {name} is #{hex6}"] = (
            name in have and got.get(name) == rgb(hex6),
            got.get(name),
        )


def set_pref(b, value):
    """Write the pref the way the Settings control does, and read it back."""
    b.get("chrome://settings/appearance")
    time.sleep(1.5)
    return b.run_async(
        "const done = arguments[arguments.length - 1];"
        "chrome.settingsPrivate.setPref(arguments[0], arguments[1], '', ok => {"
        "  chrome.settingsPrivate.getPref(arguments[0], p => done([ok, p && p.value]));"
        "});",
        [PREF, value],
    )


def check_live(checks):
    with tempfile.TemporaryDirectory(prefix="colours-live-", dir=os.environ.get("TMP")) as prof:
        with Browser(user_data_dir=prof, args=["--window-size=1200,700"]) as b:
            _, before = resolve(b)
            ok, value = set_pref(b, "slate")
            if not ok or value != "slate":
                checks["live: Settings can write the Look"] = (
                    None, "NOT CHECKED: settingsPrivate refused the pref (item 9)")
                return
            _, after = resolve(b)
    frame = "--color-frame-active"
    checks["live: Soft white before the change"] = (
        before.get(frame) == rgb(SOFT_LIGHT["frame"]), before.get(frame))
    checks["live: Slate at once, no restart"] = (
        after.get(frame) == rgb(SLATE_LIGHT["frame"]), after.get(frame))


def capture(look, dark):
    from capture_native import frame_window, grab, user32
    from drive import OFFSCREEN

    w, h = 1280, 800
    name = f"{look}-{'dark' if dark else 'light'}"
    args = [
        f"--window-size={w},{h}",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
    ] + (["--force-dark-mode"] if dark else [])
    with tempfile.TemporaryDirectory(prefix="colours-shot-", dir=os.environ.get("TMP")) as prof:
        seed_profile(prof, None if look == "soft_white" else look)
        with Browser(user_data_dir=prof, args=args, headful=True,
                     keep_switches=["enable-automation"]) as b:
            b.get("chrome://newtab")
            hwnd = frame_window(CHROME, under=b.proc.pid)
            px, py = (int(v) for v in OFFSCREEN.split(","))
            user32.MoveWindow(hwnd, px, py, w, h, True)
            time.sleep(1.0)
            grab(hwnd, str(OUT / f"{name}.png"))
    screen = DESIGN / SCREEN[dark]
    if screen.is_file():
        shutil.copyfile(screen, OUT / f"{name}-design.png")
    print("saved", OUT / f"{name}.png", "beside", screen.name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-live", action="store_true")
    opts = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    for look in ("soft_white", "slate", "dusk"):
        for dark in (False, True):
            check_look(look, dark, checks)
    if not opts.no_live:
        check_live(checks)
    if headful_allowed():
        for look in ("soft_white", "slate", "dusk"):
            for dark in (False, True):
                capture(look, dark)
    else:
        print("pictures: not taken (set BORING_ALLOW_HEADFUL=1)")

    failed = 0
    for name, (passed, seen) in checks.items():
        mark = "PASS" if passed else ("NOT CHECKED" if passed is None else "FAIL")
        failed += passed is not True
        print(f"{mark}: {name} (saw {seen})")
    (OUT / "results.json").write_text(json.dumps(checks, indent=1), encoding="utf-8")
    print("PASS: colours" if not failed else f"FAIL: colours ({failed} of {len(checks)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
