#!/usr/bin/env python3
"""Check redirect and AMP skipping in the real browser.

No real site is contacted. One small HTTP server answers on 127.0.0.1, and
the browser is told to treat the real redirector hosts (l.facebook.com,
www.google.com, ...) as that machine with --host-resolver-rules, so the
real rules, which name those hosts, are the ones exercised. The server
never forwards anyone: a page can only land on the target if the browser
itself rewrote the address, which is exactly what is being checked. The
target and start pages are on *.localhost names, which HTTPS-first leaves
as plain http.

  debounce_test   the rule tests (debounce_test.exe, next to chrome.exe)
                  pass: sample addresses in, answers out, including ones
                  that must not be followed
  skipped         a link through each redirector lands straight on the
                  target, exactly as it was written in the parameter: the
                  l.php and /url patterns, Instagram, YouTube, Reddit,
                  Slack, a chain of two, one reached by a server redirect,
                  and one typed into the address bar
  kept            javascript:, data: and file: targets, a nested file:
                  one and a target with a user name are not followed
  frames          an iframe pointed at a redirector is not rewritten
  history         Back after a skipped link returns to where it started
  switch          the Protection row is on by default, turning it off
                  stops the skipping at once and survives a restart, and
                  turning it on starts it again
"""

import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from drive import OUT, Browser, free_port

TMP = r"E:\tmp\feat-debounce"
PROFILE = os.path.join(TMP, "profile-smoke")
FILE_TARGET = os.path.join(TMP, "landed.html")

# Redirector hosts, as the real rules name them.
REDIRECTORS = [
    "l.facebook.com",
    "www.google.com",
    "l.instagram.com",
    "www.youtube.com",
    "out.reddit.com",
    "slack-redir.net",
]
RESOLVER_RULES = ",".join(f"MAP {h} 127.0.0.1" for h in REDIRECTORS)


class Handler(BaseHTTPRequestHandler):
    hits = []  # (host, path) of every request that arrived

    def do_GET(self):  # noqa: N802
        host = self.headers.get("Host", "").split(":")[0]
        Handler.hits.append((host, self.path))
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        if parts.path == "/bounce":
            # A server that sends people on to a redirector.
            self.send_response(302)
            self.send_header("Location", query["to"][0])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if parts.path == "/frame":
            body = f'<title>start</title><iframe src="{query["src"][0]}"></iframe>'
        elif host == "target.localhost":
            body = "<title>landed</title><p>landed"
        elif host in REDIRECTORS:
            body = "<title>hopped</title><p>the redirector was asked"
        else:
            body = "<title>start</title><p>start"
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def wait_for(b, script, seconds=10):
    end = time.time() + seconds
    value = None
    while time.time() < end:
        value = b.run(script)
        if value:
            return value
        time.sleep(0.25)
    return value


def enc(text):
    return quote(text, safe="")


class Run:
    def __init__(self, port):
        self.port = port
        self.start = f"http://start.localhost:{port}/start.html"
        self.target = f"http://target.localhost:{port}/landing.html?q=a%2Fb&x=1"
        self.failures = []

    def host(self, name):
        return f"http://{name}:{self.port}"

    def check(self, ok, text):
        print(("  ok    " if ok else "  FAIL  ") + text)
        if not ok:
            self.failures.append(text)

    def follow(self, b, link, wait=8):
        """Opens the start page, then goes to link as a clicked link would.
        Returns where it ended up and the page title."""
        b.get(self.start)
        b.run("location.href = arguments[0]", [link])
        done = "return ['landed','hopped'].includes(document.title)"
        wait_for(b, done, wait)
        time.sleep(0.3)
        return b.current_url(), b.run("return document.title")

    def skipped(self, b, name, link, want=None):
        want = want or self.target
        url, title = self.follow(b, link)
        self.check(url == want and title == "landed", f"{name}: landed on {url}")

    def kept(self, b, name, link):
        url, title = self.follow(b, link, wait=3)
        followed = title == "landed" or url.split(":")[0] in {"data", "javascript", "file"}
        self.check(not followed, f"{name}: not followed (ended on {url[:80]})")


def run_unit_test(run):
    exe = os.path.join(OUT, "debounce_test.exe")
    if not os.path.exists(exe):
        run.check(False, f"debounce_test.exe is missing from {OUT}")
        return
    done = subprocess.run([exe], capture_output=True, text=True, timeout=120)
    text = (done.stdout + done.stderr).strip()
    print("\n".join("    " + line for line in text.splitlines()[-8:]))
    run.check(done.returncode == 0, "debounce_test.exe passes")


