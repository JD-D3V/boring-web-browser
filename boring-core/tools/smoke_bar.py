#!/usr/bin/env python3
"""Smoke test: the Bar (ledger item 12, screen C06).

One field for an address, a search, an open tab, a Settings page or a thing
to do. Every typed query goes through the in-process test hook
--boring-bar-test (chrome/browser/ui/views/boring/boring_bar_test.cc), which
types into the Bar, waits for its results and writes boring-bar-test.txt in
the profile: one line per row (group header, title, meta, selected). Nothing
is sent to the OS as input; windows are placed off screen; every launch has
--host-resolver-rules=MAP * ~NOTFOUND so nothing can leave even by mistake.

  1. Light, with a "Weather" tab and a tab whose title is hostile HTML that
     reads like a Do row. "dark" lists the groups Do, Open tabs, Settings,
     Search in that order; "Turn on dark mode" is first and selected; the
     hostile title shows only under Open tabs as plain text; "Appearance:
     light or dark" is under Settings; no row says Chrome. The results page
     (chrome://omnibox-popup.top-chrome, read through DevTools) shows the
     same headers in order and the title as text, not markup, then the two
     key hints; its rows are 38px with 7px corners, the selected one on the
     sel token with the moon glyph and "Enter" (no other row says Enter),
     and headers are 11.5px at 600. Its picture goes beside C06. The net log
     of the run holds no address but our own local server.
  2. Same profile: switching to the hostile tab from Open tabs keeps the
     tab count and the colour scheme.
  2b. Ledger 57: a page open in tab A at http://bank.example.com/ (the
     resolver maps that name to our local server, nothing leaves); in a
     blank tab "bank.example.com" is typed and Enter pressed: the row Enter
     takes is not a search, and the tab shows bank.example.com (tab A, or
     the address opened), never a search address.
  3. Same profile: "dark" then Settings opens chrome://settings/appearance.
  4. Same profile: Enter on "dark" turns dark mode on (Preferences
     browser.theme.color_scheme2 becomes 2), the field shows the page's
     address again, nothing navigated and history has no chrome://boring-bar
     or search entry. "forget" lists Forget but does not select it.
  5. Dark: "dark" offers "Turn on light mode", with the same look on the
     dark sel token; its picture goes beside C06 dark.
  6. Under the Dusk look there is no dark or light row.
  7. --boring-bar-test=keys: Ctrl+K focuses the field with the whole address
     selected and no keyword, and the hint changes from "Ctrl+K" to "Esc to
     close"; Ctrl+E still enters search mode.

Not checked here: the hint read through UI Automation (the hook reads the
label instead), queries typed one letter at a time (net_audit.py), and the
inline-completed case of 2b (the hook sets the whole text at once and a
fresh profile has no typed history to complete from; the same dedup rule
covers it).

    python smoke_bar.py [--out E:\\tmp\\bar-shots] [--captures FOLDER]

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests)
and BORING_ALLOW_HEADFUL=1.
"""

import argparse
import base64
import contextlib
import ctypes
import html
import http.server
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

import page_checks
from capture_native import frame_window, grab
from drive import CHROME
from smoke_local import Checks
from smoke_memory import close, launch

REPORT = "boring-bar-test.txt"
GROUPS = ["Do", "Open tabs", "Settings", "Search"]
HOSTILE = "<b>Turn on dark mode</b>"
POPUP = "omnibox-popup.top-chrome"
BANNED = re.compile(r"\bchrom(e|ium)\b|\u2014", re.IGNORECASE)
# Every host but our own local server goes nowhere (without the EXCLUDE the
# rule also swallowed 127.0.0.1, so the test tabs never loaded).
NO_NETWORK = ["--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"]

# Every text node of the results page in document order, through shadow
# roots, and whether any <b> element holds the hostile title.
POPUP_TEXT = r"""(() => {
  const out = []; let markup = false;
  const walk = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      const t = node.data.trim(); if (t) out.push(t); return;
    }
    if (node.nodeType === Node.ELEMENT_NODE && node.localName === 'b' &&
        node.textContent.includes('Turn on dark mode')) markup = true;
    if (node.shadowRoot) walk(node.shadowRoot);
    for (const child of node.childNodes) walk(child);
  };
  walk(document.documentElement);
  return {texts: out, markup};
})()"""

