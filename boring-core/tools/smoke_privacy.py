#!/usr/bin/env python3
"""Check the privacy defaults and the pages that show them.

Everything network is local: two small HTTP servers, one on 127.0.0.1
and one on localhost, which the browser treats as two different sites.

  tracking      a link from one site to the other carrying fbclid lands
                without it, and the server never sees it, nor a request
                dressed up as one the person typed; a site linking to
                itself keeps its parameters, and Back returns to that
                page as it was; the Protection switch turns stripping off
  fingerprint   a canvas read twice, in two page loads, differs with the
                noise on and matches with it off
  protection    the Protection page reports HTTPS-first on, WebRTC
                hidden, dangerous sites blocked through Quad9, and the
                updater honestly off in a build without an update key
  search        the new tab page lists the browser's search engines and
                choosing one makes it the default; with search turned off
                in settings ("No Search") it says so and still offers them

Quad9 itself is not contacted: the check reads what the browser's own
settings say, which is what decides where DNS goes.
"""

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from drive import Browser, free_port

CANVAS_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>canvas</title>
<canvas id="c" width="120" height="40"></canvas>
<script>
  var c = document.getElementById('c');
  var g = c.getContext('2d');
  g.fillStyle = '#1a6b5a';
  g.fillRect(0, 0, 120, 40);
  g.fillStyle = '#ffffff';
  g.font = '16px serif';
  g.fillText('Boring 123', 6, 26);
  var data = g.getImageData(0, 0, 120, 40).data;
  var sum = 0;
  for (var i = 0; i < data.length; i++) sum = (sum * 31 + data[i]) >>> 0;
  document.title = 'sum:' + sum + ':' + g.measureText('Boring 123').width;
