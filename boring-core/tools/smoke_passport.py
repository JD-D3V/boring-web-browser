#!/usr/bin/env python3
"""Smoke test: the Passport (ledger item 13, compiled screens C04, C05, C12).

Runs the real browser with --boring-passport-test and a temp profile under
E:\\tmp. Test names (citylibrary.net, parcel-redelivery.net, royalpost.net,
rnyalpost.net, plain.net) are mapped to a local server by
--host-resolver-rules, and every other name to nowhere, so nothing leaves
the machine. (The design's .example names are reserved names, which the
Passport rightly leaves alone, like Chromium's look-alike checks do.)
Commands go through the new tab page's chrome.send('passportTest', ...), the
way smoke_search_menu.py works; no input from the OS.

What it asserts:
  1. A new site: chip "New to you" in the warn tones; UI Automation finds a
     button named "New to you" on our window.
  2. Its Passport: "New to you. Take a moment.", the host from the address
     (never the page's title, which says "A site you know" here), the
     first-visit row first, no "connection is private" row, Leave this site
     and I know this site, a footer.
  3. Look-alike: royalpost.net engaged, rnyalpost.net says it looks like it.
  4. Known by history: two earlier visits, then "Known site", "A site you
     know", "3 times since <month>", Site settings and Forget this site.
  5. I know this site: the mark is kept, the chip says Known site at once.
  6. Forget this site: the question, Cancel keeps the mark, Forget drops it.
  7. Leave this site: the tab shows the new tab page, no extra history entry.
  8. Site settings: Chromium's page info opens.
  9. Not private (http): Chromium's "Not secure" stays, no chip of ours, the
     Passport still opens and says "The connection is not private."
 10. Internal page (the new tab page): no chip, no Passport.
 11. Card details: a page with cc-number and cc-csc fields gets the row "This
     page asks for card details."; one with only name fields does not, and
     the fact does not follow to the next page.
 12. Captures: PrintWindow of our window with the Passport open on steps 2
     and 4, light and dark, beside C05 and C04 (--captures).
Not checked here: the Blocked chip (needs the
scam list setup of smoke_scam.py), Incognito and guest windows.

Usage: python boring-core/tools/smoke_passport.py [--out DIR] [--captures DIR]
"""

import argparse
import contextlib
import datetime
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import page_checks
from capture_native import frame_window, grab
from drive import CHROME, Browser
from smoke_local import Checks
from smoke_site_panel import Window

TEST_SWITCH = "--boring-passport-test"
OPENSSL = r"C:\Program Files\Git\usr\bin\openssl.exe"
NAMES = ["citylibrary.net", "parcel-redelivery.net", "royalpost.net", "rnyalpost.net", "plain.net"]
NEW, KNOWN = 2, 1


