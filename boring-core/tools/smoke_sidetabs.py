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
  9. "Open tabs" heading: with no group it sits right above the first tab;
     with one group and two loose tabs (made by smoke_tabgroups.py's test
     extension) its top is below the group's last tab and its bottom above
     the first loose tab (UI Automation bounds).
 10. The page in a rounded sheet: with cui-sheet.patch in the series the
     page stops 8 DIP (6 to 10) short of the client area's right and bottom
     edges; without it, it runs to both. In fullscreen it runs to both.
     (The 10 DIP corners and the frame colour are seen in the captures.)
Not checked here: the pinned grid (four tiles to a row; a tab cannot be
pinned without input and no pin hook exists), the group heading row. The
Earlier section is checked by smoke_earlier.py (scenario_side).

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


def rects_of(under):
    """[(name, (left, top, right, bottom))] of every named control on our
    window, in screen pixels, read through UI Automation."""
    import ctypes
    from ctypes import wintypes
    from smoke_site_panel import _call  # noqa: PLC0415

    out = []
    with Window(frame_window(CHROME, under=under)) as w:
        for text, element in w.items:
            if not (element and text):
                continue
            r = wintypes.RECT()
            _call(element, 43, ctypes.addressof(r))  # get_CurrentBoundingRectangle
            out.append((text, (r.left, r.top, r.right, r.bottom)))
    return out


def first_rect(rects, wanted):
    """The first non-empty rectangle whose name `wanted` accepts, or None."""
    for text, r in rects:
        if wanted(text) and r[2] > r[0] and r[3] > r[1]:
            return r
    return None


SERIES = Path(__file__).resolve().parents[1] / "patches" / "series"


def sheet_expected():
    """The page sits in a rounded sheet with side tabs only while
    cui-sheet.patch is in the series (the builder can take it out)."""
    try:
        names = [ln.strip() for ln in SERIES.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return False
    return "cui-sheet.patch" in names


def sheet_state(page, client, scale):
    """Screen C09's sheet from two screen rectangles (left, top, right,
    bottom): the page and our window's client area. "sheet" when the page
    stops 6 to 10 DIP short of the client's right and bottom edges (drawn 8),
    "flush" when it runs to both edges, else "other". Pure."""
    if not (page and client and scale):
        return "other", None
    right = (client[2] - page[2]) / scale
    bottom = (client[3] - page[3]) / scale
    gaps = (round(right, 1), round(bottom, 1))
    if 6 <= right <= 10 and 6 <= bottom <= 10:
        return "sheet", gaps
    if abs(right) <= 1.5 and abs(bottom) <= 1.5:
        return "flush", gaps
    return "other", gaps


def page_and_client(under, title):
    """The page's rectangle (the largest control named `title`: the tab has
    the same name but is small) and the client rectangle of our window, in
    screen pixels, and the window's scale."""
    import ctypes
    from ctypes import wintypes

    hwnd = frame_window(CHROME, under=under)
    user32 = ctypes.windll.user32
    rc = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    client = (origin.x, origin.y, origin.x + rc.right, origin.y + rc.bottom)
    scale = (user32.GetDpiForWindow(hwnd) or 96) / 96
    named = [r for text, r in rects_of(under) if text == title and r[2] > r[0] and r[3] > r[1]]
    page = max(named, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), default=None)
    return page, client, scale


