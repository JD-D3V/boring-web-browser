#!/usr/bin/env python3
"""Check the main menu's entries: the new layout, and that nothing went.

Opens the app menu through UI Automation on our own window (Expand on the
menu button, as smoke_forget.py and smoke_site_panel.py do), reads the
accessible names in it, measures it by PrintWindow of the menu's own
window, then opens each submenu the same way and reads those. Last it
presses the New tab tile and the Settings button (UI Automation Invoke)
and checks through WebDriver that each opened its tab. Sends no mouse or
keys to the desktop.

    python smoke_app_menu.py                           # wired: window pass 1e, smoke_all
    python smoke_app_menu.py --save before.json        # on the old build
                                    (its layout check fails there; the file is what counts)
    python smoke_app_menu.py --compare before.json     # on the new build

It always checks the mockup A layout (design/v9-menu): tiles, then Browse,
Page and Browser, then the bar, and the menu's height (MENU_HEIGHT).
--compare also fails if any entry of the saved menu, top level or inside a
submenu, is missing now. That the patch keeps every command is checked
without a browser by tests/test_app_menu_refresh.py.
Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import ctypes
import json
import os
import re
import sys
import tempfile
import time

from capture_app_menu import shoot_popup
from capture_native import frame_window
from drive import CHROME, Browser
from smoke_site_panel import COLLAPSE, Window, browser_windows

# The refreshed menu's height in DIP, border included, in a fresh profile
# with no update, warning or managed row: mockup A comes to 770.
MENU_HEIGHT = 769
TOLERANCE = 6

# The new menu, top to bottom: tiles, headings with their rows, the bar.
LAYOUT = [
    "New tab",
    "New window",
    "New Incognito window",
    "Browse",
    "Passwords and autofill",
    "History",
    "Downloads",
    "Bookmarks and lists",
    "Extensions",
    "Delete browsing data...",
    "Page",
    "Zoom",
    "Print...",
    "Translate...",
    "Find and edit",
    "Save and share",
    "More tools",
    "Browser",
    "Protection",
    "Forget this session",
    "About Boring Browser",
    "Settings",
    "Exit",
]
SUBMENUS = [
    "Passwords and autofill",
    "History",
    "Bookmarks and lists",
    "Extensions",
    "Find and edit",
    "Save and share",
    "More tools",
]
# A row's name ends with its shortcut ("Downloads Ctrl+J").
SHORTCUT = re.compile(r"\s+((Ctrl|Alt|Shift|F\d+)(\+\S+)*)$")


def plain(name):
    return SHORTCUT.sub("", name.strip())


def is_app_menu_button(name):
    return name.startswith("Customize and control") or name in (
        "Chromium",
        "Boring Browser",
    )


def window_names(b, frame, wanted, timeout=10.0):
    """Names of the first window of ours, not the frame, that `wanted` likes."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd in browser_windows(b.proc.pid):
            if hwnd == frame:
                continue
            try:
                with Window(hwnd) as w:
                    names = [plain(n) for n in w.names()]
            except OSError:
                continue
            if wanted(names):
                return hwnd, names
        time.sleep(0.3)
    return None, []


def open_menu(b, frame):
    with Window(frame) as w:
        w.press(is_app_menu_button)
    menu, top = window_names(b, frame, lambda ns: "Downloads" in ns)
    if not menu:
        raise SystemExit("the app menu did not open")
    return menu, top


def read_menu(b, frame, shot):
    menu, top = open_menu(b, frame)
    try:
        height = shoot_popup(menu, shot)
    except (OSError, ValueError) as e:
        print("could not measure the menu:", e)
        height = None
    subs = {}
    for row in SUBMENUS:
        if row not in top:
            continue
        try:
            with Window(menu) as w:
                w.press(lambda n, row=row: plain(n) == row)
        except (LookupError, RuntimeError) as e:
            subs[row] = [f"<could not open: {e}>"]
            continue
        _, names = window_names(
            b, frame, lambda ns: bool(ns) and "Downloads" not in ns, timeout=5
        )
        subs[row] = names
        try:
            with Window(menu) as w:
                w.press(lambda n, row=row: plain(n) == row, COLLAPSE)
        except (LookupError, RuntimeError):
            pass
        time.sleep(0.3)
    return {"top": top, "submenus": subs, "height": height}


