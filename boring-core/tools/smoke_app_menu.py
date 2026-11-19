#!/usr/bin/env python3
"""Check the main menu's entries: the new layout, and that nothing went.

Opens the app menu through UI Automation on our own window (Expand on the
menu button, as smoke_forget.py and smoke_site_panel.py do), reads the
accessible names in it, measures it by PrintWindow of the menu's own
window, then opens each submenu the same way and reads those. Last it
presses New tab, Settings, Protection and About Boring Browser (UI Automation
Invoke) and checks through WebDriver that each opened its page, presses
Reading mode in More tools and checks the reading side panel appeared, and
presses Forget this session and checks it asks first (then cancels). The menu
and its submenus must have no name that says Chrome or Chromium. A second launch
with --boring-open-app-menu=keys has the browser send key events to its own
open menu (Down, Up, Left, Right, End, Enter) and checks what each selected.
Sends no mouse or keys to the desktop.

    python smoke_app_menu.py                           # wired: window pass 1e, smoke_all
    python smoke_app_menu.py --save before.json        # on the old build
                                    (its layout check fails there; the file is what counts)
    python smoke_app_menu.py --compare before.json     # on the new build

It always checks the mockup A layout (design/v9-menu): exactly the entries of
LAYOUT in that order (an extra, repeated or moved one fails), and the menu's
height (MENU_HEIGHT).
--compare also fails if any entry of the saved menu, top level or inside a
submenu, is missing now. That the patch keeps every command is checked
without a browser by tests/test_app_menu_refresh.py.
Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import ctypes
import itertools
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
    "Delete browsing data\u2026",
    "Page",
    "Zoom",
    "Make Text Smaller",
    "Make Text Larger",
    "Full screen",
    "Print\u2026",
    "Translate\u2026",
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
# Page the Reading mode press runs on: a menu row is only a command, so the
# check is that the reading side panel opens.
ARTICLE = "data:text/html,<title>t</title><h1>Hello</h1><p>" + "word " * 300 + "</p>"
FORGET_ROW = "Forget this session"
FORGET_TITLE = "Forget this session?"
# Visible text must never name the upstream product.
UPSTREAM = re.compile(r"chrom(e|ium)", re.IGNORECASE)
KEYS_FILE = "boring-app-menu-keys.txt"
# The keys WalkKeysForTest (boring_app_menu.cc) sends, in order: Down, Up,
# Left, Right, End (X), Home (H), Enter (E).
KEYS = "DRRL" + "D" * 20 + "XLRL" + "U" * 14 + "HDDDUXLE"
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


def press_menu_button(frame):
    with Window(frame) as w:
        # On a browser page the location bar's chip is also named "Boring
        # Browser"; the menu button is the last control of that name.
        last = len(w.elements(is_app_menu_button))
        calls = itertools.count(1)
        w.press(lambda n: is_app_menu_button(n) and next(calls) == last)


def open_menu(b, frame, tries=3):
    """The open app menu's window and names, opening the menu if it is shut.

    A menu on a desktop that is busy sometimes closes by itself, so a shut
    menu is opened again rather than failing the run at once."""
    for _ in range(tries):
        menu, top = window_names(b, frame, lambda ns: "Downloads" in ns, timeout=1)
        if menu:
            return menu, top
        try:
            press_menu_button(frame)
        except (LookupError, RuntimeError, OSError):
            continue
        menu, top = window_names(b, frame, lambda ns: "Downloads" in ns)
        if menu:
            return menu, top
    raise SystemExit("the app menu did not open")


def read_submenu(b, frame, row, tries=3):
    """The names inside the submenu of `row`, or a note that it did not open."""
    why = "no window"
    for _ in range(tries):
        menu, _ = open_menu(b, frame)
        try:
            with Window(menu) as w:
                w.press(lambda n: plain(n) == row)
        except (LookupError, RuntimeError, OSError) as e:
            why = str(e)
            continue
        _, names = window_names(
            b, frame, lambda ns: bool(ns) and "Downloads" not in ns, timeout=5
        )
        try:
            with Window(menu) as w:
                w.press(lambda n: plain(n) == row, COLLAPSE)
        except (LookupError, RuntimeError, OSError):
            pass
        time.sleep(0.3)
        if names:
            return names
    return [f"<could not open: {why}>"]


def read_menu(b, frame, shot):
    menu, top = open_menu(b, frame)
    try:
        height = shoot_popup(menu, shot)
    except (OSError, ValueError) as e:
        print("could not measure the menu:", e)
        height = None
    subs = {row: read_submenu(b, frame, row) for row in SUBMENUS if row in top}
    return {"top": top, "submenus": subs, "height": height}


def handles(b):
    return b._req("GET", f"/session/{b.sid}/window/handles")["value"]


def tab_urls(b):
    """{handle: url} of every tab; the driver ends up on the last one."""
    urls = {}
    for handle in handles(b):
        b._req("POST", f"/session/{b.sid}/window", {"handle": handle})
        urls[handle] = b.current_url()
    return urls


def press_opens_tab(b, frame, name, url_prefix):
    """Press `name` in the open menu; None when a tab came to show a page at
    the prefix (a new tab, the tab in front, or one that was already open,
    as Settings is), else what went wrong. The driver is left on that tab."""
    menu, _ = window_names(b, frame, lambda ns: "Downloads" in ns, timeout=3)
    if not menu:
        menu, _ = open_menu(b, frame)
    before = tab_urls(b)
    try:
        with Window(menu) as w:
            w.press(lambda n: plain(n) == name)
    except (LookupError, RuntimeError) as e:
        return f"could not press {name}: {e}"
    deadline = time.time() + 10
    now = before
    while time.time() < deadline:
        now = tab_urls(b)
        for handle, url in now.items():
            if url.startswith(url_prefix) and before.get(handle) != url:
                b._req("POST", f"/session/{b.sid}/window", {"handle": handle})
                return None
        time.sleep(0.3)
    changed = [u for h, u in now.items() if before.get(h) != u]
    return f"{name} opened {changed}" if changed else f"{name} opened nothing"


def check_layout(menu):
    top = menu["top"]
    problems = []
    if top != LAYOUT:
        missing = [n for n in LAYOUT if n not in top]
        extra = [n for n in top if n not in LAYOUT]
        repeated = sorted({n for n in top if top.count(n) > 1})
        if missing:
            problems.append(f"missing at the top level: {missing}")
        if extra:
            problems.append(f"extra at the top level: {extra}")
        if repeated:
            problems.append(f"repeated at the top level: {repeated}")
        if not (missing or extra or repeated):
            problems.append(f"order is {top}")
    height = menu.get("height")
    if height is None:
        problems.append("the menu's height was not measured")
    elif abs(height - MENU_HEIGHT) > TOLERANCE:
        problems.append(f"the menu is {height:.0f} DIP tall, not {MENU_HEIGHT}")
    for row, names in menu["submenus"].items():
        if not names or names[0].startswith("<could not open"):
            problems.append(f"submenu {row} did not open")
    return problems


def check_upstream_names(menu):
    """No entry of the menu or of a submenu says Chrome or Chromium."""
    seen = [("top level", n) for n in menu["top"]]
    for row, names in menu["submenus"].items():
        seen += [(row, n) for n in names]
    return [f"{where} shows {n!r}" for where, n in seen if UPSTREAM.search(n)]


def targets(b):
    """(type, url) of every DevTools target in the browser."""
    infos = b._req(
        "POST",
        f"/session/{b.sid}/goog/cdp/execute",
        {"cmd": "Target.getTargets", "params": {}},
    )["value"]["targetInfos"]
    return [(t["type"], t["url"]) for t in infos]


def press_reading_mode(b, frame):
    """Press Reading mode in More tools; None when the reading side panel
    opened, else what went wrong."""
    b.get(ARTICLE)
    time.sleep(1)
    menu, _ = open_menu(b, frame)
    try:
        with Window(menu) as w:
            w.press(lambda n: plain(n) == "More tools")
    except (LookupError, RuntimeError, OSError) as e:
        return f"could not open More tools: {e}"
    sub, _ = window_names(b, frame, lambda ns: "Reading mode" in ns, timeout=5)
    if not sub:
        return "More tools did not show Reading mode"
    try:
        with Window(sub) as w:
            w.press(lambda n: plain(n) == "Reading mode")
    except (LookupError, RuntimeError, OSError) as e:
        return f"could not press Reading mode: {e}"
    deadline = time.time() + 10
    while time.time() < deadline:
        if any("read-anything-side-panel" in url for _, url in targets(b)):
            return None
        time.sleep(0.3)
    return "Reading mode opened no reading side panel"


def press_forget(b, frame):
    """Press Forget this session; None when it asked first and Cancel kept
    every tab, else what went wrong. Forget itself is smoke_forget.py's."""
    menu, _ = window_names(b, frame, lambda ns: FORGET_ROW in ns, timeout=3)
    if not menu:
        menu, _ = open_menu(b, frame)
    before = set(handles(b))
    try:
        with Window(menu) as w:
            w.press(lambda n: plain(n) == FORGET_ROW)
    except (LookupError, RuntimeError, OSError) as e:
        return f"could not press {FORGET_ROW}: {e}"
    deadline = time.time() + 10
    dialog = None
    while time.time() < deadline and not dialog:
        for hwnd in browser_windows(b.proc.pid):
            try:
                with Window(hwnd) as w:
                    names = [plain(n) for n in w.names()]
            except OSError:
                continue
            if FORGET_TITLE in names and "Cancel" in names and "Forget" in names:
                dialog = hwnd
                break
        time.sleep(0.3)
    if not dialog:
        return f"{FORGET_ROW} asked nothing"
    try:
        with Window(dialog) as w:
            w.press(lambda n: plain(n) == "Cancel")
    except (LookupError, RuntimeError, OSError) as e:
        return f"could not press Cancel: {e}"
    time.sleep(1.5)
    if set(handles(b)) != before:
        return f"Cancel on {FORGET_ROW} still closed or opened tabs"
    return None


