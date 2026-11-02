#!/usr/bin/env python3
"""Check "Forget this site" (the shield's panel) and "Forget this session"
(the app menu).

Everything is local. One HTTP server on 127.0.0.1 plays two sites, named
alpha.localhost and beta.localhost (Chromium resolves *.localhost itself,
and http on localhost is not upgraded by HTTPS-Only).

The panel, the app menu and the question the menu asks are native, so they
are opened and pressed through UI Automation on our own windows, as
smoke_site_panel.py does: it reads names and calls the controls' own
actions (Expand for the shield and the app menu button, Invoke for rows and
buttons) and sends no mouse or keys to the desktop. The pages are driven
with WebDriver.

Run one is an earlier session: it leaves a cookie on both sites and visits
each once. Run two is the session under test, on the same profile:

  - both sites get a cookie, local storage, a cached file, a notifications
    permission and a history entry
  - Forget this site on alpha asks first, Cancel keeps everything, Forget
    clears alpha's cookies, storage, cache and permission (the earlier
    cookie too), reloads the tab, and leaves beta untouched
  - Forget this session asks once, closes every tab, clears what this
    session made on both sites, its history included, keeps what was there
    before the session started (the earlier cookie, the earlier history
    entry) and leaves one new tab

Usage: python smoke_forget.py [--shots DIR] [--dark]
  --shots photographs the panel row, the question in the panel and the
  question the menu asks into DIR, with --dark in the dark theme.
"""

import argparse
import ctypes
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

from capture_native import frame_window, grab
from drive import CHROME, Browser, free_port
from smoke_site_panel import (
    Window,
    browser_windows,
    find_panel,
    poll,
    press_shield,
    switch_to,
    user32,
    window_handles,
)

ALPHA = "alpha.localhost"
BETA = "beta.localhost"
QUESTION = "Forget this site? You will be signed out of it."
MENU_ROW = "Forget this session"
DIALOG_TITLE = "Forget this session?"

# The pages carry the host and the path in their title, so the history
# page can say which visit it is listing.
PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Forget test %(site)s %(label)s</title>
<h1>Forget test %(site)s %(label)s</h1>
"""


class Handler(BaseHTTPRequestHandler):
    # How many times /cached.txt reached the server, per host: a second
    # fetch that is answered from the browser's cache does not count.
    hits = {}
    lock = threading.Lock()

    def do_GET(self):
        host = self.headers.get("Host", "").split(":")[0]
        path = self.path.split("?", 1)[0]
        if path == "/cached.txt":
            with Handler.lock:
                Handler.hits[host] = Handler.hits.get(host, 0) + 1
            body = b"cached"
            kind = "text/plain"
            cache = "max-age=3600"
        else:
            label = path.strip("/") or "home"
            body = (PAGE % {"site": host.split(".")[0], "label": label}).encode()
            kind = "text/html; charset=utf-8"
            cache = "no-store"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

    @classmethod
    def count(cls, host):
        with cls.lock:
            return cls.hits.get(host, 0)


# --- pages ---------------------------------------------------------------

STATE_JS = "return {cookie: document.cookie, k: localStorage.getItem('k')}"

FETCH_TWICE = """
const done = arguments[arguments.length - 1];
fetch('/cached.txt').then(r => r.text())
  .then(() => fetch('/cached.txt')).then(r => r.text())
  .then(() => done(true), e => done(String(e)));
"""

FETCH_ONCE = """
const done = arguments[arguments.length - 1];
fetch('/cached.txt').then(r => r.text()).then(() => done(true), e => done(String(e)));
"""

# What the settings page itself says about the site's notifications permission:
# the stored setting, not what a page is told, which also depends on the
# secure context and the prompt rules.
SETTING_JS = """
const done = arguments[arguments.length - 1];
import('chrome://resources/js/cr.js')
  .then(m => m.sendWithPromise('getOriginPermissions', arguments[0], ['notifications']))
  .then(r => done(r.length ? r[0].setting + '/' + r[0].source : 'none'),
        e => done('error: ' + e));
