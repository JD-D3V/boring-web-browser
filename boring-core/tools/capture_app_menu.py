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
    python capture_app_menu.py --out menu.png --expect-height 769

--expect-height fails the run when the menu's height, in DIP, is more than
--tolerance away from it. The refreshed menu (design/v9-menu, mockup A,
patches/157/app-menu-refresh.patch) is 769 DIP tall, border included, in a
profile with no update, warning or managed row.

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import ctypes
import os
import time
from ctypes import wintypes
from pathlib import Path

from capture_native import (
    ENUMPROC,
    chrome_pids,
    frame_window,
    parents_of,
    user32,
    write_png,
)
from capture_search_menu import grab_raw, window_rect
from drive import CHROME, OFFSCREEN, Browser

HOOK = "--boring-open-app-menu"
# The brightest a pixel of the menu's shadow comes back.
SHADOW = 24


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
    # The menu's own bounds: everything that is not the ring. Its shadow
    # comes back nearly black (up to about 17), not 0, and is no part of
    # the menu: counted, it made the menu 27 DIP taller and 22 wider.
    xs, ys = [], []
    for y in range(ph):
        for x in range(pw):
            s = (y * pw + x) * 4
            if max(px[s : s + 3]) > SHADOW:
                xs.append(x)
                ys.append(y)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cw, ch = x1 - x0 + 1, y1 - y0 + 1
    w, h = cw + 2 * margin, ch + 2 * margin
    canvas = bytearray([128, 128, 128, 255] * (w * h))
    for y in range(ch):
        for x in range(cw):
            s = ((y + y0) * pw + (x + x0)) * 4
            if max(px[s : s + 3]) <= SHADOW:
                continue
            d = ((y + margin) * w + (x + margin)) * 4
            canvas[d : d + 3] = px[s : s + 3]
    write_png(str(path), w, h, bytes(canvas))
    scale = user32.GetDpiForWindow(popup) / 96 or 1
    print(f"saved {path} ({cw}x{ch} menu, {cw / scale:.0f}x{ch / scale:.0f} DIP)")
    return ch / scale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1404x900", help="window size, WxH")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--scheme", choices=["cool", "beige", "green"], default="cool")
    ap.add_argument("--url", default="chrome://boring-newtab")
    ap.add_argument("--expect-height", type=float, help="menu height in DIP")
    ap.add_argument("--tolerance", type=float, default=6)
    args = ap.parse_args()

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    w, h = (int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get("BORING_CHROME", CHROME)

    chrome_args = [
        HOOK,
        # No update check or list fetch, and so no update row in the menu.
        "--disable-boring-updates",
        "--disable-boring-list-updates",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        f"--window-size={w},{h}",
        "--window-position=" + os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN),
    ]
    if args.dark:
        chrome_args.append("--force-dark-mode")
    if args.scheme in ("beige", "green"):
        chrome_args.append("--boring-scheme=" + args.scheme)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with Browser(
        args=chrome_args, keep_switches=["enable-automation"], headful=True
    ) as b:
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
    if args.expect_height and abs(laid - args.expect_height) > args.tolerance:
        raise SystemExit(
            f"the menu is {laid:.0f} DIP tall, expected {args.expect_height:.0f}"
        )


if __name__ == "__main__":
    main()
