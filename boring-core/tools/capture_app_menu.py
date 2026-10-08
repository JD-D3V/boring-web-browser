#!/usr/bin/env python3
"""Photograph the browser's main menu, open, in any colour scheme.

Same rules as capture_native.py and capture_search_menu.py: the windows are
drawn with PrintWindow from our own browser only, never a screen grab, and
nothing is sent to the OS as input. The menu is opened by the
--boring-open-app-menu switch (patches/app-menu-test-hook.patch), which
opens it four seconds after the toolbar is built.

    python capture_app_menu.py --out menu-cool-light.png
    python capture_app_menu.py --out menu-beige-dark.png --dark --scheme beige

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import ctypes
import os
import time
from pathlib import Path

from capture_native import chrome_pids, frame_window, parents_of, user32
from capture_search_menu import shoot, window_rect
from drive import OFFSCREEN, Browser

HOOK = "--boring-open-app-menu"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1404x900", help="window size, WxH")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--scheme", choices=["cool", "beige"], default="cool")
    ap.add_argument("--url", default="chrome://boring-newtab")
    args = ap.parse_args()

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    w, h = (int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get("BORING_CHROME", r"E:\ung\build\src\out\Default\chrome.exe")

    chrome_args = [
        HOOK,
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        f"--window-size={w},{h}",
        "--window-position=" + os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN),
    ]
    if args.dark:
        chrome_args.append("--force-dark-mode")
    if args.scheme == "beige":
        chrome_args.append("--boring-scheme=beige")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with Browser(args=chrome_args, keep_switches=["enable-automation"]) as b:
        b.get(args.url)
        frame = frame_window(binary, under=b.proc.pid)
        x, y, _, _ = window_rect(frame)
        user32.MoveWindow(frame, x, y, w, h, True)
        parents = parents_of(chrome_pids(binary))
        pids = {pid for pid, parent in parents.items() if parent == b.proc.pid}
        pids |= {pid for pid, parent in parents.items() if parent in pids}
        pids.add(b.proc.pid)
        time.sleep(7.0)  # the hook opens the menu at four seconds
        laid = shoot(frame, pids, out)
    if not laid:
        raise SystemExit("the menu did not open (no popup window over the frame)")


if __name__ == "__main__":
    main()
