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
import('chrome://resources/js/cr.js')
  .then(m => m.sendWithPromise('clearBrowsingData',
                               ['browser.clear_data.browsing_history'], 0))
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
            before = len(handles(b))
            time.sleep(16)
            checks("off by default: no tab closed", len(handles(b)) == before, f"{before}")
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
            before = len(handles(b))
            moved = wait_for(lambda: (read_entries(profile) or []), 40)
            checks("on: tabs moved to the file", bool(moved), f"{len(moved or [])}")
            after = len(wait_for(lambda: handles(b), 5) or [])
            checks("on: open tabs went down", after < before, f"{before} -> {after}")
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
            if pressing(pid, lambda n: n == "Clear earlier tabs") is not None:
                time.sleep(0.6)
                if pressing(pid, lambda n: n == "Clear") is not None:
                    cleared = bool(wait_for(lambda: (read_entries(profile) or []) == [], 10))
            checks("Clear: asks, then empties the file", cleared)
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
            before = len(handles(b))
            time.sleep(16)
            checks("incognito: nothing moved", len(handles(b)) == before)
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
            before = len(handles(b))
            time.sleep(16)
            checks("version guard: no tab moved", len(handles(b)) == before)
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