def walk_keys(args):
    """The keyboard walk: --boring-open-app-menu=keys opens the menu and
    sends it key events inside the browser (boring_app_menu.cc,
    WalkKeysForTest), which writes (key, selection) after each. Returns
    those and whether the Enter at the end opened Settings."""
    with (
        tempfile.TemporaryDirectory(
            prefix="app-menu-keys-", dir=os.environ.get("TMP") or None
        ) as profile,
        Browser(
            user_data_dir=profile,
            args=[*args, "--boring-open-app-menu=keys"],
            headful=True,
        ) as b,
    ):
        b.get("chrome://boring-newtab")
        report = os.path.join(profile, KEYS_FILE)
        deadline = time.time() + 20
        while time.time() < deadline and not os.path.exists(report):
            time.sleep(0.3)
        time.sleep(0.5)
        settings = False
        while time.time() < deadline + 5 and not settings:
            for handle in handles(b):
                b._req("POST", f"/session/{b.sid}/window", {"handle": handle})
                settings = settings or b.current_url().startswith("chrome://settings")
            time.sleep(0.3)
        text = ""
        if os.path.exists(report):
            with open(report, encoding="utf-8") as f:
                text = f.read()
    steps = [line.split(" ", 1) for line in text.splitlines() if " " in line]
    return [(k, plain(n.replace("&", ""))) for k, n in steps], settings