def heading_between(heading, above, below):
    """Screen C09: the "Open tabs" heading's top is at or below the bottom of
    the tab above it, and its bottom at or above the top of the tab below.
    Pure, so it is tested without a browser."""
    if not (heading and below):
        return False
    if above and heading[1] < above[3]:
        return False
    return heading[3] <= below[1]


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
            # WebDriver's automation bar names the product, never Chrome.
            bar_names = [n for n in names_of(under) if "automated test software" in n]
            checks(f"{theme}: the automation bar says Boring Browser",
                   bool(bar_names) and all(n.startswith("Boring Browser is being controlled")
                                           for n in bar_names), str(bar_names))
            # Screen C09: the New tab row shows its shortcut at the right.
            checks(f"{theme}: the New tab row shows Ctrl+T", "Ctrl+T" in names_of(under),
                   str(names_of(under))[:300])
            # With no group the Open tabs heading sits right above the first
            # loose tab (below Pinned when there is one).
            rects = rects_of(under)
            head = first_rect(rects, lambda t: t == OPEN_HEADING)
            first_tab = first_rect(rects, lambda t: t.startswith("Home"))
            checks(f"{theme}: with no group, Open tabs sits right above the first tab",
                   heading_between(head, None, first_tab) and first_tab[1] - head[3] <= 24,
                   f"heading {head}, first tab {first_tab}")
            # 4. The strip's other buttons are gone.
            checks(f"{theme}: no tab search button in the list", not state["tab_search"], str(state))
            # 3. Width.
            taken = width_taken(b)
            checks(f"{theme}: the page gives up about {LIST_WIDTH} DIP",
                   LIST_WIDTH <= taken <= LIST_WIDTH + 24, str(taken))
            # The page in a rounded sheet (cui-sheet.patch): 8 DIP of frame
            # to its right and below; without the patch it runs to the edges.
            want = "sheet" if sheet_expected() else "flush"
            page, client, scale = page_and_client(under, "Page2")
            got, gaps = sheet_state(page, client, scale)
            checks(f"{theme}: the page is {'in a sheet' if want == 'sheet' else 'flush'}"
                   " (series has cui-sheet.patch: " + str(want == "sheet") + ")",
                   got == want, f"right, bottom gap DIP {gaps}; page {page}; client {client}")
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
            # In fullscreen the sheet's margin goes away.
            rect = b._req("GET", f"/session/{b.sid}/window/rect")["value"]
            b._req("POST", f"/session/{b.sid}/window/fullscreen", {})
            time.sleep(1.5)
            page, client, scale = page_and_client(under, "Page2")
            got, gaps = sheet_state(page, client, scale)
            checks("fullscreen: the page runs to the edges", got == "flush", f"gaps {gaps}")
            b._req("POST", f"/session/{b.sid}/window/rect",
                   {k: rect[k] for k in ("x", "y", "width", "height")})
            time.sleep(1.5)
            # 6. New tab opens a tab.
            before = len(handles(b))
            press(under, NEW_TAB)
            time.sleep(1.5)
            after = len(handles(b))
            checks("New tab opens a tab", after == before + 1, f"{before} -> {after}")


GROUP_FIRST_JS = r"""
// cui-look-4: screen C09's order, the group first, then two loose tabs.
window.sceneGroupFirst = async () => {
  await clear();
  await group(await open(['Train times', 'Hotel booking', 'City map']), 'Trip', 'cyan');
  await open(['Local news', 'Weather']);
  return finish();
};
"""


def run_groups(checks):
    """One group and two loose tabs: the "Open tabs" heading's top is below
    the group's last tab and above the first loose tab. The group is made by
    smoke_tabgroups.py's test extension (chrome.tabs.group), driven through
    WebDriver; nothing is sent to the OS."""
    import smoke_tabgroups as tg  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="sidetabs-", dir=r"E:\tmp") as tmp:
        profile = Path(tmp) / "profile"
        seed_profile(profile, True)
        ext = Path(tmp) / "ext"
        ext.mkdir()
        tg.write_extension(ext)
        run_js = ext / "run.js"
        run_js.write_text(run_js.read_text(encoding="utf-8") + GROUP_FIRST_JS, encoding="utf-8")
        args = ["--window-size=1280,800", "--load-extension=" + str(ext)]
        with Browser(headful=True, user_data_dir=str(profile), args=args,
                     keep_switches=["enable-automation"]) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            tg.run_page(b)
            groups = tg.call(b, "sceneGroupFirst")
            checks("groups: the Trip group was made",
                   isinstance(groups, list) and len(groups) == 1 and groups[0].get("tabs") == 3, str(groups))
            time.sleep(1.5)
            rects = rects_of(DRIVER_PID[0])
            head = first_rect(rects, lambda t: t == OPEN_HEADING)
            last_group_tab = first_rect(rects, lambda t: t.startswith("City map"))
            first_loose = first_rect(rects, lambda t: t.startswith("Local news"))
            checks("groups: Open tabs sits between the group and the loose tabs",
                   heading_between(head, last_group_tab, first_loose),
                   f"heading {head}, City map {last_group_tab}, Local news {first_loose}")


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
        run_groups(checks)
        # 7. Private window shows a working window; an app window has no list.
        run_variant("private window", ["--incognito"], True, checks, {"toggle": True})
        run_variant("app window", [f"--app=http://127.0.0.1:{port}/"], True, checks,
                    {"open_heading": False, "new_tab": False})
    finally:
        server.shutdown()
    return checks.result("sidetabs")


if __name__ == "__main__":
    sys.exit(main())