# The look of the results (screen C06): the selected row, a group header,
# the glyph each Bar row masks its icon with, and whether "Enter" shows.
FOOTER = ["Enter to choose", "Up and Down to move"]
SEL = {False: "rgb(240, 238, 234)", True: "rgb(41, 41, 39)"}  # TOKENS sel
POPUP_LOOK = r"""(() => {
  const all = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      all.push(el); if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  const look = {rows: [], header: null};
  for (const m of all.filter(e => e.localName === 'cr-searchbox-match')) {
    const box = m.shadowRoot.querySelector('.container');
    const icon = m.shadowRoot.querySelector('#icon');
    const iconBox = icon && icon.shadowRoot &&
        icon.shadowRoot.querySelector('#icon');
    const enter = m.shadowRoot.querySelector('#boringEnter');
    const style = getComputedStyle(box);
    // The hint (secondary text, or "Enter") sits at the row's right end.
    const right = box.getBoundingClientRect().right;
    const hints = [m.shadowRoot.querySelector('#secondaryText'), enter]
        .filter(e => e && e.textContent.trim() &&
                getComputedStyle(e).display !== 'none');
    const site = m.shadowRoot.querySelector('#primaryText[boring-site] > .dim');
    look.rows.push({
      selected: m.hasAttribute('selected'),
      height: box.getBoundingClientRect().height,
      background: style.backgroundColor,
      radius: style.borderTopLeftRadius,
      mask: iconBox ? getComputedStyle(iconBox).webkitMaskImage : '',
      enter: !!enter && getComputedStyle(enter).display !== 'none',
      hintGap: hints.map(e => Math.round(right - e.getBoundingClientRect().right)),
      site: site ? {text: site.textContent,
                    width: site.getBoundingClientRect().width} : null,
    });
  }
  const h = all.find(e => e.localName === 'h3' && e.classList.contains('header'));
  if (h) {
    const t = h.querySelector('.text') || h;
    const s = getComputedStyle(t);
    look.header = {size: s.fontSize, weight: s.fontWeight};
  }
  return look;
})()"""


class PageServer(http.server.ThreadingHTTPServer):
    """Two local pages: /weather titled "Weather" and /hostile titled with
    HTML that reads like a Do row. Counts every request it gets."""

    def __init__(self):
        server = self
        self.paths = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                server.paths.append(self.path)
                title = {"/weather": "Weather", "/hostile": HOSTILE, "/": "Bank"}.get(self.path)
                if title is None:
                    self.send_error(404)
                    return
                body = (
                    f"<!doctype html><title>{html.escape(title)}</title>"
                    f"<p>{html.escape(title)}</p>"
                ).encode("utf-8")
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


def parse_report(text):
    """{"rows": [(header, title, meta, selected)], "state": {label: {...}},
    "after": {...}, "open": str}; None until the closing "end" line."""
    lines = text.splitlines()
    if "end" not in lines:
        return None
    out = {"rows": [], "state": {}, "after": {}, "open": ""}
    for line in lines:
        kind, _, rest = line.partition("\t")
        fields = rest.split("\t")
        if kind == "row" and len(fields) == 4:
            out["rows"].append((fields[0], fields[1], fields[2], fields[3] == "selected"))
        elif kind == "state":
            out["state"][fields[0]] = dict(f.split("=", 1) for f in fields[1:] if "=" in f)
        elif kind == "after":
            out["after"] = dict(f.split("=", 1) for f in fields if "=" in f)
        elif kind == "open":
            out["open"] = rest
    return out


def wait_report(profile, timeout=40):
    path = Path(profile) / "Default" / REPORT
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            report = parse_report(path.read_text(encoding="utf-8"))
            if report is not None:
                return report
        time.sleep(0.2)
    return {"rows": [], "state": {}, "after": {}, "open": "no report"}


def group_order(rows):
    """The headers in the order they first appear, empty ones left out."""
    seen = []
    for header, *_ in rows:
        if header and header not in seen:
            seen.append(header)
    return seen


def under(rows, title):
    return [r[0] for r in rows if r[1] == title]


def color_scheme(profile):
    """browser.theme.color_scheme2 from Preferences (0 when unset)."""
    with contextlib.suppress(OSError, ValueError):
        prefs = json.loads((Path(profile) / "Default" / "Preferences").read_text(encoding="utf-8"))
        return prefs.get("browser", {}).get("theme", {}).get("color_scheme2", 0)
    return None


def history_urls(profile):
    """Every address in History, read from a copy after the browser closed."""
    src = Path(profile) / "Default" / "History"
    if not src.is_file():
        return []
    copy = src.with_name("History-smoke-copy")
    shutil.copyfile(src, copy)
    con = sqlite3.connect(copy)
    try:
        return [row[0] for row in con.execute("SELECT url FROM urls")]
    finally:
        con.close()


