#!/usr/bin/env python3
"""Smoke test and photographs for Chromium's own side (vertical) tabs.

Chromium 154 ships vertical tabs: Settings > Appearance > Tab strip
position, the tab right-click menu, and the app menu all switch it, and
the choice is the vertical_tabs.enabled pref. This turns it on through
the same pref the Settings row writes (chrome.settingsPrivate from the
Settings page), opens six tabs, switches between them, photographs the
window, and switches back to top tabs.

Same rules as capture_native.py: the window is drawn with PrintWindow
from our own browser only, and nothing is sent to the OS as input.

    python smoke_vtabs.py --out artifacts/ui-refresh/vtabs
    python smoke_vtabs.py --out out.png --only green-dark

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import ctypes
import os
import sys
import tempfile
import time
from pathlib import Path

from capture_native import frame_window, grab, user32
from drive import OFFSCREEN, Browser

# (name, extra switches); Cool is the default scheme.
SCENES = [
    ("cool-light", []),
    ("cool-dark", ["--force-dark-mode"]),
    ("green-dark", ["--force-dark-mode", "--boring-scheme=green"]),
    ("green-light", ["--boring-scheme=green"]),
]

PREF = "vertical_tabs.enabled"


def set_pref(b, value):
    """Write the pref the way the Settings toggle does, and read it back."""
    b.get("chrome://settings/appearance")
    time.sleep(1.5)
    return b.run_async(
        "const done = arguments[arguments.length - 1];"
        "chrome.settingsPrivate.setPref(arguments[0], arguments[1], '', ok => {"
        "  chrome.settingsPrivate.getPref(arguments[0], p => done([ok, p.value]));"
        "});",
        [PREF, value],
    )


def page(n):
    title = ["Weather", "Library catalogue", "Bank statement", "Recipes",
             "A very long page title that has to be cut off somewhere", "News"][n % 6]
    return "data:text/html,<title>" + title.replace(" ", "%20") + "</title><h1>" + str(n) + "</h1>"


def run_scene(name, extra, out, size, binary, only_switch_back):
    w, h = size
    args = [
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        f"--window-size={w},{h}",
        "--window-position=" + OFFSCREEN,
    ] + extra
    results = {}
    with tempfile.TemporaryDirectory(prefix="vtabs-", dir=os.environ.get("TMP")) as prof:
        with Browser(user_data_dir=prof, args=args, keep_switches=["enable-automation"]) as b:
            hwnd = frame_window(binary, under=b.proc.pid)
            px, py = (int(v) for v in OFFSCREEN.split(","))

            def shoot(path):
                user32.MoveWindow(hwnd, px, py, w, h, True)
                time.sleep(0.8)
                grab(hwnd, str(path))
                print("saved", path)

            ok, val = set_pref(b, True)
            results["pref_on"] = bool(ok) and val is True
            for _ in range(6):
                b.run("window.open('about:blank')")
                time.sleep(0.3)
            handles = b._req("GET", f"/session/{b.sid}/window/handles")["value"]
            results["tabs_open"] = len(handles) >= 7
            titles = []
            for n, hd in enumerate(handles[1:]):
                b._req("POST", f"/session/{b.sid}/window", {"handle": hd})
                b.get(page(n))
                titles.append(b.run("return document.title"))
            results["tabs_switch"] = len(set(titles)) >= 5
            b._req("POST", f"/session/{b.sid}/window", {"handle": handles[3]})
            time.sleep(1.0)
            if not only_switch_back:
                shoot(out / f"vtabs-{name}.png")
            b._req("POST", f"/session/{b.sid}/window", {"handle": handles[0]})
            ok, val = set_pref(b, False)
            results["pref_off"] = bool(ok) and val is False
            results["still_alive"] = b.run("return document.readyState") == "complete"
            time.sleep(1.0)
            if name == SCENES[0][0]:
                shoot(out / f"vtabs-{name}-switched-back.png")
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--only", help="one scene name")
    ap.add_argument("--size", default="1404x800")
    args = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    size = tuple(int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get("BORING_CHROME", r"E:\ung\build\src\out\Default\chrome.exe")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for name, extra in SCENES:
        if args.only and args.only != name:
            continue
        res = run_scene(name, extra, out, size, binary, False)
        print(name, res)
        bad += sum(1 for v in res.values() if not v)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
