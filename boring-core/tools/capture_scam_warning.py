#!/usr/bin/env python3
"""Photograph the scam warning page: Cool and Green, light and dark.

Same setup as smoke_scam.py (a temporary list, a local name mapped to
127.0.0.1), and the same way of photographing as capture_native.py: a
PrintWindow of our own browser window, never the screen.

Usage: python capture_scam_warning.py [--out DIR]
Writes DIR/scam-warning-<cool|green>-<light|dark>.png, by default into
artifacts/scam-warning/ at the repository root.
"""

import argparse
import ctypes
import os
import tempfile
import time
from pathlib import Path

from capture_native import frame_window, grab
from drive import CHROME, Browser
from smoke_local import HTML, Pages, list_folder
from smoke_scam import (
    LISTED,
    SAFE_PAGE,
    SCAM_LIST,
    VARIANTS,
    args_for,
    open_url,
    wait_until_list_is_loaded,
)

ROOT = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "scam-warning"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)

    pages = Pages({"/": (SAFE_PAGE, HTML)})
    try:
        with list_folder({"scamlist.txt": SCAM_LIST}) as lists:
            for name, extra, _paper, _accent in VARIANTS:
                with (
                    tempfile.TemporaryDirectory(
                        prefix="scam-", dir=os.environ.get("TMP") or None
                    ) as profile,
                    Browser(
                        user_data_dir=profile,
                        args=args_for(lists, pages, extra),
                        headful=True,
                    ) as b,
                ):
                    wait_until_list_is_loaded(b)
                    open_url(b, f"http://{LISTED}:{pages.port}/")
                    time.sleep(2.0)
                    hwnd = frame_window(CHROME, under=b.proc.pid)
                    time.sleep(0.6)
                    out = os.path.join(args.out, f"scam-warning-{name}.png")
                    got = grab(hwnd, out)
                    print(f"saved {out} {got[0]}x{got[1]}")
    finally:
        pages.close()


if __name__ == "__main__":
    main()