def net_log_hosts(path):
    """Every http(s) host the net log mentions."""
    with contextlib.suppress(OSError):
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        return sorted(set(re.findall(r'"url":"https?://([^/:"]+)', text)))
    return None


def write_prefs(where, prefs):
    (where / "Default").mkdir(parents=True, exist_ok=True)
    (where / "Default" / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\tmp\bar-shots", help="folder for the photographs")
    page_checks.add_captures_option(ap)
    args = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    checks = Checks()
    work = Path(tempfile.mkdtemp(prefix="boring-bar-", dir=os.environ.get("TMP", r"E:\tmp")))
    server = PageServer()
    weather, hostile = server.url + "/weather", server.url + "/hostile"
    proc = cdp = None

    def stop():
        nonlocal proc, cdp
        if proc:
            close(proc, cdp)
        proc = cdp = None

    def hook(where, step, extra=(), urls=("about:blank",)):
        """Starts the browser with one hook step; returns its report. The
        browser stays open until stop()."""
        nonlocal proc, cdp
        with contextlib.suppress(OSError):
            (where / "Default" / REPORT).unlink()
        proc, cdp = launch(CHROME, where, [*NO_NETWORK, f"--boring-bar-test={step}", *extra], urls)
        return wait_report(where)

    def tab_count():
        return sum(1 for t in cdp.send("Target.getTargets")["targetInfos"] if t["type"] == "page")

    def popup_session():
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for t in cdp.send("Target.getTargets")["targetInfos"]:
                if POPUP in t["url"]:
                    return cdp.attach(t["targetId"])
            time.sleep(0.3)
        return None

    def photograph(name, dark):
        """The results page through DevTools and the window by PrintWindow;
        the results page goes beside C06."""
        session = popup_session()
        if session:
            shot = cdp.send("Page.captureScreenshot", session, format="png")
            path = out / f"bar-results-{name}.png"
            path.write_bytes(base64.b64decode(shot["data"]))
            print("saved", path)
            saved = page_checks.save_capture(path, "bar", "c06", dark=dark, folder=args.captures)
            if saved:
                print("saved", saved)
        with contextlib.suppress(Exception):
            hwnd = frame_window(CHROME, under=os.getpid())
            grab(hwnd, str(out / f"bar-window-{name}.png"))
        return session

    def check_look(session, dark):
        """Row height, corners, the selected row's sel colour, the header,
        the moon glyph and "Enter" on the selected Do row only."""
        mode = "dark" if dark else "light"
        look = cdp.evaluate(session, POPUP_LOOK) or {"rows": [], "header": None}
        print(f"results look, {mode}:", look)
        rows = look["rows"]
        checks(f"{mode}: every row is 38px high with 7px corners",
               bool(rows) and all(round(r["height"]) == 38 and r["radius"] == "7px" for r in rows),
               str([(r["height"], r["radius"]) for r in rows]))
        selected = [r for r in rows if r["selected"]]
        checks(f"{mode}: one row is selected, on the sel colour",
               len(selected) == 1 and selected[0]["background"] == SEL[dark], str(selected))
        checks(f"{mode}: the selected Do row draws the moon glyph",
               bool(selected) and "boring_bar_moon.svg" in selected[0]["mask"], str(selected))
        checks(f"{mode}: Enter shows on the selected Do row only",
               [r["enter"] for r in rows] == [True] + [False] * (len(rows) - 1),
               str([r["enter"] for r in rows]))
        checks(f"{mode}: every hint sits at its row's right end (10px inside)",
               all(all(g <= 12 for g in r["hintGap"]) for r in rows),
               str([r["hintGap"] for r in rows]))
        sites = [r["site"] for r in rows if r["site"]]
        checks(f"{mode}: an Open tabs row shows its site whole beside the title",
               # The dark step types "light", which matches no open tab.
               (bool(sites) or dark) and all(s["width"] > 20 and s["text"].startswith("127.0.0.1")
                                   for s in sites), str(sites))
        header = look["header"] or {}
        checks(f"{mode}: group headers are 11.5px at weight 600",
               header.get("size") == "11.5px" and header.get("weight") == "600", str(header))

    def no_banned(rows, label):
        bad = [r for r in rows if BANNED.search(" ".join(r[:3]))]
        checks(f"{label}: no row says Chrome or has an em dash", not bad, str(bad))

    try:
        def fresh_light(name):
            # A new profile per step: a reused one restores the last run's tabs.
            where = work / name
            write_prefs(where, {"browser": {"theme": {"color_scheme2": 1}}})
            return where

        light = fresh_light("light")
        tabs = ("about:blank", weather, hostile)
        net_log = work / "net-log.json"

        # 1. The screen's case, light.
        report = hook(light, "dark", [f"--log-net-log={net_log}"], tabs)
        rows = report["rows"]
        print("rows for 'dark':", rows)
        checks("the groups are Do, Open tabs, Settings, Search in that order",
               group_order(rows) == GROUPS, str(group_order(rows)))
        checks("'Turn on dark mode' is first, under Do, and selected",
               bool(rows) and rows[0][:2] == ("Do", "Turn on dark mode") and rows[0][3], str(rows[:1]))
        # An Open tabs row reads "<title> <site>" with "Switch to tab" at the right.
        site = server.url.split("//", 1)[1]
        hostile_rows = [r for r in rows if r[1].startswith(HOSTILE)]
        checks("the hostile title is listed only under Open tabs, as plain text",
               [r[0] for r in hostile_rows] == ["Open tabs"], str(hostile_rows))
        checks("the hostile tab shows its title, then its site, and Switch to tab",
               any(r[1] == f"{HOSTILE} {site}" and r[2] == "Switch to tab" for r in rows),
               str([r[:3] for r in hostile_rows]))
        checks("Settings rows end in Open",
               any(r[0] == "Settings" and r[2] == "Open" for r in rows), str(rows))
        checks("only our own row is titled like a Do row",
               under(rows, "Turn on dark mode") == ["Do"], str(under(rows, "Turn on dark mode")))
        checks("Settings lists Appearance: light or dark",
               "Settings" in under(rows, "Appearance: light or dark"))
        no_banned(rows, "light")
        session = photograph("light", dark=False)
        checks("the results page is there", session is not None)
        if session:
            seen = cdp.evaluate(session, POPUP_TEXT) or {"texts": [], "markup": True}
            heads = [t for t in seen["texts"] if t in GROUPS]
            print("results page headers:", heads)
            checks("the results page shows the headers in order",
                   [h for i, h in enumerate(heads) if h not in heads[:i]] == GROUPS, str(heads))
            checks("the results page shows the hostile title as text",
                   HOSTILE in seen["texts"] and not seen["markup"])
            bad = [t for t in seen["texts"] if BANNED.search(t)]
            checks("no text on the results page says Chrome", not bad, str(bad))
            checks("the results page shows both key hints under the rows",
                   all(f in seen["texts"] for f in FOOTER), str(seen["texts"][-4:]))
            check_look(session, dark=False)
        stop()
        hosts = net_log_hosts(net_log)
        print("hosts in the net log:", hosts)
        checks("the run asked no host but our local server",
               hosts is not None and set(hosts) <= {"127.0.0.1"}, str(hosts))
        checks("our server was asked only for its two pages",
               set(server.paths) <= {"/weather", "/hostile", "/favicon.ico"}, str(server.paths))

        # 2. Switching to the hostile tab runs nothing.
        light2 = fresh_light("light-switch")
        report = hook(light2, "turn on dark;open=Open tabs", urls=tabs)
        time.sleep(1)
        count = tab_count()
        print("after switching:", report["after"], "tabs:", count)
        checks("the open tab row switches to that tab",
               report["after"].get("url", "").endswith("/hostile"), str(report["after"]))
        # No new tab: every tab left is one we opened. Chromium closes the
        # blank tab the switch was made from (about:blank here), so there
        # may be one fewer.
        left = [t["url"] for t in cdp.send("Target.getTargets")["targetInfos"] if t["type"] == "page"]
        checks("switching opens no new tab",
               count <= len(tabs) and all(u in tabs for u in left), f"{count} {left}")
        stop()
        checks("switching to a tab titled like a Do row leaves the scheme alone",
               color_scheme(light2) == 1, str(color_scheme(light2)))

        # 2b. Ledger 57: the address of an open tab, typed, then Enter.
        bank_host = "bank.example.com"
        bank_rules = [f"--host-resolver-rules=MAP {bank_host} 127.0.0.1:{server.server_address[1]}, "
                      "MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"]
        report = hook(fresh_light("light-address"), f"{bank_host};enter", bank_rules,
                      urls=("about:blank", f"http://{bank_host}/"))
        print("rows for the open tab's address:", report["rows"])
        print("after Enter on the address:", report["after"])
        chosen = [r for r in report["rows"] if r[3]]
        checks("the row Enter takes for an open tab's address is not a search",
               len(chosen) == 1 and chosen[0][0] not in ("Search", "Open tabs")
               and "search" not in chosen[0][2].lower(), str(chosen))
        after_url = report["after"].get("url", "")
        after_host = re.match(r"https?://([^/:]+)", after_url)
        checks("Enter on an open tab's address shows that site, never a search address",
               after_host is not None and after_host.group(1) == bank_host, after_url)
        stop()

        # 3. A Settings row opens its page.
        report = hook(fresh_light("light-settings"), "dark;open=Settings", urls=tabs)
        checks("the Settings row opens chrome://settings/appearance",
               report["after"].get("url") == "chrome://settings/appearance", str(report["after"]))
        stop()

        # 4. Enter on the Do row, then a row that may not take Enter.
        light4 = fresh_light("light-enter")
        report = hook(light4, "dark;enter", urls=tabs)
        print("after Enter:", report["after"])
        checks("Enter on the Do row leaves the page where it was",
               report["after"].get("url") == "about:blank", str(report["after"]))
        checks("the field shows the page's address again, not the query",
               report["after"].get("field", "x") != "dark", str(report["after"]))
        stop()
        checks("Enter on 'Turn on dark mode' turns dark mode on",
               color_scheme(light4) == 2, str(color_scheme(light4)))
        # Every light profile of the run, so no step can leave a Do row or a
        # search for 'dark' in history.
        visited = [u for p in (light, light2, light4) for u in history_urls(p)
                   if "boring-bar" in u or "dark" in u.lower()]
        checks("history has no Do row and no search for 'dark'", not visited, str(visited))
        report = hook(light4, "forget", urls=tabs)
        forget = [r for r in report["rows"] if r[0] == "Do" and "Forget" in r[1]]
        checks("'forget' lists Forget this session", bool(forget), str(report["rows"]))
        checks("Forget never takes Enter", forget and not any(r[3] for r in forget), str(forget))
        stop()

        # 5. Dark.
        dark = work / "dark"
        write_prefs(dark, {"browser": {"theme": {"color_scheme2": 2}}})
        # Item 51: only the row's own word takes Enter, so in dark it is
        # "light" (typing "dark" while dark searches, one Down from the row).
        report = hook(dark, "light", ["--force-dark-mode"], tabs)
        rows = report["rows"]
        print("rows for 'light', dark:", rows)
        checks("dark: 'Turn on light mode' is first and selected",
               bool(rows) and rows[0][:2] == ("Do", "Turn on light mode") and rows[0][3], str(rows[:1]))
        checks("dark: the groups are in the same order (no open tab says light)",
               group_order(rows) == [g for g in GROUPS if g != "Open tabs"], str(group_order(rows)))
        no_banned(rows, "dark")
        session = photograph("dark", dark=True)
        if session:
            check_look(session, dark=True)
        stop()

        # 6. Dusk is always dark: no dark or light row.
        dusk = work / "dusk"
        write_prefs(dusk, {"boring": {"appearance": {"look": "dusk"}}})
        report = hook(dusk, "dark", urls=tabs)
        mode_rows = [r for r in report["rows"] if r[0] == "Do" and r[1].endswith("mode")]
        checks("Dusk: no dark or light row", bool(report["rows"]) and not mode_rows, str(report["rows"]))
        stop()

        # 7. Ctrl+K and Ctrl+E.
        report = hook(work / "keys", "keys", urls=(weather,))
        state = report["state"]
        print("keys:", state)
        checks("the hint says Ctrl+K while the field is closed",
               state.get("before", {}).get("hint") == "Ctrl+K", str(state.get("before")))
        k = state.get("ctrl+k", {})
        checks("Ctrl+K focuses the field with the whole address selected",
               k.get("focused") == "yes" and k.get("all_selected") == "yes", str(k))
        checks("Ctrl+K enters no keyword mode", k.get("keyword") == "no", str(k))
        checks("the hint says Esc to close while the field is open", k.get("hint") == "Esc to close", str(k))
        e = state.get("ctrl+e", {})
        checks("Ctrl+E still enters search mode",
               e.get("keyword") == "yes" or e.get("text", "").startswith("?"), str(e))
        stop()
        return checks.result("the Bar")
    finally:
        stop()
        server.shutdown()
        with contextlib.suppress(Exception):
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
