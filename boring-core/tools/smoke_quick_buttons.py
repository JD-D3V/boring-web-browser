#!/usr/bin/env python3
"""Smoke test: Settings and Extensions can be pinned to the toolbar, and the
toolbar's right click menu offers "Customize toolbar".

Several launches of one scratch profile, started straight from chrome.exe:

  1. A new profile. Nothing new is pinned. The picker (the Customize
     toolbar side panel, opened the way the menu item opens it) lists
     Settings and Extensions and does not list Translate, Cast or Send
     to your device, which do nothing in this build.
  2. Same profile. Both are ticked in the picker, which pins them.
  3. Same profile, dark. Both are still pinned after the restart, and
     unticking them removes them again.
  4. The test hook --boring-toolbar-test=<step> (boring_toolbar_menu.cc)
     runs what the menu item and the two pinned buttons run: the picker
     opens, chrome://settings opens, chrome://extensions opens.
  5. The same hook shows the right click menu, which is photographed.

Only DevTools and PrintWindow of our own windows; nothing is sent to the
OS as input. Windows are placed off screen. Not checked, because a click
is input: that a click on the empty toolbar opens the menu, that choosing
its item opens the picker, and that Chromium's own right click menu on a
pinned button is untouched.

    python smoke_quick_buttons.py [--out E:\\tmp\\feat-quick-buttons\\shots]

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import contextlib
import ctypes
import json
import os
import re
import shutil
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

from capture_native import ENUMPROC, chrome_pids, frame_window, grab, parents_of, user32
from drive import CHROME
from smoke_local import Checks
from smoke_memory import close, launch

SETTINGS = "Settings"
EXTENSIONS = "Extensions"
SETTINGS_ID = "kActionOptions"
EXTENSIONS_ID = "kActionManageExtensions"
# What the picker must not offer: each does nothing in this build.
DEAD = ("Translate", "Cast", "Send to your device")

TOOLBAR_JS = (
    "document.querySelector('customize-chrome-app').shadowRoot"
    ".querySelector('customize-chrome-toolbar')"
)
ROWS = (
    "(() => { const tb = " + TOOLBAR_JS + "; if (!tb || !tb.shadowRoot) return null;"
    " return [...tb.shadowRoot.querySelectorAll('.toggle-container')].map(r => ({"
    "name: r.innerText.trim(),"
    "on: !!(r.querySelector('cr-toggle') && r.querySelector('cr-toggle').checked),"
    "icon: !!r.querySelector('img')})); })()"
)
CLICK_ROW = (
    "(() => { const tb = " + TOOLBAR_JS + ";"
    " const row = [...tb.shadowRoot.querySelectorAll('.toggle-container')]"
    ".find(r => r.innerText.trim() === %s); if (!row) return false;"
    " row.click(); return true; })()"
)


def find_key(node, key):
    """The first value stored under `key`, however deep, or None."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for child in node.values():
            found = find_key(child, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for child in node:
            found = find_key(child, key)
            if found is not None:
                return found
    return None


def pinned_actions(profile):
    """The pinned action ids a closed profile has on disk."""
    path = Path(profile) / "Default" / "Preferences"
    with open(path, encoding="utf-8") as f:
        return find_key(json.load(f), "pinned_actions") or []


def bad_text(text):
    """Visible text that says Chrome or Chromium, or has an em or en dash."""
    return bool(re.search(r"chrom(e|ium)|\u2014|\u2013", text, re.I))


def settings_tab(cdp):
    tab = cdp.open_tab("chrome://settings/appearance", background=False)
    session = cdp.attach(tab)
    cdp.wait_for(session, "!!document.querySelector('settings-ui')", 20)
    time.sleep(1.5)
    return tab, session


def open_picker(cdp):
    """Opens the Customize toolbar panel; returns the panel's session."""
    _tab, session = settings_tab(cdp)
    cdp.evaluate(session, "chrome.send('openCustomizeChromeToolbarSection'); 'sent'")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for t in cdp.send("Target.getTargets")["targetInfos"]:
            if "customize-chrome-side-panel" in t["url"]:
                panel = cdp.attach(t["targetId"])
                if cdp.wait_for(panel, "(" + ROWS + " || []).length > 0", 10):
                    return panel
        time.sleep(0.3)
    return None


def rows(cdp, panel):
    return cdp.evaluate(panel, ROWS) or []


def click_row(cdp, panel, name):
    return cdp.evaluate(panel, CLICK_ROW % json.dumps(name))


def shoot(path):
    """PrintWindow of the biggest window of the browser this run started.
    The window is never moved; it was opened off screen."""
    hwnd = frame_window(CHROME, under=os.getpid())
    time.sleep(0.8)
    grab(hwnd, str(path))
    print("saved", path)


def wait_target(cdp, needle, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for t in cdp.send("Target.getTargets")["targetInfos"]:
            if needle in t["url"]:
                return t["url"]
        time.sleep(0.3)
    return None


def popup_window(frame):
    """A visible window of the browser this run started that is not the
    frame: the menu's own popup, which has no title, so windows_of misses it."""
    ours = {p for p, parent in parents_of(chrome_pids(CHROME)).items() if parent == os.getpid()}
    found = []

    class RECT(ctypes.Structure):
        _fields_ = [(n, wintypes.LONG) for n in ("left", "top", "right", "bottom")]

    def cb(hwnd, _lparam):
        if hwnd == frame or not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in ours:
            r = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            if 60 < w < 600 and 20 < h < 400:
                found.append(hwnd)
        return True

    user32.EnumWindows(ENUMPROC(cb), 0)
    return found[0] if found else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", default=r"E:\tmp\feat-quick-buttons\shots", help="folder for the photographs"
    )
    args = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    checks = Checks()
    work = Path(tempfile.mkdtemp(prefix="boring-qb-", dir=os.environ.get("TMP", r"E:\tmp")))
    profile = work / "profile"
    profile.mkdir()
    flags = ["--disable-features=CalculateNativeWinOcclusion"]
    proc = cdp = None

    def start(extra=(), where=profile):
        nonlocal proc, cdp
        proc, cdp = launch(CHROME, where, [*flags, *extra])
        time.sleep(3)

    def stop():
        nonlocal proc, cdp
        if proc:
            close(proc, cdp)
        proc = cdp = None

    try:
        # 1. A new profile: nothing new pinned, the picker has what it should.
        start()
        panel = open_picker(cdp)
        checks("the picker opens", panel is not None)
        listed = rows(cdp, panel) if panel else []
        names = [r["name"] for r in listed]
        print("picker rows:", names)
        checks("the picker lists Settings", SETTINGS in names)
        checks("the picker lists Extensions", EXTENSIONS in names)
        checks(
            "Settings and Extensions come first among the browser rows",
            names[:6].index(SETTINGS) < names[:6].index(EXTENSIONS)
            if SETTINGS in names[:6] and EXTENSIONS in names[:6]
            else False,
            str(names[:6]),
        )
        for dead in DEAD:
            checks(f"the picker does not offer {dead}", dead not in names)
        checks("no picker text says Chrome or has a dash", not any(bad_text(n) for n in names))
        new_rows = [r for r in listed if r["name"] in (SETTINGS, EXTENSIONS)]
        checks(
            "the new rows have an icon",
            len(new_rows) == 2 and all(r["icon"] for r in new_rows),
        )
        checks(
            "nothing is ticked that was not before",
            not any(r["on"] for r in listed if r["name"] in (SETTINGS, EXTENSIONS)),
        )
        shoot(out / "picker-light.png")
        stop()
        pins = pinned_actions(profile)
        print("pinned_actions on a new profile:", pins)
        checks(
            "a new profile pins neither Settings nor Extensions",
            SETTINGS_ID not in pins and EXTENSIONS_ID not in pins,
            str(pins),
        )

        # 2. Tick both in the picker.
        start()
        panel = open_picker(cdp)
        checks("the picker opens again", panel is not None)
        if panel:
            checks("Settings ticks", bool(click_row(cdp, panel, SETTINGS)))
            time.sleep(1)
            checks("Extensions ticks", bool(click_row(cdp, panel, EXTENSIONS)))
            time.sleep(2)
            on = {r["name"]: r["on"] for r in rows(cdp, panel)}
            checks("both rows show as on", on.get(SETTINGS) and on.get(EXTENSIONS), str(on))
            shoot(out / "pinned-light.png")
        stop()
        pins = pinned_actions(profile)
        print("pinned_actions after ticking:", pins)
        checks("both are in the profile's pinned actions", SETTINGS_ID in pins and EXTENSIONS_ID in pins, str(pins))

        # 3. After a restart they are still there, in dark; untick removes them.
        start(["--force-dark-mode"])
        panel = open_picker(cdp)
        if panel:
            on = {r["name"]: r["on"] for r in rows(cdp, panel)}
            checks("both are still ticked after a restart", on.get(SETTINGS) and on.get(EXTENSIONS), str(on))
            shoot(out / "pinned-dark.png")
            click_row(cdp, panel, SETTINGS)
            time.sleep(1)
            click_row(cdp, panel, EXTENSIONS)
            time.sleep(2)
            on = {r["name"]: r["on"] for r in rows(cdp, panel)}
            checks("unticking turns both off", not on.get(SETTINGS) and not on.get(EXTENSIONS), str(on))
            shoot(out / "unpinned-dark.png")
        else:
            checks("the picker opens after a restart", False)
        stop()
        pins = pinned_actions(profile)
        print("pinned_actions after unticking:", pins)
        checks("neither is pinned after unticking", SETTINGS_ID not in pins and EXTENSIONS_ID not in pins, str(pins))

        # 4. What the menu item and the pinned buttons run. Each in a new
        # profile, so no tab restored from an earlier run can stand in.
        for step, needle, what in (
            ("customize", "customize-chrome-side-panel", "Customize toolbar opens the picker"),
            ("settings", "chrome://settings", "the Settings button opens Settings"),
            ("extensions", "chrome://extensions", "the Extensions button opens Extensions"),
        ):
            fresh = work / f"hook-{step}"
            fresh.mkdir()
            start([f"--boring-toolbar-test={step}"], fresh)
            checks(what, wait_target(cdp, needle) is not None)
            stop()

        # 5. The right click menu itself.
        fresh = work / "hook-menu"
        fresh.mkdir()
        start(["--boring-toolbar-test=menu"], fresh)
        frame = frame_window(CHROME, under=os.getpid())
        popup, deadline = None, time.monotonic() + 15
        while popup is None and time.monotonic() < deadline:
            popup = popup_window(frame)
            time.sleep(0.1)
        checks("the right click menu opens", popup is not None)
        if popup:
            time.sleep(0.5)
            grab(popup, str(out / "right-click-menu.png"))
            print("saved", out / "right-click-menu.png")
        stop()
        return checks.result("quick buttons")
    finally:
        stop()
        with contextlib.suppress(Exception):
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
