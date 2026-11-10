#!/usr/bin/env python3
"""Check the warning for a site Quad9 blocks, in the real browser.

Quad9, the secure DNS server, answers "not found" for a site on its threat
list, the same as for a typo. When a page in the main window cannot be found
and Quad9 is the secure DNS server, the browser asks Quad9 once more and
reads the Extended DNS Error code 17 ("filtered") that only a block carries.

Nothing here touches Quad9 or a real threat list name. A small server on
127.0.0.1 plays the DNS over HTTPS server: --boring-test-quad9-endpoint
points the browser's question at it (accepted only for a loopback address),
and it answers a made up name with the real blocked answer Quad9 gave for
its documented test domain, with the name swapped (tools/quad9_wire.py).
--host-resolver-rules makes every other name "not found" at once.

Checked:
  a blocked name shows the warning, naming Quad9, with "Go back to safety"
    as the only action: no "Continue anyway", also with "No way past scam
    warnings" on or off;
  the same from a link on a page (a navigation started by the page);
  "Go back to safety" returns to the page before;
  a name that does not exist (NXDOMAIN with an SOA), a server that errors,
    one that sends junk and one that is too slow all leave the ordinary
    "site can't be reached" page;
  a server that answers with a redirect: the redirect is refused, not
    followed, and the ordinary page shows;
  intranet looking names (single label, .local, unknown ending) send no
    question;
  Secure DNS off, automatic mode, another provider, or Quad9 with a second
    server, sends no question at all.

Usage: python smoke_dns_warning.py
"""

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import quad9_wire
from drive import Browser
from smoke_local import set_local_state, wait_for

# Real top level domains: the browser leaves intranet looking names (an
# unknown ending such as .test, a single label, .local) out of the check.
BLOCKED = "blocked-demo-qz.com"
GONE = "gone-demo-qz.com"
BROKEN = "broken-demo-qz.com"
JUNK = "junk-demo-qz.com"
SLOW = "slow-demo-qz.com"
REDIRECT = "redirect-demo-qz.com"
# The server would call these blocked, so a question about one shows up as
# a warning.
INTRANET = ("printer-demo-qz", "nas-demo-qz.local", "intranet-demo-qz.test")
FROM_PAGE = "ok-demo-qz.test"
QUAD9 = "https://dns.quad9.net/dns-query"
OTHER = "https://dns.google/dns-query"

# The server holds an answer longer than the browser waits for it.
SLOW_SECONDS = 4

PAGE = (
    b"<title>Ordinary page</title><p id=ok>ordinary page</p>"
    b'<a id=link href="http://%s/">link</a>' % BLOCKED.encode()
)

WARNED = (
    "document.body && /list of dangerous sites/.test(document.body.innerText)"
)
NOT_FOUND = "document.body && /ERR_NAME_NOT_RESOLVED/.test(document.body.innerText)"
BUTTONS = (
    "return [...document.querySelectorAll('button')]"
    ".map(b => b.textContent.trim())"
)


class FakeDoh:
    """The DNS over HTTPS server: writes down each name asked and answers
    the made up names above."""

    def __init__(self):
        asked = self.asked = []
        followed = self.followed = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/followed"):
                    # Where the redirect points: a browser that follows it
                    # lands here.
                    followed.append(self.path)
                    query = parse_qs(urlparse(self.path).query).get("dns", [""])[0]
                    name, _ = quad9_wire.read_question(
                        quad9_wire.decode_get_query(query)
                    )
                    body = quad9_wire.blocked_answer(name)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/dns-message")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                query = parse_qs(urlparse(self.path).query).get("dns", [""])[0]
                try:
                    name, _ = quad9_wire.read_question(
                        quad9_wire.decode_get_query(query)
                    )
                except Exception:
                    name = ""
                asked.append(name)
                status, body = 200, b""
                if name == BLOCKED:
                    body = quad9_wire.blocked_answer(name)
                elif name == GONE:
                    body = quad9_wire.not_found_answer(name)
                elif name == BROKEN:
                    status = 500
                elif name == JUNK:
                    body = b"\xff" * 40 + b"not a dns message"
                elif name == SLOW:
                    time.sleep(SLOW_SECONDS)
                    body = quad9_wire.blocked_answer(name)
                elif name == REDIRECT:
                    self.send_response(302)
                    self.send_header("Location", "/followed?dns=" + query)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                elif name in INTRANET:
                    body = quad9_wire.blocked_answer(name)
                else:
                    status = 404
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/dns-message")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass  # the browser gave up first (the slow name)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


