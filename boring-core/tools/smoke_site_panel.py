#!/usr/bin/env python3
"""Check the shield's panel about a site and the rules on its settings page.

Everything is local. One HTTP server on 127.0.0.1 plays the test site
(http://127.0.0.1:PORT), a control site (http://localhost:PORT) and the
ad and tracker servers, whose real names are pointed at it with
--host-resolver-rules, so the filter lists see the real addresses and
nothing leaves the machine.

The shield's panel is a native bubble, so it is opened and pressed
through UI Automation on our own windows, which reads names and calls
the controls' own default actions and sends no mouse or keys to the
desktop. The panel stays open with --boring-shield-panel-test, since a
test window never has the keyboard. The site settings page is
Chromium's own page at chrome://settings/content/siteDetails, driven
with WebDriver.

Checked:

  - a page that loads an ad and a tracker shows, in the panel, how many
    were blocked and of which kinds, with the same total both ways
  - "Turn off blocking for this site" lets the ad and tracker through,
    and it stays that way when the page is loaded again
  - "Settings for this site" opens the site's settings page
  - that page has the three rows (blocking, clear on close, never
    sleep), no reader view row, and each one takes effect: blocking
    for the next load, never sleep as the panel's own switch, clear on
    close as the cookies of that site and no other gone after a restart
  - all of it is still there after the browser is restarted

Usage: python smoke_site_panel.py [--shots DIR] [--dark]
  --shots photographs the panel and the settings page into DIR, with
  --dark in the dark theme.
"""

import argparse
import ctypes
import json
import os
import re
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote

from capture_native import ENUMPROC, chrome_pids, frame_window, grab, parents_of
from drive import CHROME, Browser, free_port
from smoke_local import start_on_new_tab_page
from smoke_siteoff import (
    AD_HOST,
    GUID,
    LOAD_SCRIPT,
    TRACKER_HOST,
    TREE_SCOPE_DESCENDANTS,
    CLSID_CUIAutomation,
    IID_IUIAutomation,
    _call,
    _release,
    ole32,
    oleaut32,
    preferences_path,
    shield_name,
)

user32 = ctypes.WinDLL("user32", use_last_error=True)

SITE = "127.0.0.1"
CONTROL = "localhost"
TEST_SWITCH = "--boring-shield-panel-test"

# A page that asks for an ad script, a tracker script and an ad image,
# and writes down which of them arrived.
PAGE = f"""<!doctype html>
<meta charset="utf-8">
<title>site panel test</title>
<h1>site panel test</h1>
<script>window.arrived = {{}};</script>
<script src="http://{AD_HOST}:%(port)d/pagead/js/adsbygoogle.js"
  onload="arrived.ad = 1" onerror="arrived.ad = 0"></script>
<script src="http://{TRACKER_HOST}:%(port)d/beacon.js"
  onload="arrived.tracker = 1" onerror="arrived.tracker = 0"></script>
<img src="http://{AD_HOST}:%(port)d/pagead/banner.gif"
  onload="arrived.image = 1" onerror="arrived.image = 0">
"""

# 1x1 transparent GIF.
GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000"
    "010001000002024401003b"
)


class Handler(BaseHTTPRequestHandler):
    port = 0

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.endswith(".js"):
            body, kind = b"/* test */", "text/javascript"
        elif path.endswith(".gif"):
            body, kind = GIF, "image/gif"
        else:
            body = (PAGE % {"port": self.port}).encode()
            kind = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


# --- UI Automation, on top of the primitives in smoke_siteoff ------------

IID_INVOKE = "{fb377fbe-8ea6-46d5-9c73-6499642d3059}"
IID_EXPAND = "{619be086-1f4e-4ee4-bafa-210128738730}"
IID_TOGGLE = "{94cf8058-9b8d-4ab9-8bfd-4cd0a33c8c70}"
# (pattern id, interface, method number of the action, what it is)
ACTIONS = [
    (10000, IID_INVOKE, 3, "invoke"),
    (10005, IID_EXPAND, 3, "expand"),
    (10015, IID_TOGGLE, 3, "toggle"),
]
COLLAPSE = [(10005, IID_EXPAND, 4, "collapse")]