class _Page(BaseHTTPRequestHandler):
    def do_GET(self):
        # A hostile title: the Passport must never show it.
        body = b"<!doctype html><title>A site you know</title><p>A page.</p>"
        # Two forms for the card fact: one with card fields named by their
        # autocomplete words, one with only name fields. Never submitted.
        if self.path.startswith("/pay"):
            body = (b"<!doctype html><title>Pay</title><form>"
                    b"<input autocomplete='cc-name'><input autocomplete='cc-number'>"
                    b"<input autocomplete='cc-exp'><input autocomplete='cc-csc'>"
                    b"</form>")
        elif self.path.startswith("/names"):
            body = (b"<!doctype html><title>Names</title><form>"
                    b"<input autocomplete='given-name'><input autocomplete='family-name'>"
                    b"<input autocomplete='email'></form>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.hosts.add(self.headers.get("Host", "").split(":")[0])

    def log_message(self, *args):
        pass


def serve(cert_dir, tls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    server.hosts = set()
    if tls:
        key, crt = Path(cert_dir) / "key.pem", Path(cert_dir) / "crt.pem"
        subprocess.run(
            [OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
             "-subj", "/CN=passport.test", "-keyout", str(key), "-out", str(crt)],
            check=True, capture_output=True,
        )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(crt), str(key))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def hook(b, *command, timeout=5.0):
    """Run one test command on the new tab page and return its answer."""
    b.run("window.lastPassportTest = '__pending__';"
          "chrome.send('passportTest', arguments[0]);", [list(command)])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = b.run("return window.lastPassportTest")
        if result != "__pending__":
            return result
        time.sleep(0.05)
    return None


def open_newtab(b):
    b.get("chrome://newtab")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if b.run("return typeof window.passportTestResult === 'function'"):
            return True
        time.sleep(0.1)
    return False


def go(b, url):
    """Open `url` in the test tab and wait until its facts are in."""
    hook(b, "navigate", url)
    deadline = time.monotonic() + 10
    state = {}
    while time.monotonic() < deadline:
        state = hook(b, "passportState") or {}
        if state.get("activeUrl", "").startswith(url) and state.get("pending") == 0:
            break
        time.sleep(0.1)
    time.sleep(0.3)  # the address field's update after the last answer
    return state


def popup(b):
    hook(b, "closePopup")
    time.sleep(0.4)
    hook(b, "pressChip")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        state = hook(b, "passportPopup") or {}
        if state.get("open"):
            return state
        time.sleep(0.1)
    return hook(b, "passportPopup") or {}


def texts(state):
    return [f.get("text") for f in state.get("facts", [])]


def shoot(out, name, screen, dark, folder, checks):
    try:
        hwnd = frame_window(CHROME, under=os.getpid())
    except (LookupError, RuntimeError, OSError) as e:
        checks(f"{name}: our window to photograph", False, str(e))
        return
    time.sleep(0.8)  # past the drop-in motion
    path = Path(out) / f"passport-{name}-{'dark' if dark else 'light'}.png"
    grab(hwnd, str(path))
    print("saved", path)
    both = page_checks.save_capture(path, "passport", screen, dark=dark, folder=folder,
                                    label=f"{screen.lower()}-{name}")
    if both:
        print("saved", both)


def run(base, out, captures, dark, checks, full):
    theme = "dark" if dark else "light"
    rules = ", ".join(f"MAP {n} 127.0.0.1" for n in NAMES) + ", MAP * ~NOTFOUND"
    args = [TEST_SWITCH, f"--host-resolver-rules={rules}", "--ignore-certificate-errors",
            "--window-size=1280,800"]
    if dark:
        args.append("--force-dark-mode")
    https, http = base
    with tempfile.TemporaryDirectory(prefix="passport-", dir=r"E:\tmp") as profile, \
            Browser(user_data_dir=profile, args=args) as b:
        checks(f"{theme}: new tab page hook is ready", open_newtab(b))
        hook(b, "engage", f"https://royalpost.net:{https}/", 50)
        hook(b, "addVisit", f"https://citylibrary.net:{https}/", 30)
        hook(b, "addVisit", f"https://citylibrary.net:{https}/books", 2)
        checks(f"{theme}: test tab opens",
               (hook(b, "openTab", f"https://parcel-redelivery.net:{https}/track") or {}).get("opened"))

        # 1, 2. New to you.
        new_url = f"https://parcel-redelivery.net:{https}/track"
        go(b, new_url)
        chip = hook(b, "chipState") or {}
        checks(f"{theme}: new site chip says New to you", chip.get("text") == "New to you", str(chip))
        checks(f"{theme}: new site chip is in the warn tone", chip.get("textColor") == "warn", str(chip))
        checks(f"{theme}: chip's accessible name is its word", chip.get("a11yName") == "New to you", str(chip))
        checks(f"{theme}: chip is drawn 28 high", chip.get("height") == 28, str(chip))
        if full:
            try:
                with Window(frame_window(CHROME, under=os.getpid())) as w:
                    names = w.names()
                checks("UI Automation finds the New to you button", "New to you" in names, str(names)[:300])
            except (LookupError, RuntimeError, OSError) as e:
                checks("UI Automation finds the New to you button", False, str(e))
        state = popup(b)
        checks(f"{theme}: Passport opens from the chip", state.get("open"), str(state))
        checks(f"{theme}: verdict New to you. Take a moment.",
               state.get("verdict") == "New to you. Take a moment.", str(state.get("verdict")))
        host = state.get("host", "")
        checks(f"{theme}: host comes from the address", host.startswith("parcel-redelivery.net"), host)
        checks(f"{theme}: the page's title is never shown",
               "A site you know" not in [state.get("verdict"), host], str(state))
        facts = texts(state)
        checks(f"{theme}: first row is the first visit",
               facts[:1] == ["This is the first time you have visited this site."], str(facts))
        checks(f"{theme}: no reassuring connection row", "The connection is private." not in facts, str(facts))
        checks(f"{theme}: Leave this site and I know this site",
               state.get("buttons") == ["Leave this site", "I know this site"], str(state.get("buttons")))
        footer = state.get("footer", "")
        checks(f"{theme}: footer says what was blocked",
               footer.startswith("Blocked on this page") or footer == "Nothing blocked on this page.", footer)
        checks(f"{theme}: Passport is 384 wide or more", state.get("width", 0) >= 384, str(state.get("width")))
        shoot(out, "new", "C05", dark, captures, checks)

        # 4. Known by history.
        go(b, f"https://citylibrary.net:{https}/")
        chip = hook(b, "chipState") or {}
        checks(f"{theme}: visited site chip says Known site", chip.get("text") == "Known site", str(chip))
        state = popup(b)
        checks(f"{theme}: verdict A site you know", state.get("verdict") == "A site you know", str(state))
        first = datetime.date.today() - datetime.timedelta(days=30)
        month = first.strftime("%B") + ("" if first.year == datetime.date.today().year else f" {first.year}")
        want = f"You have visited this site 3 times since {month}."
        checks(f"{theme}: visit count and month", want in texts(state), f"{want} / {texts(state)}")
        checks(f"{theme}: Site settings and Forget this site",
               state.get("buttons") == ["Site settings", "Forget this site"], str(state.get("buttons")))
        shoot(out, "known", "C04", dark, captures, checks)
        if not full:
            return

        # 8. Site settings opens Chromium's page info.
        hook(b, "pressButton", "Site settings")
        time.sleep(0.5)
        checks("Site settings opens page info", (hook(b, "passportPopup") or {}).get("pageInfoShowing"))
        hook(b, "closePopup")

        # 6a. Card details: a page with card fields says so, one with only
        # name fields says nothing (absence is never stated as safety).
        go(b, f"https://royalpost.net:{https}/pay")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not (hook(b, "passportState") or {}).get("asksCard"):
            time.sleep(0.1)
        checks("card page: the helper saw the card fields",
               (hook(b, "passportState") or {}).get("asksCard") is True)
        state = popup(b)
        checks("card page: the Passport says it asks for card details",
               "This page asks for card details." in texts(state), str(texts(state)))
        hook(b, "closePopup")
        go(b, f"https://royalpost.net:{https}/names")
        time.sleep(1.5)  # long enough for autofill to have parsed the form
        checks("name fields only: no card fact",
               (hook(b, "passportState") or {}).get("asksCard") is False)
        state = popup(b)
        checks("name fields only: the Passport has no card row",
               "This page asks for card details." not in texts(state), str(texts(state)))
        hook(b, "closePopup")
        # Sticky per page, reset by the next page.
        go(b, f"https://royalpost.net:{https}/pay")
        time.sleep(1)
        go(b, f"https://royalpost.net:{https}/names")
        checks("the card fact does not follow to the next page",
               (hook(b, "passportState") or {}).get("asksCard") is False)

        # 3. Look-alike of a site you use.
        go(b, f"https://rnyalpost.net:{https}/")
        state = popup(b)
        checks("look-alike row names the site you use",
               "It looks like royalpost.net, a site you use, but it is not the same." in texts(state),
               str(texts(state)))

        # 7. Leave this site.
        before = (hook(b, "passportState") or {}).get("entries")
        hook(b, "pressButton", "Leave this site")
        time.sleep(1.5)
        after = hook(b, "passportState") or {}
        checks("Leave this site shows the new tab page",
               "newtab" in after.get("activeUrl", ""), after.get("activeUrl", ""))
        checks("Leave this site replaces the page", after.get("entries") == before,
               f"{before} -> {after.get('entries')}")

        # 5. I know this site.
        go(b, new_url)
        popup(b)
        hook(b, "pressButton", "I know this site")
        time.sleep(0.5)
        known = (hook(b, "knownSites") or {}).get("sites", [])
        checks("the mark is kept", known == ["parcel-redelivery.net"], str(known))
        chip = hook(b, "chipState") or {}
        checks("chip says Known site at once", chip.get("text") == "Known site", str(chip))

        # 6. Forget this site: ask, Cancel, then Forget.
        popup(b)
        hook(b, "pressButton", "Forget this site")
        state = hook(b, "passportPopup") or {}
        checks("Forget asks first", state.get("question") == "Forget this site? You will be signed out of it.",
               str(state))
        hook(b, "pressButton", "Cancel")
        state = hook(b, "passportPopup") or {}
        checks("Cancel brings the buttons back",
               state.get("buttons") == ["Site settings", "Forget this site"], str(state))
        checks("Cancel keeps the mark", (hook(b, "knownSites") or {}).get("sites") == ["parcel-redelivery.net"])
        hook(b, "pressButton", "Forget this site")
        hook(b, "pressButton", "Forget")
        time.sleep(2)
        checks("Forget drops the mark", (hook(b, "knownSites") or {}).get("sites") == [])

        # 9. Not private: Chromium's words stay, the Passport still opens.
        go(b, f"http://plain.net:{http}/")
        chip = hook(b, "chipState") or {}
        checks("http page keeps the field's own text, no chip of ours",
               chip.get("chip") == 0 and chip.get("text") == "", str(chip))
        state = popup(b)
        checks("the Passport still opens on http", state.get("open"), str(state))
        checks("it says the connection is not private",
               "The connection is not private." in texts(state), str(texts(state)))
        hook(b, "closePopup")

        # 10. Internal page.
        hook(b, "navigate", "chrome://version")
        time.sleep(1)
        chip = hook(b, "chipState") or {}
        checks("no chip on an internal page", chip.get("chip") == 0 and chip.get("layout") == 0, str(chip))
        hook(b, "closeTab")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\tmp\passport-shots")
    page_checks.add_captures_option(ap)
    args = ap.parse_args()
    Path(args.out).mkdir(parents=True, exist_ok=True)
    checks = Checks()
    with tempfile.TemporaryDirectory(prefix="passport-cert-", dir=r"E:\tmp") as certs:
        https = serve(certs, tls=True)
        http = serve(certs, tls=False)
        base = (https.server_address[1], http.server_address[1])
        try:
            run(base, args.out, args.captures, False, checks, full=True)
            run(base, args.out, args.captures, True, checks, full=False)
        finally:
            https.shutdown()
            http.shutdown()
        seen = https.hosts | http.hosts
        checks("only our test names reached the local server", seen <= set(NAMES), str(seen))
    return checks.result("passport")


if __name__ == "__main__":
    sys.exit(main())