class Pages:
    """An ordinary web page, for the page before and the page with a link."""

    def __init__(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(PAGE)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(PAGE)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self):
        return f"http://{FROM_PAGE}:{self.port}/"

    def close(self):
        self.server.shutdown()


def browser_args(doh, pages):
    return [
        "--disable-boring-list-updates",
        f"--boring-test-quad9-endpoint=http://127.0.0.1:{doh.port}/dns-query",
        # The page with the link is the only name that resolves. The rule
        # would also fail the address 127.0.0.1 the fake server is on.
        f"--host-resolver-rules=MAP {FROM_PAGE} 127.0.0.1, "
        "MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
        # HTTPS-Only would upgrade these plain http names (see
        # smoke_lookalike.seed_profile). This replaces drive.py's own
        # --disable-features, so it carries that one too.
        "--disable-features=CalculateNativeWinOcclusion,HttpsUpgrades,"
        "HttpsFirstBalancedMode",
        "--window-size=1360,900",
        # Never on the desktop and never in front: see drive.py.
        "--window-position=-32000,-32000",
    ]


def seed_profile(profile, mode, template):
    """Secure DNS settings (Local State) and HTTPS-Only off, set before the
    browser starts."""
    folder = os.path.join(profile, "Default")
    os.makedirs(folder, exist_ok=True)
    prefs = {
        "https_only_mode_enabled": False,
        "https_first_balanced_mode_enabled": False,
    }
    with open(os.path.join(folder, "Preferences"), "w", encoding="utf-8") as f:
        json.dump(prefs, f)
    set_local_state(profile, "dns_over_https.mode", mode)
    set_local_state(profile, "dns_over_https.templates", template)


def open_url(b, url):
    """Navigates. A site that cannot be found is a failed navigation, which
    WebDriver reports as an error, and that is not a failure here."""
    try:
        b.get(url)
    except RuntimeError as e:
        if "ERR_NAME_NOT_RESOLVED" not in str(e):
            raise


def text(b):
    return b.run("return document.body ? document.body.innerText : ''")


def current_url(b):
    try:
        return b.current_url()
    except RuntimeError:
        return ""


