#!/usr/bin/env python3
"""Photograph "What the browser connects to" with one filter list added,
using PrintWindow of our own window (see smoke_own_lists.py for the test
server and the switch that lets it be plain http on this machine).

  python capture_own_lists.py --out E:\\tmp\\feat-own-lists\\light.png
  python capture_own_lists.py --out E:\\tmp\\feat-own-lists\\dark.png --dark
"""

import argparse
import ctypes
import os
import shutil
import tempfile
import time

from capture_native import frame_window, grab, user32
from drive import CHROME, OFFSCREEN, Browser
from smoke_local import list_folder, browser_args
from smoke_own_lists import BUNDLED, SWITCH, ListServer, add, row_with

TMP = os.environ.get("TMP", r"E:\tmp")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1000x1000", help="window size, WxH")
    ap.add_argument("--dark", action="store_true")
    args = ap.parse_args()

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    w, h = (int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get("BORING_CHROME", CHROME)
    work = tempfile.mkdtemp(prefix="own-lists-cap-", dir=TMP)
    server = ListServer()
    try:
        with list_folder(BUNDLED) as lists:
            chrome_args = [
                *browser_args(lists),
                SWITCH,
                "--disable-backgrounding-occluded-windows",
                "--disable-features=CalculateNativeWinOcclusion",
                f"--window-size={w},{h}",
                "--window-position=" + OFFSCREEN,
            ]
            if args.dark:
                chrome_args.append("--force-dark-mode")
            with Browser(
                user_data_dir=os.path.join(work, "profile"),
                args=chrome_args,
                keep_switches=["enable-automation"],
                headful=True,
            ) as b:
                b.get("chrome://boring-protection")
                time.sleep(2)
                add(b, server.url("/list.txt"))
                row_with(b, "Updated")
                time.sleep(1.0)
                b.run(
                    "document.getElementById('connections-lists')"
                    ".scrollIntoView({block: 'end'}); return 1"
                )
                time.sleep(1.0)
                hwnd = frame_window(binary, under=b.proc.pid)
                x, y = (int(v) for v in OFFSCREEN.split(","))
                user32.MoveWindow(hwnd, x, y, w, h, True)
                time.sleep(0.8)
                got = grab(hwnd, args.out)
        print(f"saved {args.out} {got[0]}x{got[1]}")
    finally:
        server.close()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
