#!/usr/bin/env python3
"""Photograph "Keep a copy in a folder" on the Protection page with
PrintWindow of our own window (see smoke_folder_copy.py for the test
folder switch).

  python capture_folder_copy.py --out E:\\tmp\\feat-folder-copy\\saved-light.png
  python capture_folder_copy.py --out E:\\tmp\\feat-folder-copy\\saved-dark.png --dark
  python capture_folder_copy.py --out E:\\tmp\\feat-folder-copy\\off-light.png --state off
  python capture_folder_copy.py --out E:\\tmp\\feat-folder-copy\\preview-light.png --state preview
"""

import argparse
import ctypes
import json
import os
import shutil
import tempfile
import time

from capture_native import frame_window, grab, user32
from drive import CHROME, OFFSCREEN, Browser
from smoke_folder_copy import BOOKMARKS, ROOT, SETTINGS, wait_js

HTML = (
    "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<TITLE>Bookmarks</TITLE>\n<H1>Bookmarks</H1>\n"
    '<DL><p>\n<DT><H3 PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>\n<DL><p>\n'
    '<DT><A HREF="https://example.com/">Example</A>\n</DL><p>\n</DL><p>\n'
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1000x1000", help="window size, WxH")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--state", choices=["saved", "off", "preview"], default="saved")
    args = ap.parse_args()

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    w, h = (int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get("BORING_CHROME", CHROME)
    os.makedirs(ROOT, exist_ok=True)
    work = tempfile.mkdtemp(prefix="cap-", dir=ROOT)
    folder = os.path.join(work, "Cloud copy")
    os.makedirs(folder)
    chrome_args = [
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        f"--window-size={w},{h}",
        "--window-position=" + OFFSCREEN,
    ]
    if args.state == "preview":
        # A folder with a copy that differs: the row waits, Load lists it.
        with open(os.path.join(folder, BOOKMARKS), "w", encoding="utf-8") as f:
            f.write(HTML)
        with open(os.path.join(folder, SETTINGS), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "settings": {
                "boring.fingerprint_noise": False,
                "boring.adblock.level": 1,
                "boring.ai.provider": "ollama"}}, f)
    if args.state != "off":
        chrome_args.append("--boring-folder-copy-dir=" + folder)
    if args.dark:
        chrome_args.append("--force-dark-mode")
    try:
        with Browser(user_data_dir=os.path.join(work, "profile"), args=chrome_args,
                     keep_switches=["enable-automation"]) as b:
            b.get("chrome://boring-protection")
            wait_js(b, "return !!document.getElementById('folder-copy')")
            if args.state == "saved":
                wait_js(b, "return /Last saved/.test("
                           "document.getElementById('folder-copy-status').innerText)", 40)
            elif args.state == "preview":
                wait_js(b, "return !document.getElementById('folder-load').hidden")
                time.sleep(1)
                b.run("document.getElementById('folder-load').click(); return 1")
                wait_js(b, "return !document.getElementById('folder-preview').hidden", 30)
            time.sleep(1.0)
            b.run("document.getElementById('folder-copy-row').scrollIntoView("
                  "{block: 'center'}); return 1")
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
