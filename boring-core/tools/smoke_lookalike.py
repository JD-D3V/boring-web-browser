#!/usr/bin/env python3
"""Check the look-alike address warning in the real browser.

A site whose name copies another site's is stopped with the same full page
warning the scam list uses, before any request goes to it. The test names
are mapped to a small local web server with --host-resolver-rules, so
nothing leaves the machine, and the server writes down every Host it is
asked for: a warned site must never be asked at all.

Checked:
  paypa1.com and rnicrosoft.com (plain letters, our matcher), a copy of
    apple.com written with a Cyrillic a (Chromium's skeleton check) and
    paypal.com-test.com (Chromium's target embedding) each show the
    warning, name the real site, and the server never hears of them;
  look-alikes under free hosting names (paypa1-login.github.io, a copy of
    amazon under github.io, a copy of paypal under pages.dev) show the
    warning too, and ordinary names under the same names do not (ledger 77);
  example·com.com (fails Chromium's spoof checks, no real site to name)
    shows the warning with "Go back to safety";
  "Go to paypal.com" is the main action and goes to https://paypal.com/;
  "Go back to safety" leaves the warning for the page before it;
  ordinary sites (an unrelated name, appie.com, apple-tree.com, a real
    accented name, paypal-support.com) open with no warning;
  "Continue anyway" opens the site, and a second visit has no warning;
  "No way past scam warnings" takes "Continue anyway" away;
  "Warn about scam tricks" off turns the warning off;
  the page follows the window's colours, light and dark.

Usage: python smoke_lookalike.py
"""

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from drive import Browser
from smoke_local import wait_for
from smoke_scam import VARIANTS

PAGE = b"<title>Ordinary page</title><p id=ok>ordinary page</p>"

# (name people see, what the warning must say it copies)
PLAIN = ("paypa1.com", "paypal.com")
RN = ("rnicrosoft.com", "microsoft.com")
CYRILLIC = ("аpple.com".encode("idna").decode(), "apple.com")  # xn--pple-43d.com
EMBEDDED = ("paypal.com-test.com", "paypal.com")
# Fails the spoof checks (a Latin middle dot) and copies no one site.
NO_TARGET = "example·com.com".encode("idna").decode()

ORDINARY = [
    "ordinary-shop.com",
    "appie.com",
    "apple-tree.com",
    "paypal-support.com",
    "münchen.de".encode("idna").decode(),
]

# A look-alike under a name anyone can register a page under. The shared
# suffix is not the site's own name, so the label in front is what is read.
HOSTED = [
    ("paypa1-login.github.io", "paypal.com"),
    ("amaz0n.github.io", "amazon.com"),
    ("paypa1.pages.dev", "paypal.com"),
]
# Ordinary names under github.io. paypal.github.io is a real Pages site name,
# not a copy. (No ordinary pages.dev name: .dev is HSTS preloaded, so a plain
# http page there cannot load, and "no warning" would prove nothing.)
HOSTED_ORDINARY = ["my-notes.github.io", "paypal.github.io", "ordinary-shop.github.io"]

ALL_HOSTS = [
    PLAIN[0],
    RN[0],
    CYRILLIC[0],
    EMBEDDED[0],
    NO_TARGET,
    *ORDINARY,
    *(h for h, _ in HOSTED),
    *HOSTED_ORDINARY,
]

WARNED = (
    "document.body && /different site|copying another site/.test(document.body.innerText)"
)
BUTTON = (
    "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === %s)"
)
CONTINUE = BUTTON % "'Continue anyway'"
WARN_LABEL = "return document.querySelector('label[for=warn-scam-tricks]').textContent"
COLOURS = (
    "return [getComputedStyle(document.body).backgroundColor,"
    " getComputedStyle(document.querySelector('button.primary'))"
    ".backgroundColor]"
)


class Recorder:
    """A local web server that writes down the Host of every request."""

    def __init__(self):
        seen = self.seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.headers.get("Host", "").split(":")[0])
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

    def close(self):
        self.server.shutdown()


