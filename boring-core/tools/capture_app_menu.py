#!/usr/bin/env python3
"""Photograph the browser's main menu, open, in any colour scheme.

Same rules as capture_native.py and capture_search_menu.py: the windows are
drawn with PrintWindow from our own browser only, never a screen grab, and
nothing is sent to the OS as input. The menu is opened by the
--boring-open-app-menu switch (patches/app-menu-test-hook.patch), which
opens it four seconds after the toolbar is built. Windows then closes it
again within a couple of seconds, so this polls and photographs it at once.

    python capture_app_menu.py --out menu-cool-light.png
    python capture_app_menu.py --out menu-beige-dark.png --dark --scheme beige

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import ctypes
import os
import time
from pathlib import Path

from ctypes import wintypes

from capture_native import (ENUMPROC, chrome_pids, frame_window, parents_of,
                            user32, write_png)
from capture_search_menu import grab_raw, window_rect
from drive import OFFSCREEN, Browser

HOOK = "--boring-open-app-menu"


def find_menu(frame, pids):
    """The menu's own popup window, once it is open: ours, visible, narrow."""
    found = []

    def cb(hwnd, _lparam):
        if hwnd == frame or not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            x, y, w, h = window_rect(hwnd)
            if 0 < w < 800 and h > 100:
                found.append(hwnd)
        return True

    user32.EnumWindows(ENUMPROC(cb), 0)
    return found[0] if found else None


def shoot_popup(popup, path, margin=16):
    """The popup on its own, on a mid grey.

    The frame sits off screen, so Windows places the menu on the visible
    screen instead of over the frame, and it closes again within a couple
    of seconds. It fades in first, so wait out the fade before the grab.
    The window carries a transparent shadow ring that PrintWindow returns
    as black; it is cropped, and the black left in the rounded corners is
    painted over with the background.
    """
    time.sleep(0.6)
    _, _, pw, ph = window_rect(popup)
    _, _, px = grab_raw(popup)
    # The menu's own bounds: everything that is not the black ring.
    xs, ys = [], []
    for y in range(ph):
        for x in range(pw):
            s = (y * pw + x) * 4
            if px[s] or px[s + 1] or px[s + 2]:
                xs.append(x)
                ys.append(y)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cw, ch = x1 - x0 + 1, y1 - y0 + 1
    w, h = cw + 2 * margin, ch + 2 * margin
    canvas = bytearray([128, 128, 128, 255] * (w * h))
    for y in range(ch):
        for x in range(cw):
            s = ((y + y0) * pw + (x + x0)) * 4
            if px[s] == 0 and px[s + 1] == 0 and px[s + 2] == 0:
                continue
            d = ((y + margin) * w + (x + margin)) * 4
            canvas[d:d + 3] = px[s:s + 3]
    write_png(str(path), w, h, bytes(canvas))
    print(f"saved {path} ({cw}x{ch} menu)")
    return True


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
        popup = None
        deadline = time.time() + 15
        while time.time() < deadline and popup is None:
            time.sleep(0.1)
            popup = find_menu(frame, pids)
        laid = bool(popup) and shoot_popup(popup, out)
    if not laid:
        raise SystemExit("the menu did not open (no popup window over the frame)")


if __name__ == "__main__":
    main()
