#!/usr/bin/env python3
"""Check Global Privacy Control (https://w3c.github.io/gpc/) in the browser.

A local server records the Sec-GPC header of every request. One page load
makes a top-level navigation, an iframe navigation, an image, a fetch, a
dedicated worker script and a fetch from that worker, and reads
navigator.globalPrivacyControl in the page, the iframe and the worker.

  on by default   every request carries exactly one "Sec-GPC: 1" and every
                  navigator.globalPrivacyControl is true, in a normal
                  window, an incognito window and a guest session
  the switch      turning it off on the Protection page stops the header
                  and makes the property false for the next page, and the
                  choice is saved
  off             with boring.global_privacy_control false, no request
                  carries Sec-GPC and the property is false (not missing),
                  in a normal window and an incognito window

Nothing is contacted: the server is on 127.0.0.1.

Usage:
  python boring-core/tools/smoke_gpc.py
"""

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from drive import Browser, free_port

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>gpc</title>
<script>
  var tag = location.search;
  var out = {page: String(navigator.globalPrivacyControl)};
  var frame = new Promise(function(done) {
    addEventListener('message', function(e) { done(e.data); });
  });
  var f = document.createElement('iframe');
  f.src = '/frame.html' + tag;
  document.documentElement.appendChild(f);
  var image = new Promise(function(done) {
    var i = new Image();
    i.onload = i.onerror = done;
    i.src = '/pixel.gif' + tag;
  });
  var worker = new Promise(function(done) {
    var w = new Worker('/worker.js' + tag);
    w.onmessage = function(e) { done(e.data); };
    w.onerror = function() { done('worker failed'); };
  });
  Promise.all([fetch('/fetch' + tag), image, frame, worker]).then(
      function(r) {
        out.frame = r[2];
        out.worker = r[3];
        document.title = 'done:' + JSON.stringify(out);
      },
      function(e) { document.title = 'done:' + JSON.stringify({error: String(e)}); });
</script>
"""

FRAME = """<!doctype html>
<meta charset="utf-8">
<script>parent.postMessage(String(navigator.globalPrivacyControl), '*');</script>
"""

WORKER = """
fetch('/worker-fetch' + self.location.search).then(
    function() { postMessage(String(self.navigator.globalPrivacyControl)); },
    function() { postMessage('worker fetch failed'); });
"""

# A 1x1 transparent GIF.
PIXEL = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000"
    "010001000002024401003b"
)

# Every request one page load makes, by path without the query.
REQUESTS = [
    "/page.html",
    "/frame.html",
    "/pixel.gif",
    "/fetch",
    "/worker.js",
    "/worker-fetch",
]

FAILURES = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILURES.append(what)
    return ok


class Recorder(BaseHTTPRequestHandler):
    # Path with query -> every Sec-GPC value the request carried.
    seen = {}

    def do_GET(self):  # noqa: N802
        Recorder.seen[self.path] = self.headers.get_all("Sec-GPC") or []
        path = self.path.split("?", 1)[0]
        body, kind = {
            "/page.html": (PAGE.encode(), "text/html; charset=utf-8"),
            "/frame.html": (FRAME.encode(), "text/html; charset=utf-8"),
            "/worker.js": (WORKER.encode(), "text/javascript"),
            "/pixel.gif": (PIXEL, "image/gif"),
        }.get(path, (b"ok", "text/plain"))
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        # Every load reaches the server, so every request is recorded.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def wait_for(b, script, seconds=15):
    end = time.time() + seconds
    value = None
    while time.time() < end:
        value = b.run(script)
        if value:
            return value
        time.sleep(0.25)
    return value


def set_pref(profile, dotted, value):
    path = os.path.join(profile, "Default", "Preferences")
    with open(path, encoding="utf-8") as f:
        prefs = json.load(f)
    node = prefs
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def saved_pref(profile):
    path = os.path.join(profile, "Default", "Preferences")
    with open(path, encoding="utf-8") as f:
        prefs = json.load(f)
    return prefs.get("boring", {}).get("global_privacy_control")


_loads = [0]


def check_load(b, origin, label, expect_on):
    """One page load; every request and every property match expect_on."""
    _loads[0] += 1
    tag = f"?load={_loads[0]}"
    b.get(origin + "/page.html" + tag)
    title = wait_for(b, "return document.title.startsWith('done:') && document.title")
    if not check(bool(title), f"{label}: the page finished its requests"):
        return
    result = json.loads(title[len("done:"):])
    want = "true" if expect_on else "false"
    for where in ("page", "frame", "worker"):
        check(
            result.get(where) == want,
            f"{label}: navigator.globalPrivacyControl in the {where} is {want}"
            f" (got {result.get(where)!r})",
        )
    header = ["1"] if expect_on else []
    for path in REQUESTS:
        got = Recorder.seen.get(path + tag)
        check(
            got == header,
            f"{label}: {path} {'carried one Sec-GPC: 1' if expect_on else 'carried no Sec-GPC'}"
            f" (got {got!r})",
        )


def main():
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{port}"
    try:
        with tempfile.TemporaryDirectory() as root:
            profile = os.path.join(root, "profile")

            with Browser(user_data_dir=profile) as b:
                check_load(b, origin, "normal window, default", True)
                b.get("chrome://boring-protection")
                check(
                    bool(wait_for(b, "return document.getElementById('gpc').checked === true")),
                    "Protection: the Global Privacy Control switch is on",
                )
                row = b.run(
                    "return document.querySelector('label[for=gpc]').innerText"
                )
                check(
                    "Ask sites not to sell or share your data" in (row or ""),
                    "Protection: the row says what it does",
                )
                b.run("document.getElementById('gpc').click()")
                time.sleep(1)
                check_load(b, origin, "normal window, switched off on Protection", False)
            check(saved_pref(profile) is False, "the switch was saved as off")

            with Browser(user_data_dir=profile) as b:
                check_load(b, origin, "normal window, off", False)
            with Browser(user_data_dir=profile, args=["--incognito"]) as b:
                check_load(b, origin, "incognito, off", False)

            set_pref(profile, "boring.global_privacy_control", True)
            with Browser(user_data_dir=profile, args=["--incognito"]) as b:
                check_load(b, origin, "incognito, on", True)

            guest = os.path.join(root, "guest")
            with Browser(user_data_dir=guest, args=["--guest"]) as b:
                check_load(b, origin, "guest, default", True)
    finally:
        server.shutdown()

    for failure in FAILURES:
        print("FAIL:", failure)
    if FAILURES:
        return 1
    print("PASS: Global Privacy Control header, property, switch and windows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
