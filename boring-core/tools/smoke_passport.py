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
  3. Look-alike: royalpost.net engaged, rnyalpost.net says it looks like it;
     after the page's own history.replaceState the row and chip stay (53).
  4. Known by history: two earlier visits, then "Known site", "A site you
     know", "3 times since <month>", Site settings and Forget this site.
  4a. Ledger 58: with the tab set to have first shown a site 5 days ago,
     link visits seeded on days 3 and 2 count no day (chip New to you,
     never Known); typed visits on days 4 and 1 make it Known site.
  5. I know this site: the mark is kept, the chip says Known site at once.
  6. Forget this site: the question, Cancel keeps the mark, Forget drops it.
  7. Leave this site: the tab shows the new tab page, no extra history entry.
  8. Site settings: Chromium's page info opens.
  9. Not private (http, HTTPS-First off in this profile): Chromium's "Not
     secure" stays, no chip of ours, the Passport still opens and says "The
     connection is not private." Item 52, the chip only ever where Chromium
     says SECURE: an https page with a form posting to http (Chromium 157
     keeps it SECURE at load and after typing; sending it brings Chromium's
     insecure-form warning page, with no chip), an http image on an https
     page (not SECURE, no chip), and an error page (no chip). The test
     certificate is trusted by its key hash, so the other https pages are
     plainly SECURE.
 10. Internal page (the new tab page): no chip, no Passport.
 11. Card details: a page with cc-number and cc-csc fields gets the row "This
     page asks for card details."; one with only name fields does not, and
     the fact does not follow to the next page.
 12. Captures: PrintWindow of our window with the Passport open on steps 2
     and 4, light and dark, beside C05 and C04 (--captures).
 13. Warning pages and other windows (run_warnings, run_windows): the Blocked
     chip on a scam-listed host (a test list like smoke_scam.py's) with no
     Passport pop-up; no chip of ours on a certificate warning page, the
     HTTPS-First warning page, a file page or a data page; the chip in a private window, a guest window and a
     pop-up, none in an app window (which has no address field).
Not checked here: the Scam list chip (after "Continue anyway"), the
registration date (left out).

Usage: python boring-core/tools/smoke_passport.py [--out DIR] [--captures DIR]
"""

import argparse
import base64
import contextlib
import datetime
import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import page_checks
from capture_native import frame_window, grab
from drive import CHROME, Browser
from smoke_local import Checks, list_folder, wait_for
from smoke_memory import close, launch
from smoke_site_panel import Window, browser_windows

# Who started the browser in hand: chromedriver (drive.Browser) or this script.
UNDER = [None]


def our_pid():
    return UNDER[0] or os.getpid()


TEST_SWITCH = "--boring-passport-test"
OPENSSL = r"C:\Program Files\Git\usr\bin\openssl.exe"
NAMES = ["citylibrary.net", "parcel-redelivery.net", "royalpost.net", "rnyalpost.net", "plain.net",
         "selfmade.net", "jsoff-passport.net"]
# Ledger 59 (S-D7): a site where the person blocked JavaScript (seeded in
# Preferences as a Site settings exception).
JS_OFF_HOST = "jsoff-passport.net"
NEW, KNOWN = 2, 1
SECURE = 3  # security_state::SECURE
# A 1x1 PNG for the mixed content page.
DOT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


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
        elif self.path.startswith("/mixedform"):
            # An https page whose form posts to http (?to=the http port).
            # Chromium 157 keeps such a page SECURE (the mixed-forms warning
            # pref is on by default, chrome_security_state_util.cc) and stops
            # the submission with its own insecure-form warning page instead.
            # ?edit=1 types into the field, ?submit=1 sends the form.
            query = parse_qs(urlparse(self.path).query)
            to = query.get("to", ["80"])[0]
            script = b""
            if "edit" in query:
                script += (b"var f=document.querySelector('input');f.focus();f.value='x';"
                           b"f.dispatchEvent(new Event('input',{bubbles:true}));")
            if "submit" in query:
                script += b"setTimeout(function(){document.forms[0].submit();},500);"
            body = (b"<!doctype html><title>A site you know</title>"
                    b"<form action='http://plain.net:" + to.encode("ascii") + b"/send' method='post'>"
                    b"<input name='q'></form><script>" + script + b"</script>")
        elif self.path.startswith("/mixedimage"):
            # An https page showing an http image: Chromium's displayed mixed
            # content state (the profile allows insecure content, or Chromium
            # would fetch it over https). Not 127.0.0.1: a loopback address
            # counts as trustworthy, so it would not be mixed content.
            to = parse_qs(urlparse(self.path).query).get("to", ["80"])[0]
            body = (b"<!doctype html><title>A site you know</title><p>A page.</p>"
                    b"<img src='http://plain.net:" + to.encode("ascii") + b"/river-photo.png' width='40' height='40'>")
        elif self.path.startswith("/river-photo.png"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(DOT_PNG)))
            self.end_headers()
            self.wfile.write(DOT_PNG)
            self.server.hosts.add(self.headers.get("Host", "").split(":")[0])
            return
        elif self.path.startswith("/replace"):
            # The page rewrites its own address after load, the way a
            # look-alike would try to drop the Passport's warnings.
            body = (b"<!doctype html><title>A site you know</title><p>A page.</p>"
                    b"<script>setTimeout(function () {"
                    b"history.replaceState(null, '', '/replaced?x=1#top');}, 300);</script>")
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

    def do_POST(self):
        # Only the http form would post here; Chromium's warning must stop it.
        POSTS.append(self.path)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


POSTS = []


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
        server.spki = spki_hash(crt)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def spki_hash(crt):
    """The certificate's public key hash, for --ignore-certificate-errors-spki-list.
    That switch makes the page plainly SECURE; the blanket
    --ignore-certificate-errors keeps the error bits, so Chromium (rightly)
    marks the page not secure and no chip of ours shows (item 52)."""
    pub = subprocess.run([OPENSSL, "x509", "-in", str(crt), "-pubkey", "-noout"],
                         check=True, capture_output=True).stdout
    der = subprocess.run([OPENSSL, "pkey", "-pubin", "-outform", "der"], input=pub,
                         check=True, capture_output=True).stdout
    return base64.b64encode(hashlib.sha256(der).digest()).decode("ascii")


def trust_flag(base):
    return f"--ignore-certificate-errors-spki-list={base[2]}"


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


LINE_TOKEN = {False: "#e2dfd9", True: "#2d2d2a"}  # Window.dc.html TOKENS line


def button_look(state, theme, dark, outline, checks):
    """Screens C04, C05: the outline button has ink text and the edge on the
    pop-up's own surface, nothing has focus when the pop-up opens, and the
    hairlines between the fact rows are the line token (default Look)."""
    look = {b.get("label"): b for b in state.get("buttonLook", [])}
    button = look.get(outline, {})
    checks(f"{theme}: {outline} is an outline button with ink text",
           button.get("textInk") and button.get("edge") and button.get("onSurface")
           and not button.get("solid"), str(button))
    checks(f"{theme}: no button shows a focus ring when the pop-up opens",
           bool(look) and not any(b.get("focused") for b in look.values()), str(look))
    checks(f"{theme}: the fact rows' hairline is the line token",
           state.get("line") == LINE_TOKEN[dark], str(state.get("line")))


def shoot(out, name, screen, dark, folder, checks):
    try:
        hwnd = frame_window(CHROME, under=our_pid())
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
    args = [TEST_SWITCH, f"--host-resolver-rules={rules}", trust_flag(base),
            "--window-size=1280,800"]
    if dark:
        args.append("--force-dark-mode")
    https, http = base[:2]
    with tempfile.TemporaryDirectory(prefix="passport-", dir=r"E:\tmp") as profile:
        seed_profile(profile, https)
        run_in(b_args=args, profile=profile, base=base, out=out, captures=captures, dark=dark,
               checks=checks, full=full)


def seed_profile(profile, https=None):
    """HTTPS-First (on by default) puts Chromium's own warning page in front
    of every http page; step 9 is about the http page a person reaches past
    it, so this profile has it off, the way smoke_lookalike.py seeds it. The
    warning page itself is checked in run_warnings.
    It also allows insecure content (Site settings, "Insecure content"),
    which is what stops Chromium upgrading an http image to https: step 9c
    needs real mixed content on the page.
    With `https`, JavaScript is blocked for JS_OFF_HOST (Site settings,
    "JavaScript", Not allowed) for ledger 59's card question check."""
    folder = Path(profile) / "Default"
    folder.mkdir(parents=True, exist_ok=True)
    content = {"default_content_setting_values": {"mixed_script": 1}}
    if https:
        content["content_settings"] = {"exceptions": {"javascript": {
            f"https://{JS_OFF_HOST}:{https},*": {"setting": 2}}}}
    (folder / "Preferences").write_text(json.dumps(
        {"https_only_mode_enabled": False, "https_first_balanced_mode_enabled": False,
         "profile": content}), encoding="utf-8")


def run_in(b_args, profile, base, out, captures, dark, checks, full):
    theme = "dark" if dark else "light"
    https, http = base[:2]
    with Browser(headful=True, user_data_dir=profile, args=b_args) as b:
        UNDER[0] = b.proc.pid  # chromedriver starts Chrome
        checks(f"{theme}: new tab page hook is ready", open_newtab(b))
        hook(b, "engage", f"https://royalpost.net:{https}/", 50)
        # Known by history needs two different earlier days (30 and 2 days ago).
        # The hook adds them as typed visits, the person's own (ledger 58);
        # they are before this tab ever showed the site, so either way counts.
        hook(b, "addVisit", f"https://citylibrary.net:{https}/", 30)
        hook(b, "addVisit", f"https://citylibrary.net:{https}/books", 2)
        # A blank test tab: opening it on the new site would be a visit of
        # its own, and "first time" would depend on how fast history wrote it.
        checks(f"{theme}: test tab opens", (hook(b, "openTab", "about:blank") or {}).get("opened"))

        # 1, 2. New to you.
        new_url = f"https://parcel-redelivery.net:{https}/track"
        go(b, new_url)
        chip = hook(b, "chipState") or {}
        checks(f"{theme}: the test certificate leaves the page SECURE",
               chip.get("securityLevel") == SECURE, str(chip))
        checks(f"{theme}: new site chip says New to you", chip.get("text") == "New to you", str(chip))
        checks(f"{theme}: new site chip is in the warn tone", chip.get("textColor") == "warn", str(chip))
        checks(f"{theme}: chip's accessible name is its word", chip.get("a11yName") == "New to you", str(chip))
        checks(f"{theme}: chip is drawn 28 high", chip.get("height") == 28, str(chip))
        if full:
            try:
                with Window(frame_window(CHROME, under=our_pid())) as w:
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
        button_look(state, theme, dark, "I know this site", checks)
        look = {b.get("label"): b for b in state.get("buttonLook", [])}
        checks(f"{theme}: Leave this site is the one solid button",
               look.get("Leave this site", {}).get("solid") is True, str(look))
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
        button_look(state, theme, dark, "Site settings", checks)
        look = {b.get("label"): b for b in state.get("buttonLook", [])}
        forget = look.get("Forget this site", {})
        checks(f"{theme}: Forget this site is quiet text on the pop-up's surface",
               forget.get("textQuiet") and forget.get("onSurface") and not forget.get("edge"),
               str(forget))
        shoot(out, "known", "C04", dark, captures, checks)
        if not full:
            return

        # 8. Site settings opens Chromium's page info.
        hook(b, "pressButton", "Site settings")
        time.sleep(0.5)
        checks("Site settings opens page info", (hook(b, "passportPopup") or {}).get("pageInfoShowing"))
        hook(b, "closePopup")

        # 4a. Ledger 58: a page cannot earn Known site with visits it made
        # itself. The tab is set to have first shown selfmade.net 5 days
        # ago; link visits on days 3 and 2 (after that, as a page reloading
        # itself past midnight would make) do not count.
        self_url = f"https://selfmade.net:{https}/"
        go(b, self_url)
        hook(b, "addVisit", self_url + "a", 3, "link")
        hook(b, "addVisit", self_url + "b", 2, "link")

        def settle_first_seen(days_ago):
            hook(b, "setFirstSeen", self_url, days_ago)
            deadline = time.monotonic() + 10
            state = {}
            while time.monotonic() < deadline:
                state = hook(b, "passportState") or {}
                if state.get("pending") == 0:
                    break
                time.sleep(0.1)
            time.sleep(0.3)
            return state

        state = settle_first_seen(5)
        chip = hook(b, "chipState") or {}
        print("self-made visits:", state, chip)
        checks("self-made link visits after the tab showed the site count no day",
               state.get("daysBeforeToday") == 0 and state.get("firstShownDaysAgo") == 5, str(state))
        checks("self-made link visits never make Known site",
               chip.get("text") in ("New to you", "") and chip.get("text") != "Known site", str(chip))
        # Visits the person typed on two earlier days do count.
        hook(b, "addVisit", self_url + "c", 4)
        hook(b, "addVisit", self_url + "d", 1)
        state = settle_first_seen(5)
        chip = hook(b, "chipState") or {}
        checks("typed visits on two earlier days make Known site",
               state.get("daysBeforeToday") == 2 and chip.get("text") == "Known site", f"{state} {chip}")

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
        # Ledger 59 (S-D7): the same card page on a site where JavaScript is
        # blocked: the card question is not asked.
        go(b, f"https://{JS_OFF_HOST}:{https}/pay")
        time.sleep(1.5)  # as long as the card page above needed
        checks("JavaScript blocked: no card fact",
               (hook(b, "passportState") or {}).get("asksCard") is not True,
               str(hook(b, "passportState")))
        state = popup(b)
        checks("JavaScript blocked: the Passport has no card row",
               "This page asks for card details." not in texts(state), str(texts(state)))
        hook(b, "closePopup")

        # 3. Look-alike of a site you use.
        go(b, f"https://rnyalpost.net:{https}/")
        state = popup(b)
        checks("look-alike row names the site you use",
               "It looks like royalpost.net, a site you use, but it is not the same." in texts(state),
               str(texts(state)))
        hook(b, "closePopup")

        # 3a. The look-alike rewrites its own address (history.replaceState):
        # the facts are the document's, so the warning row and the chip stay.
        go(b, f"https://rnyalpost.net:{https}/replace")
        deadline = time.monotonic() + 5
        state = {}
        while time.monotonic() < deadline:
            state = hook(b, "passportState") or {}
            if "/replaced?x=1#top" in state.get("activeUrl", ""):
                break
            time.sleep(0.1)
        time.sleep(0.3)
        checks("replaceState: the page did rewrite its address",
               "/replaced?x=1#top" in state.get("activeUrl", ""), str(state.get("activeUrl")))
        checks("replaceState: the look-alike fact is kept", state.get("lookalike") is True, str(state))
        chip = hook(b, "chipState") or {}
        checks("replaceState: the chip still says New to you", chip.get("text") == "New to you", str(chip))
        state = popup(b)
        checks("replaceState: the look-alike row stays",
               "It looks like royalpost.net, a site you use, but it is not the same." in texts(state),
               str(texts(state)))
        hook(b, "closePopup")
        go(b, f"https://rnyalpost.net:{https}/")

        # 7. Leave this site.
        before = (hook(b, "passportState") or {}).get("entries")
        popup(b)  # the button is the Passport's own
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

        # 9a. An https page of a known site with a form that posts to http.
        # Chromium 157 keeps it SECURE, at load and after typing (the
        # mixed-forms warning pref is on by default), so the chip may show
        # exactly as it does beside Chromium's lock. The chip follows the
        # level, whatever it is. Chromium marks the form when it is sent: its
        # insecure-form warning page, where no chip of ours may show.
        def chip_follows_level(label, chip):
            level = chip.get("securityLevel")
            ours = chip.get("chip") not in (None, 0)
            checks(f"{label}: a chip of ours only on a SECURE page", level == SECURE or not ours, str(chip))
        go(b, f"https://citylibrary.net:{https}/mixedform?to={http}")
        time.sleep(1)
        chip = hook(b, "chipState") or {}
        checks("http form on https: Chromium keeps it SECURE at load", chip.get("securityLevel") == SECURE,
               str(chip))
        chip_follows_level("http form on https, at load", chip)
        go(b, f"https://citylibrary.net:{https}/mixedform?to={http}&edit=1")
        time.sleep(1)
        chip = hook(b, "chipState") or {}
        checks("http form on https: Chromium keeps it SECURE after typing", chip.get("securityLevel") == SECURE,
               str(chip))
        chip_follows_level("http form on https, after typing", chip)
        hook(b, "navigate", f"https://citylibrary.net:{https}/mixedform?to={http}&submit=1")
        deadline = time.monotonic() + 8
        state = {}
        while time.monotonic() < deadline:
            state = hook(b, "passportState") or {}
            if state.get("activeUrl", "").startswith(f"http://plain.net:{http}/send"):
                break
            time.sleep(0.2)
        time.sleep(1)
        state = hook(b, "passportState") or {}
        chip = hook(b, "chipState") or {}
        checks("http form sent: Chromium's warning page is up",
               state.get("activeUrl", "").startswith(f"http://plain.net:{http}/send")
               and state.get("eligible") is False, str(state))
        checks("http form sent: no chip of ours", chip.get("chip") == 0 and chip.get("layout") == 0, str(chip))
        checks("http form sent: nothing was posted to http", "/send" not in POSTS, str(POSTS))
        # 9c. Real mixed content (an http image on an https page of a known
        # site): Chromium's not-fully-secure state, its icon, no chip of ours.
        go(b, f"https://citylibrary.net:{https}/mixedimage?to={http}")
        time.sleep(1.5)
        chip = hook(b, "chipState") or {}
        checks("mixed content: the page is not SECURE", chip.get("securityLevel") not in (None, SECURE), str(chip))
        checks("mixed content: no chip of ours", chip.get("chip") == 0 and chip.get("text") == "", str(chip))
        chip_follows_level("mixed content", chip)
        # Ledger 59 (S-D5): this known site is not SECURE here, so the
        # Passport never opens in the "A site you know" layout.
        state = popup(b)
        checks("not SECURE on a known site: the Passport is not in the A site you know layout",
               state.get("verdict") != "A site you know", str(state)[:300])
        hook(b, "closePopup")
        # 9b. An error page (the name goes nowhere): Chromium's icon, no chip.
        go(b, f"https://gone-passport.net:{https}/")
        time.sleep(1)
        chip = hook(b, "chipState") or {}
        checks("error page: no chip of ours", chip.get("chip") == 0 and chip.get("layout") == 0, str(chip))

        # 10. Internal page.
        hook(b, "navigate", "chrome://version")
        time.sleep(1)
        chip = hook(b, "chipState") or {}
        checks("no chip on an internal page", chip.get("chip") == 0 and chip.get("layout") == 0, str(chip))
        hook(b, "closeTab")


CHIP_NAMES = {"Known site", "New to you", "Blocked", "Scam list"}
SCAM_HOST = "scam-passport.net"
FILE_URL = Path(r"E:\tmp\passport-file-page.html")


def chip_names_of_ours(timeout=0.0):
    """The Passport chip names found on any window of ours, by UI Automation."""
    found = set()
    windows = 0
    deadline = time.monotonic() + timeout
    while True:
        windows = 0
        for hwnd in browser_windows(our_pid()):
            try:
                with Window(hwnd) as w:
                    windows += 1
                    found |= CHIP_NAMES & set(w.names())
            except (OSError, RuntimeError):
                continue
        if found or time.monotonic() >= deadline:
            return found, windows
        time.sleep(0.5)


def scam_list_text():
    """A scam list holding SCAM_HOST. The browser refuses one with fewer than
    10 hosts (kMinHosts), so it is padded the way smoke_scam.py pads it."""
    return ("# boring scam blocklist, test copy\n" + SCAM_HOST + "\n"
            "# --- test entries below this line, not protection ---\n"
            + "".join(f"boring-scam-pad-{i:02d}.invalid\n" for i in range(1, 12)))


def run_warnings(base, checks):
    """The Blocked chip on a scam-listed host, a certificate warning page, and
    file and data pages. No --ignore-certificate-errors here: the certificate
    page is the point, and the scam warning comes before any connection."""
    https, http = base[:2]
    rules = ", ".join(f"MAP {n} 127.0.0.1" for n in NAMES + [SCAM_HOST]) + ", MAP * ~NOTFOUND"
    FILE_URL.write_text("<!doctype html><title>A file</title><p>A file.</p>", encoding="utf-8")
    with list_folder({"scamlist.txt": scam_list_text()}) as lists, \
            tempfile.TemporaryDirectory(prefix="passport-", dir=r"E:\tmp") as profile, \
            Browser(headful=True, user_data_dir=profile, args=[
                TEST_SWITCH, f"--boring-list-dir={lists}", "--disable-boring-list-updates",
                f"--host-resolver-rules={rules}", "--window-size=1280,800"]) as b:
        UNDER[0] = b.proc.pid  # chromedriver starts Chrome
        checks("warnings: new tab page hook is ready", open_newtab(b))
        b.get("chrome://boring-protection")
        checks("warnings: the scam list loads", wait_for(
            b, "document.body.innerText.includes('blocked before they open')", 20000))
        open_newtab(b)
        checks("warnings: test tab opens",
               (hook(b, "openTab", f"https://{SCAM_HOST}:{https}/") or {}).get("opened"))

        # The scam warning page: the Blocked chip, in the bad tones, and no
        # Passport behind it (the chip opens Chromium's page info).
        go(b, f"https://{SCAM_HOST}:{https}/")
        time.sleep(1)
        state = hook(b, "passportState") or {}
        chip = hook(b, "chipState") or {}
        checks("scam warning page: it is our warning", state.get("blockedPage") is True, str(state))
        checks("scam warning page: chip says Blocked", chip.get("text") == "Blocked", str(chip))
        checks("scam warning page: chip is in the bad tone", chip.get("textColor") == "bad", str(chip))
        checks("scam warning page: chip is drawn 28 high", chip.get("height") == 28, str(chip))
        popup(b)
        shown = hook(b, "passportPopup") or {}
        checks("scam warning page: no Passport pop-up of ours", not shown.get("open"), str(shown))
        hook(b, "closePopup")

        # A certificate warning page: Chromium's own words stay, no chip of ours.
        go(b, f"https://plain.net:{https}/")
        time.sleep(1)
        chip = hook(b, "chipState") or {}
        checks("certificate warning page: no chip of ours", chip.get("chip") == 0 and chip.get("text") in ("", None),
               str(chip))

        # HTTPS-First (on by default here): an http address gets Chromium's
        # own warning page first. Chromium's icon, no chip, no Passport.
        go(b, f"http://plain.net:{http}/")
        time.sleep(1)
        state = hook(b, "passportState") or {}
        chip = hook(b, "chipState") or {}
        checks("HTTPS-First warning page: it is Chromium's page, not ours",
               state.get("eligible") is False and state.get("blockedPage") is False, str(state))
        checks("HTTPS-First warning page: no chip of ours", chip.get("chip") == 0 and chip.get("layout") == 0,
               str(chip))

        # File and data pages are not the web: no chip.
        for label, url in (("file page", FILE_URL.as_uri()),
                           ("data page", "data:text/html,%3Ctitle%3Eplain%3C/title%3E%3Cp%3Ehi")):
            hook(b, "navigate", url)
            time.sleep(1.5)
            state = hook(b, "passportState") or {}
            chip = hook(b, "chipState") or {}
            checks(f"{label}: it is the page that opened", state.get("activeUrl", "").startswith(url[:8]),
                   str(state.get("activeUrl")))
            checks(f"{label}: no chip", chip.get("chip") == 0 and chip.get("layout") == 0, str(chip))
        hook(b, "closeTab")


def run_windows(base, checks):
    """Where the chip shows and where it does not, by UI Automation on our own
    windows: a private window and a guest window show it (the Passport reads
    the normal profile's history and writes nothing), an app window has no
    address field and so no chip, a pop-up has its slim address bar."""
    https, http = base[:2]
    rules = ", ".join(f"MAP {n} 127.0.0.1" for n in NAMES) + ", MAP * ~NOTFOUND"
    flags = [f"--host-resolver-rules={rules}", trust_flag(base), "--window-size=1280,800"]
    site = f"https://parcel-redelivery.net:{https}/track"
    for label, extra in (("private window", ["--incognito"]), ("guest window", ["--guest"])):
        with tempfile.TemporaryDirectory(prefix="passport-", dir=r"E:\tmp") as profile, \
                Browser(headful=True, user_data_dir=profile, args=flags + extra) as b:
            UNDER[0] = b.proc.pid  # chromedriver starts Chrome
            b.get(site)
            found, windows = chip_names_of_ours(timeout=10)
            checks(f"{label}: our window was found", windows > 0)
            checks(f"{label}: a new public site gets its chip", "New to you" in found, str(found))
    with tempfile.TemporaryDirectory(prefix="passport-", dir=r"E:\tmp") as tmp:
        where = Path(tmp) / "app"
        (where / "Default").mkdir(parents=True)
        UNDER[0] = None  # launched by this script
        proc, cdp = launch(CHROME, where, flags + [f"--app={site}"], urls=())
        try:
            time.sleep(4)
            found, windows = chip_names_of_ours()
            checks("app window: our window was found", windows > 0)
            checks("app window: no chip", not found, str(found))
        finally:
            close(proc, cdp)
        where = Path(tmp) / "popup"
        (where / "Default").mkdir(parents=True)
        UNDER[0] = None  # launched by this script
        proc, cdp = launch(CHROME, where, flags)
        try:
            time.sleep(3)
            page = next(t for t in cdp.send("Target.getTargets")["targetInfos"] if t["type"] == "page")
            session = cdp.attach(page["targetId"])
            opened = cdp.send(
                "Runtime.evaluate", session, userGesture=True, returnByValue=True,
                expression=f"window.open({site!r}, 'passportpop', 'popup,width=520,height=420') ? 'opened' : 'blocked'")
            checks("pop-up: it opened", opened.get("result", {}).get("value") == "opened", str(opened))
            found, windows = chip_names_of_ours(timeout=12)
            checks("pop-up: a second window exists", windows >= 2, str(windows))
            checks("pop-up: its slim address bar carries the chip", "New to you" in found, str(found))
        finally:
            close(proc, cdp)


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
        base = (https.server_address[1], http.server_address[1], https.spki)
        try:
            run(base, args.out, args.captures, False, checks, full=True)
            run(base, args.out, args.captures, True, checks, full=False)
            run_warnings(base, checks)
            run_windows(base, checks)
        finally:
            https.shutdown()
            http.shutdown()
        seen = https.hosts | http.hosts
        checks("only our test names reached the local server", seen <= set(NAMES), str(seen))
    return checks.result("passport")


if __name__ == "__main__":
    sys.exit(main())
