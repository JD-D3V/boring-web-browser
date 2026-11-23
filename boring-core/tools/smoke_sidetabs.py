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
     edges, with four rounded corners; without it, it runs to both. The
     page's edges come from its own pixels (painted magenta after the
     photograph, read with PrintWindow). With the sheet only: in fullscreen
     it runs to both, maximised it keeps the sheet (both put the window on
     a monitor for a moment).
 11. Ledger 60: side tabs replace the top row. Top tabs at start, switched
     live to side from Settings (chrome.settingsPrivate, as the Tabs row
     writes it) with several tabs open, a second window, back to top, side
     again, then a restart on the same profile: each window shows either
     the side list with no tab in the top 40 DIP band, or the top row with
     no list, never both; no tab is lost; every tab but the open one is
     named once in UI Automation.
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


def shortcut_of(under, name):
    """The UI Automation AcceleratorKey of the first control named `name`.
    The shortcut a button draws is inside the button, so it is not a name of
    its own; the button carries it as its key shortcut."""
    import ctypes
    from smoke_site_panel import _call, oleaut32
    found = None
    with Window(frame_window(CHROME, under=under)) as w:
        for text, element in w.items:
            if text != name or not element:
                continue
            key = ctypes.c_void_p()
            try:
                _call(element, 24, ctypes.addressof(key))  # get_CurrentAcceleratorKey
                found = ctypes.wstring_at(key.value) if key else ""
            except OSError:
                found = ""
            finally:
                if key:
                    oleaut32.SysFreeString(key)
            if found:
                return found
    return found


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


MAGENTA = (255, 0, 255)
PAINT_PAGE_JS = (
    "document.documentElement.style.background = '#ff00ff';"
    "document.body.style.background = '#ff00ff';"
    "document.body.style.color = '#ff00ff';"
    "return [innerWidth, innerHeight];"
)


def _print_window(hwnd):
    """(width, height, BGRA bytes, window rect) of our window, drawn by
    PrintWindow (our window only, never a screen grab)."""
    import ctypes
    from capture_native import BITMAPINFOHEADER, RECT, gdi32, user32  # noqa: PLC0415

    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    screen = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)
    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth, info.biHeight, info.biPlanes, info.biBitCount = w, -h, 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, screen)
    return w, h, bytes(buf), (r.left, r.top, r.right, r.bottom)


def colour_box(w, h, bgra, colour):
    """(left, top, right, bottom) of the pixels exactly `colour` (RGB), right
    and bottom exclusive, or None. Pure."""
    want = bytes((colour[2], colour[1], colour[0]))
    xs, ys = [], []
    for y in range(0, h):
        row = bgra[y * w * 4:(y + 1) * w * 4]
        first = last = None
        for x in range(w):
            if row[x * 4:x * 4 + 3] == want:
                if first is None:
                    first = x
                last = x
        if first is not None:
            xs += [first, last]
            ys.append(y)
    if not ys:
        return None
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def rounded_corners(w, bgra, box, colour, inset):
    """How many of the box's four corner pixels are NOT `colour` while the
    pixels `inset` inside along both edges are: 4 means four rounded
    corners. Pure."""
    want = bytes((colour[2], colour[1], colour[0]))

    def at(x, y):
        return bgra[(y * w + x) * 4:(y * w + x) * 4 + 3] == want

    left, top, right, bottom = box[0], box[1], box[2] - 1, box[3] - 1
    count = 0
    for cx, cy, dx, dy in ((left, top, 1, 1), (right, top, -1, 1), (left, bottom, 1, -1), (right, bottom, -1, -1)):
        if not at(cx, cy) and at(cx + dx * inset, cy) and at(cx, cy + dy * inset):
            count += 1
    return count


