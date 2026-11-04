#!/usr/bin/env python3
"""Smoke test: tabs survive a crash and an update restart, closed windows
can be reopened, and Chromium's own split view is there.

Three launches of one scratch profile, started straight from chrome.exe
(no chromedriver, so no automation switches change what startup does):

  1. A new profile. The "On startup" pref must default to "continue where
     you left off". Open three tabs, wait for the session to reach disk,
     then kill the browser hard (the crash).
  2. Same profile. The session on disk must hold the three tabs, and the
     browser must offer to restore them (Chromium shows its "Restore
     pages?" bubble after a crash; it never restores one by itself, to
     stay out of crash loops, and a bubble button cannot be pressed
     without sending input). A tiny extension then drives the same
     TabRestoreService that Ctrl+Shift+T and History > Recently closed
     read: close a window with two tabs, reopen it. It also joins two
     tabs in a split view with Chromium's own chrome.tabs.createSplit.
     Three more tabs are opened and the browser is closed cleanly, the
     way an update restart closes it.
  3. Same profile again, dark. The three tabs and the split come back by
     themselves, and a pref the user sets stays set.

Only WebDriver-free DevTools and PrintWindow of our own window; nothing
is sent to the OS as input. Windows are placed off screen.

    python smoke_tabs.py [--out E:\\tmp\\feat-tabs]

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import contextlib
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from capture_native import frame_window, grab
from drive import CHROME, OFFSCREEN, require_headful
from smoke_local import Checks
from smoke_memory import Cdp, close

STARTUP_PREF = "session.restore_on_startup"
CONTINUE = 1  # SessionStartupPref::kPrefValueLast
NEW_TAB_PAGE = 5

EXTENSION = {
    "manifest.json": json.dumps(
        {
            "manifest_version": 3,
            "name": "smoke_tabs driver",
            "version": "1.0",
            "permissions": ["tabs", "sessions"],
            "background": {"service_worker": "bg.js"},
        }
    ),
    "bg.js": (
        "chrome.runtime.onInstalled.addListener(() =>\n"
        "  chrome.tabs.create({url: 'page.html'}));\n"
    ),
    "page.html": "<!doctype html><title>driver</title>",
}

# Close a window with two tabs and reopen it, through the session store.
WINDOW_ROUNDTRIP = """(async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const [a, b] = %s;
  // No bounds: the extension API refuses off screen ones, and --window-position
  // already puts every new window of this browser off screen.
  const w = await chrome.windows.create({url: [a, b], focused: false});
  await wait(2500);
  await chrome.windows.remove(w.id);
  await wait(1000);
  const closed = await chrome.sessions.getRecentlyClosed();
  const entry = closed.find(s => s.window && s.window.tabs.length === 2);
  if (!entry) return {listed: false, count: closed.length};
  await chrome.sessions.restore(entry.window.sessionId);
  await wait(2000);
  const all = await chrome.windows.getAll({populate: true});
  const back = all.find(x => x.id !== w.id &&
      x.tabs.some(t => (t.url || t.pendingUrl || '').startsWith(a)) &&
      x.tabs.some(t => (t.url || t.pendingUrl || '').startsWith(b)));
  const result = {listed: true, reopened: !!back, tabs: back ? back.tabs.length : 0,
                  left: back ? back.left : null, top: back ? back.top : null};
  // Out of the way, so the photographs below are of the first window.
  if (back) await chrome.windows.remove(back.id);
  return result;
})()"""

# Two tabs in one split view, then bring the split to the front.
SPLIT = """(async () => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const [a, b] = %s;
  const here = await chrome.tabs.getCurrent();
  const t1 = await chrome.tabs.create({url: a, windowId: here.windowId, active: false});
  const t2 = await chrome.tabs.create({url: b, windowId: here.windowId, active: false});
  await wait(1500);
  const split = await chrome.tabs.createSplit([t1.id, t2.id]);
  await chrome.tabs.update(t1.id, {active: true});
  await wait(500);
  const x = await chrome.tabs.get(t1.id);
  const y = await chrome.tabs.get(t2.id);
  return {made: Number.isInteger(split), same: !!x.splitViewId && x.splitViewId === y.splitViewId};
})()"""


# The split view ids of the two tabs, as the browser sees them now.
SPLIT_STATE = """(async () => {
  const [a, b] = %s;
  const all = await chrome.tabs.query({});
  const x = all.find(t => (t.url || t.pendingUrl || '').startsWith(a));
  const y = all.find(t => (t.url || t.pendingUrl || '').startsWith(b));
  return {a: x ? x.splitViewId : null, b: y ? y.splitViewId : null};
})()"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        name = (self.headers.get("Host") or "").split(":")[0].split(".")[0]
        data = f"<!doctype html><title>{name}</title><p>{name}</p>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def launch(profile, extra):
    require_headful()
    port_file = profile / "DevToolsActivePort"
    if port_file.exists():
        port_file.unlink()
    proc = subprocess.Popen(
        [
            CHROME,
            f"--user-data-dir={profile}",
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-boring-updates",
            "--disable-boring-list-updates",
            "--window-position=" + OFFSCREEN,
            "--window-size=1200,850",
            "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion",
            *extra,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 60
    while not port_file.exists() or port_file.stat().st_size == 0:
        if time.monotonic() > deadline or proc.poll() is not None:
            proc.kill()
            raise RuntimeError("the browser did not open DevTools")
        time.sleep(0.1)
    port, path = port_file.read_text().split()[:2]
    return proc, Cdp(f"ws://127.0.0.1:{port}{path}")


def hard_kill(proc):
    """The crash: no shutdown, no chance to save anything more."""
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    with contextlib.suppress(Exception):
        proc.wait(15)


def page_urls(cdp):
    return [
        t["url"]
        for t in cdp.send("Target.getTargets")["targetInfos"]
        if t["type"] == "page"
    ]


def wait_urls(cdp, wanted, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        urls = page_urls(cdp)
        if all(any(u.startswith(w) for u in urls) for w in wanted):
            return True
        time.sleep(0.3)
    return False


def crash_offer(cdp, timeout=20):
    """Startup.CrashBubbleShown as the browser recorded it this run: one
    sample, true, when it found the last session ended badly and showed
    its "Restore pages?" bubble."""
    deadline = time.monotonic() + timeout
    seen = {}
    while time.monotonic() < deadline:
        try:
            seen = cdp.send("Browser.getHistogram", name="Startup.CrashBubbleShown")[
                "histogram"
            ]
            if seen.get("count"):
                break
        except RuntimeError:
            pass  # not recorded yet
        time.sleep(0.3)
    return {k: seen.get(k) for k in ("count", "sum")}


def run_js(cdp, session, expression):
    """A failed script is a failed check, not the end of the run."""
    try:
        return cdp.evaluate(session, expression) or {}
    except RuntimeError as e:
        return {"error": str(e)[:300]}


def get_pref(cdp, name):
    tab = cdp.open_tab("chrome://settings/", background=False)
    session = cdp.attach(tab)
    try:
        cdp.wait_for(session, "!!(window.chrome && chrome.settingsPrivate)")
        return cdp.evaluate(
            session,
            f"new Promise(r => chrome.settingsPrivate.getPref('{name}', p => r(p.value)))",
        )
    finally:
        cdp.detach(session)
        cdp.send("Target.closeTarget", targetId=tab)


def set_pref(cdp, name, value):
    tab = cdp.open_tab("chrome://settings/", background=False)
    session = cdp.attach(tab)
    try:
        cdp.wait_for(session, "!!(window.chrome && chrome.settingsPrivate)")
        return cdp.evaluate(
            session,
            f"new Promise(r => chrome.settingsPrivate.setPref('{name}', {json.dumps(value)}, '', ok =>"
            f" chrome.settingsPrivate.getPref('{name}', p => r([ok, p.value]))))",
        )
    finally:
        cdp.detach(session)
        cdp.send("Target.closeTarget", targetId=tab)


def extension_page(cdp, timeout=30):
    """The driver extension's page, once it is one of the tabs."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for t in cdp.send("Target.getTargets")["targetInfos"]:
            if t["type"] == "page" and t["url"].endswith("/page.html"):
                return t["targetId"]
        time.sleep(0.3)
    return None


def wait_marked_open(profile, timeout=40):
    """Chromium marks a session as open (exit_type "Crashed", cleared by a
    clean exit) in the profile's Preferences, and writes the file some
    seconds later. A kill before that looks like a clean exit, not a crash."""
    path = profile / "Default" / "Preferences"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            if re.search(r'"exit_type"\s*:\s*"Crashed"', path.read_text("utf-8")):
                return True
        time.sleep(0.5)
    return False


def session_bytes(profile):
    out = b""
    folder = profile / "Default" / "Sessions"
    for f in folder.glob("*") if folder.exists() else []:
        out += f.read_bytes()
    return out


def shoot(path):
    """PrintWindow of the biggest window of the browser this run started.
    The window is never moved; it was opened off screen."""
    hwnd = frame_window(CHROME, under=os.getpid())
    time.sleep(0.8)
    grab(hwnd, str(path))
    print("saved", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\tmp\feat-tabs", help="folder for the photographs")
    args = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    checks = Checks()
    work = Path(tempfile.mkdtemp(prefix="boring-tabs-", dir=os.environ.get("TMP")))
    profile = work / "profile"
    extension = work / "driver"
    extension.mkdir()
    for name, text in EXTENSION.items():
        (extension / name).write_text(text, encoding="utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def url(name):
        return f"http://{name}.localhost:{server.server_port}/"

    crash_tabs = [url(f"crash{n}") for n in (1, 2, 3)]
    window_tabs = [url("closed1"), url("closed2")]
    split_tabs = [url("split1"), url("split2")]
    restart_tabs = [url(f"restart{n}") for n in (1, 2, 3)]
    proc = None
    try:
        # 1. A new profile, three tabs, then the crash.
        proc, cdp = launch(profile, [])
        time.sleep(2)
        checks(
            "a new profile continues where you left off",
            get_pref(cdp, STARTUP_PREF) == CONTINUE,
        )
        for u in crash_tabs:
            cdp.open_tab(u, background=False)
        checks("three tabs open", wait_urls(cdp, crash_tabs))
        time.sleep(6)  # the session is written a couple of seconds after a change
        checks("the open session is marked on disk", wait_marked_open(profile))
        hard_kill(proc)
        saved = session_bytes(profile)
        checks(
            "the crashed session holds all three tabs",
            all(f"crash{n}.localhost".encode() in saved for n in (1, 2, 3)),
        )

        # 2. The relaunch after the crash.
        # chrome.tabs.createSplit is behind a flag of its own (the split view
        # itself is not); only this test turns it on, to drive the split.
        proc, cdp = launch(
            profile,
            [f"--load-extension={extension}", "--enable-features=ApiTabsSplitView"],
        )
        shown = crash_offer(cdp)
        checks(
            "after a crash the browser offers to restore the tabs",
            shown.get("count") == 1 and shown.get("sum") == 1,
            str(shown),
        )

        driver = extension_page(cdp)
        checks("the driver extension loaded", bool(driver))
        if driver:
            ds = cdp.attach(driver)
            res = run_js(cdp, ds, WINDOW_ROUNDTRIP % json.dumps(window_tabs))
            checks(
                "a closed window with two tabs is listed as recently closed",
                bool(res.get("listed")),
                str(res),
            )
            checks(
                "that window reopens with both tabs",
                bool(res.get("reopened")) and res.get("tabs") == 2,
                str(res),
            )
            checks(
                "and it reopens off screen, not on the desktop",
                (res.get("left") or 0) < -1000 and (res.get("top") or 0) < -1000,
                str(res),
            )
            res = run_js(cdp, ds, SPLIT % json.dumps(split_tabs))
            checks(
                "two tabs join in Chromium's own split view",
                bool(res.get("made")) and bool(res.get("same")),
                str(res),
            )
            cdp.detach(ds)
            time.sleep(1)
            shoot(out / "split-light.png")
        for u in restart_tabs:
            cdp.open_tab(u, background=False)
        checks("three more tabs open", wait_urls(cdp, restart_tabs))
        time.sleep(6)
        close(proc, cdp)  # the way an update closes the browser
        proc = None

        # 3. The restart.
        proc, cdp = launch(
            profile,
            [
                "--force-dark-mode",
                f"--load-extension={extension}",
                "--enable-features=ApiTabsSplitView",
            ],
        )
        checks(
            "tabs come back after a clean restart",
            wait_urls(cdp, restart_tabs, timeout=30),
        )
        checks("the split view tabs come back too", wait_urls(cdp, split_tabs))
        # A restored tab loads when it is shown: show the driver, ask it
        # whether the two tabs are still one split view, then show them.
        driver = extension_page(cdp)
        if driver:
            cdp.show(driver)
            ds = cdp.attach(driver)
            cdp.wait_for(ds, "!!(window.chrome && chrome.tabs && chrome.tabs.query)")
            res = run_js(cdp, ds, SPLIT_STATE % json.dumps(split_tabs))
            checks(
                "and they are still one split view",
                bool(res.get("a")) and res.get("a") == res.get("b"),
                str(res),
            )
            cdp.detach(ds)
        cdp.show(cdp.find_tab(split_tabs[0]))
        time.sleep(2)
        shoot(out / "split-dark.png")
        ok, value = set_pref(cdp, STARTUP_PREF, NEW_TAB_PAGE)
        checks("a startup choice the user makes sticks", bool(ok) and value == NEW_TAB_PAGE)
    finally:
        if proc and proc.poll() is None:
            hard_kill(proc)
        server.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    return checks.result("tabs survive a crash and a restart; closed windows and split view work")


if __name__ == "__main__":
    sys.exit(main())