def check_skipped(run, b):
    t = enc(run.target)
    fb = run.host("l.facebook.com")
    goog = run.host("www.google.com")
    run.skipped(b, "Facebook l.php", f"{fb}/l.php?u={t}&h=AT0abc")
    run.skipped(b, "Google /url?q=", f"{goog}/url?sa=t&rct=j&q={t}&ved=2ah")
    run.skipped(b, "Google /url?url=", f"{goog}/url?sa=t&q=&url={t}&ved=2ah")
    run.skipped(b, "Instagram", f"{run.host('l.instagram.com')}/?u={t}&e=AT1")
    run.skipped(
        b, "YouTube", f"{run.host('www.youtube.com')}/redirect?event=video_description&q={t}"
    )
    run.skipped(b, "Reddit", f"{run.host('out.reddit.com')}/t3_abc?url={t}&token=x")
    run.skipped(b, "Slack", f"{run.host('slack-redir.net')}/link?url={t}")
    chain = f"{fb}/l.php?u={enc(f'{goog}/url?q={t}')}"
    run.skipped(b, "Facebook then Google", chain)

    # A server that redirects into a redirector is skipped too.
    b.get(f"{run.host('start.localhost')}/bounce?to={enc(f'{fb}/l.php?u={t}')}")
    wait_for(b, "return document.title === 'landed'")
    url = b.current_url()
    run.check(url == run.target, f"server redirect into l.php: landed on {url}")

    # As typed into the address bar.
    b.get(f"{fb}/l.php?u={t}")
    wait_for(b, "return document.title === 'landed'")
    url = b.current_url()
    run.check(url == run.target, f"typed l.php address: landed on {url}")


def check_kept(run, b):
    fb = run.host("l.facebook.com")
    goog = run.host("www.google.com")
    file_url = "file:///" + FILE_TARGET.replace("\\", "/")
    for name, bad in [
        ("javascript:", "javascript:document.title='landed'"),
        ("javascript: with a tab", "java\tscript:document.title='landed'"),
        ("data:", "data:text/html,<title>landed</title>"),
        ("file:", file_url),
        ("a user name", f"http://user:pass@target.localhost:{run.port}/landing.html"),
    ]:
        run.kept(b, name, f"{fb}/l.php?u={enc(bad)}")
    inner = f"{fb}/l.php?u={enc(file_url)}"
    run.kept(b, "file: nested in a second redirector", f"{goog}/url?q={enc(inner)}")


def check_frames_and_history(run, b):
    slack = f"{run.host('slack-redir.net')}/link?url={enc(run.target)}"
    Handler.hits.clear()
    b.get(f"{run.host('start.localhost')}/frame?src={enc(slack)}")
    time.sleep(2)
    asked = any(h == "slack-redir.net" for h, _ in Handler.hits)
    run.check(asked, "an iframe pointed at a redirector is loaded as it is")
    run.check(b.run("return document.title") == "start", "the page holding it stays")

    run.follow(b, f"{run.host('l.facebook.com')}/l.php?u={enc(run.target)}")
    b.run("history.back()")
    wait_for(b, "return document.title === 'start'")
    url = b.current_url()
    run.check(url == run.start, f"Back after a skipped link goes to {url}")


def row_state(b):
    b.get("chrome://boring-protection")
    wait_for(b, "return document.getElementById('skip-redirects') !== null")
    time.sleep(1)  # the page fills in its switches when the browser answers
    return b.run(
        "var e = document.getElementById('skip-redirects');"
        "return {checked: e.checked, type: e.type, labels: e.labels.length,"
        " text: e.labels[0].textContent.replace(/\\s+/g, ' ').trim()}"
    )


def toggle(b):
    b.run("document.getElementById('skip-redirects').click()")
    time.sleep(0.8)


def main():
    os.makedirs(TMP, exist_ok=True)
    with open(FILE_TARGET, "w", encoding="utf-8") as f:
        f.write("<title>landed</title>")
    shutil.rmtree(PROFILE, ignore_errors=True)

    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    run = Run(port)
    args = [f"--host-resolver-rules={RESOLVER_RULES}"]

    try:
        print("rule tests")
        run_unit_test(run)

        with Browser(user_data_dir=PROFILE, args=args) as b:
            print("switch, first start")
            row = row_state(b)
            print("  row:", row)
            run.check(row["checked"] is True, "Skip tracking redirects is on by default")
            run.check(
                row["type"] == "checkbox" and row["labels"] == 1,
                "the row is a labelled checkbox",
            )
            run.check("Skip tracking redirects" in row["text"], "the row says what it is")

            print("skipped")
            check_skipped(run, b)
            print("kept")
            check_kept(run, b)
            print("frames and history")
            check_frames_and_history(run, b)

            print("switch, off and on again")
            row_state(b)
            toggle(b)
            url, _ = run.follow(b, f"{run.host('l.facebook.com')}/l.php?u={enc(run.target)}", wait=3)
            run.check(
                urlsplit(url).hostname != "target.localhost",
                f"with the switch off the redirector is asked (ended on {url[:60]})",
            )
            row_state(b)
            toggle(b)
            run.skipped(b, "switch turned back on", f"{run.host('l.facebook.com')}/l.php?u={enc(run.target)}")
            row_state(b)
            toggle(b)  # leave it off for the restart

        with Browser(user_data_dir=PROFILE, args=args) as b:
            print("switch, after a restart")
            row = row_state(b)
            run.check(row["checked"] is False, "the off choice is still off after a restart")
            url, _ = run.follow(b, f"{run.host('l.facebook.com')}/l.php?u={enc(run.target)}", wait=3)
            run.check(
                urlsplit(url).hostname != "target.localhost",
                f"still not skipping (ended on {url[:60]})",
            )
    finally:
        server.shutdown()

    print()
    if run.failures:
        print(f"{len(run.failures)} FAILED:")
        for text in run.failures:
            print("  ", text)
        return 1
    print("all debounce checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