def page_from_pixels(under, b):
    """The page's rectangle on screen, found by painting it magenta and
    reading our window's own pixels, plus the window's client rectangle,
    scale and the number of rounded corners."""
    import ctypes
    from ctypes import wintypes

    b.run(PAINT_PAGE_JS)
    time.sleep(0.8)
    hwnd = frame_window(CHROME, under=under)
    user32 = ctypes.windll.user32
    w, h, bgra, wr = _print_window(hwnd)
    rc = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    client = (origin.x, origin.y, origin.x + rc.right, origin.y + rc.bottom)
    scale = (user32.GetDpiForWindow(hwnd) or 96) / 96
    box = colour_box(w, h, bgra, MAGENTA)
    if not box:
        return None, client, scale, 0
    page = (wr[0] + box[0], wr[1] + box[1], wr[0] + box[2], wr[1] + box[3])
    return page, client, scale, rounded_corners(w, bgra, box, MAGENTA, max(4, round(6 * scale)))


def cdp(b, cmd, params):
    return b._req("POST", f"/session/{b.sid}/goog/cdp/execute", {"cmd": cmd, "params": params})


def top_row_tabs(rects, titles, client, scale):
    """Tabs named in `titles` that sit in a horizontal tab strip: in the top
    band of the client area (their top within 40 DIP of it) and wider than
    tall. Pure."""
    out = []
    for text, r in rects:
        if not any(text.startswith(t) for t in titles):
            continue
        if r[2] <= r[0] or r[3] <= r[1]:
            continue
        if r[1] - client[1] < 40 * scale and (r[2] - r[0]) > 2 * (r[3] - r[1]):
            out.append((text, r))
    return out


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
            key = shortcut_of(under, NEW_TAB)
            checks(f"{theme}: the New tab row shows Ctrl+T", key == "Ctrl+T", repr(key))
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
            # The page's own pixels (painted magenta for the measure, after
            # the photograph) give its edges; UI Automation has no page box.
            shoot(out, dark, captures, checks)
            want = "sheet" if sheet_expected() else "flush"
            page, client, scale, corners = page_from_pixels(under, b)
            got, gaps = sheet_state(page, client, scale)
            checks(f"{theme}: the page is {'in a sheet' if want == 'sheet' else 'flush'}"
                   " (series has cui-sheet.patch: " + str(want == "sheet") + ")",
                   got == want, f"right, bottom gap DIP {gaps}; page {page}; client {client}")
            if want == "sheet":
                checks(f"{theme}: the sheet has four rounded corners", corners == 4, str(corners))
            if not full:
                return
            # 5. The toggle narrows the list and widens it again.
            press(under, TOGGLE)
            narrow = wait_for(lambda: width_taken(b) < LIST_WIDTH - 40, 8)
            checks("the toggle narrows the list to icons", bool(narrow), str(width_taken(b)))
            press(under, TOGGLE)
            wide = wait_for(lambda: width_taken(b) >= LIST_WIDTH, 8)
            checks("the toggle widens it again", bool(wide), str(width_taken(b)))
            if not sheet_expected():
                # Without the sheet there is no margin to lose in fullscreen or
                # keep when maximised, and nothing to put on a monitor.
                run_new_tab(b, under, checks)
                return
            # In fullscreen the sheet's margin goes away. WebDriver cannot
            # make an off-screen window fullscreen, so the page asks for it
            # with a user gesture (DevTools); the window then covers a
            # monitor for about two seconds.
            cdp(b, "Runtime.evaluate", {"expression": "document.documentElement.requestFullscreen()",
                                        "userGesture": True, "awaitPromise": True})
            time.sleep(1.5)
            full = b.run("return [innerWidth, innerHeight, screen.width, screen.height, "
                         "!!document.fullscreenElement]")
            page, client, scale, _c = page_from_pixels(under, b)
            got, gaps = sheet_state(page, client, scale)
            checks("fullscreen: the page fills the screen", bool(full[4]) and full[0] == full[2]
                   and full[1] == full[3], str(full))
            checks("fullscreen: the page runs to the edges", got == "flush", f"gaps {gaps}")
            cdp(b, "Runtime.evaluate", {"expression": "document.exitFullscreen()",
                                        "userGesture": True, "awaitPromise": True})
            time.sleep(1.5)
            # Maximised: the sheet keeps its 8 DIP and corners.
            rect = b._req("GET", f"/session/{b.sid}/window/rect")["value"]
            try:
                b._req("POST", f"/session/{b.sid}/window/maximize", {})
                time.sleep(1.5)
                page, client, scale, corners = page_from_pixels(under, b)
                got, gaps = sheet_state(page, client, scale)
                checks("maximised: the page is " + ("in a sheet" if sheet_expected() else "flush"),
                       got == ("sheet" if sheet_expected() else "flush"), f"gaps {gaps}")
                if sheet_expected():
                    checks("maximised: four rounded corners", corners == 4, str(corners))
                grab(frame_window(CHROME, under=under), str(Path(out) / "sidetabs-maximised.png"))
            except RuntimeError as e:
                checks("maximised: WebDriver could maximise the window", False, str(e)[:200])
            b._req("POST", f"/session/{b.sid}/window/rect",
                   {k: rect[k] for k in ("x", "y", "width", "height")})
            time.sleep(1.5)
            run_new_tab(b, under, checks)


