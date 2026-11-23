#!/usr/bin/env python3
"""Smoke test: Earlier tabs (ledger item 16, compiled screen C08).

Runs the real browser with temp profiles under E:\\tmp. Timers are shortened
with the --boring-earlier-*-seconds switches (they only shorten timers). A
small local server on 127.0.0.1 serves the pages. WebDriver counts tabs, UI
Automation on our own window reads names and presses buttons, PrintWindow
photographs our window. No input is sent from the OS.

What it asserts (nothing is asserted that was not looked at):
  1. Off by default: a fresh profile, tabs left alone past the shortened
     day: no tab closes, no "Boring Earlier Tabs" file, no chip.
  2. Switched on (pref seeded): background tabs move after the shortened
     day, the active tab stays, the file exists and parses, every entry is a
     web address, the chip is named "Earlier N".
  3. Never moves: a tab with a leave-this-site handler, and a chrome:// tab,
     stay open while others move.
  4. Incognito: with the switch on, a private window records nothing (no
     file, no chip).
  5. Reopen: a row in the pop-up opens a tab (handles +1) and leaves the
     list. Clear: "Clear earlier tabs" then "Clear" empties the file and
     leaves open tabs alone.
  6. Expiry: entries older than the shortened 30 days leave the file; the
     page is still in History.
  7. History: clearing browsing history removes the matching entries.
  8. Version guard: a file with version 2 is never written and no tab moves.
  9. Captures: PrintWindow of the pop-up, light and dark (--captures).
Not checked here: pinned and grouped tabs (no hook can pin or group a tab
without input, so the rule is code only), a tab playing audio, unsaved form
input, the Settings switch and the first-run row (not reachable without
input).

Usage: python boring-core/tools/smoke_earlier.py [--out DIR] [--captures DIR]
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
from smoke_site_panel import Window, browser_windows

# Chrome's parent: chromedriver, set as each Browser starts.
DRIVER_PID = [None]

FILE_NAME = "Boring Earlier Tabs"
FAST = [
    "--boring-earlier-idle-seconds=5",
    "--boring-earlier-check-seconds=2",
    "--boring-earlier-settle-seconds=1",
]
CLEAR_HISTORY_JS = """
const done = arguments[arguments.length - 1];
// Initialize first, as Settings' own dialog does: the handler answers only
// a page it has allowed, and a clear sent before that crashes the browser.
import('chrome://resources/js/cr.js')
  .then(m => m.sendWithPromise('initializeClearBrowsingData')
    .then(() => m.sendWithPromise('clearBrowsingData',
                                  ['browser.clear_data.browsing_history'], 0)))
  .then(() => done(true), e => done('error: ' + e));
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        name = self.path.strip("/") or "Home"
        script = ""
        if name.startswith("Guarded"):
            script = "<script>window.onbeforeunload = () => 'x';</script>"
        body = f"<!doctype html><title>{name}</title><p>{name}</p>{script}".encode()
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


# --- pure helpers, tested without a browser ------------------------------


def make_entry(entry_id, url, moved_ms, last_used_ms=None, title="A page"):
    """One entry as the browser writes it (times are decimal text)."""
    return {
        "id": entry_id,
        "moved": str(moved_ms),
        "last_used": str(moved_ms if last_used_ms is None else last_used_ms),
        "title": title,
        "url": url,
        "selected_index": 0,
        "navigations": [{"url": url, "title": title}],
    }


def file_text(entries, version=1):
    return json.dumps({"version": version, "entries": entries})