</script>
"""


class Recorder(BaseHTTPRequestHandler):
    seen = []
    # Sec-Fetch-Site of each page request, by path.
    fetch_site = {}
    # Set by the loop check: /loop.html without its parameter goes to
    # /hop on the other site, and /hop puts the parameter back. Gives up
    # after a few rounds, so a browser that loops fails the check rather
    # than hanging it.
    loop_hop = ""
    hop_to = ""
    hops = 0

    def do_GET(self):  # noqa: N802
        Recorder.seen.append(self.headers.get("Host", "") + self.path)
        Recorder.fetch_site[self.path] = self.headers.get("Sec-Fetch-Site")
        bounce = {"/loop.html": Recorder.loop_hop, "/hop": Recorder.hop_to}
        if self.path == "/hop":
            Recorder.hops += 1
        if bounce.get(self.path) and Recorder.hops <= 5:
            self.send_response(302)
            self.send_header("Location", bounce[self.path])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"<!doctype html><title>landed</title><p>landed"
        if self.path.startswith("/canvas"):
            body = CANVAS_PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Keeps pages out of the back/forward cache, so going back is a
        # real navigation the browser has to check, not a page restored
        # from memory.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(host, port):
    server = ThreadingHTTPServer((host, port), Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


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


def wait_for(b, script, seconds=10):
    end = time.time() + seconds
    value = None
    while time.time() < end:
        value = b.run(script)
        if value:
            return value
        time.sleep(0.25)
    return value


def follow(b, start, target):
    """Opens start, then navigates from it to target as a link would."""
    b.get(start)
    b.run("location.href = arguments[0]", [target])
    wait_for(b, "return document.title === 'landed'")
    time.sleep(0.5)
    return b.current_url()


def check_tracking(profile, a, b_origin, failures):
    target = b_origin + "/landing.html?fbclid=abc123&keep=1"
    with Browser(user_data_dir=profile) as b:
        Recorder.seen.clear()
        landed = follow(b, a + "/start.html", target)
        print("cross-site link landed on", landed)
        if "fbclid" in landed or "keep=1" not in landed:
            failures.append(f"cross-site fbclid not stripped cleanly: {landed}")
        if any("fbclid" in s for s in Recorder.seen):
            failures.append("the server saw fbclid before it was stripped")
        # The clean request must still say it came from another site, or
        # it gets cookies and trust meant for an address typed by hand.
        site = Recorder.fetch_site.get("/landing.html?keep=1")
        print("cross-site link arrived with Sec-Fetch-Site", site)
        if site != "cross-site":
            failures.append(f"the stripped link arrived as Sec-Fetch-Site {site}")

        same = a + "/landing.html?fbclid=abc123&keep=1"
        landed = follow(b, a + "/start.html", same)
        print("same-site link landed on", landed)
        if "fbclid=abc123" not in landed:
            failures.append(f"a site linking to itself lost its parameters: {landed}")

        # Back to that page goes to it as it was, and stays one step.
        depth = b.run("return history.length")
        b.get(b_origin + "/other.html")
        b.run("history.back()")
        wait_for(b, f"return location.origin === '{a}'")
        time.sleep(0.5)
        back = b.current_url()
        print("back landed on", back)
        if back != landed or b.run("return history.length") != depth + 1:
            failures.append(f"going back was rewritten as a new page: {back}")

        # A site that sends the clean address straight back to one with
        # the parameter gets its parameter, not a page that never loads.
        Recorder.hops = 0
        Recorder.loop_hop = a + "/hop"
        Recorder.hop_to = b_origin + "/loop.html?fbclid=abc123"
        landed_loop = follow(b, a + "/start.html", Recorder.hop_to)
        hops = Recorder.hops
        Recorder.loop_hop = Recorder.hop_to = ""
        print(f"bouncing site landed on {landed_loop} after {hops} hops")
        if hops > 1 or "fbclid" not in landed_loop:
            failures.append(f"stripping went round a redirect loop {hops} times")

    set_pref(profile, "boring.strip_tracking_params", False)
    with Browser(user_data_dir=profile) as b:
        landed = follow(b, a + "/start.html", target)
        print("with stripping off landed on", landed)
        if "fbclid=abc123" not in landed:
            failures.append("turning stripping off did not keep the parameter")

        # Turned back on while that page is still in history: going back
        # returns to it as it was, one step, rather than starting a new
        # page that Back can never get past.
        depth = b.run("return history.length")
        b.get("chrome://boring-protection")
        wait_for(b, "return document.getElementById('strip-params').checked === false")
        b.run("document.getElementById('strip-params').click()")
        time.sleep(0.5)
        b.run("history.back()")
        wait_for(b, f"return location.origin === '{b_origin}'")
        time.sleep(1)
        back = b.current_url()
        print("back after turning it on landed on", back)
        if back != landed or b.run("return history.length") != depth + 1:
            failures.append(f"going back was rewritten as a new page: {back}")
    set_pref(profile, "boring.strip_tracking_params", True)


def canvas_readings(profile, url):
    readings = []
    with Browser(user_data_dir=profile) as b:
        for _ in range(2):
            b.get(url)
            readings.append(
                wait_for(
                    b, "return document.title.startsWith('sum:') && document.title"
                )
            )
    return readings


def check_fingerprint(profile, a, failures):
    url = a + "/canvas.html"
    on = canvas_readings(profile, url)
    print("noise on, two loads:", on)
    if on[0] == on[1]:
        failures.append("fingerprint noise on, but two loads read the same canvas")
    set_pref(profile, "boring.fingerprint_noise", False)
    off = canvas_readings(profile, url)
    print("noise off, two loads:", off)
    if off[0] != off[1]:
        failures.append("fingerprint noise off, but the canvas still changed")
    set_pref(profile, "boring.fingerprint_noise", True)


def check_protection(profile, failures):
    with Browser(user_data_dir=profile) as b:
        b.get("chrome://boring-protection")
        wait_for(
            b,
            "return document.getElementById('https-state').textContent !== 'Starting'",
        )
        wait_for(
            b,
            "return document.getElementById('update-state').textContent !== 'Starting'",
        )
        state = b.run(
            "var t = function(id) { return document.getElementById(id).textContent; };"
            "return {https: t('https-state'), webrtc: t('webrtc-state'),"
            " scam: t('scam-state'), scamDesc: t('scam-desc'),"
            " update: t('update-state'), updateDesc: t('update-desc'),"
            " strip: document.getElementById('strip-params').checked,"
            " noise: document.getElementById('fingerprint').checked}"
        )
    print("protection page:", state)
    if state["https"] != "On":
        failures.append(f"HTTPS-first is not on by default: {state['https']}")
    if state["webrtc"] != "Hidden":
        failures.append(f"WebRTC addresses are not hidden: {state['webrtc']}")
    if state["scam"] != "On" or "Quad9" not in state["scamDesc"]:
        failures.append(
            f"dangerous sites are not blocked through Quad9: {state['scam']}"
        )
    if not state["strip"] or not state["noise"]:
        failures.append("tracking stripping or fingerprint noise is not on by default")
    if (
        state["update"] != "Manual"
        or "does not update itself" not in state["updateDesc"]
    ):
        failures.append(f"the updater does not say plainly that it is off: {state}")


def choose_in_settings(b, name):
    """Makes `name` the default the way chrome://settings/search does."""
    b.get("chrome://settings/search")
    return b.run_async(
        "var name = arguments[0], done = arguments[arguments.length - 1];"
        "import('chrome://resources/js/cr.js').then(function(cr) {"
        "  return cr.sendWithPromise('getSearchEnginesList').then("
        "    function(lists) {"
        "      var all = [].concat.apply([], Object.values(lists));"
        "      var e = all.find(function(x) { return x.name === name; });"
        "      if (!e) return done('');"
        "      chrome.send('setDefaultSearchEngine', [e.id, 1, null]);"
        "      done(e.name);"
        "    });"
        "}).catch(function(err) { done('error: ' + err); });",
        [name],
    )


