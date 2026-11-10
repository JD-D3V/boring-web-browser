#!/usr/bin/env python3
"""Check "Stop screen takeovers" in the real build.

A local stand-in for a tech support scam page (testdata/takeover_scam.html)
goes fullscreen, locks the keyboard, loops alarm audio, sets a leave-page
prompt and loops alert(). The browser must:
  - leave fullscreen on a single Esc, with the keyboard locked either way
  - trip, replace the page with chrome://boring-takeover, and close the tab
    from the one button on it, with no leave-page prompt in the way
Each way a page locks the browser has its own named check: dialogs
(the fourth in ten seconds is not shown, and none blocks the tab once it
trips), alarm audio, pointer lock, keyboard lock and the leave-page
prompt. The page tells this script what it held, through /__report
requests (see testdata/takeover_scam.html), because the page is replaced
before a test could ask it. A check the headless browser cannot exercise
prints SKIP with the reason; it is never counted as passed.
A page with a normal video (testdata/takeover_video.html) must go
fullscreen, keep playing and not trip, even though it also locks the
keyboard and adds history entries by itself.

Input goes through DevTools (Input.dispatch*), never to the desktop, and the
browser runs headless so fullscreen cannot cover a real display.
"""

import functools
import http.server
import sys
import threading
from urllib.parse import parse_qs, urlsplit
import time
from pathlib import Path

from drive import Browser, free_port

DATA = Path(__file__).resolve().parent / "testdata"
GET_ME_OUT = "chrome://boring-takeover/"


REPORTS = []  # (time, key, value) from the test pages, see takeover_scam.html


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if not self.report():
            super().do_GET()

    def do_POST(self):  # noqa: N802
        if not self.report():
            self.send_error(404)

    def report(self):
        parts = urlsplit(self.path)
        if parts.path != "/__report":
            return False
        q = parse_qs(parts.query)
        REPORTS.append((time.time(), q["k"][0], q["v"][0]))
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def log_message(self, *args):
        pass


def reports(key):
    return [(t, v) for t, k, v in REPORTS if k == key]


