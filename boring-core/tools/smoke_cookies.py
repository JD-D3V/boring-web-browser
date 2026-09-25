#!/usr/bin/env python3
"""Check "Hide cookie notices" on the Protection page.

A local page shows a cookie banner that only the test cookie list
names, plus an element the main test list hides, which proves the
engine is running whatever happens to the banner. Checked:

  - off by default: the banner shows, and the switch on the
    Protection page is off
  - the switch is a real checkbox with its label, and turning it on
    is saved in the profile
  - after a restart with it on, the banner is hidden (a generic rule
    and a site rule, both from cookies.txt)
  - turned off again from the page and restarted, the banner shows

Whether the change applies to pages without a restart is printed as a
NOTE, not counted: it depends on when the engine reads the pref.

Usage: python smoke_cookies.py
"""

import sys
import tempfile

from drive import Browser
from smoke_local import (
    HTML,
    TEST_SITE,
    Checks,
    Pages,
    browser_args,
    get_profile_pref,
    hidden_expr,
    list_folder,
    shown_expr,
    wait_for,
)

PREF = "boring.adblock.hide_cookie_notices"

LISTS = {
    "easylist.txt": (
        "[Adblock Plus 2.0]\n! Title: boring cookie smoke test\n##.boring-control-ad\n"
    ),
    "ubo.txt": "! Title: boring cookie smoke test, nothing here\n",
    "cookies.txt": (
        "[Adblock Plus 2.0]\n"
        "! Title: boring cookie smoke test, cookie rules\n"
        "##.boring-cookie-banner\n"
        f"{TEST_SITE}###boring-cookie-dialog\n"
    ),
}

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>cookie test</title>
<h1>cookie test</h1>
<div class="boring-control-ad">control ad</div>
<div class="boring-cookie-banner">We use cookies. <button>Accept</button></div>
<div id="boring-cookie-dialog">Cookie settings</div>
<p id="content">The article.</p>
"""

BANNER = ".boring-cookie-banner"
DIALOG = "#boring-cookie-dialog"


def engine_running(b):
    """True once the main list hides its control element."""
    return wait_for(b, hidden_expr(".boring-control-ad"), timeout_ms=30000)


def banner_state(b, want_hidden, timeout_ms=5000):
    """True when both cookie elements are hidden (or both shown)."""
    expr = hidden_expr if want_hidden else shown_expr
    return wait_for(b, f"{expr(BANNER)} && {expr(DIALOG)}", timeout_ms=timeout_ms)


def open_switch(b):
    b.get("chrome://boring-protection")
    return wait_for(b, "!!document.getElementById('hide-cookies')")


def main():
    check = Checks()
    pages = Pages({"/page.html": (PAGE, HTML)})
    page = pages.url(TEST_SITE, "/page.html")
    try:
        with (
            list_folder(LISTS) as lists,
            tempfile.TemporaryDirectory(prefix="cookies-") as profile,
        ):
            args = browser_args(lists)
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running", engine_running(b))
                # Give a wrong hide every chance to happen first.
                check(
                    "off by default, the banner shows",
                    not wait_for(
                        b, f"{hidden_expr(BANNER)} || {hidden_expr(DIALOG)}", 3000
                    ),
                )

                check("the Protection page has the switch", open_switch(b))
                control = b.run(
                    "var e = document.getElementById('hide-cookies');"
                    "var l = document.querySelector('label[for=hide-cookies]');"
                    "return {type: e.type, checked: e.checked,"
                    " label: l ? l.textContent.trim() : ''}"
                )
                check(
                    "it is a real checkbox, off, labelled Hide cookie notices",
                    control
                    == {
                        "type": "checkbox",
                        "checked": False,
                        "label": "Hide cookie notices",
                    },
                    str(control),
                )
                b.run("document.getElementById('hide-cookies').click()")
                check(
                    "the switch turns on",
                    wait_for(b, "document.getElementById('hide-cookies').checked"),
                )

                # Not counted: see the docstring.
                b.get(page)
                engine_running(b)
                live = banner_state(b, want_hidden=True, timeout_ms=8000)
                print(
                    "NOTE: without a restart the banner is "
                    + ("hidden" if live else "still shown")
                )

            check("the setting is saved", get_profile_pref(profile, PREF) is True)

            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running after a restart", engine_running(b))
                check(
                    "with the switch on, the banner is hidden",
                    banner_state(b, want_hidden=True, timeout_ms=15000),
                )
                check(
                    "the article itself stays",
                    b.run(f"return {shown_expr('#content')}"),
                )

                check(
                    "the switch shows on",
                    open_switch(b)
                    and b.run("return document.getElementById('hide-cookies').checked"),
                )
                b.run("document.getElementById('hide-cookies').click()")
                check(
                    "the switch turns off",
                    wait_for(b, "!document.getElementById('hide-cookies').checked"),
                )

            check("turning it off is saved", get_profile_pref(profile, PREF) is False)

            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running again", engine_running(b))
                check(
                    "with the switch off again, the banner shows",
                    not wait_for(
                        b, f"{hidden_expr(BANNER)} || {hidden_expr(DIALOG)}", 4000
                    ),
                )
    finally:
        pages.close()
    return check.result("cookie notices are hidden only when the switch is on")


if __name__ == "__main__":
    sys.exit(main())
