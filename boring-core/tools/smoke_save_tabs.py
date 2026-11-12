#!/usr/bin/env python3
"""Check "Save all tabs" (Release 4, ledger item 4), from the app menu and
from the tab menu.

Everything is local: one HTTP server on 127.0.0.1 serves three pages with
their own titles. Two windows are open, two pages in the first and one in
the second, plus a new tab page that must not be saved.

The menus and the note the command shows are native, so they are opened
and pressed through UI Automation on our own windows, as smoke_forget.py
does: the app menu button's own Expand, the rows' Invoke, and for the tab
menu the tab's own ShowContextMenu (IUIAutomationElement3), which views
runs as the keyboard's context menu. No mouse or keys go to the desktop.
The bookmarks are read on chrome://bookmarks through chrome.bookmarks.

Checked:
  - the app menu has the row; one press saves every page of both windows,
    and nothing else, into a new folder under Other bookmarks named
    "Tabs <date and time>", with one folder per window
  - a note says how many tabs and where, with Show and Done; Done closes it
  - the tab menu has the row last; it saves again into a second folder,
    and Show opens the bookmarks page on that folder

Usage: python smoke_save_tabs.py [--shots DIR]
"""

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from capture_native import frame_window, grab
from drive import CHROME, Browser
from smoke_forget import big_windows, is_app_menu_button, names_of, new_tab, press, window_with
from smoke_site_panel import GUID, Window, _call, _release, browser_windows, poll, switch_to, window_handles

ROW = "Save all tabs"
NOTE = "Tabs saved"
PAGES = {"/alpha": "Save test alpha", "/bravo": "Save test bravo", "/charlie": "Save test charlie"}
IID_ELEMENT3 = "{8471DF34-AEE0-4A01-A7DE-7DB9AF12C296}"
SHOW_CONTEXT_MENU = 91  # IUIAutomationElement3::ShowContextMenu

TREE_JS = """
const done = arguments[arguments.length - 1];
if (!(window.chrome && chrome.bookmarks)) { done(null); return; }
chrome.bookmarks.getTree(t => done(JSON.stringify(t)));
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        title = PAGES.get(self.path.split("?")[0])
        if title is None:
            self.send_response(404)
            self.end_headers()
            return
        body = f"<!doctype html><title>{title}</title><h1>{title}</h1>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def saved_folders(b):
    """Every folder under Other bookmarks whose name starts with "Tabs ", as
    {title: {sub-folder or "": [urls]}}, read on chrome://bookmarks."""
    b.get("chrome://bookmarks")
    text = poll(lambda: b.run_async(TREE_JS), timeout=15)
    if not text:
        return None
    root = json.loads(text)[0]
    other = next((n for n in root.get("children", []) if n.get("id") == "2"), None)
    out = {}
    for node in (other or {}).get("children", []):
        if node.get("url") or not node.get("title", "").startswith("Tabs "):
            continue
        groups = {}
        for child in node.get("children", []):
            if child.get("url"):
                groups.setdefault("", []).append(child["url"])
            else:
                groups[child["title"]] = [c["url"] for c in child.get("children", [])]
        out[node["title"]] = groups
    return out


def show_tab_menu(frame, title):
    """Open the tab menu of the tab named `title` through the tab's own
    ShowContextMenu. Returns how it went."""
    with Window(frame) as w:
        for element in w.elements(lambda n: n.startswith(title)):
            e3 = ctypes.c_void_p()
            guid = GUID(IID_ELEMENT3)
            try:
                _call(element, 0, ctypes.addressof(guid), ctypes.addressof(e3))
                _call(e3, SHOW_CONTEXT_MENU)
                return "ShowContextMenu"
            except OSError as e:
                last = repr(e)
            finally:
                _release(e3)
        return f"refused ({last})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=None)
    opts = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    if opts.shots:
        os.makedirs(opts.shots, exist_ok=True)
    failures = []

    def check(name, ok, detail=""):
        print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail else ""))
        if not ok:
            failures.append(name)

    def shot(hwnd, name):
        if opts.shots and hwnd:
            print("saved", grab(hwnd, os.path.join(opts.shots, name + ".png")))

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    urls = {p: f"http://127.0.0.1:{server.server_port}{p}" for p in PAGES}

    args = ["--disable-background-mode", "--window-size=1200,800"]
    with Browser(args=args, headful=True) as b:
        frame = frame_window(CHROME, under=b.proc.pid)
        b.get(urls["/alpha"])
        new_tab(b)
        b.get(urls["/bravo"])
        new_tab(b)  # a new tab page, which is not saved
        first = set(window_handles(b))
        handle = b._req("POST", f"/session/{b.sid}/window/new", {"type": "window"})["value"]
        switch_to(b, handle["handle"])
        b.get(urls["/charlie"])
        check("two windows are open", poll(lambda: big_windows(b) == 2), str(big_windows(b)))

        # -- the app menu
        with Window(frame) as w:
            how = w.press(is_app_menu_button)
        print(f"  app menu button pressed by {how}")
        menu, names = window_with(b, frame, lambda ns: ROW in ns)
        check("the app menu has Save all tabs", bool(menu))
        shot(menu, "save-tabs-app-menu")
        if menu:
            press(menu, ROW)
        note, names = window_with(b, frame, lambda ns: NOTE in ns and "Done" in ns)
        check("one press saves and says so", bool(note), str(names[:12]))
        check(
            "the note says how many and has Show and Done",
            any(n.startswith("3 tabs are in your bookmarks now") for n in names)
            and "Show" in names,
            str(names[:12]),
        )
        shot(note, "save-tabs-note")
        if note:
            press(note, "Done")
        check("Done closes the note", poll(lambda: not names_of(note)) if note else False)

        switch_to(b, sorted(first)[0])
        new_tab(b)
        folders = saved_folders(b) or {}
        print("  saved:", json.dumps(folders))
        check("one dated folder under Other bookmarks", len(folders) == 1, str(list(folders)))
        groups = next(iter(folders.values()), {})
        windows = sorted(sorted(v) for v in groups.values())
        want = sorted([sorted([urls["/alpha"], urls["/bravo"]]), [urls["/charlie"]]])
        check(
            "one folder per window, with every page and no new tab page",
            sorted(groups) == ["Window 1", "Window 2"] and windows == want,
            json.dumps(groups),
        )

        # -- the tab menu
        how = show_tab_menu(frame, PAGES["/alpha"])
        print(f"  tab menu: {how}")
        menu, names = window_with(b, frame, lambda ns: ROW in ns and "Reload" in ns)
        check("the tab menu has Save all tabs", bool(menu), how)
        check("as its last row", bool(names) and names[-1] == ROW, str(names[-4:]))
        shot(menu, "save-tabs-tab-menu")
        if menu:
            press(menu, ROW)
        note, names = window_with(b, frame, lambda ns: NOTE in ns and "Show" in ns)
        check("the tab menu row saves and says so", bool(note))
        before = set(window_handles(b))
        if note:
            press(note, "Show")
        opened = poll(lambda: set(window_handles(b)) - before or None, timeout=10) or set()
        shown = ""
        for h in opened:
            switch_to(b, h)
            shown = b.current_url()
        check("Show opens the bookmarks page on the new folder", shown.startswith("chrome://bookmarks/?id="), shown)
        check("a second dated folder", len(saved_folders(b) or {}) == 2)

    if failures:
        print(f"FAIL: {len(failures)} check(s): {failures}")
        sys.exit(1)
    print("PASS: Save all tabs saves every tab from both menus")


if __name__ == "__main__":
    main()
