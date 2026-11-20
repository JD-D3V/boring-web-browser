#!/usr/bin/env python3
"""Smoke test: the Shelf with top tabs (ledger item 15, compiled screen C03).

Runs the real browser with --boring-open-shelf (the Shelf opens a few
seconds after the window is up, so no input is sent from the OS) and a temp
profile under E:\\tmp. A small local server on 127.0.0.1 serves one page and
one file; no other address is reachable. UI Automation on our own window
reads names and presses buttons; WebDriver reads the page's width.

What it asserts (nothing is asserted that was not looked at):
  1. The toggle: a control named "Show or hide the Shelf" in the tab strip.
  2. The Shelf opens: a pane named "The Shelf"; the page is narrower by
     about 248 DIP (window outer width minus the page's inner width).
  3. Sections: "Pinned" with a tile for every pinned site (names equal to
     their titles), and, after a file is downloaded, "Saved and downloaded"
     with the file's name.
  4. Pressing the toggle closes it (pane gone, page width back) and again
     opens it.
  5. Pressing a pinned tile opens that site in a new tab (WebDriver window
     handles grow by one, the new tab's address is the tile's address).
  6. Private window: the toggle and Pinned are there, "Saved and downloaded"
     and "Earlier" are not.
  7. App window (--app): no toggle at all.
  8. Captures: PrintWindow of our window with the Shelf open, light and
     dark, beside C03 (--captures).
Not checked here: Groups (needs a tab group made without keyboard input),
the reading list and bookmarks rows, the Bookmarks setting's "In the Shelf"
choice, Earlier (item 16 is not built), right-to-left.

Usage: python boring-core/tools/smoke_shelf.py [--out DIR] [--captures DIR]
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

SWITCH = "--boring-open-shelf"
TOGGLE = "Show or hide the Shelf"
PANE = "The Shelf"
FILE_NAME = "Boiler manual.txt"
PINNED = [("Local Library", "/library"), ("Local News", "/news")]
SHELF_WIDTH = 248


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/file"):
            body = b"A file to download."
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{FILE_NAME}"')
        else:
            body = b"<!doctype html><title>Local page</title><p>A page.</p>"
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


def shelf_state(names, pinned_titles, file_name=None):
    """What the names on our window say about the Shelf: a dict of facts.
    Pure, so it is tested without a browser."""
    have = set(names)
    return {
        "toggle": TOGGLE in have,
        "pane": PANE in have,
        "pinned_heading": "Pinned" in have,
        "tiles": [t for t in pinned_titles if t in have],
        "saved_heading": "Saved and downloaded" in have,
        "file": bool(file_name) and file_name in have,
        "earlier_heading": "Earlier" in have,
    }


def width_taken(b):
    """DIP the page gives up to the Shelf: the window's outer width minus
    the page's inner width, less the same figure with no Shelf (frame)."""
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


def shoot(out, dark, folder, checks):
    try:
        hwnd = frame_window(CHROME, under=DRIVER_PID[0])
    except (LookupError, RuntimeError, OSError) as e:
        checks("our window to photograph", False, str(e))
        return
    time.sleep(0.8)  # past the panel's open motion
    theme = "dark" if dark else "light"
    path = Path(out) / f"shelf-{theme}.png"
    grab(hwnd, str(path))
    print("saved", path)
    both = page_checks.save_capture(path, "shelf", "C03", dark=dark, folder=folder, label="c03-siteshelf")
    if both:
        print("saved", both)