def run_new_tab(b, under, checks):
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


LIVE_TITLES = ["Live1", "Live2", "Live3", "Live4"]


def set_side_tabs(b, value):
    """Write vertical_tabs.enabled the way Settings, Appearance, Tabs does
    (chrome.settingsPrivate from the Settings page, in the running window)."""
    b.get("chrome://settings/appearance")
    time.sleep(1.5)
    return b.run_async(
        "const done = arguments[arguments.length - 1];"
        "chrome.settingsPrivate.setPref(arguments[0], arguments[1], '', ok => {"
        "  chrome.settingsPrivate.getPref(arguments[0], p => done([ok, p.value]));"
        "});",
        ["vertical_tabs.enabled", value],
    )


def frames_of(pid):
    """Our browser windows (those with an address bar): [(hwnd, names, rects, client, scale)]."""
    import ctypes
    from ctypes import wintypes

    from smoke_site_panel import _call, browser_windows  # noqa: PLC0415

    user32 = ctypes.windll.user32
    out = []
    for hwnd in browser_windows(pid):
        try:
            with Window(hwnd) as w:
                names = w.names()
                if "Address and search bar" not in names:
                    continue
                rects = []
                for text, element in w.items:
                    if not (element and text):
                        continue
                    r = wintypes.RECT()
                    _call(element, 43, ctypes.addressof(r))
                    rects.append((text, (r.left, r.top, r.right, r.bottom)))
        except (LookupError, OSError):
            continue
        rc = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rc))
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(origin))
        client = (origin.x, origin.y, origin.x + rc.right, origin.y + rc.bottom)
        scale = (user32.GetDpiForWindow(hwnd) or 96) / 96
        out.append((hwnd, names, rects, client, scale))
    return out


def tab_layout(frame, titles):
    """'side' when the window shows the side list and no tab of `titles` in a
    top row, 'top' when every such tab is in the top row and there is no
    list, else 'mixed'; with how often each title is named."""
    _hwnd, names, rects, client, scale = frame
    counts = {t: sum(1 for n in names if n.startswith(t)) for t in titles}
    top = top_row_tabs(rects, titles, client, scale)
    has_list = OPEN_HEADING in names
    present = [t for t in titles if counts[t]]
    if has_list and not top:
        return "side", counts
    in_top = {t for t in titles for text, _r in top if text.startswith(t)}
    if not has_list and set(present) <= in_top:
        return "top", counts
    return "mixed", counts


