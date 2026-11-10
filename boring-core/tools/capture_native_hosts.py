#!/usr/bin/env python3
"""Photograph the "Apps on this computer" rows on the Protection page,
scrolled into view, with PrintWindow of our own window. The two test
hosts of smoke_native_hosts.py are registered under HKCU for the shot and
removed afterwards; one is switched on, the other left blocked.

  python capture_native_hosts.py --out E:\\tmp\\feat-native-hosts\\light.png
  python capture_native_hosts.py --out E:\\tmp\\feat-native-hosts\\dark.png --dark
"""

import argparse
import ctypes
import os
import shutil
import tempfile
import time

from capture_native import frame_window, grab, user32
from drive import CHROME, OFFSCREEN, Browser
from smoke_native_hosts import (
    HOST,
    HOST_GOOGLE,
    ROOT,
    addon_id,
    open_protection,
    register,
    set_switch,
    unregister,
    write_addon,
    write_host_files,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1000x1000", help="window size, WxH")
    ap.add_argument("--dark", action="store_true")
    args = ap.parse_args()

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    w, h = (int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get("BORING_CHROME", CHROME)
    os.makedirs(ROOT, exist_ok=True)
    work = tempfile.mkdtemp(prefix="cap-", dir=ROOT)
    unregister()
    chrome_args = [
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        f"--window-size={w},{h}",
        "--window-position=" + OFFSCREEN,
        "--load-extension=" + write_addon(work),
    ]
    if args.dark:
        chrome_args.append("--force-dark-mode")
    try:
        manifests, write_manifests = write_host_files(work)
        register(lambda name: manifests[name])
        with Browser(
            user_data_dir=os.path.join(work, "profile"),
            args=chrome_args,
            keep_switches=["enable-automation"],
            headful=True,
        ) as b:
            write_manifests(addon_id(b))
            if not open_protection(b):
                raise SystemExit("the host rows never appeared")
            # One on, the other blocked, whatever the profile started with.
            for name, on in ((HOST, True), (HOST_GOOGLE, False)):
                if (
                    b.run(f"return document.getElementById('host-{name}').checked")
                    != on
                ):
                    set_switch(b, name, on)
            b.run(
                "document.getElementById('connections-hosts').scrollIntoView(); return 1"
            )
            time.sleep(1.0)
            hwnd = frame_window(binary, under=b.proc.pid)
            x, y = (int(v) for v in OFFSCREEN.split(","))
            user32.MoveWindow(hwnd, x, y, w, h, True)
            time.sleep(0.8)
            got = grab(hwnd, args.out)
        print(f"saved {args.out} {got[0]}x{got[1]}")
    finally:
        unregister()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
