#!/usr/bin/env python3
r"""Launch the browser the way a person does and look for what must not show.

Ledger 121 and 122 (Release 3). Chromium 157 can show a "continue where you
left off" infobar on a start and a promo bubble for side tabs; this build
turns both off (patches/157/feature-defaults.patch). Headless runs cannot see
either, and the test tools start the browser with --no-first-run and friends,
so this one does not:

  1. a fresh profile, only --user-data-dir (plus the window position and two
     occlusion switches, so the window stays off every monitor and keeps
     painting for the picture), two pages given as arguments, as a shortcut
     with addresses would
  2. wait, read the window, close it with WM_CLOSE posted to OUR OWN window
  3. start it again on the same profile, no addresses, wait, read the window

"Read" means UI Automation on our own windows (names of every control of
every visible top level window of the build, so a bubble counts) and
PrintWindow of the frame. No mouse, no keys, no screen capture. The browser
is always ended in a finally block, by process id and only from this build.

Fails when any control name mentions "left off", "restore pages", "continue
where", a side tabs promo ("vertical tabs", "tabs on the side") or the
pin-to-taskbar infobar ("Pin Boring Browser to your taskbar"). Also prints
whether the bookmarks bar hint was seen, as proof that the scan reads the
browser's own controls.

Usage: python check_user_launch.py --out DIR [--wait 30]
Needs BORING_OUT (the build folder), as the other tools do. The profile goes
under TMP.
"""

import argparse
import contextlib
import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

from capture_native import ENUMPROC, RECT, chrome_pids, grab
from drive import CHROME
from smoke_site_panel import Window

user32 = ctypes.WinDLL("user32", use_last_error=True)
WM_CLOSE = 0x0010

BAD = re.compile(
    r"left off|restore pages|continue where|vertical tabs|tabs on the side|side tabs"
    # Chromium's pin-to-taskbar infobar, held off while the browser is not the
    # default (ledger 129, Q52).
    r"|pin boring browser|pin to taskbar|to your taskbar",
    re.IGNORECASE,
)
HINT = re.compile(r"bookmarks you add show here", re.IGNORECASE)


def visible_windows(pids):
    """Every visible top level window of these processes, titled or not
    (a bubble often has no title)."""
    found = []

    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value in pids:
                found.append(hwnd)
        return True

    user32.EnumWindows(ENUMPROC(cb), 0)
    return found


def title_of(hwnd):
    buf = ctypes.create_unicode_buffer(200)
    user32.GetWindowTextW(hwnd, buf, 200)
    return buf.value


def frame_of(pids):
    best, best_area = None, 0
    for hwnd in visible_windows(pids):
        r = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if w > 400 and w * h > best_area:
            best, best_area = hwnd, w * h
    return best


def end_browser(proc):
    """Close the frame politely, wait, then end whatever is left of OUR
    build by process id."""
    pids = chrome_pids(CHROME)
    frame = frame_of(pids)
    if frame:
        user32.PostMessageW(frame, WM_CLOSE, 0, 0)
    deadline = time.time() + 30
    while time.time() < deadline and chrome_pids(CHROME):
        time.sleep(0.5)
    left = chrome_pids(CHROME)
    for pid in left:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    return not left


def launch(profile, urls, label, wait, out):
    print(f"--- {label}: starting", flush=True)
    args = [
        CHROME,
        f"--user-data-dir={profile}",
        "--window-position=-32000,-32000",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
        *urls,
    ]
    proc = subprocess.Popen(args)
    problems = []
    try:
        deadline = time.time() + 40
        frame = None
        while time.time() < deadline and not frame:
            time.sleep(0.5)
            frame = frame_of(chrome_pids(CHROME))
        if not frame:
            return ["no browser window appeared"], False
        print(
            f"    window: {title_of(frame)!r}; waiting {wait} s for bars and bubbles",
            flush=True,
        )
        time.sleep(wait)
        pids = chrome_pids(CHROME)
        names = []
        windows = visible_windows(pids)
        for hwnd in windows:
            with Window(hwnd) as w:
                names.extend((title_of(hwnd), n) for n in w.names())
        frame = frame_of(pids) or frame
        shot = out / f"{label}.png"
        size = grab(frame, str(shot))
        print(
            f"    {len(windows)} visible windows, {len(names)} control names, picture {shot} {size}"
        )
        (out / f"{label}-names.txt").write_text(
            "\n".join(f"[{t}] {n}" for t, n in names), encoding="utf-8"
        )
        for t, n in names:
            if BAD.search(n) or BAD.search(t):
                problems.append(f"window [{t}] has a control named {n!r}")
        seen_hint = any(HINT.search(n) for _t, n in names)
        print(f"    bookmarks bar hint seen by the scan: {seen_hint}")
        return problems, seen_hint
    finally:
        clean = end_browser(proc)
        print(f"    closed: {'cleanly' if clean else 'had to be ended'}", flush=True)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--wait", type=int, default=30)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if chrome_pids(CHROME):
        print("stop: a browser from this build is already running")
        return 2
    profile = tempfile.mkdtemp(
        prefix="boring-userlaunch-", dir=os.environ.get("TMP") or None
    )
    failures = []
    try:
        p1, hint1 = launch(
            profile,
            ["https://example.com/", "https://example.org/"],
            "launch1-fresh-with-two-pages",
            args.wait,
            args.out,
        )
        p2, hint2 = launch(
            profile, [], "launch2-same-profile-no-address", args.wait, args.out
        )
        failures = p1 + p2
        print()
        print("fresh profile shows the bookmarks bar hint:", hint1)
        print("second start shows the bookmarks bar hint:", hint2)
        for f in failures:
            print("FAIL", f)
        print(
            "PASS no restore bar, no side tabs promo and no pin to taskbar bar in either start"
            if not failures
            else f"FAIL {len(failures)} control(s) found"
        )
    finally:
        end_browser(None)
        shutil.rmtree(profile, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