def serve():
    handler = functools.partial(Handler, directory=str(DATA))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Tab:
    def __init__(self, b):
        self.b = b

    def cdp(self, cmd, params):
        return self.b._req(
            "POST",
            f"/session/{self.b.sid}/goog/cdp/execute",
            {"cmd": cmd, "params": params},
        )

    def click(self, x, y):
        for kind in ("mousePressed", "mouseReleased"):
            self.cdp(
                "Input.dispatchMouseEvent",
                {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
            )

    def esc(self):
        key = {
            "key": "Escape",
            "code": "Escape",
            "windowsVirtualKeyCode": 27,
            "nativeVirtualKeyCode": 27,
        }
        self.cdp("Input.dispatchKeyEvent", dict(key, type="rawKeyDown"))
        self.cdp("Input.dispatchKeyEvent", dict(key, type="keyUp"))

    def move(self, x, y):
        self.cdp(
            "Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y}
        )

    def take_alert(self):
        """Accepts the dialog that is up and returns its text, or None."""
        try:
            text = self.b._req("GET", f"/session/{self.b.sid}/alert/text")["value"]
            self.b._req("POST", f"/session/{self.b.sid}/alert/accept", {})
            return text or ""
        except RuntimeError:
            return None

    def accept_alert(self):
        return self.take_alert() is not None

    def handles(self):
        return self.b._req("GET", f"/session/{self.b.sid}/window/handles")["value"]

    def open_tab(self):
        h = self.b._req(
            "POST", f"/session/{self.b.sid}/window/new", {"type": "tab"}
        )["value"]["handle"]
        self.b._req("POST", f"/session/{self.b.sid}/window", {"handle": h})


def wait(fn, timeout=15, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except RuntimeError:
            pass
        time.sleep(step)
    return False


def fullscreen(b):
    return b.run("return !!document.fullscreenElement")


def esc_leaves(t, b, base, mode):
    t.open_tab()
    b.get(f"{base}/takeover_scam.html?mode={mode}")
    t.click(200, 200)
    went = wait(lambda: fullscreen(b))
    t.esc()
    left = wait(lambda: not fullscreen(b), timeout=5)
    return went and left


def check_dialog_loop(t, b, base, checks):
    """A page that loops alert() and confirm() gets three, not ten."""
    del REPORTS[:]
    t.open_tab()
    b.get(f"{base}/takeover_scam.html?mode=dialogs")
    t.click(200, 200)
    shown = 0
    end = time.time() + 25
    while time.time() < end and not reports("done"):
        if t.accept_alert():
            shown += 1
        time.sleep(0.05)
    returned = len(reports("dlg"))
    print(f"INFO dialogs: shown {shown}, returned {returned}")
    checks["dialogs: a looping alert/confirm page is cut off after three"] = (
        shown == 3 and bool(reports("done"))
    )
    checks["dialogs: the loop is not left waiting on a dialog"] = (
        returned == 10 and not t.accept_alert()
    )


def check_after_trip(t, b, dialogs, checks):
    """What the page held before it was replaced, and that it is gone."""
    loaded = time.time()
    states = [(when, v.split(",")) for when, v in reports("state")]
    print("INFO page reports:", len(states), "last:", states[-1][1] if states else None)
    print("INFO dialog texts:", dialogs, "report keys:",
          sorted({k for _, k, _ in REPORTS}))
    print("INFO dialogs accepted:", len(dialogs), "pointer lock reports:",
          reports("pl"), "refused:", len(reports("plerr")))

    # Dialogs: at most three reached the person, and none blocks the tab now.
    time.sleep(1.5)
    checks["dialogs: after the takeover is detected no dialog blocks the tab"] = (
        len(dialogs) <= 3 and not t.accept_alert()
    )

    # Alarm audio. The alarm was playing, and its page no longer reports.
    playing = [s for _, s in states if s[2] == "0" and float(s[3]) > 0]
    stopped = not [w for w, _ in states if w > loaded]
    checks["alarm audio: it was playing, then stopped with the page"] = (
        bool(playing) and stopped
    )
    if not playing:
        print("INFO the alarm never started playing in headless, so no state to compare")

    # Pointer lock.
    locked = any(v == "1" for _, v in reports("pl")) or any(
        s[1] == "1" for _, s in states
    )
    if locked:
        checks["pointer lock: the lock does not outlive the takeover"] = b.run(
            "return document.pointerLockElement === null"
        ) and not [w for w, v in reports("pl") if w > loaded and v == "1"]
    else:
        checks["pointer lock: the lock does not outlive the takeover"] = None
        print("INFO pointer lock was never granted in headless (refused:",
              [v for _, v in reports("plerr")], "), so there is no lock to release")

    # Keyboard lock.
    answered = [v for _, v in reports("kl")]
    checks["keyboard lock: the scam page's request in fullscreen was accepted"] = (
        answered == ["ok"]
    )
    # Neither the page nor DevTools can read whether the browser still holds
    # a keyboard lock (a new lock() is answered "locked" even outside
    # fullscreen, which was tried). The browser drops the lock when fullscreen ends; what can
    # be checked is the fullscreen state and that Esc leaves it (above).
    checks["keyboard lock: released once the takeover is detected"] = None


def check_leave_trap(t, b, base, checks):
    """A page that arms a leave-page prompt cannot hold the tab with it.

    Trips on history spam rather than dialogs, so the page's script is not
    stuck inside an alert when the browser steps in."""
    del REPORTS[:]
    t.open_tab()
    before = len(t.handles())
    b.get(f"{base}/takeover_scam.html?mode=trap")
    t.click(200, 200)
    dialogs = []

    def tripped():
        text = t.take_alert()
        if text is not None:
            dialogs.append(text)
        return b.current_url().startswith(GET_ME_OUT)

    went = wait(tripped, timeout=30, step=0.4)
    time.sleep(1)
    print("INFO leave-page trap: prompts accepted:", dialogs, "handler ran:",
          len(reports("bu")), "report keys:", sorted({k for _, k, _ in REPORTS}))
    checks["leave-page trap: the page is replaced"] = went
    # ChromeDriver answers a leave-page prompt by itself, so a prompt the
    # browser did show could not be told apart here: what is checked is that
    # the trap was armed, its handler ran, and the tab was still replaced.
    checks["leave-page trap: armed, its handler ran, the tab was still replaced"] = (
        went and bool(reports("bu"))
    )
    if went:
        wait(lambda: b.run("return !!document.getElementById('close')"))
        try:
            b.run("document.getElementById('close').click(); return 1")
        except RuntimeError:
            pass
        wait(lambda: len(t.handles()) == before - 1, timeout=10)
        b._req("POST", f"/session/{b.sid}/window", {"handle": t.handles()[-1]})


def diagnose(t, b):
    """Say what the browser thinks it is showing, when the page is not what we expect."""
    print("DIAG url:", b.current_url())
    for label, fn in (
        ("handles", lambda: t.handles()),
        ("title", lambda: b._req("GET", f"/session/{b.sid}/title")["value"]),
        (
            "doc",
            lambda: b.run(
                "return [document.readyState, document.title,"
                " document.body ? document.body.innerText.slice(0, 200) : null]"
            ),
        ),
        (
            "targets",
            lambda: [
                (x.get("type"), x.get("url"), x.get("title"))
                for x in t.cdp("Target.getTargets", {})["value"]["targetInfos"]
            ],
        ),
    ):
        try:
            print("DIAG", label + ":", fn())
        except Exception as e:  # diagnostics must never hide the real failure
            print("DIAG", label, "failed:", str(e)[:200])


def main():
    checks = {}
    srv = serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    # Headless: a page that goes fullscreen must never take over a real
    # display. The browser logic under test (fullscreen, Esc, dialogs) runs
    # the same; there is just no visible window.
    b = Browser(args=["--headless=new", "--window-position=-32000,-32000"])
    try:
        t = Tab(b)
        del REPORTS[:]
        checks["Esc leaves fullscreen, keyboard locked"] = esc_leaves(
            t, b, base, "lock"
        )
        # The page is still open and no longer fullscreen.
        checks["keyboard lock: the page's request in fullscreen was accepted"] = [
            v for _, v in reports("kl")
        ] == ["ok"]
        check_dialog_loop(t, b, base, checks)

        check_leave_trap(t, b, base, checks)

        # The full scam page.
        del REPORTS[:]
        t.open_tab()
        before = len(t.handles())
        b.get(f"{base}/takeover_scam.html?mode=all")
        t.click(200, 200)
        # A mouse move right after the click: the page asks for pointer lock
        # on it, and the click is the user gesture that lets it.
        for x, y in ((220, 220), (240, 240), (260, 260)):
            t.move(x, y)
        dialogs = []

        def tripped():
            text = t.take_alert()
            if text is not None:
                dialogs.append(text)
            return b.current_url().startswith(GET_ME_OUT)

        checks["scam page trips Get me out"] = wait(tripped, timeout=30, step=0.4)
        if checks["scam page trips Get me out"]:
            # The address changes when the navigation commits, a moment
            # before the new document is there to read.
            checks["Get me out page loads"] = wait(
                lambda: b.run(
                    "return document.readyState === 'complete'"
                    " && !!document.getElementById('close')"
                ),
                timeout=15,
            )
            if not checks["Get me out page loads"]:
                diagnose(t, b)
            text = b.run("return document.body.innerText")
            checks["Get me out says the computer is fine"] = (
                "Your computer is fine" in text and "Close this tab" in text
            )
            checks["fullscreen is gone"] = not fullscreen(b)
            check_after_trip(t, b, dialogs, checks)
            checks["Get me out names the host the page was on"] = b.run(
                "var e = document.getElementById('site');"
                " return !e.hidden && e.textContent.startsWith('The page was on ')"
            )
            # Words typed into the address are not shown, only a host name.
            b.get(GET_ME_OUT + "?site=Call%20Microsoft%20on%20800")
            wait(lambda: b.run("return !!document.getElementById('close')"))
            checks["free text in ?site= is not shown"] = b.run(
                "return document.getElementById('site').hidden"
                " && !document.body.innerText.includes('Call Microsoft')"
            )
            # A name that reads as a phone number is not shown either.
            b.get(GET_ME_OUT + "?site=call-microsoft-1-800-555-0100")
            wait(lambda: b.run("return !!document.getElementById('close')"))
            checks["phone-number-like ?site= is not shown"] = b.run(
                "return document.getElementById('site').hidden"
            )
            # Leaving: the person can go on to any other page from here.
            b.get(f"{base}/takeover_video.html")
            checks["leave: the tab can be left for another page"] = wait(
                lambda: b.run("return window.ready")
            )
            b.get(GET_ME_OUT + "?site=example.com")
            wait(lambda: b.run("return !!document.getElementById('close')"))
            try:
                b.run("document.getElementById('close').click(); return 1")
            except RuntimeError:
                pass  # the tab can be gone before the driver gets its answer
            checks["one click closes the tab"] = wait(
                lambda: len(t.handles()) == before - 1, timeout=10
            )
            if not checks["one click closes the tab"]:
                diagnose(t, b)
            b._req("POST", f"/session/{b.sid}/window", {"handle": t.handles()[-1]})

        # A normal video must not trip.
        t.open_tab()
        b.get(f"{base}/takeover_video.html")
        checks["video page ready"] = wait(lambda: b.run("return window.ready"))
        x, y = b.run(
            "var r = document.getElementById('fs').getBoundingClientRect();"
            "return [r.x + r.width / 2, r.y + r.height / 2]"
        )
        t.click(x, y)
        checks["video goes fullscreen"] = wait(lambda: fullscreen(b))
        time.sleep(4)
        checks["video stays fullscreen"] = fullscreen(b)
        checks["video keeps playing"] = b.run(
            "var v = document.getElementById('v'); return !v.paused"
        )
        checks["video page not replaced"] = b.current_url().startswith(base)
    finally:
        b.quit()
        srv.shutdown()

    ok = all(v for v in checks.values() if v is not None)
    for name, passed in checks.items():
        label = "SKIP " if passed is None else ("PASS " if passed else "FAIL ")
        print(label + name)
    print("smoke_takeover:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
