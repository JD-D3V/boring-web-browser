#!/usr/bin/env python3
"""Photograph the look-alike warning page: light and dark.

Same setup as smoke_lookalike.py (local names mapped to 127.0.0.1) and the
same way of photographing as capture_native.py: a PrintWindow of our own
browser window, never the screen.

Usage: python capture_lookalike.py [--out DIR]
Writes DIR/lookalike-<site|no-site>-<light|dark>.png, by default into
artifacts/lookalike/ at the repository root.
"""

import argparse
import ctypes
import os
import tempfile
import time
from pathlib import Path

from capture_native import frame_window, grab
from drive import CHROME, Browser
from smoke_local import wait_for
from smoke_lookalike import (
    NO_TARGET,
    PLAIN,
    WARNED,
    Recorder,
    browser_args,
    open_url,
)

ROOT = Path(__file__).resolve().parents[2]

# (file word, extra browser arguments)
SCHEMES = [("light", []), ("dark", ["--force-dark-mode"])]
# (file word, host)
PAGES = [("site", PLAIN[0]), ("no-site", NO_TARGET)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "lookalike"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)

    server = Recorder()
    try:
        for scheme, extra in SCHEMES:
            with (
                tempfile.TemporaryDirectory(
                    prefix="lookalike-", dir=os.environ.get("TMP") or None
                ) as profile,
                Browser(
                    user_data_dir=profile, args=browser_args(extra), headful=True
                ) as b,
            ):
                for word, host in PAGES:
                    open_url(b, f"http://{host}:{server.port}/")
                    wait_for(b, WARNED)
                    time.sleep(1.5)
                    hwnd = frame_window(CHROME, under=b.proc.pid)
                    time.sleep(0.6)
                    out = os.path.join(args.out, f"lookalike-{word}-{scheme}.png")
                    got = grab(hwnd, out)
                    print(f"saved {out} {got[0]}x{got[1]}")
    finally:
        server.close()


if __name__ == "__main__":
    main()