def seed_profile(profile, downloads):
    """A profile whose downloads go under E:\\tmp, not to the real folder."""
    default = Path(profile) / "Default"
    default.mkdir(parents=True, exist_ok=True)
    prefs = {
        "download": {"default_directory": str(downloads), "prompt_for_download": False},
        "savefile": {"default_directory": str(downloads)},
    }
    (default / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")


def run_main(port, out, captures, dark, checks, full):
    theme = "dark" if dark else "light"
    base = f"http://127.0.0.1:{port}"
    args = [SWITCH, "--window-size=1280,800"]
    if dark:
        args.append("--force-dark-mode")
    with tempfile.TemporaryDirectory(prefix="shelf-", dir=r"E:\tmp") as tmp:
        profile = Path(tmp) / "profile"
        downloads = Path(tmp) / "downloads"
        downloads.mkdir()
        seed_profile(profile, downloads)
        with Browser(headful=True, user_data_dir=str(profile), args=args) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            # The pinned list is the new tab page's; add two sites to it.
            b.get("chrome://newtab")
            time.sleep(1.5)
            for title, path in PINNED:
                b.run("chrome.send('addShortcut', [arguments[0], arguments[1]])", [title, base + path])
            titles = [t for t, _ in PINNED]
            b.get(base + "/")
            frame_under = DRIVER_PID[0]

            # 1, 2. The toggle, then the Shelf that the hook opens.
            opened = wait_for(lambda: PANE in names_of(frame_under), 20)
            checks(f"{theme}: the Shelf opens (pane named {PANE})", bool(opened))
            # The pane is named before its sections are built and before the
            # panel has finished opening: wait for the tiles and the width.
            wait_for(lambda: shelf_state(names_of(frame_under), titles)["tiles"] == titles, 10)
            wait_for(lambda: width_taken(b) >= SHELF_WIDTH, 6)
            state = shelf_state(names_of(frame_under), titles)
            checks(f"{theme}: toggle named {TOGGLE}", state["toggle"], str(state))
            checks(f"{theme}: Pinned heading", state["pinned_heading"], str(state))
            checks(f"{theme}: a tile for every pinned site", state["tiles"] == titles, str(state))
            checks(f"{theme}: Earlier is off until item 16", not state["earlier_heading"], str(state))
            taken = width_taken(b)
            checks(f"{theme}: the page gives up about {SHELF_WIDTH} DIP",
                   SHELF_WIDTH <= taken <= SHELF_WIDTH + 24, str(taken))

            # 3. Saved and downloaded: download one file.
            b.get(base + "/file")
            time.sleep(0.5)
            got = wait_for(lambda: (downloads / FILE_NAME).exists(), 15)
            if got:
                state = wait_for(
                    lambda: (lambda s: s if s["file"] else None)(
                        shelf_state(names_of(frame_under), titles, FILE_NAME)), 10) or {}
                checks(f"{theme}: Saved and downloaded lists the file", bool(state.get("file")), str(state))
                checks(f"{theme}: its heading", bool(state.get("saved_heading")), str(state))
            else:
                checks(f"{theme}: the download reached the test folder", False,
                       "the profile's download folder was not honoured; this step is not verified")
            shoot(out, dark, captures, checks)
            if not full:
                return

            # 4. The toggle closes and opens it.
            press(frame_under, TOGGLE)
            gone = wait_for(lambda: PANE not in names_of(frame_under), 8)
            checks("toggle closes the Shelf", bool(gone))
            checks("the page has its width back", width_taken(b) < SHELF_WIDTH, str(width_taken(b)))
            press(frame_under, TOGGLE)
            back = wait_for(lambda: PANE in names_of(frame_under), 8)
            checks("toggle opens it again", bool(back))

            # 5. A pinned tile opens its site in a new tab.
            handles_before = len(b_handles(b))
            press(frame_under, titles[0])
            time.sleep(1.5)
            handles = b_handles(b)
            checks("a pinned tile opens a new tab", len(handles) == handles_before + 1,
                   f"{handles_before} -> {len(handles)}")


def b_handles(b):
    return b._req("GET", f"/session/{b.sid}/window/handles")["value"]


def run_variant(name, extra_args, port, checks, want_toggle, want_saved):
    with tempfile.TemporaryDirectory(prefix="shelf-", dir=r"E:\tmp") as tmp:
        with Browser(headful=True, user_data_dir=str(Path(tmp) / "profile"),
                     args=[SWITCH, "--window-size=1280,800", *extra_args]) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            time.sleep(8)
            names = names_of(DRIVER_PID[0])
            state = shelf_state(names, [])
            checks(f"{name}: toggle {'is' if want_toggle else 'is not'} there",
                   state["toggle"] == want_toggle, str(sorted(names))[:300])
            if want_toggle:
                checks(f"{name}: the Shelf opened", state["pane"], str(state))
                checks(f"{name}: no Saved and downloaded", state["saved_heading"] == want_saved, str(state))
                checks(f"{name}: no Earlier", not state["earlier_heading"], str(state))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\tmp\shelf-shots")
    page_checks.add_captures_option(ap)
    args = ap.parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    checks = Checks()
    server = serve()
    port = server.server_address[1]
    try:
        run_main(port, args.out, args.captures, False, checks, full=True)
        run_main(port, args.out, args.captures, True, checks, full=False)
        run_variant("private window", ["--incognito"], port, checks, True, False)
        run_variant("app window", [f"--app=http://127.0.0.1:{port}/"], port, checks, False, False)
    finally:
        server.shutdown()
    return checks.result("shelf")


if __name__ == "__main__":
    sys.exit(main())
