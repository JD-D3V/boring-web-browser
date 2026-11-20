#!/usr/bin/env python3
"""Smoke test: side tabs in the Shelf (ledger item 14, compiled screen C09).

Runs the real browser with a temp profile under E:\\tmp that already has
vertical_tabs.enabled set (written to its Preferences file, so no input is
sent from the OS). A small local server on 127.0.0.1 serves the pages. UI
Automation on our own window reads names and presses buttons; WebDriver reads
the page's width and counts tabs.

What it asserts (nothing is asserted that was not looked at):
  1. Default: a fresh profile keeps top tabs (no "Open tabs" heading, the
     Shelf toggle is in the tab strip).
  2. Side tabs on: a control named "Show or hide the Shelf", the headings
     "Open tabs" (and no "Pinned" while nothing is pinned), a "New tab" button.
  3. The list is about 248 DIP wide (the page gives up 248 to 272 DIP).
  4. Tab search, the organizer and the other strip buttons are not drawn
     (no control named like "Search tabs").
  5. Pressing the toggle narrows the list to icons (the page gets wider);
     pressing it again widens it.
  6. Pressing "New tab" opens a tab (WebDriver window handles grow by one).
  7. Private window: side tabs, or top tabs, but a working window with its
     toggle. App window: no list.
  8. Captures: PrintWindow of our window with side tabs, light and dark,
     beside C09 (--captures).
Not checked here: the pinned grid (four tiles to a row; a tab cannot be
pinned without input and no pin hook exists), the group heading row, the
Earlier section (item 16 is not built), the sheet's radius (drawn 10, built 8).

Usage: python boring-core/tools/smoke_sidetabs.py [--out DIR] [--captures DIR]
"""

import argparse
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import page_checks
from capture_native import frame_window, grab
from drive import CHROME, Browser
from smoke_local import Checks
from smoke_site_panel import Window

# Chrome's parent: chromedriver, set as each Browser starts.
DRIVER_PID = [None]

TOGGLE = "Show or hide the Shelf"
NEW_TAB = "New tab"
OPEN_HEADING = "Open tabs"
PINNED_HEADING = "Pinned"
LIST_WIDTH = 248


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        title = self.path.strip("/") or "Home"
        body = f"<!doctype html><title>{title}</title><p>{title}</p>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def side_tabs_state(names):
    """What the names on our window say about the side tabs list: a dict of
    facts. Pure, so it is tested without a browser."""
    have = set(names)
    return {
        "toggle": TOGGLE in have,
        "open_heading": OPEN_HEADING in have,
        "pinned_heading": PINNED_HEADING in have,
        "new_tab": NEW_TAB in have,
        "tab_search": any("search tabs" in n.lower() for n in have),
    }


def width_taken(b):
    """DIP the page gives up beside the list: the window's outer width minus
    the page's inner width."""
    outer, inner = b.run("return [window.outerWidth, window.innerWidth]")
    return outer - inner


def names_of(under):
    with Window(frame_window(CHROME, under=under)) as w:
        return w.names()


def press(under, name):
    with Window(frame_window(CHROME, under=under)) as w:
        return w.press(lambda text: text == name)


def wait_for(fn, timeout=15.0, step=0.4):
    deadline = time.monotonic() + timeout
    value = fn()
    while not value and time.monotonic() < deadline:
        time.sleep(step)
        value = fn()
    return value


def handles(b):
    return b._req("GET", f"/session/{b.sid}/window/handles")["value"]