def accessible_name(element):
    """A control's accessible name, empty when it has none."""
    name = ctypes.c_void_p()
    try:
        _call(element, 23, ctypes.addressof(name))
        return ctypes.wstring_at(name.value) if name else ""
    except OSError:
        return ""
    finally:
        if name:
            oleaut32.SysFreeString(name)


class Window:
    """The controls of one window of ours, by accessible name.

    Holds the COM objects until close(), so use it as a context manager.
    """

    def __init__(self, hwnd):
        ole32.CoInitializeEx(None, 0x2)
        self.automation = ctypes.c_void_p()
        ole32.CoCreateInstance(
            ctypes.byref(GUID(CLSID_CUIAutomation)),
            None,
            0x1,
            ctypes.byref(GUID(IID_IUIAutomation)),
            ctypes.byref(self.automation),
        )
        if not self.automation:
            raise RuntimeError("UI Automation is not available")
        self.root = ctypes.c_void_p()
        self.found = ctypes.c_void_p()
        self.items = []
        condition = ctypes.c_void_p()
        try:
            _call(self.automation, 6, hwnd, ctypes.addressof(self.root))
            _call(self.automation, 21, ctypes.addressof(condition))
            _call(
                self.root,
                6,
                TREE_SCOPE_DESCENDANTS,
                condition.value,
                ctypes.addressof(self.found),
            )
            count = ctypes.c_int()
            _call(self.found, 3, ctypes.addressof(count))
            # The window's own name too: a bubble's title is the window's.
            self.items.append((accessible_name(self.root), None))
            for i in range(count.value):
                element = ctypes.c_void_p()
                _call(self.found, 4, i, ctypes.addressof(element))
                self.items.append((accessible_name(element), element))
        except Exception:
            self.close()
            raise
        finally:
            _release(condition)

    def close(self):
        for _text, element in self.items:
            if element:
                _release(element)
        self.items = []
        for obj in (self.found, self.root, self.automation):
            _release(obj)
        self.found = self.root = self.automation = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def names(self):
        return [text for text, _ in self.items if text]

    def elements(self, wanted):
        """Every control whose name `wanted` accepts. A switch and its
        label share a name, so the first is not always the one wanted."""
        found = [e for text, e in self.items if e and text and wanted(text)]
        if not found:
            raise LookupError("no control with that name")
        return found

    def pattern(self, element, pattern_id, iid):
        out = ctypes.c_void_p()
        guid = GUID(iid)
        try:
            _call(
                element, 14, pattern_id, ctypes.addressof(guid), ctypes.addressof(out)
            )
        except OSError:
            return None
        return out if out else None

    def press(self, wanted, actions=ACTIONS):
        """Do a control's default action. Returns which pattern did it.

        A control offers the pattern that fits it (a button that opens a
        dialog offers Expand, not Invoke), and one that refuses its
        action says so with an error, so the next is tried.
        """
        refused = []
        for element in self.elements(wanted):
            for pattern_id, iid, method, label in actions:
                pattern = self.pattern(element, pattern_id, iid)
                if pattern is None:
                    continue
                try:
                    _call(pattern, method)
                    return label
                except OSError as e:
                    refused.append(f"{label}: {e!r}")
                finally:
                    _release(pattern)
        raise RuntimeError(
            "the control has no action to call"
            + (f" ({'; '.join(refused)})" if refused else "")
        )

    def toggle_state(self, wanted):
        """1 when a switch is on, 0 when off."""
        for element in self.elements(wanted):
            pattern = self.pattern(element, 10015, IID_TOGGLE)
            if pattern is None:
                continue
            state = ctypes.c_int()
            try:
                _call(pattern, 4, ctypes.addressof(state))
            finally:
                _release(pattern)
            return state.value
        raise RuntimeError("the control is not a switch")


def browser_windows(driver_pid):
    """Every visible top level window of the browser a driver started."""
    pids = chrome_pids(CHROME)
    ours = {pid for pid, parent in parents_of(pids).items() if parent == driver_pid}
    found = []

    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value in ours:
                found.append(hwnd)
        return True

    user32.EnumWindows(ENUMPROC(cb), 0)
    return found