def newtab_search_state(b):
    return b.run(
        "var q = document.getElementById('q');"
        "return {engines: Array.from("
        "    document.querySelectorAll('#engines button')).map("
        "    function(x) { return x.textContent.slice(1); }),"
        " placeholder: q.placeholder, disabled: q.disabled,"
        " shown: !document.getElementById('search').hidden};"
    )


def check_search_off(profile, failures):
    """No Search in settings: the new tab page says search is off, still
    lists real engines to choose from, and choosing one works."""
    with Browser(user_data_dir=profile) as b:
        chosen = choose_in_settings(b, "No Search")
        print("chose in settings:", repr(chosen))
        if chosen != "No Search":
            failures.append(f"could not choose No Search in settings: {chosen!r}")
            return
        time.sleep(1)
        b.get("chrome://boring-newtab")
        wait_for(b, "return document.querySelectorAll('#engines button').length >= 2")
        state = newtab_search_state(b)
        print("new tab with search off:", state)
        if len(state["engines"]) < 2 or not state["shown"]:
            failures.append(f"with search off the new tab page is empty: {state}")
            return
        if "No Search" in state["engines"]:
            failures.append("the new tab page offers No Search as an engine")
        if not state["disabled"] or "Search is off" not in state["placeholder"]:
            failures.append(f"the new tab page does not say search is off: {state}")
        pick = state["engines"][0]
        b.run(
            "var want = arguments[0];"
            "Array.from(document.querySelectorAll('#engines button')).find("
            "  function(x) { return x.textContent.slice(1) === want; }).click();",
            [pick],
        )
        after = wait_for(
            b,
            f"return document.getElementById('q').placeholder === 'Search {pick}'",
        )
        print(f"search off -> chose {pick!r}: {bool(after)}")
        if not after:
            failures.append(f"with search off, choosing {pick!r} did not work")


def check_search(profile, failures):
    with Browser(user_data_dir=profile) as b:
        b.get("chrome://boring-newtab")
        count = wait_for(
            b,
            "var n = document.querySelectorAll('#engines button').length;"
            "return n >= 2 && n;",
        )
        if not count:
            failures.append("the new tab page lists no search engines to choose from")
            return
        before = b.run("return document.getElementById('q').placeholder")
        other = b.run(
            "var picks = Array.from("
            "    document.querySelectorAll('#engines button'));"
            "var p = picks.find(function(x) {"
            "  return x.getAttribute('aria-selected') !== 'true' && !x.disabled;"
            "});"
            "if (!p) return '';"
            "var name = p.textContent.slice(1); p.click(); return name;"
        )
        after = wait_for(
            b,
            "var q = document.getElementById('q').placeholder;"
            f"return q === 'Search {other}' && q;",
        )
        print(f"search engines: {count}, {before!r} -> {after!r}")
        if not other or not after:
            failures.append(f"choosing {other!r} did not change the search engine")
        b.get("chrome://boring-newtab")
        kept = wait_for(
            b, f"return document.getElementById('q').placeholder === 'Search {other}'"
        )
        if not kept:
            failures.append("the chosen search engine did not stay the default")


def main():
    failures = []
    with tempfile.TemporaryDirectory() as root:
        profile = os.path.join(root, "profile")
        port_a, port_b = free_port(), free_port()
        servers = [serve("127.0.0.1", port_a), serve("localhost", port_b)]
        a = f"http://127.0.0.1:{port_a}"
        b_origin = f"http://localhost:{port_b}"
        try:
            check_protection(profile, failures)
            check_tracking(profile, a, b_origin, failures)
            check_fingerprint(profile, a, failures)
            check_search(profile, failures)
            check_search_off(profile, failures)
        finally:
            for server in servers:
                server.shutdown()

    for failure in failures:
        print("FAIL:", failure)
    if failures:
        return 1
    print(
        "PASS: privacy defaults, tracking stripping, "
        "fingerprint noise and search choice"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