def main():
    failures = []

    def check(name, ok, detail=""):
        print(
            ("PASS: " if ok else "FAIL: ")
            + name
            + (f" ({detail})" if detail and not ok else "")
        )
        if not ok:
            failures.append(name)

    doh = FakeDoh()
    pages = Pages()
    tmp = os.environ.get("TMP") or None

    def session(mode, template):
        profile = tempfile.TemporaryDirectory(prefix="dnswarn-", dir=tmp)
        seed_profile(profile.name, mode, template)
        return profile, Browser(
            user_data_dir=profile.name, args=browser_args(doh, pages)
        )

    try:
        # --- Quad9 is the secure DNS server -------------------------------
        profile, b = session("secure", QUAD9)
        with profile, b:
            before = pages.url()
            open_url(b, before)
            wait_for(b, "!!document.getElementById('ok')")

            doh.asked.clear()
            open_url(b, f"http://{BLOCKED}/")
            shown = wait_for(b, WARNED)
            check("a blocked name shows the warning", shown)
            body = text(b) if shown else ""
            check(
                "it names Quad9 and says the site was not opened",
                "Quad9" in body and "It was not opened." in body,
                body[:300].replace("\n", " | "),
            )
            check("it shows the address", BLOCKED in body)
            check(
                "Go back to safety is the only action",
                b.run(BUTTONS) == ["Go back to safety"]
                and "ontinue" not in body
                and not b.run(
                    "return document.querySelectorAll('[onclick*=proceedAnyway]').length"
                ),
                repr(b.run(BUTTONS)),
            )
            check(
                "the name was asked of Quad9 once",
                doh.asked.count(BLOCKED) == 1,
                repr(doh.asked),
            )
            b.run(
                "[...document.querySelectorAll('button')]"
                ".find(x => x.textContent.trim() === 'Go back to safety').click()"
            )
            time.sleep(2)
            check(
                "Go back to safety returns to the page before",
                current_url(b) == before,
                current_url(b),
            )

            # A navigation the page itself starts (a link click) takes
            # another path in the browser than one typed in the address bar.
            wait_for(b, "!!document.getElementById('link')")
            b.run("document.getElementById('link').click()")
            check(
                "a link to a blocked name shows the warning",
                wait_for(b, WARNED),
                text(b)[:200],
            )

            # "No way past scam warnings" on: nothing changes, since there
            # was never a way past.
            b.get("chrome://boring-protection")
            wait_for(
                b,
                "document.getElementById('ads-state').textContent === 'On'",
                10000,
            )
            b.run("document.getElementById('no-bypass').click()")
            wait_for(b, "document.getElementById('no-bypass').checked")
            open_url(b, f"http://{BLOCKED}/")
            check(
                "no way past scam warnings on: the same warning",
                wait_for(b, WARNED)
                and b.run(BUTTONS) == ["Go back to safety"],
            )

            # Anything but a clear block leaves the ordinary page.
            for name, why in (
                (GONE, "a name that does not exist"),
                (BROKEN, "a server error"),
                (JUNK, "an answer that is not DNS"),
                (SLOW, "an answer that comes too late"),
            ):
                doh.asked.clear()
                open_url(b, f"http://{name}/")
                found = wait_for(b, NOT_FOUND, 15000)
                check(
                    f"{why}: the ordinary page, no warning",
                    found and not b.run(f"return !!({WARNED})"),
                    text(b)[:200],
                )
                check(
                    f"{why}: Quad9 was asked",
                    name in doh.asked,
                    repr(doh.asked),
                )

            # The server sends the browser to another address: the redirect
            # is refused, so the question is not handed on.
            doh.asked.clear()
            doh.followed.clear()
            open_url(b, f"http://{REDIRECT}/")
            found = wait_for(b, NOT_FOUND, 15000)
            time.sleep(1)
            check(
                "a redirect from the server: the ordinary page, no warning",
                found and not b.run(f"return !!({WARNED})"),
                text(b)[:200],
            )
            check("a redirect from the server: Quad9 was asked", REDIRECT in doh.asked)
            check(
                "a redirect from the server: not followed",
                not doh.followed,
                repr(doh.followed),
            )

            # Intranet looking names are not sent to Quad9 at all.
            for name in INTRANET:
                doh.asked.clear()
                open_url(b, f"http://{name}/")
                found = wait_for(b, NOT_FOUND, 15000)
                time.sleep(1)
                check(
                    f"{name}: the ordinary page, no warning",
                    found and not b.run(f"return !!({WARNED})"),
                    text(b)[:200],
                )
                check(f"{name}: no question was sent", not doh.asked, repr(doh.asked))

        # --- Secure DNS off, and anything but Quad9 alone -------------------
        for label, mode, template in (
            ("Secure DNS off", "off", QUAD9),
            ("another provider", "secure", OTHER),
            ("automatic mode", "automatic", QUAD9),
            ("Quad9 and a second server", "secure", f"{QUAD9} {OTHER}"),
        ):
            profile, b = session(mode, template)
            with profile, b:
                doh.asked.clear()
                open_url(b, f"http://{BLOCKED}/")
                found = wait_for(b, NOT_FOUND, 15000)
                time.sleep(1)
                check(
                    f"{label}: the ordinary page, no warning",
                    found and not b.run(f"return !!({WARNED})"),
                    text(b)[:200],
                )
                check(f"{label}: no question was sent", not doh.asked, repr(doh.asked))
    finally:
        doh.close()
        pages.close()

    if failures:
        print(f"{len(failures)} failed")
        return 1
    print("all Quad9 block warning checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