def check_layout(checks, label, pid, titles, want):
    ok = wait_for(lambda: [f for f in frames_of(pid) if tab_layout(f, titles)[0] == want], 15)
    frames = frames_of(pid)
    for i, f in enumerate(frames):
        got, counts = tab_layout(f, titles)
        checks(f"{label}: window {i + 1} shows {want} tabs only", got == want,
               f"got {got}; {counts}; top row {top_row_tabs(f[2], titles, f[3], f[4])[:3]}")
        # The open tab (the last one opened) also has its page in the tree,
        # which repeats its title; every other tab is named once.
        once = {t: c for t, c in counts.items() if t in titles[:-1]}
        checks(f"{label}: window {i + 1} names each tab once",
               all(c <= 1 for c in once.values()), str(once))
    return bool(ok)


def run_live_switch(port, out, checks):
    """Ledger 60: side tabs replace the top row, they never double up.
    Start with top tabs, switch to side live from Settings (several tabs
    open), open a second window, switch back to top, switch to side again,
    then restart the browser on the same profile."""
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="sidetabs-", dir=r"E:\tmp") as tmp:
        profile = Path(tmp) / "profile"
        seed_profile(profile, False)
        with Browser(headful=True, user_data_dir=str(profile), args=["--window-size=1280,800"]) as b:
            DRIVER_PID[0] = b.proc.pid
            pid = b.proc.pid
            b.get(base + "/Home")
            for t in LIVE_TITLES:
                b.run("window.open(arguments[0])", [f"{base}/{t}"])
                time.sleep(0.4)
            tabs_before = len(handles(b))
            check_layout(checks, "live, at start", pid, LIVE_TITLES, "top")
            ok = set_side_tabs(b, True)
            checks("live: Settings writes side tabs on", ok == [True, True], str(ok))
            check_layout(checks, "live, switched to side", pid, LIVE_TITLES, "side")
            checks("live, switched to side: no tab lost", len(handles(b)) == tabs_before,
                   f"{tabs_before} -> {len(handles(b))}")
            time.sleep(1.0)
            try:
                path = Path(out) / "sidetabs-live-light.png"
                grab(frame_window(CHROME, under=pid), str(path))
                print("saved", path)
            except (LookupError, RuntimeError, OSError) as e:
                checks("live: our window to photograph", False, str(e))
            # A second window, opened with side tabs on.
            b._req("POST", f"/session/{b.sid}/window/new", {"type": "window"})
            time.sleep(2.0)
            two = wait_for(lambda: len(frames_of(pid)) >= 2, 10)
            checks("live: a second window opened", bool(two), str(len(frames_of(pid))))
            check_layout(checks, "live, two windows, side", pid, LIVE_TITLES, "side")
            # Back to the top: the top row returns, the list goes.
            ok = set_side_tabs(b, False)
            checks("live: Settings writes side tabs off", ok == [True, False], str(ok))
            check_layout(checks, "live, switched back to top", pid, LIVE_TITLES, "top")
            checks("live, back to top: no tab lost", len(handles(b)) == tabs_before + 1,
                   f"{tabs_before} + 1 -> {len(handles(b))}")
            ok = set_side_tabs(b, True)
            checks("live: side tabs on again before the restart", ok == [True, True], str(ok))
        # Restart on the same profile: side tabs stay on, no top row.
        with Browser(headful=True, user_data_dir=str(profile), args=["--window-size=1280,800"]) as b:
            DRIVER_PID[0] = b.proc.pid
            b.get(base + "/Restart1")
            for t in ("Restart2", "Restart3"):
                b.run("window.open(arguments[0])", [f"{base}/{t}"])
                time.sleep(0.5)
            check_layout(checks, "after a restart", b.proc.pid, ["Restart2", "Restart3"], "side")


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
        # 11. Ledger 60: side tabs replace the top row, at start and live.
        run_live_switch(port, args.out, checks)
        # 7. Private window shows a working window; an app window has no list.
        run_variant("private window", ["--incognito"], True, checks, {"toggle": True})
        run_variant("app window", [f"--app=http://127.0.0.1:{port}/"], True, checks,
                    {"open_heading": False, "new_tab": False})
    finally:
        server.shutdown()
    return checks.result("sidetabs")


if __name__ == "__main__":
    sys.exit(main())
