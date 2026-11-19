#!/usr/bin/env python3
"""Smoke test: Settings and Extensions can be pinned to the toolbar, and the
toolbar's right click menu offers "Customize toolbar".

Several launches of one scratch profile, started straight from chrome.exe:

  1. A new profile. The toolbar's buttons are the stock set. The picker
     lists exactly the expected rows: Settings and Extensions, and not
     Translate, Cast, Send to your device or any other Google feature.
  2. Same profile. Both are ticked in the picker, which pins them. After
     a restart both buttons are on the toolbar, enabled, with plain
     tooltips, and a right click on a pinned button opens that button's
     own menu, not ours.
  3. Same profile, dark. Both are still pinned after the restart, and
     unticking them removes them again.
  4. The test hook --boring-toolbar-test=<step> (boring_toolbar_menu.cc)
     runs what the menu item and the two pinned buttons run. The panel
     the item opens is read whole: rows, headings, title, every visible
     text, and the overview behind its back button, which must show no
     Google sections.
  5. A right click on empty toolbar space, sent through the window's own
     root view, opens our menu with its one item. The hook reports the
     menu's window, which is photographed. While a tab's first page is
     still loading, the item is greyed out.
  6. Translate, Cast and Send to your device pinned by hand, with a French
     page from a local server in front: Translate and Send stay off though
     chrome://translate-internals shows the page read as French, and no
     Cast button is made.
  7. With --disable-extensions only the Extensions button is off; with
     incognito forced through the profile's pref both are off, and the
     incognito window has no toolbar menu.

The hook writes what it saw to boring-toolbar-test.txt in the profile.
Only DevTools and PrintWindow of our own windows; nothing is sent to the
OS as input. Windows are placed off screen. Not checked: the OS side of a
real mouse click (the press is made inside the browser, after Windows
would have delivered it), and choosing the menu item by click.

    python smoke_quick_buttons.py [--out E:\\tmp\\feat-quick-buttons\\shots]

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import contextlib
import ctypes
import http.server
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from capture_native import frame_window, grab
from drive import CHROME
from smoke_local import Checks
from smoke_memory import close, launch

SETTINGS = "Settings"
EXTENSIONS = "Extensions"
SETTINGS_ID = "kActionOptions"
EXTENSIONS_ID = "kActionManageExtensions"
# What the picker must not offer: each does nothing in this build.
DEAD = ("Translate", "Cast", "Send to your device")
DEAD_IDS = ("kActionShowTranslate", "kActionRouteMedia", "kActionSendTabToSelf")
# Google features that must stay out of the picker too.
ABSENT = (*DEAD, "Google Lens", "Lens", "Search companion", "Chrome Labs", "Contextual tasks")
# The picker's rows, in order, on a new profile.
EXPECTED_ROWS = [
    "Home", "Forward", "Open in split view", "New Incognito window",
    SETTINGS, EXTENSIONS, "Password Manager", "Payments", "Contact info",
    "Bookmarks", "Reading list", "History", "Downloads", "Delete browsing data",
    "Print", "Create QR code", "Reading mode", "Copy link", "Task manager",
    "Developer tools",
]  # fmt: skip
# The picker page's headings and the overview's sections.
EXPECTED_HEADINGS = ["Toolbar", "Navigation", "Your Boring Browser", "Tools and actions"]
EXPECTED_SECTIONS = ["appearance", "toolbarButton"]
# A new profile's toolbar buttons (class names), left to right.
EXPECTED_FRESH = [
    "BackForwardButton", "BackForwardButton", "ReloadButton", "ExtensionsToolbarButton",
    "PinnedActionToolbarButton", "BoringProtectionButton", "BrowserAppMenuButton",
]  # fmt: skip
# The pinned buttons' tooltips. Extensions keeps its action's own text.
TOOLTIPS = {SETTINGS: "Settings", EXTENSIONS: "Manage extensions"}
PINNED = "PinnedActionToolbarButton"
REPORT = "boring-toolbar-test.txt"
# The Translate and Send buttons' tooltips, when pinned by hand.
DEAD_TIPS = ("Translate this page", "Send to your device")
# A web page in French, for Translate and Send to act on.
FR_PAGE = (
    '<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Le jardin</title></head>'
    "<body><h1>Le jardin de ma grand-mère</h1><p>Chaque matin, ma grand-mère sortait dans le jardin"
    " avec son chapeau de paille et son panier. Elle cueillait les tomates les plus mûres, quelques"
    " herbes pour la soupe et des fleurs pour la table de la cuisine. Les oiseaux chantaient dans le"
    " vieux cerisier pendant qu'elle travaillait, et le chat dormait au soleil près de la porte.</p>"
    "<p>Nous passions des heures à l'aider, puis nous mangions ensemble sous les arbres.</p></body></html>"
)
# The rows chrome://translate-internals logs for a page it has read.
DETECTION = (
    "[...document.querySelectorAll('tr')].filter(r => r.textContent.includes(%s))"
    ".map(r => [...r.cells].map(c => c.textContent.trim()))"
)


class PageServer(http.server.ThreadingHTTPServer):
    """A local web server: /fr answers with FR_PAGE after 1.5 s, /slow
    after 15 s, so a page is still loading when the hook acts."""

    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                time.sleep(15 if self.path == "/slow" else 1.5)
                body = FR_PAGE.encode("utf-8")
                with contextlib.suppress(OSError):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

            def log_message(self, *args):
                pass

        super().__init__(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server_address[1]}"
        threading.Thread(target=self.serve_forever, daemon=True).start()

TOOLBAR_JS = (
    "document.querySelector('customize-chrome-app').shadowRoot"
    ".querySelector('customize-chrome-toolbar')"
)
ROWS = (
    "(() => { const tb = " + TOOLBAR_JS + "; if (!tb || !tb.shadowRoot) return null;"
    " return [...tb.shadowRoot.querySelectorAll('.toggle-container')].map(r => ({"
    "name: r.innerText.trim(),"
    "on: !!(r.querySelector('cr-toggle') && r.querySelector('cr-toggle').checked),"
    "icon: !!r.querySelector('img')})); })()"
)
CLICK_ROW = (
    "(() => { const tb = " + TOOLBAR_JS + ";"
    " const row = [...tb.shadowRoot.querySelectorAll('.toggle-container')]"
    ".find(r => r.innerText.trim() === %s); if (!row) return false;"
    " row.click(); return true; })()"
)
# Every visible text and heading of the page, through every shadow root.
PAGE_TEXT = (
    "(() => { const texts = [], heads = [];"
    " const vis = e => !!e && e.checkVisibility({visibilityProperty: true});"
    " const walk = root => { for (const n of root.childNodes) {"
    "  if (n.nodeType === 3) { const t = n.textContent.trim();"
    "   if (t && vis(n.parentElement)) texts.push(t); }"
    "  else if (n.nodeType === 1 && !['STYLE', 'SCRIPT', 'TEMPLATE'].includes(n.tagName)) {"
    "   if (/^H[1-6]$/.test(n.tagName) && vis(n)) heads.push(n.innerText.trim());"
    "   if (n.shadowRoot) walk(n.shadowRoot); walk(n); } } };"
    " walk(document); return {title: document.title, texts, heads}; })()"
)
BACK = (
    "(() => { const h = " + TOOLBAR_JS + ".shadowRoot.querySelector('#heading');"
    " const b = h && h.shadowRoot && h.shadowRoot.querySelector('#backButton');"
    " if (!b) return false; b.click(); return true; })()"
)
SECTIONS = (
    "[...document.querySelector('customize-chrome-app').shadowRoot"
    ".querySelectorAll('#overviewPage > .section')]"
    ".filter(e => e.checkVisibility()).map(e => e.id)"
)


def find_key(node, key):
    """The first value stored under `key`, however deep, or None."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for child in node.values():
            found = find_key(child, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for child in node:
            found = find_key(child, key)
            if found is not None:
                return found
    return None


def pinned_actions(profile):
    """The pinned action ids a closed profile has on disk."""
    path = Path(profile) / "Default" / "Preferences"
    with open(path, encoding="utf-8") as f:
        return find_key(json.load(f), "pinned_actions") or []


def bad_text(text):
    """Visible text that says Chrome or Chromium, or has an em or en dash."""
    return bool(re.search(r"chrom(e|ium)|\u2014|\u2013", text, re.I))


def settings_tab(cdp):
    tab = cdp.open_tab("chrome://settings/appearance", background=False)
    session = cdp.attach(tab)
    cdp.wait_for(session, "!!document.querySelector('settings-ui')", 20)
    time.sleep(1.5)
    return tab, session


def open_picker(cdp):
    """Opens the Customize toolbar panel; returns the panel's session."""
    _tab, session = settings_tab(cdp)
    cdp.evaluate(session, "chrome.send('openCustomizeChromeToolbarSection'); 'sent'")
    return find_panel(cdp)


def rows(cdp, panel):
    return cdp.evaluate(panel, ROWS) or []


def click_row(cdp, panel, name):
    return cdp.evaluate(panel, CLICK_ROW % json.dumps(name))


def shoot(path):
    """PrintWindow of the biggest window of the browser this run started.
    The window is never moved; it was opened off screen."""
    hwnd = frame_window(CHROME, under=os.getpid())
    time.sleep(0.8)
    grab(hwnd, str(path))
    print("saved", path)


def wait_target(cdp, needle, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for t in cdp.send("Target.getTargets")["targetInfos"]:
            if needle in t["url"]:
                return t["url"]
        time.sleep(0.3)
    return None


def parse_report(text):
    """The hook's report as {"hit": str, "ours": str, "hwnd": int,
    "items": [(label, on)], "buttons": [(class, name, tooltip, on)]}.
    None until its closing "end" line is there."""
    lines = text.splitlines()
    if "end" not in lines:
        return None
    out = {"items": [], "buttons": []}
    for line in lines:
        kind, _, rest = line.partition("\t")
        fields = rest.split("\t")
        if kind == "item":
            out["items"].append((fields[0], fields[-1] == "on"))
        elif kind == "button":
            out["buttons"].append((*fields[:3], fields[-1] == "on"))
        elif kind == "hwnd":
            out["hwnd"] = int(rest)
        elif kind in ("hit", "ours"):
            out[kind] = rest
    return out


def wait_report(profile, timeout=20):
    """Waits for the hook's report in this user data folder."""
    path = Path(profile) / "Default" / REPORT
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            report = parse_report(path.read_text(encoding="utf-8"))
            if report is not None:
                return report
        time.sleep(0.2)
    return None


def page_text(cdp, session):
    return cdp.evaluate(session, PAGE_TEXT) or {"title": "", "texts": [], "heads": []}


def find_panel(cdp):
    """The Customize toolbar panel's session, once its rows are there."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for t in cdp.send("Target.getTargets")["targetInfos"]:
            if "customize-chrome-side-panel" in t["url"]:
                panel = cdp.attach(t["targetId"])
                if cdp.wait_for(panel, "(" + ROWS + " || []).length > 0", 10):
                    return panel
        time.sleep(0.3)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out", default=r"E:\tmp\feat-quick-buttons\shots", help="folder for the photographs"
    )
    args = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    checks = Checks()
    work = Path(tempfile.mkdtemp(prefix="boring-qb-", dir=os.environ.get("TMP", r"E:\tmp")))
    profile = work / "profile"
    profile.mkdir()
    flags = ["--disable-features=CalculateNativeWinOcclusion"]
    proc = cdp = None

    server = PageServer()

    def start(extra=(), where=profile, urls=("about:blank",), background=()):
        nonlocal proc, cdp
        with contextlib.suppress(OSError):
            (Path(where) / "Default" / REPORT).unlink()
        proc, cdp = launch(CHROME, where, [*flags, *extra], urls)
        # chrome:// pages are not opened from the command line.
        for url in background:
            cdp.send("Target.createTarget", url=url, background=True)
        time.sleep(3)

    def stop():
        nonlocal proc, cdp
        if proc:
            close(proc, cdp)
        proc = cdp = None

    def hook(step, where=profile, extra=(), urls=("about:blank",), background=()):
        """Starts the browser with one hook step and returns its report."""
        start([f"--boring-toolbar-test={step}", *extra], where, urls, background)
        return wait_report(where) or {"items": [], "buttons": []}

    def new_profile(name, prefs=None):
        """A new user data folder, with a hand-written Preferences file."""
        where = work / name
        (where / "Default").mkdir(parents=True)
        if prefs:
            (where / "Default" / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")
        return where

    def tabs():
        return {t["url"]: t["targetId"] for t in cdp.send("Target.getTargets")["targetInfos"] if t["type"] == "page"}

    def pinned(report):
        """The pinned buttons by tooltip; their names end in " - pinned"."""
        return {b[2]: b for b in report["buttons"] if b[0] == PINNED}

    def check_panel(panel):
        """The panel the menu item opens, read whole, then its overview."""
        names = [r["name"] for r in rows(cdp, panel)]
        checks("the panel lists exactly the expected rows", names == EXPECTED_ROWS, str(names))
        text = page_text(cdp, panel)
        print("panel title:", text["title"], "headings:", text["heads"])
        checks("the panel headings are the expected ones", text["heads"] == EXPECTED_HEADINGS, str(text["heads"]))
        bad = [t for t in [text["title"], *text["texts"]] if bad_text(t)]
        checks("no panel text or title says Chrome or has a dash", not bad, str(bad))
        checks("the panel goes back to its overview", bool(cdp.evaluate(panel, BACK)))
        time.sleep(1.5)
        sections = cdp.evaluate(panel, SECTIONS) or []
        over = page_text(cdp, panel)
        print("overview sections:", sections, "headings:", over["heads"])
        checks("the overview shows no Google sections", sections == EXPECTED_SECTIONS, str(sections))
        bad = [t for t in over["texts"] if bad_text(t)]
        checks("no overview text says Chrome or has a dash", not bad, str(bad))
        shoot(out / "overview-light.png")

    try:
        # 1. A new profile: the stock toolbar, and the picker has what it should.
        report = hook("buttons")
        print("toolbar on a new profile:", report["buttons"])
        checks("the toolbar lists its buttons", bool(report["buttons"]))
        checks(
            "a new profile has no Settings or Extensions button",
            not set(TOOLTIPS.values()) & set(pinned(report)),
            str(report["buttons"]),
        )
        fresh_classes = [b[0] for b in report["buttons"]]
        checks("a new profile's toolbar is the stock one", fresh_classes == EXPECTED_FRESH, str(fresh_classes))
        panel = open_picker(cdp)
        checks("the picker opens", panel is not None)
        listed = rows(cdp, panel) if panel else []
        names = [r["name"] for r in listed]
        print("picker rows:", names)
        checks("the picker rows are exactly the expected ones", names == EXPECTED_ROWS, str(names))
        for name in ABSENT:
            checks(f"the picker does not offer {name}", name not in names)
        new_rows = [r for r in listed if r["name"] in (SETTINGS, EXTENSIONS)]
        checks(
            "the new rows have an icon",
            len(new_rows) == 2 and all(r["icon"] for r in new_rows),
        )
        checks(
            "nothing is ticked that was not before",
            not any(r["on"] for r in listed if r["name"] in (SETTINGS, EXTENSIONS)),
        )
        shoot(out / "picker-light.png")
        stop()
        pins = pinned_actions(profile)
        print("pinned_actions on a new profile:", pins)
        checks(
            "a new profile pins neither Settings nor Extensions",
            SETTINGS_ID not in pins and EXTENSIONS_ID not in pins,
            str(pins),
        )

        # 2. Tick both in the picker.
        start()
        panel = open_picker(cdp)
        checks("the picker opens again", panel is not None)
        if panel:
            checks("Settings ticks", bool(click_row(cdp, panel, SETTINGS)))
            time.sleep(1)
            checks("Extensions ticks", bool(click_row(cdp, panel, EXTENSIONS)))
            time.sleep(2)
            on = {r["name"]: r["on"] for r in rows(cdp, panel)}
            checks("both rows show as on", on.get(SETTINGS) and on.get(EXTENSIONS), str(on))
            shoot(out / "pinned-light.png")
        stop()
        pins = pinned_actions(profile)
        print("pinned_actions after ticking:", pins)
        checks("both are in the profile's pinned actions", SETTINGS_ID in pins and EXTENSIONS_ID in pins, str(pins))

        # The two buttons are really on the toolbar, enabled, with plain tooltips.
        report = hook("buttons")
        print("pinned buttons after ticking:", list(pinned(report).values()))
        for name in (SETTINGS, EXTENSIONS):
            b = pinned(report).get(TOOLTIPS[name])
            checks(f"the {name} button is on the toolbar and enabled", bool(b and b[3]), str(b))
            checks(
                f"the {name} button's tooltip is short and plain",
                bool(b and b[2]) and len(b[2]) <= 30 and not bad_text(b[2]),
                str(b),
            )
        stop()

        # A right click on a pinned button opens that button's own menu.
        report = hook("pinned-menu")
        print("right click on a pinned button:", report)
        checks(
            "a right click on a pinned button opens its own menu, not ours",
            report.get("hit") == PINNED and report.get("ours") == "0" and len(report["items"]) > 1,
            str(report),
        )
        stop()

        # 3. After a restart they are still there, in dark; untick removes them.
        start(["--force-dark-mode"])
        panel = open_picker(cdp)
        if panel:
            on = {r["name"]: r["on"] for r in rows(cdp, panel)}
            checks("both are still ticked after a restart", on.get(SETTINGS) and on.get(EXTENSIONS), str(on))
            shoot(out / "pinned-dark.png")
            click_row(cdp, panel, SETTINGS)
            time.sleep(1)
            click_row(cdp, panel, EXTENSIONS)
            time.sleep(2)
            on = {r["name"]: r["on"] for r in rows(cdp, panel)}
            checks("unticking turns both off", not on.get(SETTINGS) and not on.get(EXTENSIONS), str(on))
            shoot(out / "unpinned-dark.png")
        else:
            checks("the picker opens after a restart", False)
        stop()
        pins = pinned_actions(profile)
        print("pinned_actions after unticking:", pins)
        checks("neither is pinned after unticking", SETTINGS_ID not in pins and EXTENSIONS_ID not in pins, str(pins))

        # 4. What the menu item and the pinned buttons run. Each in a new
        # profile, so no tab restored from an earlier run can stand in.
        for step, needle, what in (
            ("customize", "customize-chrome-side-panel", "Customize toolbar opens the picker"),
            ("settings", "chrome://settings", "the Settings button opens Settings"),
            ("extensions", "chrome://extensions", "the Extensions button opens Extensions"),
        ):
            fresh = work / f"hook-{step}"
            fresh.mkdir()
            start([f"--boring-toolbar-test={step}"], fresh)
            checks(what, wait_target(cdp, needle) is not None)
            if step == "customize":
                panel = find_panel(cdp)
                checks("the panel it opens is readable", panel is not None)
                if panel:
                    check_panel(panel)
            stop()

        # 5. A right click on empty toolbar space opens our menu.
        fresh = work / "hook-menu"
        fresh.mkdir()
        report = hook("menu", fresh)
        print("right click on empty toolbar space:", report)
        checks(
            "a right click on empty toolbar space opens our menu",
            report.get("ours") == "1" and report["items"] == [("Customize toolbar", True)],
            str(report),
        )
        checks(
            "its item is short and plain",
            bool(report["items"]) and all(len(t) <= 30 and not bad_text(t) for t, _ in report["items"]),
        )
        if report.get("hwnd"):
            time.sleep(0.3)
            grab(report["hwnd"], str(out / "right-click-menu.png"))
            print("saved", out / "right-click-menu.png")
        stop()

        # While a tab's first page is still loading the panel cannot open
        # yet, so the item is there but greyed out.
        report = hook("menu", new_profile("hook-menu-loading"), urls=[server.url + "/slow"])
        print("right click while the first page loads:", report)
        checks(
            "while the first page loads, the item is greyed out",
            report.get("ours") == "1" and report["items"] == [("Customize toolbar", False)],
            str(report),
        )
        stop()

        # 6. Translate, Cast and Send to your device, pinned by hand in an
        # old or edited profile, with a French web page in front. A working
        # build turns Translate on once it reads the page as French, and Send
        # on for any web page (offering sign in when signed out). Here both
        # buttons are made but stay off, and no Cast button is made at all.
        fr = server.url + "/fr"
        fresh = new_profile("hook-dead", {"toolbar": {"pinned_actions": list(DEAD_IDS)}})
        report = hook("buttons", fresh, urls=[fr], background=["chrome://translate-internals"])
        listed_at = (fresh / "Default" / REPORT).stat().st_mtime if report["buttons"] else 0
        dead = {b[2]: b for b in report["buttons"] if b[0] == PINNED and b[2] != "Downloads"}
        print("pinned by hand:", list(dead.values()))
        checks("exactly the Translate and Send buttons are made", sorted(dead) == sorted(DEAD_TIPS), str(dead))
        for tip in DEAD_TIPS:
            checks(f"the {tip} button stays off on a French web page", tip in dead and not dead[tip][3], str(dead.get(tip)))
        open_tabs = tabs()
        state = None
        if fr in open_tabs:
            state = cdp.evaluate(cdp.attach(open_tabs[fr]), "[document.visibilityState, document.documentElement.lang]")
        checks("the French page was loaded and in front", state == ["visible", "fr"], str(state))
        internals = next((t for u, t in open_tabs.items() if u.startswith("chrome://translate-internals")), None)
        log = cdp.evaluate(cdp.attach(internals), DETECTION % json.dumps(fr)) if internals else None
        print("translate-internals rows for the page:", log)
        read = [r for r in log or [] if "fr (French)" in r]
        checks(
            "the browser read the page as French before the buttons were listed",
            bool(read) and datetime.strptime(read[0][0], "%Y-%m-%d %H:%M:%S").timestamp() <= listed_at,
            f"{log} listed at {listed_at}",
        )
        stop()

        # 7. The pinned Settings and Extensions buttons follow their commands.
        # With extensions turned off only Extensions goes off. Where policy
        # forces incognito (set here through the profile's own pref) both go
        # off, and the incognito window gets no toolbar menu.
        pins = {"toolbar": {"pinned_actions": [SETTINGS_ID, EXTENSIONS_ID]}}
        forced = {**pins, "incognito": {"mode_availability": 2}}
        for name, prefs, extra, want in (
            ("no-extensions", pins, ["--disable-extensions"], {SETTINGS: True, EXTENSIONS: False}),
            ("forced-incognito", forced, [], {SETTINGS: False, EXTENSIONS: False}),
        ):
            report = hook("buttons", new_profile(f"hook-{name}", prefs), extra)
            got = {n: pinned(report).get(TOOLTIPS[n]) for n in want}
            print(f"pinned buttons, {name}:", got)
            for n, on in want.items():
                checks(
                    f"{name}: the {n} button is there and {'on' if on else 'off'}",
                    bool(got[n]) and got[n][3] == on,
                    str(got[n]),
                )
            stop()
        report = hook("menu", work / "hook-forced-incognito")
        print("right click in a forced incognito window:", report)
        checks(
            "an incognito window has no toolbar menu",
            report.get("hit") == "ToolbarView" and report.get("ours") == "0" and not report["items"],
            str(report),
        )
        stop()
        return checks.result("quick buttons")
    finally:
        stop()
        server.shutdown()
        with contextlib.suppress(Exception):
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