def check_keys(steps, settings):
    """Left and Right move across the tiles and the bar; Up and Down step
    through a row's buttons first, as in the stock zoom row, and never stop
    on a heading; Enter presses the selected button."""
    problems = [] if settings else ["Enter on Settings opened no Settings page"]
    if "".join(k for k, _ in steps) != KEYS:
        return [f"the key walk stopped after {len(steps)} keys: {steps}", *problems]
    names = [name for _, name in steps]
    if set(names) & {"Browse", "Page", "Browser"}:
        problems.append(f"a heading took the selection: {names}")
    want = {
        0: "New tab",
        1: "New window",  # Right
        2: "New Incognito window",  # Right
        3: "New window",  # Left
        24: "Exit",  # End
        25: "Settings",  # Left
        26: "Exit",  # Right
        27: "Settings",  # Left
        42: "New tab",  # Home
        45: "Passwords and autofill",  # Down past Browse
        46: "New Incognito window",  # Up past Browse
        47: "Exit",  # End
        48: "Settings",  # Left, then Enter
    }
    for i, name in want.items():
        if names[i] != name:
            problems.append(f"key {i + 1} ({KEYS[i]}) selected {names[i]}, not {name}")
    down, up = names[4:24], names[28:42]
    for walk, pairs in (
        (
            down,
            [
                ("New Incognito window", "Passwords and autofill"),
                ("Delete browsing data\u2026", "Make Text Smaller"),
                ("More tools", "Protection"),
            ],
        ),
        (
            up,
            [
                ("Protection", "More tools"),
                ("Make Text Smaller", "Delete browsing data\u2026"),
            ],
        ),
    ):
        for a, b in pairs:
            if not any(walk[k : k + 2] == [a, b] for k in range(len(walk) - 1)):
                problems.append(f"no step from {a} to {b} in {walk}")
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
            ("Protection", "chrome://boring-protection"),
            ("About Boring Browser", "chrome://settings/help"),
        ):
            pressed.append(press_opens_tab(b, frame, name, prefix))
        pressed.append(press_reading_mode(b, frame))
        pressed.append(press_forget(b, frame))
    steps, settings = walk_keys(args)

    print("top level:", menu["top"])
    print("keys:", steps)
    for row, names in menu["submenus"].items():
        print(f"{row}: {names}")
    if opts.save:
        with open(opts.save, "w", encoding="utf-8") as f:
            json.dump(menu, f, indent=1)
        print("saved", opts.save)
    problems = check_layout(menu) + check_upstream_names(menu)
    problems += [p for p in pressed if p]
    problems += check_keys(steps, settings)
    if opts.compare:
        with open(opts.compare, encoding="utf-8") as f:
            problems += compare(json.load(f), menu)
    for p in problems:
        print("FAIL", p)
    print("PASS" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