"""

# All the text of a page, shadow trees included: the history page keeps
# its entries in them.
ALL_TEXT = """
function texts(root, out) {
  for (const el of root.querySelectorAll('*')) {
    if (el.shadowRoot) {
      texts(el.shadowRoot, out);
      out.push(el.shadowRoot.textContent || '');
    }
  }
  return out;
}
return document.body.textContent + '\\n' + texts(document, []).join('\\n');
"""


def safe(fn, default=None):
    """fn(), or `default` while the page cannot answer (a reload, a
    window that is closing)."""
    try:
        return fn()
    except Exception:
        return default


def state(b):
    return safe(lambda: b.run(STATE_JS)) or {"cookie": None, "k": None}


def seed(b, url):
    """Visit `url` and leave a cookie, local storage and a cached file."""
    b.get(url)
    b.run(
        "document.cookie = 's1=1; Max-Age=3600; path=/';"
        "localStorage.setItem('k', 'v'); return true"
    )
    return b.run_async(FETCH_TWICE)


def settings_page(b, origin):
    """Open the site's settings page, once it can take WebUI messages."""
    b.get("chrome://settings/content/siteDetails?site=" + quote(origin, safe=""))
    return poll(lambda: safe(lambda: b.run("return typeof chrome.send")) == "function")


def notifications_setting(b, origin):
    """'setting/source' of the site's notifications permission, e.g. 'allow/preference'
    or 'ask/default'."""
    if not settings_page(b, origin):
        return "no settings page"
    return safe(lambda: b.run_async(SETTING_JS, [origin]), "no answer")


def allow_notifications(b, origin):
    """Give the site the notifications permission, the way its settings page
    does (WebUI message), without a prompt. Returns what the page then says."""
    if not settings_page(b, origin):
        return "no settings page"
    b.run(
        "chrome.send('setOriginPermissions', [arguments[0], 'notifications', 'allow'])",
        [origin],
    )
    time.sleep(1.0)
    return safe(lambda: b.run_async(SETTING_JS, [origin]), "no answer")


def history_text(b, marker):
    """The history page's text, once it lists `marker`; None if it never does."""
    b.get("chrome://history")
    return poll(
        lambda: (lambda t: t if t and marker in t else None)(
            safe(lambda: b.run(ALL_TEXT))
        ),
        timeout=20,
    )


def new_tab(b):
    handle = b._req("POST", f"/session/{b.sid}/window/new", {"type": "tab"})["value"]
    switch_to(b, handle["handle"])


# --- native windows -------------------------------------------------------


def names_of(hwnd):
    try:
        with Window(hwnd) as w:
            return w.names()
    except OSError:
        return []