def browser_args(extra=()):
    rules = ", ".join(f"MAP {h} 127.0.0.1" for h in ALL_HOSTS)
    return [
        "--disable-boring-list-updates",
        # Anything else, such as the real paypal.com, does not exist here.
        f"--host-resolver-rules={rules}, MAP * ~NOTFOUND",
        # HTTPS-Only is on by default and would upgrade these plain http
        # names (see seed_profile). This replaces drive.py's own
        # --disable-features, so it carries that one too.
        "--disable-features=CalculateNativeWinOcclusion,HttpsUpgrades,"
        "HttpsFirstBalancedMode",
        "--window-size=1360,900",
        # Never on the desktop and never in front: see drive.py.
        "--window-position=-32000,-32000",
        *extra,
    ]


def seed_profile(profile):
    """Turns HTTPS-Only off in a new profile, before the browser starts.

    The names here are plain http on ports of this machine, and HTTPS-Only
    (on by default) would upgrade every one. The ordinary pages have to
    load for "no warning" to mean something."""
    folder = os.path.join(profile, "Default")
    os.makedirs(folder, exist_ok=True)
    prefs = {
        "https_only_mode_enabled": False,
        "https_first_balanced_mode_enabled": False,
    }
    with open(os.path.join(folder, "Preferences"), "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def open_url(b, url):
    """Navigates. A warning page is a blocked navigation, which WebDriver
    may report as an error, and that is not a failure here."""
    try:
        b.get(url)
    except RuntimeError as e:
        if "ERR_BLOCKED_BY_CLIENT" not in str(e):
            raise


def text(b):
    return b.run("return document.body ? document.body.innerText : ''")


def switch_is(b, element, want, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if b.run(f"return document.getElementById('{element}').checked") is want:
            return True
        time.sleep(0.2)
    return False


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

    server = Recorder()

    def url(host):
        return f"http://{host}:{server.port}/"

    tmp = os.environ.get("TMP") or None
    try:
        with tempfile.TemporaryDirectory(prefix="lookalike-", dir=tmp) as profile:
            seed_profile(profile)
            with Browser(user_data_dir=profile, args=browser_args()) as b:
                # --- the warnings ---------------------------------------
                for host, real in (PLAIN, RN, CYRILLIC, EMBEDDED, *HOSTED):
                    open_url(b, url(host))
                    shown = wait_for(b, WARNED)
                    check(f"{host}: the warning shows", shown)
                    body = text(b) if shown else ""
                    check(
                        f"{host}: it says the name looks like {real}",
                        f"looks like {real}, but it is a different site" in body,
                        body[:200].replace("\n", " | "),
                    )
                    check(f"{host}: it shows the address", host in body)
                    check(
                        f"{host}: Go to {real} is the main action",
                        bool(b.run(f"return !!({BUTTON % repr('Go to ' + real)})"))
                        and bool(
                            b.run("return !!document.querySelector('button.primary')")
                        ),
                    )
                    check(
                        f"{host}: Continue anyway is offered",
                        bool(b.run(f"return !!({CONTINUE})")),
                    )
                    if host == PLAIN[0]:
                        got = b.run(COLOURS)
                        name, _extra, paper, accent = VARIANTS[0]
                        check(
                            f"{name}: page colour",
                            got[0] == paper,
                            f"{got[0]} != {paper}",
                        )
                        check(
                            f"{name}: main button colour",
                            got[1] == accent,
                            f"{got[1]} != {accent}",
                        )

                heard = [
                    h
                    for h in server.seen
                    if h in (PLAIN[0], RN[0], CYRILLIC[0], EMBEDDED[0])
                    or h in dict(HOSTED)
                ]
                check("no request went to a warned site", not heard, repr(heard))

                # Go to the real site. It does not exist here, so the page
                # fails to load, and the address is what is checked.
                open_url(b, url(PLAIN[0]))
                wait_for(b, WARNED)
                b.run(f"({BUTTON % repr('Go to paypal.com')}).click()")
                deadline = time.monotonic() + 10
                went = ""
                while time.monotonic() < deadline:
                    try:
                        went = b.current_url()
                    except RuntimeError:
                        went = ""
                    if went.startswith("https://paypal.com"):
                        break
                    time.sleep(0.3)
                check(
                    "Go to paypal.com goes to the real site",
                    went == "https://paypal.com/",
                    went,
                )

                # --- a copy with no real site to name ----------------------
                open_url(b, url(ORDINARY[0]))
                wait_for(b, "!!document.getElementById('ok')")
                before = b.current_url()
                open_url(b, url(NO_TARGET))
                shown = wait_for(b, WARNED)
                check(f"{NO_TARGET}: the warning shows", shown)
                body = text(b) if shown else ""
                check(
                    "it says the address is copying another site",
                    "copying another site" in body,
                    body[:200],
                )
                check(
                    "Go back to safety is the main action",
                    bool(b.run(f"return !!({BUTTON % repr('Go back to safety')})"))
                    and bool(
                        b.run("return !!document.querySelector('button.primary')")
                    ),
                )
                b.run(f"({BUTTON % repr('Go back to safety')}).click()")
                time.sleep(2)
                try:
                    now = b.current_url()
                except RuntimeError:
                    now = ""
                check(
                    "Go back to safety leaves for the page before",
                    now == before,
                    f"{now} != {before}",
                )

                # --- ordinary sites -------------------------------------
                for host in [*ORDINARY, *HOSTED_ORDINARY]:
                    open_url(b, url(host))
                    loaded = wait_for(b, "!!document.getElementById('ok')", 10000)
                    check(
                        f"{host}: opens with no warning",
                        loaded and not b.run(f"return !!({WARNED})"),
                        f"{b.current_url()}: {text(b)[:150]!r}",
                    )

                # --- continue anyway ------------------------------------
                heard_before = server.seen.count(RN[0])
                open_url(b, url(RN[0]))
                wait_for(b, WARNED)
                b.run(f"({CONTINUE}).click()")
                check(
                    "Continue anyway opens the site",
                    wait_for(b, "!!document.getElementById('ok')", 10000),
                    b.current_url(),
                )
                check(
                    "only now did the site hear of the visit",
                    server.seen.count(RN[0]) > heard_before,
                )
                open_url(b, url(RN[0]))
                check(
                    "a second visit has no warning",
                    wait_for(b, "!!document.getElementById('ok')", 10000)
                    and not b.run(f"return !!({WARNED})"),
                )

                # --- the switches ---------------------------------------
                b.get("chrome://boring-protection")
                wait_for(
                    b,
                    "document.getElementById('ads-state').textContent === 'On'",
                    10000,
                )
                check(
                    "Warn about scam tricks is on and says it covers names",
                    bool(
                        b.run(
                            "return document.getElementById('warn-scam-tricks').checked"
                        )
                    )
                    and "name copies another" in b.run(WARN_LABEL),
                )
                b.run("document.getElementById('no-bypass').click()")
                check(
                    "No way past scam warnings turns on",
                    switch_is(b, "no-bypass", True),
                )
                open_url(b, url(CYRILLIC[0]))
                shown = wait_for(b, WARNED)
                check("no way past: the warning still shows", shown)
                check(
                    "no way past: Continue anyway is gone",
                    not b.run(f"return !!({CONTINUE})"),
                )
                check(
                    "no way past: the main button is still there",
                    bool(b.run(f"return !!({BUTTON % repr('Go to apple.com')})")),
                )
                check(
                    "no way past: the page says why",
                    "cannot be opened from this warning" in text(b),
                )

                b.get("chrome://boring-protection")
                wait_for(
                    b,
                    "document.getElementById('ads-state').textContent === 'On'",
                    10000,
                )
                b.run("document.getElementById('warn-scam-tricks').click()")
                check(
                    "Warn about scam tricks turns off",
                    switch_is(b, "warn-scam-tricks", False),
                )
                heard_before = server.seen.count(EMBEDDED[0])
                open_url(b, url(EMBEDDED[0]))
                check(
                    "switch off: a look-alike opens with no warning",
                    wait_for(b, "!!document.getElementById('ok')", 10000)
                    and not b.run(f"return !!({WARNED})"),
                    b.current_url(),
                )
                check(
                    "switch off: the site is asked",
                    server.seen.count(EMBEDDED[0]) > heard_before,
                )

            # --- dark ----------------------------------------------------
            name, extra, paper, accent = VARIANTS[1]
            with (
                tempfile.TemporaryDirectory(prefix="lookalike-", dir=tmp) as dark,
                Browser(user_data_dir=dark, args=browser_args(extra)) as b,
            ):
                open_url(b, url(PLAIN[0]))
                wait_for(b, WARNED)
                got = b.run(COLOURS)
                check(f"{name}: page colour", got[0] == paper, f"{got[0]} != {paper}")
                check(
                    f"{name}: main button colour",
                    got[1] == accent,
                    f"{got[1]} != {accent}",
                )
    finally:
        server.close()

    if failures:
        print(f"{len(failures)} failed")
        return 1
    print("all look-alike warning checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
