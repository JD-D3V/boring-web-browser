#!/usr/bin/env python3
r"""Photograph the two scam guard bars, light and dark.

The same way capture_native.py photographs: a PrintWindow of our own
browser window, never the screen, with the window off the desktop. Pages
come from smoke_scam_guards.py's test server, on a *.localhost name.

  remote-access  a click on an AnyDesk download: the question bar
  clickfix       a click on the fake "I'm not a robot" button: the notice

Usage: python capture_scam_guards.py [--out DIR]
Writes DIR/<remote-access|clickfix>-<light|dark>.png, by default into
E:\tmp\feat-scam-guards\shots. Needs BORING_OUT, as the smoke tests do.
"""

import argparse
import ctypes
import os
import shutil
import tempfile
import time
from pathlib import Path

from capture_native import OFFSCREEN, frame_window, grab, user32
from drive import CHROME, Browser
from smoke_scam_guards import (
    BAR,
    click_id,
    serve,
    set_windows_clipboard_text,
    wait,
    windows_clipboard_text,
)

SIZE = (1404, 640)

SHOTS = {
    # name: (page, element to click)
    "remote-access": ("scam_guards_downloads.html", "anydesk"),
    "clickfix": ("scam_guards_clickfix.html?mode=exec", "copy"),
}


def photograph(port, name, dark, out_dir):
    page, element = SHOTS[name]
    root = Path(tempfile.mkdtemp(prefix="guards-shot-", dir=os.environ.get("TMP")))
    try:
        log = root / "chrome.log"
        args = [
            "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion",
            "--enable-logging",
            "--log-level=0",
            f"--log-file={log}",
            f"--window-size={SIZE[0]},{SIZE[1]}",
        ]
        if dark:
            args.append("--force-dark-mode")
        # No "controlled by automated test software" bar in the picture.
        with Browser(
            user_data_dir=str(root / "profile"),
            args=args,
            keep_switches=["enable-automation"],
        ) as b:
            b.get(f"http://guards.localhost:{port}/{page}")
            wait(lambda: b.run(f"return !!document.getElementById('{element}')"))
            click_id(b, element)

            def said():
                try:
                    return BAR in log.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    return False

            if not wait(said, timeout=20):
                print(f"{name}: no bar appeared")
                return
            time.sleep(1.5)  # the bar slides in
            hwnd = frame_window(CHROME, under=b.proc.pid)
            px, py = (int(v) for v in OFFSCREEN.split(","))
            user32.MoveWindow(hwnd, px, py, SIZE[0], SIZE[1], True)
            time.sleep(0.8)
            out = out_dir / f"{name}-{'dark' if dark else 'light'}.png"
            got = grab(hwnd, str(out))
            print(f"saved {out} {got[0]}x{got[1]}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\tmp\feat-scam-guards\shots")
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)

    saved = windows_clipboard_text()
    srv = serve()
    try:
        port = srv.server_address[1]
        for dark in (False, True):
            for name in SHOTS:
                photograph(port, name, dark, out_dir)
    finally:
        srv.shutdown()
        if saved is not None:
            set_windows_clipboard_text(saved)


if __name__ == "__main__":
    main()
