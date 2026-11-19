#!/usr/bin/env python3
"""Smoke test: the toolbar and the bookmarks bar as the compiled screens draw
them (ledger item 5; screens 1 and 14 in design/v12-compiled).

Several short launches of scratch profiles, started straight from chrome.exe:

  1. A new profile, light. The test hook --boring-toolbar-test=buttons lists
     the toolbar in order. After the address bar it reads Forget, Protected,
     Downloads, a hairline, the menu: Forget is a pinned button with its
     word, the shield says "Protected", the accounts slot shows nothing (no
     avatar), and the hairline sits right before the menu. Photographed
     beside the compiled screen 1.
  2. Same profile. Forget is pressed through UI Automation on our own
     window: the "Forget this session?" question comes up, Cancel keeps
     every tab.
  3. Same profile. The Customize toolbar picker lists "Forget this
     session", ticked; unticking it unpins it. After a dark restart there
     is no Forget button and the profile's pinned list still lacks it.
  4. A profile from before Forget existed (pinned list: Downloads only)
     gets Forget pinned once, first; one where that already happened and
     Forget was unpinned keeps it unpinned.
  5. A new profile, dark, photographed beside the compiled screen 1, dark.
  6. Bookmarks bar: off on a new profile. With Chromium's own setting
     bookmark_bar.show_on_all_tabs on, the bar shows the bookmarks and All
     bookmarks; photographed light and dark beside the compiled screen 14.

The hook writes what it saw to boring-toolbar-test.txt in the profile.
Only DevTools, UI Automation and PrintWindow of our own windows; nothing is
sent to the OS as input. Not checked here: sizes in pixels (compare the
pictures), and Forget itself (smoke_forget.py).

    python smoke_toolbar.py [--out E:\\tmp\\cui-toolbar\\shots]

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import contextlib
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from capture_native import frame_window, grab
from drive import CHROME
from smoke_local import Checks
from smoke_memory import close, launch
from smoke_quick_buttons import click_row, open_picker, pinned_actions, rows
from smoke_site_panel import Window, browser_windows

FORGET_ID = "kActionBoringForgetSession"
DOWNLOADS_ID = "kActionShowDownloads"
FORGET_ROW = "Forget this session"
FORGET_TITLE = "Forget this session?"
REPORT = "boring-toolbar-test.txt"
PINNED = "PinnedActionToolbarButton"
# What the toolbar reads after the address bar on a new profile, as drawn.
EXPECTED_ROW = ["Forget", "Protected", "Downloads", "hairline", "menu"]
# The same once Forget is unpinned.
UNPINNED_ROW = ["Protected", "Downloads", "hairline", "menu"]
# Buttons that come before the drawn row, or show only now and then.
LEADING = {"BackForwardButton", "ReloadButton", "HomeButton", "ExtensionsToolbarButton", "BoringReaderButton"}
BOOKMARKS = ["Mail", "Bank", "Council", "Recipes"]
SHOTS = r"E:\WEBBrowser\design\v12-compiled\shots-final"


def read_report(profile, timeout=20):
    """The hook's report, in order: ("button", class, name, tooltip, text,
    on) and ("divider",) entries. None until its "end" line is there."""
    path = Path(profile) / "Default" / REPORT
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            lines = path.read_text(encoding="utf-8").splitlines()
            if "end" in lines:
                out = []
                for line in lines:
                    kind, _, rest = line.partition("\t")
                    fields = rest.split("\t")
                    if kind == "button" and len(fields) >= 5:
                        out.append(("button", *fields[:4], fields[-1] == "on"))
                    elif kind == "divider":
                        out.append(("divider",))
                return out
        time.sleep(0.2)
    return None


def tag(entry):
    """A short word for one toolbar entry, as the screens name them."""
    if entry[0] == "divider":
        return "hairline"
    _, cls, _name, tip, _text, _on = entry
    if cls == PINNED and tip == FORGET_ROW:
        return "Forget"
    if cls == PINNED and tip == "Downloads":
        return "Downloads"
    if cls == "BoringProtectionButton":
        return "Protected"
    if cls == "BrowserAppMenuButton":
        return "menu"
    return cls


def drawn_row(report):
    return [tag(e) for e in report or [] if not (e[0] == "button" and e[1] in LEADING)]


def find(report, wanted):
    return next((e for e in report or [] if e[0] == "button" and tag(e) == wanted), None)


def boring_pref(profile, key):
    """boring.toolbar.<key> from a closed profile's Preferences, or None."""
    with contextlib.suppress(OSError, ValueError):
        prefs = json.loads((Path(profile) / "Default" / "Preferences").read_text(encoding="utf-8"))
        return prefs.get("boring", {}).get("toolbar", {}).get(key)
    return None