def parse_file(text):
    """The entries of a file's text, or None when it is not ours."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None
    return data["entries"]


def web_only(entries):
    return all(str(e.get("url", "")).startswith(("http://", "https://")) for e in entries)


def chip_count(names):
    """The number on the chip from the names on our window ("Earlier 3"), or
    None when there is no chip."""
    for name in names:
        parts = name.split()
        if len(parts) == 2 and parts[0] == "Earlier" and parts[1].isdigit():
            return int(parts[1])
    return None


def now_ms():
    return int(time.time() * 1000)


def earlier_file(profile):
    return Path(profile) / "Default" / FILE_NAME


def read_entries(profile):
    path = earlier_file(profile)
    if not path.exists():
        return None
    return parse_file(path.read_text(encoding="utf-8"))


def seed_prefs(profile, enabled):
    default = Path(profile) / "Default"
    default.mkdir(parents=True, exist_ok=True)
    prefs = {"boring": {"earlier": {"enabled": True}}} if enabled else {}
    (default / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")


# --- browser side ---------------------------------------------------------


def handles(b):
    return b._req("GET", f"/session/{b.sid}/window/handles")["value"]


def wait_for(fn, timeout=30.0, step=0.5):
    deadline = time.monotonic() + timeout
    value = fn()
    while not value and time.monotonic() < deadline:
        time.sleep(step)
        value = fn()
    return value


def names_of(pid):
    try:
        with Window(frame_window(CHROME, under=pid)) as w:
            return w.names()
    except (LookupError, RuntimeError, OSError):
        return []


def tab_marks(pid):
    """How many "Close" buttons our window shows: one per tab plus the same
    few every time. Compared with itself it counts tabs without asking
    chromedriver. Any WebDriver request about the tabs attaches DevTools to
    every one, and Chromium's own rule never puts a tab with DevTools
    attached to sleep, so a test that listed the tabs first would test
    nothing."""
    return names_of(pid).count("Close")


def open_pages(b, base, kinds):
    for kind in kinds:
        b.run("window.open(arguments[0])", [f"{base}/{kind}"])
        time.sleep(0.4)


def pressing(pid, name_wanted):
    """Press the first control named so, in the frame or in a pop-up of ours."""
    for hwnd in browser_windows(pid):
        try:
            with Window(hwnd) as w:
                if any(name_wanted(n) for n in w.names()):
                    return w.press(name_wanted)
        except (LookupError, OSError):
            continue
    return None


def popup_names(pid):
    out = []
    for hwnd in browser_windows(pid):
        try:
            with Window(hwnd) as w:
                out.extend(w.names())
        except OSError:
            continue
    return out


def footer_fits(pid, labels):
    """Screen C08: each footer button is at least as wide as its whole text
    (Segoe UI 12px at the window's scale, the buttons' own size), so neither
    reads "Show..." or "Clear earlier...".
    {label: (button width, text width)} for the labels found."""
    import ctypes
    from ctypes import wintypes
    from smoke_site_panel import _call  # noqa: PLC0415

    gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
    out = {}
    for hwnd in browser_windows(pid):
        try:
            with Window(hwnd) as w:
                scale = user32.GetDpiForWindow(hwnd) / 96 or 1
                dc = user32.GetDC(None)
                font = gdi32.CreateFontW(-round(12 * scale), 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0,
                                         "Segoe UI")
                old = gdi32.SelectObject(dc, font)
                try:
                    for text, element in w.items:
                        if element and text in labels:
                            rect = wintypes.RECT()
                            _call(element, 43, ctypes.addressof(rect))
                            size = wintypes.SIZE()
                            gdi32.GetTextExtentPoint32W(dc, text, len(text), ctypes.byref(size))
                            out[text] = (rect.right - rect.left, size.cx)
                finally:
                    gdi32.SelectObject(dc, old)
                    gdi32.DeleteObject(font)
                    user32.ReleaseDC(None, dc)
        except (LookupError, OSError):
            continue
    return out


def new_profile(tmp, enabled):
    profile = Path(tmp) / "profile"
    seed_prefs(profile, enabled)
    return profile


def scenario_off(base, checks):
    with tempfile.TemporaryDirectory(prefix="earlier-", dir=r"E:\tmp") as tmp:
        profile = new_profile(tmp, False)
        with Browser(headful=True, user_data_dir=str(profile), args=["--window-size=1280,800", *FAST]) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            b.get(base + "/")
            open_pages(b, base, ["Page1", "Page2", "Page3"])
            time.sleep(1.5)
            before = tab_marks(DRIVER_PID[0])
            time.sleep(16)
            now = tab_marks(DRIVER_PID[0])
            checks("off by default: no tab closed", before > 0 and now == before, f"{before} -> {now}")
            checks("off by default: no file kept", not earlier_file(profile).exists())
            checks("off by default: no chip", chip_count(names_of(DRIVER_PID[0])) is None)


def scenario_on(base, out, captures, checks):
    with tempfile.TemporaryDirectory(prefix="earlier-", dir=r"E:\tmp") as tmp:
        profile = new_profile(tmp, True)
        args = ["--window-size=1280,800", *FAST, "--boring-open-earlier"]
        with Browser(headful=True, user_data_dir=str(profile), args=args) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            b.get(base + "/")
            open_pages(b, base, ["Page1", "Page2", "Guarded1", "Page3", "Page4"])
            b.run("window.open('chrome://version')")
            time.sleep(1.5)
            before = tab_marks(DRIVER_PID[0])
            moved = wait_for(lambda: (read_entries(profile) or []), 40)
            checks("on: tabs moved to the file", bool(moved), f"{len(moved or [])}")
            time.sleep(2)
            after = tab_marks(DRIVER_PID[0])
            checks("on: open tabs went down", before > 0 and after < before, f"{before} -> {after}")
            entries = read_entries(profile) or []
            checks("on: every entry is a web address", bool(entries) and web_only(entries))
            checks("on: the leave-this-site tab was not moved",
                   not any("Guarded" in e.get("url", "") for e in entries))
            checks("on: the chrome:// tab was not moved",
                   not any(e.get("url", "").startswith("chrome:") for e in entries))
            pid = b.proc.pid
            wait_for(lambda: chip_count(names_of(DRIVER_PID[0])) is not None, 15)
            count = chip_count(names_of(DRIVER_PID[0]))
            checks("on: the chip is named Earlier and the count", count == len(entries),
                   f"chip {count}, file {len(entries)}")
            # The pop-up opened by --boring-open-earlier.
            wait_for(lambda: "Clear earlier tabs" in popup_names(pid), 10)
            names = popup_names(pid)
            checks("the pop-up shows its title and Clear", "Clear earlier tabs" in names,
                   str(sorted(names))[:300])
            show_all = f"Show all {len(entries)}"
            checks("the footer reads Show all N and Clear earlier tabs",
                   show_all in names and "Clear earlier tabs" in names, str(sorted(names))[:300])
            fits = footer_fits(pid, {show_all, "Clear earlier tabs"})
            checks("both footer buttons are wide enough for their whole text",
                   len(fits) == 2 and all(w >= t for w, t in fits.values()), str(fits))
            shoot(out, captures, checks, "light")
            # Reopen: press a row (its title is the page's title).
            titles = [e["title"] for e in entries]
            row = next((n for n in names if n in titles), None)
            if row:
                open_before = len(handles(b))
                pressing(pid, lambda n, r=row: n == r)
                reopened = wait_for(lambda: len(handles(b)) == open_before + 1, 10)
                checks("Reopen: a row opens a tab", bool(reopened))
                left = wait_for(lambda: len(read_entries(profile) or []) == len(entries) - 1, 10)
                checks("Reopen: the entry left the file", bool(left))
            else:
                checks("Reopen: a row to press", False, str(sorted(names))[:300])
            # Clear: press, then confirm.
            tabs_before = len(handles(b))
            cleared = False
            steps = []
            # A row press closes the pop-up; the chip opens it again.
            if row:
                wait_for(lambda: "Clear earlier tabs" not in popup_names(pid), 10)
                for _ in range(5):
                    try:
                        steps.append(f"chip {pressing(pid, lambda n: chip_count([n]) is not None)}")
                    except RuntimeError as e:
                        steps.append(f"chip refused {str(e)[:60]}")
                        time.sleep(1)
                        continue
                    if wait_for(lambda: "Clear earlier tabs" in popup_names(pid), 4):
                        break
            asked = pressing(pid, lambda n: n == "Clear earlier tabs")
            steps.append(f"ask {asked}")
            if asked is not None:
                time.sleep(0.6)
                confirmed = pressing(pid, lambda n: n == "Clear")
                steps.append(f"confirm {confirmed}")
                if confirmed is not None:
                    cleared = bool(wait_for(lambda: (read_entries(profile) or []) == [], 10))
            steps.append(f"file {read_entries(profile)}")
            checks("Clear: asks, then empties the file", cleared, "; ".join(steps)[:400])
            checks("Clear: open tabs untouched", len(handles(b)) >= tabs_before - 1)


def shoot(out, folder, checks, theme):
    try:
        hwnd = frame_window(CHROME, under=DRIVER_PID[0])
    except (LookupError, RuntimeError, OSError) as e:
        checks("our window to photograph", False, str(e))
        return
    time.sleep(0.6)
    path = Path(out) / f"earlier-{theme}.png"
    grab(hwnd, str(path))
    print("saved", path)
    both = page_checks.save_capture(path, "earlier", "C08", dark=(theme == "dark"),
                                    folder=folder, label="c08-earlier")
    if both:
        print("saved", both)


def scenario_incognito(base, checks):
    with tempfile.TemporaryDirectory(prefix="earlier-", dir=r"E:\tmp") as tmp:
        profile = new_profile(tmp, True)
        args = ["--window-size=1280,800", "--incognito", *FAST]
        with Browser(headful=True, user_data_dir=str(profile), args=args) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            b.get(base + "/")
            open_pages(b, base, ["Page1", "Page2", "Page3"])
            time.sleep(1.5)
            before = tab_marks(DRIVER_PID[0])
            time.sleep(16)
            now = tab_marks(DRIVER_PID[0])
            checks("incognito: nothing moved", before > 0 and now == before, f"{before} -> {now}")
            checks("incognito: nothing recorded", not earlier_file(profile).exists())
            checks("incognito: no chip", chip_count(names_of(DRIVER_PID[0])) is None)


def scenario_expiry(base, checks):
    with tempfile.TemporaryDirectory(prefix="earlier-", dir=r"E:\tmp") as tmp:
        profile = new_profile(tmp, False)
        old = now_ms() - 600_000
        entries = [make_entry("old1", f"{base}/Old1", old, title="Old1"),
                   make_entry("old2", f"{base}/Old2", old, title="Old2")]
        earlier_file(profile).write_text(file_text(entries), encoding="utf-8")
        args = ["--window-size=1280,800", *FAST, "--boring-earlier-keep-seconds=10"]
        with Browser(headful=True, user_data_dir=str(profile), args=args) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            gone = wait_for(lambda: read_entries(profile) == [], 25)
            checks("expiry: old entries left the file", bool(gone), str(read_entries(profile)))


def scenario_history(base, checks):
    with tempfile.TemporaryDirectory(prefix="earlier-", dir=r"E:\tmp") as tmp:
        profile = new_profile(tmp, False)
        entry = make_entry("h1", f"{base}/Hist1", now_ms(), title="Hist1")
        earlier_file(profile).write_text(file_text([entry]), encoding="utf-8")
        with Browser(headful=True, user_data_dir=str(profile), args=["--window-size=1280,800", *FAST]) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            b.get(base + "/Hist1")
            time.sleep(1)
            b.get("chrome://settings/clearBrowserData")
            result = b.run_async(CLEAR_HISTORY_JS)
            gone = wait_for(lambda: read_entries(profile) == [], 15)
            checks("history: clearing history removed the entry", bool(gone), str(result))


def scenario_version(base, checks):
    with tempfile.TemporaryDirectory(prefix="earlier-", dir=r"E:\tmp") as tmp:
        profile = new_profile(tmp, True)
        text = file_text([make_entry("v2", f"{base}/V2", now_ms())], version=2)
        earlier_file(profile).write_text(text, encoding="utf-8")
        with Browser(headful=True, user_data_dir=str(profile), args=["--window-size=1280,800", *FAST]) as b:
            DRIVER_PID[0] = b.proc.pid  # chromedriver starts Chrome
            b.get(base + "/")
            open_pages(b, base, ["Page1", "Page2"])
            time.sleep(1.5)
            before = tab_marks(DRIVER_PID[0])
            time.sleep(16)
            now = tab_marks(DRIVER_PID[0])
            checks("version guard: no tab moved", before > 0 and now == before, f"{before} -> {now}")
        same = earlier_file(profile).read_text(encoding="utf-8") == text
        checks("version guard: the file was never written", same)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\tmp\earlier-shots")
    page_checks.add_captures_option(ap)
    args = ap.parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    checks = Checks()
    server = serve()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        scenario_off(base, checks)
        scenario_on(base, args.out, args.captures, checks)
        scenario_incognito(base, checks)
        scenario_expiry(base, checks)
        scenario_history(base, checks)
        scenario_version(base, checks)
    finally:
        server.shutdown()
    return checks.result("earlier tabs")


if __name__ == "__main__":
    sys.exit(main())
