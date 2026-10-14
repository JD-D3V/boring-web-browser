#!/usr/bin/env python3
"""Click the new tab page's Colours link and photograph what opens.

Same rules as capture_native.py: the window is drawn with PrintWindow from
our own browser only, and the click is an in-page click through WebDriver,
nothing sent to the OS. The link asks the browser for its colour picker
(Customize Chrome), which opens as a side panel in the same window.

    python capture_colours_link.py --out colours-panel.png
"""

import argparse
import ctypes
import os
import time

from capture_native import frame_window, grab, user32
from drive import OFFSCREEN, Browser


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1404x800", help="window size, WxH")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--wait", type=float, default=5.0)
    args = ap.parse_args()

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    w, h = (int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get("BORING_CHROME", r"E:\ung\build\src\out\Default\chrome.exe")
    chrome_args = [
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        f"--window-size={w},{h}",
        "--window-position=" + os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN),
    ]
    if args.dark:
        chrome_args.append("--force-dark-mode")
    with Browser(args=chrome_args, keep_switches=["enable-automation"]) as b:
        b.get("chrome://boring-newtab")
        time.sleep(2.0)
        found = b.run("var c=document.getElementById('colours');"
                      "if(!c) return 'no button'; c.click(); return 'clicked'")
        print("button:", found)
        time.sleep(args.wait)
        hwnd = frame_window(binary, under=b.proc.pid)
        x, y, = (int(v) for v in OFFSCREEN.split(","))
        user32.MoveWindow(hwnd, x, y, w, h, True)
        time.sleep(0.8)
        got = grab(hwnd, args.out)
    print(f"saved {args.out} {got[0]}x{got[1]}")


if __name__ == "__main__":
    main()