def bookmarks_file(titles):
    """A Bookmarks file: the titles on the bar, one page in Other bookmarks
    (so the All bookmarks button has something to open)."""

    def url(i, title):
        return {"id": str(10 + i), "name": title, "type": "url", "url": f"https://{title.lower()}.example/", "date_added": "0"}

    def folder(i, name, children):
        return {"id": str(i), "name": name, "type": "folder", "children": children, "date_added": "0", "date_modified": "0"}

    return {
        "checksum": "",
        "version": 1,
        "roots": {
            "bookmark_bar": folder(1, "Bookmarks bar", [url(i, t) for i, t in enumerate(titles)]),
            "other": folder(2, "Other bookmarks", [url(9, "Later")]),
            "synced": folder(3, "Mobile bookmarks", []),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\tmp\cui-toolbar\shots", help="folder for the photographs")
    ap.add_argument("--shots", default=SHOTS, help="the compiled screens, to copy beside ours")
    args = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    checks = Checks()
    work = Path(tempfile.mkdtemp(prefix="boring-toolbar-", dir=os.environ.get("TMP", r"E:\tmp")))
    flags = ["--disable-features=CalculateNativeWinOcclusion", "--window-size=1280,800"]
    proc = cdp = None

    def start(where, extra=(), urls=("about:blank",)):
        nonlocal proc, cdp
        with contextlib.suppress(OSError):
            (Path(where) / "Default" / REPORT).unlink()
        proc, cdp = launch(CHROME, where, [*flags, *extra], urls)
        time.sleep(3)

    def stop():
        nonlocal proc, cdp
        if proc:
            close(proc, cdp)
        proc = cdp = None

    def hook(where, extra=()):
        start(where, ["--boring-toolbar-test=buttons", *extra])
        report = read_report(where) or []
        print("toolbar:", report)
        return report

    def new_profile(name, prefs=None, bookmarks=None):
        where = work / name
        (where / "Default").mkdir(parents=True)
        if prefs:
            (where / "Default" / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")
        if bookmarks:
            (where / "Default" / "Bookmarks").write_text(json.dumps(bookmarks), encoding="utf-8")
        return where

    def shoot(name, compiled):
        """PrintWindow of our own window, with the compiled screen copied
        beside it under the same name."""
        hwnd = frame_window(CHROME, under=os.getpid())
        time.sleep(0.8)
        grab(hwnd, str(out / f"{name}.png"))
        source = Path(args.shots) / compiled
        if source.is_file():
            shutil.copyfile(source, out / f"{name}-compiled.png")
        else:
            print("no compiled screen at", source)
        print("saved", out / f"{name}.png")

    def frame_names():
        with Window(frame_window(CHROME, under=os.getpid())) as w:
            return list(w.names())

    def page_count():
        return len([t for t in cdp.send("Target.getTargets")["targetInfos"] if t["type"] == "page"])

    def press_forget():
        """None when Forget asked first and Cancel kept every tab."""
        before = page_count()
        try:
            with Window(frame_window(CHROME, under=os.getpid())) as w:
                w.press(lambda n: n.startswith(FORGET_ROW))
        except (LookupError, RuntimeError, OSError) as e:
            return f"could not press Forget: {e}"
        deadline = time.time() + 10
        while time.time() < deadline:
            for hwnd in browser_windows(proc.pid):
                try:
                    with Window(hwnd) as w:
                        names = list(w.names())
                except OSError:
                    continue
                if FORGET_TITLE in names and "Cancel" in names and "Forget" in names:
                    try:
                        with Window(hwnd) as w:
                            w.press(lambda n: n == "Cancel")
                    except (LookupError, RuntimeError, OSError) as e:
                        return f"could not press Cancel: {e}"
                    time.sleep(1.5)
                    return None if page_count() == before else "Cancel still closed or opened tabs"
            time.sleep(0.3)
        return "Forget asked nothing"

    try:
        # 1. A new profile, light.
        profile = new_profile("profile")
        report = hook(profile)
        row = drawn_row(report)
        checks("the toolbar reads Forget, Protected, Downloads, hairline, menu", row == EXPECTED_ROW, str(row))
        forget = find(report, "Forget")
        checks("Forget is a pinned button with the word Forget", bool(forget) and forget[4] == "Forget", str(forget))
        checks(
            "Forget is named Forget this session and is on",
            bool(forget) and forget[2].startswith(FORGET_ROW) and forget[3] == FORGET_ROW and forget[5],
            str(forget),
        )
        shield = find(report, "Protected")
        checks("the shield says Protected", bool(shield) and shield[4] == "Protected", str(shield))
        checks(
            "no avatar or accounts button (the slot is empty)",
            not any(e[0] == "button" and "Avatar" in e[1] for e in report),
            str(report),
        )
        shoot("toolbar-light", "c01-newtab.png")
        stop()
        checks("the one-time pin is marked done", boring_pref(profile, "forget_pinned_once") is True)

        # 2. Forget asks first; Cancel keeps every tab.
        start(profile, urls=("about:blank", "about:blank#two"))
        problem = press_forget()
        checks("Forget asks first and Cancel keeps every tab", problem is None, str(problem))
        stop()

        # 3. The picker lists Forget, ticked; unticking unpins it, for good.
        start(profile)
        panel = open_picker(cdp)
        checks("the picker opens", panel is not None)
        if panel:
            on = {r["name"]: r["on"] for r in rows(cdp, panel)}
            checks("the picker lists Forget this session, ticked", on.get(FORGET_ROW) is True, str(on))
            checks("unticking Forget works", bool(click_row(cdp, panel, FORGET_ROW)))
            time.sleep(2)
            on = {r["name"]: r["on"] for r in rows(cdp, panel)}
            checks("the row shows as off", on.get(FORGET_ROW) is False, str(on))
        stop()
        pins = pinned_actions(profile)
        checks("Forget left the pinned list", FORGET_ID not in pins, str(pins))
        report = hook(profile, ["--force-dark-mode"])
        row = drawn_row(report)
        checks("after a restart Forget stays unpinned", row == UNPINNED_ROW, str(row))
        stop()
        pins = pinned_actions(profile)
        checks("and the pinned list still lacks it", FORGET_ID not in pins, str(pins))

        # 4. Older profiles.
        old = new_profile("old", {"toolbar": {"pinned_actions": [DOWNLOADS_ID]}})
        row = drawn_row(hook(old))
        checks("an older profile gets Forget pinned once, first", row == EXPECTED_ROW, str(row))
        stop()
        pins = pinned_actions(old)
        checks("its pinned list starts with Forget", pins[:2] == [FORGET_ID, DOWNLOADS_ID], str(pins))
        row = drawn_row(hook(old))
        checks("a second start pins nothing more", row == EXPECTED_ROW, str(row))
        stop()
        done = new_profile(
            "old-unpinned",
            {"toolbar": {"pinned_actions": [DOWNLOADS_ID]}, "boring": {"toolbar": {"forget_pinned_once": True}}},
        )
        row = drawn_row(hook(done))
        checks("a profile that unpinned Forget after the one-time pin keeps it unpinned", row == UNPINNED_ROW, str(row))
        stop()

        # 5. A new profile, dark.
        dark = new_profile("dark")
        row = drawn_row(hook(dark, ["--force-dark-mode"]))
        checks("dark: the same row", row == EXPECTED_ROW, str(row))
        shoot("toolbar-dark", "dark/c01-newtab.png")
        stop()

        # 6. The bookmarks bar: off by default, on with its own setting.
        marks = bookmarks_file(BOOKMARKS)
        off = new_profile("bookmarks-off", bookmarks=marks)
        start(off)
        names = frame_names()
        checks("a new profile shows no bookmarks bar", not any(n.startswith(t) for t in BOOKMARKS for n in names), str(names))
        stop()
        checks(
            "the setting is off by default",
            not json.loads((off / "Default" / "Preferences").read_text(encoding="utf-8"))
            .get("bookmark_bar", {})
            .get("show_on_all_tabs", False),
        )
        for theme, extra, compiled in (("light", [], "c14-bookmarkstop.png"), ("dark", ["--force-dark-mode"], "dark/c14-bookmarkstop.png")):
            on = new_profile(f"bookmarks-{theme}", {"bookmark_bar": {"show_on_all_tabs": True}}, marks)
            start(on, extra)
            names = frame_names()
            checks(
                f"{theme}: the bar shows every bookmark",
                all(any(n.startswith(t) for n in names) for t in BOOKMARKS),
                str(names),
            )
            checks(
                f"{theme}: the bar has All bookmarks",
                any(n.lower() == "all bookmarks" for n in names),
                str([n for n in names if "bookmark" in n.lower()]),
            )
            shoot(f"bookmarks-{theme}", compiled)
            stop()
        return checks.result("toolbar")
    finally:
        stop()
        with contextlib.suppress(Exception):
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
