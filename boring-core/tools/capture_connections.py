#!/usr/bin/env python3
"""Photograph the "What the browser connects to" section of the Protection
page, scrolled into view, with PrintWindow of our own window.

  python capture_connections.py --out E:\\tmp\\feat-connections\\light.png
  python capture_connections.py --out E:\\tmp\\feat-connections\\dark.png --dark
"""

import argparse
import ctypes
import os
import time

from capture_native import frame_window, grab, user32
from drive import CHROME, OFFSCREEN, Browser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1000x900", help="window size, WxH")
    ap.add_argument("--dark", action="store_true")
    args = ap.parse_args()

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    w, h = (int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get("BORING_CHROME", CHROME)
    chrome_args = [
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        f"--window-size={w},{h}",
        "--window-position=" + os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN),
    ]
    if args.dark:
        chrome_args.append("--force-dark-mode")
    with Browser(args=chrome_args, keep_switches=["enable-automation"]) as b:
        b.get("chrome://boring-protection")
        for _ in range(40):
            if b.run("return document.querySelectorAll('#connections-own .setting-row').length > 0"):
                break
            time.sleep(0.5)
        time.sleep(1.5)
        b.run("document.getElementById('connections-title').scrollIntoView(); return 1")
        time.sleep(1.0)
        hwnd = frame_window(binary, under=b.proc.pid)
        x, y = (int(v) for v in OFFSCREEN.split(","))
        user32.MoveWindow(hwnd, x, y, w, h, True)
        time.sleep(0.8)
        got = grab(hwnd, args.out)
    print(f"saved {args.out} {got[0]}x{got[1]}")


if __name__ == "__main__":
    main()
