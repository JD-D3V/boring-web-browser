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
  6. Bookmarks bar: on for a new profile. With Chromium's own setting
     bookmark_bar.show_on_all_tabs off it is hidden; on, the bar shows the
     bookmarks and All bookmarks; photographed light and dark beside the
     compiled screen 14.

The hook writes what it saw to boring-toolbar-test.txt in the profile.
Only DevTools, UI Automation and PrintWindow of our own windows; nothing is
sent to the OS as input. Not checked here: sizes in pixels (compare the
pictures), and Forget itself (smoke_forget.py).

    python smoke_toolbar.py [--out E:\\tmp\\cui-toolbar\\shots] [--captures FOLDER]

With --captures (or BORING_CAPTURES) each photograph is also saved beside its
compiled screen as <folder>/toolbar/c01-light.png, c01-dark.png, c14-light.png
and c14-dark.png: the real capture on the left, the compiled screen on the
right.

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

import page_checks
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


# Colours of the photographs (Window.dc.html TOKENS): the bar, the ok green
# of the shield's tick, and the faint ink of a disabled arrow (ink3).
BAR_RGB = {"light": (255, 255, 255), "dark": (28, 28, 26)}
OK_RGB = {"light": (26, 127, 85), "dark": (76, 195, 138)}
FAINT_RGB = {"light": (170, 166, 157), "dark": (99, 97, 91)}
TOOLBAR_HEIGHT = 50
BOOKMARKS_HEIGHT = 32


def distance(a, b):
    return sum(abs(x - y) for x, y in zip(a, b))