def foreground_is_ours(driver_pid):
    """Whether the window the person is working in belongs to the test
    browser, and its title. It must not: nothing here may take the
    keyboard."""
    ours = set()
    if driver_pid:
        pids = chrome_pids(CHROME)
        ours = {pid for pid, parent in parents_of(pids).items() if parent == driver_pid}
    hwnd = user32.GetForegroundWindow()
    owner = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
    title = ctypes.create_unicode_buffer(60)
    user32.GetWindowTextW(hwnd, title, 60)
    return owner.value in ours, title.value


def press_shield(frame, close=False):
    """Open the panel through the shield's Expand, or put it away with
    Collapse. UI Automation runs the shield's own code, so nothing is
    sent to the desktop and no window is raised."""
    with Window(frame) as w:
        return w.press(
            lambda n: n.startswith("Protection,"), COLLAPSE if close else ACTIONS
        )


def find_panel(b, frame, timeout=10.0):
    """The panel's window and its control names, once it is on screen."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd in browser_windows(b.proc.pid):
            if hwnd == frame:
                continue
            try:
                with Window(hwnd) as w:
                    names = w.names()
            except OSError:
                continue
            if "Open Protection" in names:
                return hwnd, names
        time.sleep(0.3)
    return None, []


def poll(fn, timeout=10.0, step=0.25):
    """The first truthy answer of fn, or its last answer at the timeout."""
    deadline = time.time() + timeout
    value = fn()
    while not value and time.time() < deadline:
        time.sleep(step)
        value = fn()
    return value


# --- the settings page ---------------------------------------------------

DEEP = """
function deep(root, selector) {
  const hit = root.querySelector(selector);
  if (hit) return hit;
  for (const el of root.querySelectorAll('*')) {
    if (el.shadowRoot) {
      const found = deep(el.shadowRoot, selector);
      if (found) return found;
    }
  }
  return null;
}
function deepAll(root, selector, out) {
  out.push(...root.querySelectorAll(selector));
  for (const el of root.querySelectorAll('*')) {
    if (el.shadowRoot) deepAll(el.shadowRoot, selector, out);
  }
  return out;
}
"""

ROW_IDS = ["boringBlocking", "boringClearOnClose", "boringNeverSleep"]
ROW_LABELS = {
    "boringBlocking": "Block ads and trackers",
    "boringClearOnClose": "Clear data when the browser closes",
    "boringNeverSleep": "Never sleep this site",
}


def settings_rows(b):
    """Each row's label and state, plus how many of our rows there are."""
    return b.run(
        DEEP
        + """
      const out = {};
      for (const id of arguments[0]) {
        const e = deep(document, '#' + id);
        out[id] = e ? {label: e.label, checked: !!e.checked} : null;
      }
      out.all = deepAll(document, 'settings-toggle-button[id^=boring]', [])
          .map(e => e.label);
      out.headings = deepAll(document, 'h2', []).map(e => e.textContent.trim());
      return out;
    """,
        [ROW_IDS],
    )


def state_of(rows, row_id):
    """A row's switch, or None when the row is not there."""
    return (rows.get(row_id) or {}).get("checked")


def click_row(b, row_id):
    return b.run(
        DEEP + "const e = deep(document, '#' + arguments[0]); e.click(); return !!e;",
        [row_id],
    )


def open_settings(b, origin):
    b.get("chrome://settings/content/siteDetails?site=" + quote(origin, safe=""))
    return poll(
        lambda: (settings_rows(b) or {}).get("boringClearOnClose") is not None,
        timeout=20,
    )


# --- the test ------------------------------------------------------------


def window_handles(b):
    return b._req("GET", f"/session/{b.sid}/window/handles")["value"]


def current_handle(b):
    return b._req("GET", f"/session/{b.sid}/window")["value"]


def switch_to(b, handle):
    b._req("POST", f"/session/{b.sid}/window", {"handle": handle})


def arrived(b):
    """What the test page says has loaded, or None before it can say."""
    return b.run("return window.arrived || null")


def page_loaded(b):
    """The page's three requests, once they have all answered."""
    return poll(
        lambda: (lambda a: a if a and len(a) == 3 else None)(arrived(b)), timeout=15
    )


