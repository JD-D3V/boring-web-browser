#!/usr/bin/env python3
"""Check "Stop screen takeovers" in the real build.

A local stand-in for a tech support scam page (testdata/takeover_scam.html)
goes fullscreen, locks the keyboard, loops alarm audio, sets a leave-page
prompt and loops alert(). The browser must:
  - leave fullscreen on a single Esc, with the keyboard locked either way
  - trip, replace the page with chrome://boring-takeover, and close the tab
    from the one button on it, with no leave-page prompt in the way
A page with a normal video (testdata/takeover_video.html) must go
fullscreen, keep playing and not trip, even though it also locks the
keyboard and adds history entries by itself.

Input goes through DevTools (Input.dispatch*), never to the desktop.
"""

import functools
import http.server
import sys
import threading
import time
from pathlib import Path

from drive import Browser, free_port

DATA = Path(__file__).resolve().parent / "testdata"
GET_ME_OUT = "chrome://boring-takeover/"


def serve():
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(DATA)
    )
    handler.log_message = lambda *a, **k: None
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

    def accept_alert(self):
        try:
            self.b._req("POST", f"/session/{self.b.sid}/alert/accept", {})
            return True
        except RuntimeError:
            return False

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


def main():
    checks = {}
    srv = serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    b = Browser()
    try:
        t = Tab(b)
        checks["Esc leaves fullscreen, keyboard locked"] = esc_leaves(
            t, b, base, "lock"
        )
        checks["Esc leaves fullscreen, Escape locked"] = esc_leaves(
            t, b, base, "lockesc"
        )

        # The full scam page.
        t.open_tab()
        before = len(t.handles())
        b.get(f"{base}/takeover_scam.html?mode=all")
        t.click(200, 200)

        def tripped():
            t.accept_alert()
            return b.current_url().startswith(GET_ME_OUT)

        checks["scam page trips Get me out"] = wait(tripped, timeout=30, step=0.4)
        if checks["scam page trips Get me out"]:
            text = b.run("return document.body.innerText")
            checks["Get me out says the computer is fine"] = (
                "Your computer is fine" in text and "Close this tab" in text
            )
            checks["fullscreen is gone"] = not fullscreen(b)
            try:
                b.run("document.getElementById('close').click(); return 1")
            except RuntimeError:
                pass  # the tab can be gone before the driver gets its answer
            checks["one click closes the tab"] = wait(
                lambda: len(t.handles()) == before - 1, timeout=10
            )
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

    ok = all(checks.values())
    for name, passed in checks.items():
        print(("PASS " if passed else "FAIL ") + name)
    print("smoke_takeover:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