def measure(path, theme):
    """What a photograph shows: the toolbar's height (the address bar sits
    in its middle), the bar plus the bookmarks bar down to the hairline,
    the back arrow's strongest colour, and ink just before and just after
    the shield's green tick. None when PIL is missing."""
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        bar = BAR_RGB[theme]
        top = next(y for y in range(h) if im.getpixel((3, y)) == bar)
        line = next((y for y in range(top, h) if im.getpixel((3, y)) != bar), h)
        # The address bar's rows (with its focus ring when focused): the
        # first non-bar row, down to the last within 42 of it; bookmarks
        # below the toolbar start further down than that.
        field = [y for y in range(top, min(top + 80, line)) if im.getpixel((300, y)) != bar]
        field = [y for y in field if y <= field[0] + 42] if field else []
        mid = (field[0] + field[-1]) / 2 if field else top
        band = range(top + 4, top + 44)
        arrow = max((im.getpixel((x, y)) for x in range(8, 44) for y in band), key=lambda c: distance(c, bar))
        greens = [x for x in range(w // 2, w) for y in band if distance(im.getpixel((x, y)), OK_RGB[theme]) < 40]
        def inked(x0, x1):
            return sum(1 for x in range(max(0, x0), min(w, x1)) for y in band if distance(im.getpixel((x, y)), bar) > 300)
        before = inked(min(greens) - 14, min(greens) - 2) if greens else None
        after = inked(max(greens) + 2, max(greens) + 40) if greens else None
    return {"toolbar": round(2 * (mid - top + 0.5)), "bars": line - top, "arrow": arrow, "before": before, "after": after}


def check_toolbar_picture(checks, theme, path):
    m = measure(path, theme)
    if m is None:
        print("no PIL: the toolbar photograph is not measured")
        return
    checks(f"{theme}: the toolbar row is {TOOLBAR_HEIGHT} high", abs(m["toolbar"] - TOOLBAR_HEIGHT) <= 1, str(m))
    checks(f"{theme}: the tick comes before the word Protected", m["before"] == 0 and (m["after"] or 0) > 10, str(m))
    checks(f"{theme}: a disabled back arrow is the faint ink", distance(m["arrow"], FAINT_RGB[theme]) <= 18, str(m["arrow"]))


def check_icon_files(checks):
    """Back, forward, reload, the star and the menu dots come from our 2px
    glyph files: the ones 157 really builds them from (see the notes in
    .workflow/scratch/compiled/fix/progress-2.md)."""
    src = os.environ.get("BORING_SRC")
    if not src:
        print("BORING_SRC not set: the icon files are not checked")
        return
    for rel in ("components/vector_icons/back_arrow_chrome_refresh_old.icon",
                "components/vector_icons/forward_arrow_chrome_refresh_old.icon",
                "components/vector_icons/reload_chrome_refresh_old.icon",
                "components/omnibox/browser/vector_icons/star.icon",
                "chrome/app/vector_icons/boring_menu.icon"):
        with contextlib.suppress(OSError):
            text = (Path(src) / rel).read_text(encoding="utf-8")
            checks(f"{rel} is our 2px glyph", "boring" in text.splitlines()[0] and "2 px stroke" in text, text.splitlines()[0])
            continue
        checks(f"{rel} is our 2px glyph", False, "missing")


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
    page_checks.add_captures_option(ap)
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

    def shoot(name, screen, dark):
        """PrintWindow of our own window; with --captures it is also saved
        beside the compiled screen as toolbar/<screen>-<light|dark>.png."""
        hwnd = frame_window(CHROME, under=os.getpid())
        time.sleep(0.8)
        grab(hwnd, str(out / f"{name}.png"))
        print("saved", out / f"{name}.png")
        both = page_checks.save_capture(out / f"{name}.png", "toolbar", screen, dark=dark, folder=args.captures)
        if both:
            print("saved", both)

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
            # The dialog belongs to the browser process, a child of ours.
            for hwnd in browser_windows(os.getpid()):
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
        # Ledger item 43 (JD, Q16): Chromium's own Extensions button stays.
        checks(
            "Chromium's own Extensions button stays on the toolbar",
            any(e[0] == "button" and e[1] == "ExtensionsToolbarButton" for e in report or []),
            str(report),
        )
        shoot("toolbar-light", "c01", False)
        check_toolbar_picture(checks, "light", out / "toolbar-light.png")
        check_icon_files(checks)
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
        shoot("toolbar-dark", "c01", True)
        check_toolbar_picture(checks, "dark", out / "toolbar-dark.png")
        stop()

        # 6. The bookmarks bar: on by default (ledger item 42), and its own
        # setting hides and shows it.
        marks = bookmarks_file(BOOKMARKS)
        fresh = new_profile("bookmarks-default", bookmarks=marks)
        start(fresh)
        names = frame_names()
        checks("a new profile shows the bookmarks bar", all(any(n.startswith(t) for n in names) for t in BOOKMARKS), str(names))
        stop()
        checks(
            "the setting is on by default (nothing turned it off)",
            json.loads((fresh / "Default" / "Preferences").read_text(encoding="utf-8"))
            .get("bookmark_bar", {})
            .get("show_on_all_tabs", True)
            is not False,
        )
        off = new_profile("bookmarks-off", {"bookmark_bar": {"show_on_all_tabs": False}}, marks)
        start(off)
        names = frame_names()
        checks("the setting off hides the bar", not any(n.startswith(t) for t in BOOKMARKS for n in names), str(names))
        stop()
        # Ledger item 32 (JD, Q18): the saved tab groups button is off the
        # bar by default (checked below on every bar); the bar menu's switch
        # writes bookmark_bar.show_tab_groups, and with it on the button is back.
        groups = new_profile(
            "bookmarks-groups", {"bookmark_bar": {"show_on_all_tabs": True, "show_tab_groups": True}}, marks
        )
        start(groups)
        names = frame_names()
        checks("the Tab groups switch on puts the button back on the bar", "Tab groups" in names, str(names))
        stop()
        for theme, extra in (("light", []), ("dark", ["--force-dark-mode"])):
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
            checks(f"{theme}: no Tab groups button on the bar", "Tab groups" not in names, str(names))
            shoot(f"bookmarks-{theme}", "c14", theme == "dark")
            m = measure(out / f"bookmarks-{theme}.png", theme)
            if m:
                checks(
                    f"{theme}: toolbar and bookmarks bar are {TOOLBAR_HEIGHT} + {BOOKMARKS_HEIGHT} high",
                    abs(m["bars"] - TOOLBAR_HEIGHT - BOOKMARKS_HEIGHT) <= 1,
                    str(m),
                )
            stop()
        return checks.result("toolbar")
    finally:
        stop()
        with contextlib.suppress(Exception):
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