def handles(b):
    return b._req("GET", f"/session/{b.sid}/window/handles")["value"]


def press_opens_tab(b, frame, name, url_prefix):
    """Press `name` in the open menu; None when it opened a tab at the
    prefix, else what went wrong."""
    menu, _ = window_names(b, frame, lambda ns: "Downloads" in ns, timeout=3)
    if not menu:
        menu, _ = open_menu(b, frame)
    before = handles(b)
    try:
        with Window(menu) as w:
            w.press(lambda n: plain(n) == name)
    except (LookupError, RuntimeError) as e:
        return f"could not press {name}: {e}"
    deadline = time.time() + 10
    url = None
    while time.time() < deadline:
        new = [h for h in handles(b) if h not in before]
        if new:
            b._req("POST", f"/session/{b.sid}/window", {"handle": new[-1]})
            url = b.current_url()
            if url.startswith(url_prefix):
                return None
        time.sleep(0.3)
    return f"{name} opened {url}" if url else f"{name} opened no tab"


def check_layout(menu):
    top = menu["top"]
    missing = [n for n in LAYOUT if n not in top]
    # A name can show twice (a control and its label); the first counts.
    order = list(dict.fromkeys(n for n in top if n in LAYOUT))
    wanted = [n for n in LAYOUT if n in order]
    problems = [f"missing at the top level: {missing}"] if missing else []
    if order != wanted:
        problems.append(f"order is {order}")
    height = menu.get("height")
    if height is None:
        problems.append("the menu's height was not measured")
    elif abs(height - MENU_HEIGHT) > TOLERANCE:
        problems.append(f"the menu is {height:.0f} DIP tall, not {MENU_HEIGHT}")
    for row, names in menu["submenus"].items():
        if not names or names[0].startswith("<could not open"):
            problems.append(f"submenu {row} did not open")
    return problems


def compare(before, after):
    problems = []
    gone = sorted(set(before["top"]) - set(after["top"]))
    if gone:
        problems.append(f"gone from the top level: {gone}")
    for row, names in before["submenus"].items():
        now = after["submenus"].get(row, [])
        lost = sorted(set(names) - set(now))
        if lost:
            problems.append(f"gone from {row}: {lost}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", help="write what the menu holds to this file")
    ap.add_argument("--compare", help="a file --save wrote on the old build")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--shot", help="keep the picture of the open menu here")
    opts = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)

    args = [
        "--disable-background-mode",
        "--disable-boring-updates",
        "--disable-boring-list-updates",
        "--window-size=1360,900",
    ]
    if opts.dark:
        args.append("--force-dark-mode")
    pressed = []
    with (
        tempfile.TemporaryDirectory(
            prefix="app-menu-", dir=os.environ.get("TMP") or None
        ) as profile,
        Browser(user_data_dir=profile, args=args, headful=True) as b,
    ):
        b.get("chrome://boring-newtab")
        frame = frame_window(CHROME, under=b.proc.pid)
        menu = read_menu(b, frame, opts.shot or os.path.join(profile, "menu.png"))
        for name, prefix in (
            ("New tab", "chrome://"),
            ("Settings", "chrome://settings"),
        ):
            pressed.append(press_opens_tab(b, frame, name, prefix))

    print("top level:", menu["top"])
    for row, names in menu["submenus"].items():
        print(f"{row}: {names}")
    if opts.save:
        with open(opts.save, "w", encoding="utf-8") as f:
            json.dump(menu, f, indent=1)
        print("saved", opts.save)
    problems = check_layout(menu) + [p for p in pressed if p]
    if opts.compare:
        with open(opts.compare, encoding="utf-8") as f:
            problems += compare(json.load(f), menu)
    for p in problems:
        print("FAIL", p)
    print("PASS" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