def seed_profile(profile, vertical):
    """A profile with side tabs on, written before the browser starts."""
    default = Path(profile) / "Default"
    default.mkdir(parents=True, exist_ok=True)
    prefs = {"vertical_tabs": {"enabled": bool(vertical)}}
    (default / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")


def shoot(out, dark, folder, checks):
    try:
        hwnd = frame_window(CHROME, under=DRIVER_PID[0])
    except (LookupError, RuntimeError, OSError) as e:
        checks("our window to photograph", False, str(e))
        return
    time.sleep(0.8)
    theme = "dark" if dark else "light"
    path = Path(out) / f"sidetabs-{theme}.png"
    grab(hwnd, str(path))
    print("saved", path)
    both = page_checks.save_capture(path, "sidetabs", "C09", dark=dark, folder=folder, label="c09-sidetabs")
    if both:
        print("saved", both)


def run_main(port, out, captures, dark, checks, full):
    theme = "dark" if dark else "light"
    base = f"http://127.0.0.1:{port}"
    args = ["--window-size=1280,800"]
    if dark:
        args.append("--force-dark-mode")
    with tempfile.TemporaryDirectory(prefix="sidetabs-", dir=r"E:\tmp") as tmp:
        profile = Path(tmp) / "profile"
        seed_profile(profile, True)
        with Browser(headful=True, user_data_dir=str(profile), args=args) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            b.get(base + "/")
            for n in range(3):
                b.run("window.open(arguments[0])", [f"{base}/Page{n}"])
                time.sleep(0.4)
            # Measure in the tab a person sees: WebDriver stays on the first
            # tab, which window.open sent to the background, and a background
            # tab is not resized when the list narrows. Switching to a tab
            # makes it the active one.
            b._req("POST", f"/session/{b.sid}/window", {"handle": handles(b)[-1]})
            under = DRIVER_PID[0]
            # 2. The list and its parts.
            ready = wait_for(lambda: TOGGLE in names_of(under), 20)
            state = side_tabs_state(names_of(under))
            checks(f"{theme}: a control named {TOGGLE}", bool(ready), str(state))
            checks(f"{theme}: Open tabs heading", state["open_heading"], str(state))
            checks(f"{theme}: no Pinned heading while nothing is pinned", not state["pinned_heading"], str(state))
            checks(f"{theme}: a New tab button", state["new_tab"], str(state))
            # 4. The strip's other buttons are gone.
            checks(f"{theme}: no tab search button in the list", not state["tab_search"], str(state))
            # 3. Width.
            taken = width_taken(b)
            checks(f"{theme}: the page gives up about {LIST_WIDTH} DIP",
                   LIST_WIDTH <= taken <= LIST_WIDTH + 24, str(taken))
            shoot(out, dark, captures, checks)
            if not full:
                return
            # 5. The toggle narrows the list and widens it again.
            press(under, TOGGLE)
            narrow = wait_for(lambda: width_taken(b) < LIST_WIDTH - 40, 8)
            checks("the toggle narrows the list to icons", bool(narrow), str(width_taken(b)))
            press(under, TOGGLE)
            wide = wait_for(lambda: width_taken(b) >= LIST_WIDTH, 8)
            checks("the toggle widens it again", bool(wide), str(width_taken(b)))
            # 6. New tab opens a tab.
            before = len(handles(b))
            press(under, NEW_TAB)
            time.sleep(1.5)
            after = len(handles(b))
            checks("New tab opens a tab", after == before + 1, f"{before} -> {after}")


def run_variant(name, extra_args, vertical, checks, expect):
    with tempfile.TemporaryDirectory(prefix="sidetabs-", dir=r"E:\tmp") as tmp:
        profile = Path(tmp) / "profile"
        seed_profile(profile, vertical)
        with Browser(headful=True, user_data_dir=str(profile), args=["--window-size=1280,800", *extra_args]) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            time.sleep(8)
            names = names_of(DRIVER_PID[0])
            state = side_tabs_state(names)
            for key, want in expect.items():
                checks(f"{name}: {key} is {want}", state[key] == want, str(sorted(names))[:300])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\tmp\sidetabs-shots")
    page_checks.add_captures_option(ap)
    args = ap.parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    checks = Checks()
    server = serve()
    port = server.server_address[1]
    try:
        # 1. Top tabs stay the default.
        run_variant("default profile", [], False, checks, {"open_heading": False, "toggle": True})
        run_main(port, args.out, args.captures, False, checks, full=True)
        run_main(port, args.out, args.captures, True, checks, full=False)
        # 7. Private window shows a working window; an app window has no list.
        run_variant("private window", ["--incognito"], True, checks, {"toggle": True})
        run_variant("app window", [f"--app=http://127.0.0.1:{port}/"], True, checks,
                    {"open_heading": False, "new_tab": False})
    finally:
        server.shutdown()
    return checks.result("sidetabs")


if __name__ == "__main__":
    sys.exit(main())