def window_with(b, frame, wanted, timeout=10.0):
    """(hwnd, names) of the first window of ours, the frame included,
    whose names satisfy `wanted`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd in browser_windows(b.proc.pid):
            names = names_of(hwnd)
            if wanted(names):
                return hwnd, names
        time.sleep(0.3)
    return None, []


def press(hwnd, name, actions=None):
    with Window(hwnd) as w:
        if actions is None:
            return w.press(lambda n: n == name)
        return w.press(lambda n: n == name, actions)


def big_windows(b):
    """How many browser windows are open: our top level windows that are
    not a tooltip or a menu."""
    from ctypes import wintypes

    count = 0
    for hwnd in browser_windows(b.proc.pid):
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        if r.right - r.left > 400 and r.bottom - r.top > 300:
            count += 1
    return count


def watch_closing(b, before, timeout=30.0):
    """Wait for the old tabs to go and one new one to be there, saying how
    the counts moved. The new handles, or None at the timeout."""
    start = time.time()
    last = None
    while time.time() - start < timeout:
        handles = safe(lambda: window_handles(b), [])
        old = len(set(handles) & before)
        seen = (len(handles), old, big_windows(b))
        if seen != last:
            print(
                f"  t={time.time() - start:4.1f}s tabs={seen[0]} "
                f"of which old={seen[1]} windows={seen[2]}"
            )
            last = seen
        if len(handles) == 1 and not old:
            return handles
        time.sleep(0.5)
    return None


def dump_tabs(b):
    """Say where each tab is, for a failure."""
    for handle in safe(lambda: window_handles(b), []):
        try:
            switch_to(b, handle)
            print(f"  tab {handle[:8]}: {b.current_url()}")
        except Exception as e:
            print(f"  tab {handle[:8]}: unreadable ({e!r})"[:200])


def is_app_menu_button(name):
    return name.startswith("Customize and control") or name in (
        "Chromium",
        "Boring Browser",
        "Chrome",
    )


# --- the test -------------------------------------------------------------


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

    def shot(hwnd, name):
        if opts.shots and hwnd:
            path = os.path.join(opts.shots, f"{name}-{theme}.png")
            w, h = grab(hwnd, path)
            print(f"saved {path} {w}x{h}")

    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def url(host, label):
        return f"http://{host}:{port}/{label}"

    alpha_origin = f"http://{ALPHA}:{port}"
    beta_origin = f"http://{BETA}:{port}"

    # TEST_SWITCH keeps the panel open when its window has no keyboard.
    args = [
        "--boring-shield-panel-test",
        "--disable-background-mode",
        # Chromium's own log, in the profile, with our steps in it.
        "--enable-logging",
        "--vmodule=boring_forget=1",
    ]
    args += ["--window-size=1360,900"]
    if opts.dark:
        args.append("--force-dark-mode")

    try:
        with tempfile.TemporaryDirectory(prefix="forget-") as profile:
            # --- run one: an earlier session -----------------------------
            with Browser(user_data_dir=profile, args=args) as b:
                for host in (ALPHA, BETA):
                    b.get(url(host, "before"))
                    b.run("document.cookie = 'old=1; Max-Age=3600; path=/'; return 1")
                    check(
                        f"earlier session: cookie on {host}",
                        "old=1" in state(b)["cookie"],
                    )
            time.sleep(1.0)

            # --- run two: the session under test -------------------------
            with Browser(user_data_dir=profile, args=args) as b:
                frame = frame_window(CHROME, under=b.proc.pid)

                # What both sites hold before anything is forgotten.
                for host in (ALPHA, BETA):
                    check(
                        f"{host}: a cookie, storage and a cached file are set",
                        seed(b, url(host, "during")) is True
                        and "s1=1" in state(b)["cookie"]
                        and state(b)["k"] == "v"
                        and Handler.count(host) == 1,
                        f"requests for the cached file: {Handler.count(host)}",
                    )
                    allowed = allow_notifications(b, f"http://{host}:{port}")
                    b.get(url(host, "during"))
                    check(
                        f"{host}: notifications are allowed",
                        allowed.startswith("allow/"),
                        allowed,
                    )
                text = history_text(b, f"Forget test {ALPHA.split('.')[0]} during")
                check(
                    "history lists this session's visits and the earlier one",
                    bool(text)
                    and "Forget test beta during" in text
                    and "Forget test alpha before" in text,
                )

                # -- Forget this site, on alpha
                b.get(url(ALPHA, "during"))
                time_origin = b.run("return performance.timeOrigin")
                try:
                    press_shield(frame)
                except Exception as e:
                    print(f"  could not press the shield: {e!r}")
                hwnd, names = find_panel(b, frame)
                check("the shield opens its panel", bool(hwnd))
                check(
                    "the panel has a Forget this site row", "Forget this site" in names
                )
                check(
                    "and no question yet",
                    QUESTION not in names,
                )
                time.sleep(1.0)
                shot(hwnd, "forget-row")

                if hwnd:
                    press(hwnd, "Forget this site")
                    names = poll(
                        lambda: (lambda ns: ns if QUESTION in ns else None)(
                            names_of(hwnd)
                        ),
                        timeout=5,
                    ) or names_of(hwnd)
                    check(
                        "pressing the row asks first, in the panel", QUESTION in names
                    )
                    check(
                        "with Forget and Cancel",
                        "Forget" in names and "Cancel" in names,
                    )
                    time.sleep(0.6)
                    shot(hwnd, "forget-confirm")
                    check(
                        "nothing is deleted while it asks",
                        "s1=1" in state(b)["cookie"] and state(b)["k"] == "v",
                    )

                    press(hwnd, "Cancel")
                    names = poll(
                        lambda: (lambda ns: ns if QUESTION not in ns else None)(
                            names_of(hwnd)
                        ),
                        timeout=5,
                    ) or names_of(hwnd)
                    check(
                        "Cancel puts the row back",
                        "Forget this site" in names and QUESTION not in names,
                    )
                    check(
                        "and keeps everything",
                        "s1=1" in state(b)["cookie"] and state(b)["k"] == "v",
                    )

                    press(hwnd, "Forget this site")
                    poll(lambda: QUESTION in names_of(hwnd), timeout=5)
                    press(hwnd, "Forget")

                reloaded = poll(
                    lambda: (
                        safe(lambda: b.run("return performance.timeOrigin"))
                        not in (None, time_origin)
                    ),
                    timeout=20,
                )
                check("Forget reloads the tab", bool(reloaded))
                cleared = poll(
                    lambda: (
                        lambda s: "s1" not in (s["cookie"] or "") and s["k"] is None
                    )(state(b)),
                    timeout=10,
                )
                s = state(b)
                check(
                    "alpha: cookies and storage are gone, the earlier cookie too",
                    bool(cleared) and "old" not in (s["cookie"] or ""),
                    str(s),
                )
                loc = notifications_setting(b, alpha_origin)
                check(
                    "alpha: notifications are no longer allowed",
                    not loc.startswith("allow/"),
                    loc,
                )
                b.get(url(ALPHA, "during"))
                b.run_async(FETCH_ONCE)
                check(
                    "alpha: the cache is gone, the file came from the server again",
                    Handler.count(ALPHA) == 2,
                    str(Handler.count(ALPHA)),
                )

                loc = notifications_setting(b, beta_origin)
                check(
                    "beta: notifications are still allowed",
                    loc.startswith("allow/"),
                    loc,
                )
                b.get(url(BETA, "during"))
                s = state(b)
                check(
                    "beta: cookies and storage are untouched",
                    "s1=1" in s["cookie"] and "old=1" in s["cookie"] and s["k"] == "v",
                    str(s),
                )
                b.run_async(FETCH_ONCE)
                check(
                    "beta: the cache is untouched",
                    Handler.count(BETA) == 1,
                    str(Handler.count(BETA)),
                )

                # -- Forget this session
                new_tab(b)
                b.get(url(BETA, "second-tab"))
                before = set(window_handles(b))
                check("two tabs are open", len(before) == 2, str(len(before)))
                # alpha has data again, so the session has something to forget.
                b.get(url(ALPHA, "during-again"))
                b.run(
                    "document.cookie = 's2=1; Max-Age=3600; path=/';"
                    "localStorage.setItem('k', 'v'); return 1"
                )

                try:
                    with Window(frame) as w:
                        how = w.press(is_app_menu_button)
                    print(f"  app menu button pressed by {how}")
                except Exception as e:
                    print(f"  could not press the app menu button: {e!r}")
                    with Window(frame) as w:
                        print(f"  frame names: {w.names()[:60]}")
                menu, names = window_with(b, frame, lambda ns: MENU_ROW in ns)
                check("the app menu has Forget this session", bool(menu))
                if menu:
                    press(menu, MENU_ROW)
                dialog, names = window_with(
                    b, frame, lambda ns: DIALOG_TITLE in ns and "Cancel" in ns
                )
                check("the menu row asks once, with a dialog", bool(dialog))
                check("with Forget and Cancel", "Forget" in names and "Cancel" in names)
                time.sleep(0.8)
                shot(dialog, "fire-confirm")
                check("nothing is closed while it asks", len(window_handles(b)) == 2)
                if dialog:
                    press(dialog, "Forget")

                # The window the driver was on is closed; wait for the new one.
                after = watch_closing(b, before)
                check(
                    "every tab is closed and one new tab is left",
                    bool(after),
                    str(safe(lambda: window_handles(b))),
                )
                if not after:
                    dump_tabs(b)
                if after:
                    switch_to(b, after[0])
                    nt = b.current_url()
                    check(
                        "the new tab is the new tab page",
                        "newtab" in nt or nt.startswith("chrome"),
                        nt,
                    )
                    check(
                        "and there is one window",
                        big_windows(b) == 1,
                        str(big_windows(b)),
                    )

                    text = history_text(b, "Forget test alpha before")
                    check(
                        "history from this session is gone",
                        bool(text)
                        and "Forget test alpha during" not in text
                        and "Forget test beta during" not in text
                        and "second-tab" not in text
                        and "during-again" not in text,
                    )
                    check(
                        "and the earlier session's history is kept",
                        bool(text) and "Forget test beta before" in text,
                    )

                    s = None
                    for host in (ALPHA, BETA):
                        b.get(url(host, "after"))
                        s = state(b)
                        gone = (
                            "s1" not in (s["cookie"] or "")
                            and "s2" not in (s["cookie"] or "")
                            and s["k"] is None
                        )
                        check(
                            f"{host}: this session's cookies and storage are gone",
                            gone,
                            str(s),
                        )
                    b.get(url(BETA, "after"))
                    check(
                        "beta: the cookie from before the session is kept",
                        "old=1" in state(b)["cookie"],
                        str(state(b)),
                    )
                    b.run_async(FETCH_ONCE)
                    check(
                        "beta: this session's cache is gone",
                        Handler.count(BETA) == 2,
                        str(Handler.count(BETA)),
                    )

            # What the browser said about the steps of Forget this session.
            log = os.path.join(profile, "chrome_debug.log")
            if os.path.exists(log):
                with open(log, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if "boring_forget" in line:
                            print("  log: " + line.strip()[-160:])
    finally:
        server.shutdown()

    if failures:
        print(f"\n{len(failures)} failed: " + "; ".join(failures))
        return 1
    print("PASS: Forget this site and Forget this session do what they say")
    return 0


if __name__ == "__main__":
    sys.exit(main())
