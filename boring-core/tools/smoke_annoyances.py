#!/usr/bin/env python3
"""Check "block page annoyances": the switch and the two lists it uses.

Serves local pages with their own test lists (see smoke_local.py). The
page has a newsletter pop-up, a sticky sign-up footer, a body that will
not scroll (overflow: hidden) and a script that steals the scroll back
to the top. annoyances.txt (Fanboy's Newsletter List in a real build)
hides the pop-up and footer and lifts the scroll lock; aggressive-ubo.txt
(uBO's Annoyances, trusted) stops the scroll stealing with the shipped
aeld scriptlet. Checked:

  - on by default: all four are dealt with, the article stays, and the
    switch on the Protection page is on
  - turned off from the page: saved, and after a restart all four are
    back as the page made them
  - turned on again, with blocking off for one site from the shield:
    that site is left alone and the other is still cleaned up

Usage: python smoke_annoyances.py
"""

import sys
import tempfile

from drive import Browser
from smoke_local import (
    HTML,
    OTHER_SITE,
    TEST_SITE,
    Checks,
    Pages,
    browser_args,
    get_profile_pref,
    hidden_expr,
    list_folder,
    resources_shipped,
    set_profile_pref,
    shown_expr,
    wait_for,
)

PREF = "boring.block_annoyances"
OFF_SITES_PREF = "boring.blocking_off_sites"
SITES = f"{TEST_SITE},{OTHER_SITE}"

LISTS = {
    "easylist.txt": (
        "[Adblock Plus 2.0]\n! Title: boring annoyances smoke test\n"
        "##.boring-control-ad\n"
    ),
    "ubo.txt": "! Title: boring annoyances smoke test, nothing here\n",
    "cookies.txt": "! Title: boring annoyances smoke test, no cookie rules\n",
    "aggressive-ubo.txt": (
        "! Title: boring annoyances smoke test, uBO annoyances\n"
        f"{SITES}##+js(aeld, scroll)\n"
    ),
    "annoyances.txt": (
        "[Adblock Plus 2.0]\n! Title: boring annoyances smoke test, newsletter\n"
        "##.boring-newsletter-modal\n"
        f"{SITES}##.boring-sticky-footer\n"
        f"{SITES}##body.boring-scroll-lock:style(overflow: auto !important)\n"
    ),
}

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>annoyances test</title>
<style>
  body.boring-scroll-lock { overflow: hidden; }
  .boring-newsletter-modal { position: fixed; top: 20%; left: 20%; right: 20%;
    padding: 2em; background: #fff; border: 1px solid #000; }
  .boring-sticky-footer { position: fixed; bottom: 0; left: 0; right: 0; }
</style>
<body class="boring-scroll-lock">
<div class="boring-control-ad">control ad</div>
<div class="boring-newsletter-modal">Sign up for our newsletter</div>
<div class="boring-sticky-footer">Subscribe today</div>
<p id="content">The article.</p>
<div style="height: 4000px"></div>
<script>
window.__scrollStolen = false;
window.addEventListener('scroll', function() {
  window.__scrollStolen = true;
  window.scrollTo(0, 0);
});
</script>
</body>
"""

MODAL = ".boring-newsletter-modal"
FOOTER = ".boring-sticky-footer"
UNLOCKED = "getComputedStyle(document.body).overflowY !== 'hidden'"


def engine_running(b):
    return wait_for(b, hidden_expr(".boring-control-ad"), timeout_ms=30000)


def scroll_kept(b):
    """Scrolls down; True when nothing on the page pulled it back."""
    b.run("window.scrollTo(0, 800); return 1")
    stolen = wait_for(b, "window.__scrollStolen === true", timeout_ms=1500)
    return not stolen and b.run("return window.scrollY") > 400


def cleaned(b, url, tries=10):
    """True once the page loads with all four annoyances dealt with. The
    annoyance engine is built when a profile first asks, so a few loads
    may pass before it is there."""
    for _ in range(tries):
        b.get(url)
        if wait_for(
            b, f"{hidden_expr(MODAL)} && {hidden_expr(FOOTER)} && {UNLOCKED}", 2000
        ):
            return scroll_kept(b)
    return False


def untouched(b, url):
    """True when the page keeps all four, as it made them. Check that
    the engine runs first: a page left alone proves nothing otherwise."""
    b.get(url)
    if wait_for(
        b, f"{hidden_expr(MODAL)} || {hidden_expr(FOOTER)} || {UNLOCKED}", 3000
    ):
        return False
    b.run("window.scrollTo(0, 800); return 1")
    return wait_for(b, "window.__scrollStolen === true", timeout_ms=3000)


def open_switch(b):
    b.get("chrome://boring-protection")
    return wait_for(b, "!!document.getElementById('hide-annoyances')")


def main():
    check = Checks()
    if not resources_shipped(check):
        return check.result("")
    pages = Pages({"/page.html": (PAGE, HTML)})
    page = pages.url(TEST_SITE, "/page.html")
    other = pages.url(OTHER_SITE, "/page.html")
    try:
        with (
            list_folder(LISTS) as lists,
            tempfile.TemporaryDirectory(prefix="annoyances-") as profile,
        ):
            args = browser_args(lists)

            # On by default.
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running", engine_running(b))
                check(
                    "on by default: pop-up and footer hidden, scroll lock "
                    "lifted, scroll not stolen",
                    cleaned(b, page),
                )
                check(
                    "the article itself stays",
                    b.run(f"return {shown_expr('#content')}"),
                )

                check("the Protection page has the switch", open_switch(b))
                control = b.run(
                    "var e = document.getElementById('hide-annoyances');"
                    "var l = document.querySelector('label[for=hide-annoyances]');"
                    "return {type: e.type, checked: e.checked,"
                    " label: l ? l.textContent.trim().toLowerCase() : ''}"
                )
                check(
                    "it is a real checkbox, on, labelled for annoyances",
                    control["type"] == "checkbox"
                    and control["checked"] is True
                    and "annoyances" in control["label"],
                    str(control),
                )
                b.run("document.getElementById('hide-annoyances').click()")
                check(
                    "the switch turns off",
                    wait_for(b, "!document.getElementById('hide-annoyances').checked"),
                )

            check("turning it off is saved", get_profile_pref(profile, PREF) is False)

            # Off: the page keeps all four.
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running after a restart", engine_running(b))
                check(
                    "with the switch off, pop-up, footer, lock and stealing stay",
                    untouched(b, page),
                )
                check(
                    "the switch shows off",
                    open_switch(b)
                    and b.run(
                        "return !document.getElementById('hide-annoyances').checked"
                    ),
                )
                b.run("document.getElementById('hide-annoyances').click()")
                check(
                    "the switch turns on again",
                    wait_for(b, "document.getElementById('hide-annoyances').checked"),
                )

            check("turning it on is saved", get_profile_pref(profile, PREF) is True)

            # On, with blocking off for one site: that site is left alone.
            set_profile_pref(profile, OFF_SITES_PREF, [OTHER_SITE])
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running once more", engine_running(b))
                check("on a site with blocking on, it is cleaned up", cleaned(b, page))
                check(
                    "on a site with blocking off, the page keeps all four",
                    untouched(b, other),
                )
    finally:
        pages.close()
    return check.result(
        "page annoyances are blocked only when the switch is on and the "
        "site's blocking is on"
    )


if __name__ == "__main__":
    sys.exit(main())