def summary_numbers(names):
    """(total, kinds as a dict) from the panel's two summary lines."""
    total, kinds = None, {}
    for name in names:
        m = re.fullmatch(r"(\d+) blocked on this page", name)
        if m:
            total = int(m.group(1))
        m = re.fullmatch(r"\d+ (ads?|trackers?|cookie banners?|scripts?)(, .*)?", name)
        if m:
            for part in name.split(", "):
                n, word = part.split(" ", 1)
                kinds[word.rstrip("s")] = int(n)
    return total, kinds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=None)
    ap.add_argument("--dark", action="store_true")
    opts = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    if opts.shots:
        os.makedirs(opts.shots, exist_ok=True)
    theme = "dark" if opts.dark else "light"

    failures = []

    def check(name, ok, detail=""):
        print(
            f"{'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail else "")
        )
        if not ok:
            failures.append(name)

    port = free_port()
    Handler.port = port
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    origin = f"http://{SITE}:{port}"
    page = f"{origin}/page.html"
    control_page = f"http://{CONTROL}:{port}/page.html"
    ad_script = f"http://{AD_HOST}:{port}/pagead/js/adsbygoogle.js"
    args = [
        TEST_SWITCH,
        "--disable-background-mode",
        f"--host-resolver-rules=MAP {AD_HOST} 127.0.0.1, MAP {TRACKER_HOST} 127.0.0.1",
        "--window-size=1360,900",
    ]
    if opts.dark:
        args.append("--force-dark-mode")

    def shot(hwnd, name):
        if opts.shots and hwnd:
            path = os.path.join(opts.shots, f"{name}-{theme}.png")
            w, h = grab(hwnd, path)
            print(f"saved {path} {w}x{h}")

    def dump(b, frame, why):
        """Say what the windows held, so a failure can be understood."""
        print(f"  ({why})")
        for hwnd in browser_windows(b.proc.pid):
            try:
                with Window(hwnd) as w:
                    kind = "frame" if hwnd == frame else "popup"
                    print(f"  {kind} {hwnd}: {w.names()[:40]}")
            except OSError as e:
                print(f"  window {hwnd}: unreadable ({e})")

    def open_panel(b, frame):
        """Press the shield; the panel's window and names, or (None, [])."""
        focus_note(b, "before the press")
        try:
            how = press_shield(frame)
        except (LookupError, OSError, RuntimeError) as e:
            dump(b, frame, f"could not press the shield: {e!r}")
            return None, []
        hwnd, names = find_panel(b, frame)
        if not hwnd:
            dump(b, frame, f"pressed the shield by {how}, no panel appeared")
        else:
            print(f"  panel (shield pressed by {how}): {names}")
            focus_note(b, "panel open")
        return hwnd, names

    def focus_note(b, when):
        """Say who holds the keyboard. Not a check: the person may move
        to another window while this runs."""
        ours, title = foreground_is_ours(b.proc.pid)
        print(f"  focus {when}: test browser has it: {ours} ({title!r})")

    def close_panel(frame):
        press_shield(frame, close=True)
        time.sleep(0.8)

    try:
        with tempfile.TemporaryDirectory(prefix="sitepanel-") as profile:
            # --- run one: the panel, then the settings page ------------------
            print(f"  focus before the browser starts: {foreground_is_ours(0)[1]!r}")
            with Browser(user_data_dir=profile, args=args, headful=True) as b:
                frame = frame_window(CHROME, under=b.proc.pid)
                focus_note(b, "browser started")
                page_tab = current_handle(b)

                b.get(page)
                # The lists load in the background at startup.
                ready = False
                for _ in range(20):
                    result = b.run_async(LOAD_SCRIPT, [ad_script])
                    if result == "blocked":
                        ready = True
                        break
                    time.sleep(2)
                check("lists loaded, ads blocked on the test site", ready)

                b.get(page)
                got = page_loaded(b) or {}
                check(
                    "the page's ad and tracker are blocked",
                    got.get("ad") == 0 and got.get("tracker") == 0,
                    json.dumps(got),
                )
                name = shield_name(frame, "Protection, on")
                check("shield says on", name == "Protection, on", name)

                # -- the panel
                hwnd, names = open_panel(b, frame)
                check("the shield opens a panel", bool(hwnd))
                total, kinds = summary_numbers(names)
                check(
                    "the panel counts what was blocked, more than none",
                    bool(total) and total >= 2,
                    f"{total}",
                )
                check(
                    "it names the kinds: ads and trackers",
                    "ad" in kinds and "tracker" in kinds,
                    json.dumps(kinds),
                )
                check(
                    "the kinds add up to the total",
                    total is not None and sum(kinds.values()) == total,
                    f"{sum(kinds.values())} of {total}",
                )
                check(
                    "one clear action to turn blocking off for this site",
                    "Turn off blocking for this site" in names,
                )
                check(
                    "a link to the site's settings", "Settings for this site" in names
                )
                check(
                    "the panel is titled with the site",
                    f"Blocking is on for {SITE}" in names,
                    str([n for n in names if "Blocking is" in n]),
                )
                # The panel fades in; a photograph taken at once is of a
                # half-made one.
                time.sleep(1.0)
                shot(hwnd, "panel")
                if hwnd:
                    with Window(hwnd) as w:
                        w.press(lambda n: n == "Turn off blocking for this site")
                    time.sleep(1.0)

                # -- the page is loaded again by the choice
                loaded = poll(
                    lambda: (lambda a: a if a and a.get("ad") == 1 else None)(
                        arrived(b)
                    ),
                    timeout=15,
                )
                check(
                    "turning blocking off lets the ad and tracker through",
                    bool(loaded) and loaded.get("tracker") == 1,
                    json.dumps(loaded),
                )
                want = f"Protection, blocking off for {SITE}"
                name = shield_name(frame, want)
                check("shield says blocking is off here", name == want, name)

                b.get(page)
                again = page_loaded(b) or {}
                check(
                    "it stays off when the page is loaded again",
                    again.get("ad") == 1 and again.get("tracker") == 1,
                    json.dumps(again),
                )

                # -- off panel, then on to the settings page
                before = set(window_handles(b))
                hwnd, names = open_panel(b, frame)
                check(
                    "the panel offers to turn blocking back on",
                    "Turn blocking back on" in names
                    and "Turn off blocking for this site" not in names,
                )
                check(
                    "and has no count where nothing is blocked",
                    summary_numbers(names)[0] is None,
                )
                if hwnd:
                    with Window(hwnd) as w:
                        w.press(lambda n: n == "Settings for this site")
                new = poll(
                    lambda: [h for h in window_handles(b) if h not in before],
                    timeout=10,
                )
                check("Settings for this site opens a tab", bool(new))
                settings_tab = new[0] if new else None

                if settings_tab:
                    switch_to(b, settings_tab)
                    url = unquote(b.current_url())
                    check(
                        "that tab is this site's settings page",
                        url.startswith("chrome://settings/content/siteDetails")
                        and origin in url,
                        url,
                    )
                    check("the page shows our rows", open_settings(b, origin))
                    rows = settings_rows(b)
                    for row_id in ROW_IDS:
                        check(
                            f"row: {ROW_LABELS[row_id]}",
                            (rows.get(row_id) or {}).get("label") == ROW_LABELS[row_id],
                            json.dumps(rows.get(row_id)),
                        )
                    check(
                        "no other row of ours, and no reader view row",
                        sorted(rows.get("all", [])) == sorted(ROW_LABELS.values()),
                        json.dumps(rows.get("all")),
                    )
                    check(
                        "and they sit under a Protection heading",
                        "Protection" in rows.get("headings", []),
                    )
                    shot(frame, "site-settings")
                    check(
                        "blocking row agrees with the panel: off here",
                        state_of(rows, "boringBlocking") is False,
                    )
                    check(
                        "clear on close and never sleep start off",
                        state_of(rows, "boringClearOnClose") is False
                        and state_of(rows, "boringNeverSleep") is False,
                    )

                    # -- blocking: on, the next load blocks; off, it does not
                    click_row(b, "boringBlocking")
                    switch_to(b, page_tab)
                    time.sleep(1.0)
                    b.get(page)
                    got = page_loaded(b) or {}
                    check(
                        "blocking row on: the next load blocks again",
                        got.get("ad") == 0 and got.get("tracker") == 0,
                        json.dumps(got),
                    )
                    switch_to(b, settings_tab)
                    click_row(b, "boringBlocking")
                    switch_to(b, page_tab)
                    time.sleep(1.0)
                    b.get(page)
                    got = page_loaded(b) or {}
                    check(
                        "blocking row off: the next load lets them through",
                        got.get("ad") == 1 and got.get("tracker") == 1,
                        json.dumps(got),
                    )

                    # -- never sleep, as the panel's own switch sees it
                    switch_to(b, settings_tab)
                    click_row(b, "boringNeverSleep")
                    switch_to(b, page_tab)
                    time.sleep(1.0)
                    hwnd, names = open_panel(b, frame)
                    state = None
                    if hwnd:
                        with Window(hwnd) as w:
                            state = w.toggle_state(
                                lambda n: n == "Never sleep this site"
                            )
                    check(
                        "never sleep row on: the panel's switch is on",
                        state == 1,
                        f"{state}",
                    )
                    if hwnd:
                        close_panel(frame)

                    # -- clear on close, with a cookie on the site and on a
                    #    control site that has no rule
                    switch_to(b, settings_tab)
                    click_row(b, "boringClearOnClose")
                    time.sleep(1.0)
                    check("the settings page opens again", open_settings(b, origin))
                    rows = settings_rows(b)
                    check(
                        "clear on close is kept as Chromium's own cookie setting",
                        state_of(rows, "boringClearOnClose") is True
                        and state_of(rows, "boringNeverSleep") is True
                        and state_of(rows, "boringBlocking") is False,
                        json.dumps(rows),
                    )
                    switch_to(b, page_tab)
                    for url in (page, control_page):
                        b.get(url)
                        b.run("document.cookie = 'keep=1; Max-Age=3600; path=/'")
                        check(
                            f"cookie set on {url.split(':')[1][2:]}",
                            "keep=1" in b.run("return document.cookie"),
                        )

                # A new profile now continues where it left off, which would
                # bring this run's tabs back in run two and put the shield on
                # another tab. Say "new tab page" the way a person would.
                start_on_new_tab_page(b)

            if not os.path.exists(preferences_path(profile)):
                check("profile has a Preferences file", False)
                return 1
            with open(preferences_path(profile), encoding="utf-8") as f:
                prefs = json.load(f).get("boring", {})
            check(
                "never sleep is saved for the origin",
                origin in prefs.get("performance", {}).get("never_sleep_sites", []),
                json.dumps(prefs.get("performance")),
            )
            check(
                "blocking off is saved for the site",
                SITE in prefs.get("blocking_off_sites", []),
                json.dumps(prefs.get("blocking_off_sites")),
            )

            # --- run two: the same profile, restarted ------------------------
            with Browser(user_data_dir=profile, args=args, headful=True) as b:
                frame = frame_window(CHROME, under=b.proc.pid)
                b.get(page)
                got = page_loaded(b) or {}
                check(
                    "after a restart blocking is still off for the site",
                    got.get("ad") == 1 and got.get("tracker") == 1,
                    json.dumps(got),
                )
                want = f"Protection, blocking off for {SITE}"
                name = shield_name(frame, want)
                check("and the shield says so", name == want, name)
                check(
                    "clear on close removed the site's cookie at quit",
                    "keep=1" not in b.run("return document.cookie"),
                )
                b.get(control_page)
                check(
                    "and left the control site's cookie alone",
                    "keep=1" in b.run("return document.cookie"),
                )
                check("the settings page opens", open_settings(b, origin))
                rows = settings_rows(b)
                check(
                    "its rows still say: blocking off, clear on close, never sleep",
                    state_of(rows, "boringBlocking") is False
                    and state_of(rows, "boringClearOnClose") is True
                    and state_of(rows, "boringNeverSleep") is True,
                    json.dumps(rows),
                )
    finally:
        server.shutdown()

    if failures:
        print(f"\n{len(failures)} failed: " + "; ".join(failures))
        return 1
    print("PASS: the panel explains what was blocked and the site's rules work")
    return 0


if __name__ == "__main__":
    sys.exit(main())
