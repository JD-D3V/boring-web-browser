#!/usr/bin/env python3
"""Photograph the search engine menu, open and closed, light and dark.

For JD's review of release 2. Uses the same rules as capture_native.py:
the window is drawn with PrintWindow from our own browser's windows
only, never a screen grab, and nothing is sent to the OS as input. The
menu is opened and closed through the new tab page's test hook
(--boring-search-menu-test), the path smoke_search_menu.py checks.

The menu is its own popup window, so it is photographed on its own and
laid over the browser frame at its real offset.

    python capture_search_menu.py
    python capture_search_menu.py --out E:\\WEBBrowser\\artifacts\\r2-search-menu

Writes, for each theme (light, dark):
    omnibox-closed-<theme>.png   a search typed, menu rolled up
    omnibox-open-<theme>.png     the menu opened from the engine icon
    newtab-open-<theme>.png      the menu opened from the new tab button

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke
tests). Nothing contacts the network: every host resolves to nothing.
"""

import argparse
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

from capture_native import (
    BITMAPINFOHEADER,
    ENUMPROC,
    RECT,
    chrome_pids,
    frame_window,
    gdi32,
    parents_of,
    user32,
    write_png,
)
from drive import OFFSCREEN, Browser
from smoke_search_menu import OFFLINE, TEST_SWITCH, hook, open_newtab, wait_state

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "artifacts" / "r2-search-menu"
QUERY = "quiet morning walks"


def window_rect(hwnd):
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def grab_raw(hwnd):
    """The window's own pixels, BGRA top down, via PrintWindow."""
    _, _, w, h = window_rect(hwnd)
    screen = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    gdi32.SelectObject(mem, bmp)
    # 2 is PW_RENDERFULLCONTENT, which brings composited content with it.
    user32.PrintWindow(hwnd, mem, 2)
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth = w
    info.biHeight = -h
    info.biPlanes = 1
    info.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, screen)
    return w, h, bytearray(buf.raw)


def popups_over(frame, pids):
    """Our other visible windows that sit over the frame: the menu."""
    fx, fy, fw, fh = window_rect(frame)
    found = []

    def cb(hwnd, _lparam):
        if hwnd == frame or not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        x, y, w, h = window_rect(hwnd)
        overlaps = x < fx + fw and y < fy + fh and x + w > fx and y + h > fy
        if w > 0 and h > 0 and overlaps:
            found.append(hwnd)
        return True

    user32.EnumWindows(ENUMPROC(cb), 0)
    return found


def composite(frame_px, fw, fh, popup_px, pw, ph, ox, oy):
    """Lay the popup over the frame. Its pixels are premultiplied BGRA."""
    blank = True
    for y in range(ph):
        ty = oy + y
        if ty < 0 or ty >= fh:
            continue
        for x in range(pw):
            tx = ox + x
            if tx < 0 or tx >= fw:
                continue
            s = (y * pw + x) * 4
            a = popup_px[s + 3]
            if a == 0:
                continue
            blank = False
            d = (ty * fw + tx) * 4
            for c in range(3):
                frame_px[d + c] = min(
                    255, popup_px[s + c] + frame_px[d + c] * (255 - a) // 255
                )
    return not blank


def shoot(frame, pids, path):
    fx, fy, fw, fh = window_rect(frame)
    _, _, pixels = grab_raw(frame)
    laid = 0
    for popup in popups_over(frame, pids):
        px, py, pw, ph = window_rect(popup)
        _, _, popup_px = grab_raw(popup)
        if composite(pixels, fw, fh, popup_px, pw, ph, px - fx, py - fy):
            laid += 1
    write_png(str(path), fw, fh, bytes(pixels))
    print(f"saved {path} ({laid} popup window(s) laid over)")
    return laid


def run(theme, out, size, binary):
    w, h = size
    args = [
        TEST_SWITCH,
        OFFLINE,
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        f"--window-size={w},{h}",
        "--window-position=" + os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN),
    ]
    if theme == "dark":
        args.append("--force-dark-mode")
    ok = True
    with Browser(args=args, keep_switches=["enable-automation"]) as b:
        if not open_newtab(b):
            print("the new tab page did not load")
            return False
        frame = frame_window(binary, under=b.proc.pid)
        x, y, _, _ = window_rect(frame)
        user32.MoveWindow(frame, x, y, w, h, True)
        time.sleep(1.0)
        parents = parents_of(chrome_pids(binary))
        pids = {pid for pid, parent in parents.items() if parent == b.proc.pid}
        pids |= {pid for pid, parent in parents.items() if parent in pids}

        # From the address bar's engine icon, with a search typed.
        opened = hook(b, "openFromOmnibox", QUERY) or {}
        state = wait_state(b, lambda s: s.get("open") and s.get("progress") == 1)
        time.sleep(0.4)
        if not opened.get("shown") or not state.get("open"):
            print("the menu did not open from the address bar:", opened, state)
            ok = False
        elif not shoot(frame, pids, out / f"omnibox-open-{theme}.png"):
            print("the menu window photographed empty")
            ok = False
        hook(b, "escape")
        wait_state(b, lambda s: not s.get("open"))
        time.sleep(0.4)
        shoot(frame, pids, out / f"omnibox-closed-{theme}.png")

        # From the new tab page's own engine button.
        open_newtab(b)
        b.run("document.getElementById('engine').click()")
        state = wait_state(b, lambda s: s.get("open") and s.get("progress") == 1)
        time.sleep(0.4)
        if state.get("open"):
            shoot(frame, pids, out / f"newtab-open-{theme}.png")
        else:
            print("the menu did not open from the new tab button")
            ok = False
        hook(b, "escape")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--size", default="1404x760", help="window size, WxH")
    args = ap.parse_args()

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    size = tuple(int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get(
        "BORING_CHROME",
        os.path.join(
            os.environ.get("BORING_OUT", r"E:\ung\build\src\out\Default"),
            "chrome.exe",
        ),
    )
    results = [run(theme, out, size, binary) for theme in ("light", "dark")]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
