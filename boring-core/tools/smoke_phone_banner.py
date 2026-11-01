#!/usr/bin/env python3
r"""Check the phone number banner in the real build.

A page that is a scary warning showing a phone number ("your computer is
infected, call Microsoft now") gets a quiet bar: "Real companies do not
put phone numbers in pop-up warnings." An ordinary contact page or a news
story about these scams, even with the same words and a number, does not.
When the bar shows, the tab counts as one that looked like a scam, so a
remote access download in it gets the strong wording from the scam guards.
Covered by the "Warn about scam tricks" switch.

Test pages are phone_banner.html (?mode=), served from a *.localhost name
(HTTPS-Only is on, and localhost names are the plain-http ones it leaves
alone). The browser runs headless and input goes through DevTools, never
to the desktop. A bar is native browser UI, which WebDriver cannot see, so
the browser is started with logging on and each bar says its wording in
the log, as in smoke_scam_guards.py, whose session and server this reuses.

Needs BORING_OUT, as the other smoke tests do.
"""

import os
import sys
from pathlib import Path

import smoke_scam_guards
from smoke_scam_guards import (
    ASK,
    ASK_STRONG,
    GET_ME_OUT,
    Session,
    click,
    serve,
    steady,
    wait,
)

# Profiles and downloads go in this test's own folder, not the guards'.
smoke_scam_guards.WORK = (
    Path(os.environ.get("TMP", r"E:\tmp")) / "feat-phone-banner" / "smoke"
)

# The wording, as decided. A change here is a change to what people read.
NOTICE = "Real companies do not put phone numbers in pop-up warnings."


def banners(s):
    return s.bars().count(NOTICE)


def page(s, mode):
    s.b.get(f"{s.base}/phone_banner.html?mode={mode}")
    return wait(lambda: s.b.run("return document.body.children.length > 0"))


def ordinary_pages(s, checks):
    """Pages with the words and a number, but not laid out as a warning."""
    for mode, label in (
        ("contact", "a shop contact page"),
        ("news", "a news story about the scam"),
        ("weak", "a plain page that says call Windows Support"),
    ):
        checks[f"{label} loads"] = page(s, mode)
        # Two looks are taken, at load and three seconds later.
        checks[f"{label} gets no banner"] = steady(lambda: banners(s) == 0, 6)


def scam_pages(s, checks):
    checks["scam page loads"] = page(s, "scam")
    checks["scam page gets the banner"] = wait(lambda: banners(s) == 1, timeout=15)
    checks["the banner is shown once"] = steady(lambda: banners(s) == 1, 5)
    checks["the banner is the quiet notice, not a question"] = ASK not in s.bars()

    # Same tab, a remote tool download: the strong wording.
    s.download("anydesk")
    checks["remote tool after the banner: strong wording"] = wait(
        lambda: ASK_STRONG in s.bars()
    )
    checks["remote tool after the banner: not the plain wording"] = ASK not in s.bars()

    # A tab with no banner is still asked in the plain words.
    s.open_tab()
    s.download("anydesk")
    checks["remote tool in a clean tab: plain wording"] = wait(lambda: ASK in s.bars())

    # A pop-up that appears a moment after load is found by the second look.
    before = banners(s)
    s.open_tab()
    checks["late page loads"] = page(s, "late")
    checks["a pop-up built after load gets the banner"] = wait(
        lambda: banners(s) == before + 1, timeout=15
    )


def after_a_takeover(port, checks):
    """A tab that tripped the takeover detector needs much less."""
    with Session("tripped", port, answer="safe") as s:
        s.open_tab()
        s.b.get(f"{s.base}/takeover_scam.html?mode=all")
        click(s.b, 200, 200)

        def tripped():
            s.accept_alert()
            return s.b.current_url().startswith(GET_ME_OUT)

        checks["takeover page trips"] = wait(tripped, timeout=30, step=0.4)
        if not checks["takeover page trips"]:
            return
        checks["tripped tab: weak page loads"] = page(s, "weak")
        checks["tripped tab: the weak page gets the banner"] = wait(
            lambda: banners(s) == 1, timeout=15
        )


def switch_off(port, checks):
    """The Protection switch turns the banner off, live."""
    with Session("off", port) as s:
        s.b.get("chrome://boring-protection")
        ready = wait(
            lambda: s.b.run("return !!document.getElementById('warn-scam-tricks')")
        )
        checks["Protection has the switch"] = ready
        if not ready:
            return
        s.b.run("document.getElementById('warn-scam-tricks').click()")
        s.b.get("chrome://boring-protection")
        checks["the switch is off"] = wait(
            lambda: s.b.run("return document.getElementById('warn-scam-tricks').checked")
            is False
        )
        checks["switch off: scam page loads"] = page(s, "scam")
        checks["switch off: no banner"] = steady(lambda: banners(s) == 0, 7)


def main():
    checks = {}
    srv = serve()
    port = srv.server_address[1]
    try:
        with Session("main", port, answer=None) as s:
            ordinary_pages(s, checks)
            scam_pages(s, checks)
        after_a_takeover(port, checks)
        switch_off(port, checks)
    finally:
        srv.shutdown()

    ok = all(checks.values())
    for name, passed in checks.items():
        print(("PASS " if passed else "FAIL ") + name)
    print("smoke_phone_banner:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
