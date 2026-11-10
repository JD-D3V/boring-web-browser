#!/usr/bin/env python3
"""Photograph the "Apps you added" part of the Protection page, scrolled
into view, with PrintWindow of our own window. Test add-ons are loaded
unpacked so the rows have something in them (see smoke_apps_rows.py).

  python capture_apps_rows.py --out E:\\tmp\\feat-apps-rows\\light.png
  python capture_apps_rows.py --out E:\\tmp\\feat-apps-rows\\dark.png --dark
  python capture_apps_rows.py --out E:\\tmp\\feat-apps-rows\\empty.png --empty
"""

import argparse
import ctypes
import os
import shutil
import tempfile
import time

from capture_native import frame_window, grab, user32
from drive import CHROME, OFFSCREEN, Browser
from smoke_apps_rows import TMP, test_extensions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1000x1000", help="window size, WxH")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--empty", action="store_true", help="no test add-ons")
    args = ap.parse_args()

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    w, h = (int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get("BORING_CHROME", CHROME)
    work = tempfile.mkdtemp(prefix="apps-rows-cap-", dir=TMP)
    chrome_args = [
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        f"--window-size={w},{h}",
        "--window-position=" + OFFSCREEN,
    ]
    if not args.empty:
        extensions = test_extensions(work)
        chrome_args.append("--load-extension=" + ",".join(extensions))
    if args.dark:
        chrome_args.append("--force-dark-mode")
    try:
        with Browser(
            user_data_dir=os.path.join(work, "profile"),
            args=chrome_args,
            keep_switches=["enable-automation"],
            headful=True,
        ) as b:
            b.get("chrome://boring-protection")
            want = 1 if args.empty else len(extensions) + 1
            for _ in range(40):
                if b.run(
                    "var n = document.querySelectorAll("
                    "'#connections-apps [id^=app-], #ai-assistant-row').length;"
                    f"return n >= {want}"
                ):
                    break
                time.sleep(0.5)
            time.sleep(1.0)
            b.run(
                "document.getElementById('connections-apps').scrollIntoView(); return 1"
            )
            time.sleep(1.0)
            hwnd = frame_window(binary, under=b.proc.pid)
            x, y = (int(v) for v in OFFSCREEN.split(","))
            user32.MoveWindow(hwnd, x, y, w, h, True)
            time.sleep(0.8)
            got = grab(hwnd, args.out)
        print(f"saved {args.out} {got[0]}x{got[1]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
