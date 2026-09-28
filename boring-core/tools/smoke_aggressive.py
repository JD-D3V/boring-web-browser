#!/usr/bin/env python3
"""Check the Aggressive blocking level adds its lists, and only then.

Serves a local page with its own test lists (see smoke_local.py). The
Aggressive lists (aggressive-ubo.txt, trusted, and aggressive-fanboy.txt)
hide an annoyance and block a social widget script. Checked:

  - Standard (the default): the main list works, the annoyance shows
    and the widget script loads
  - Aggressive (boring.adblock.level 1): both are blocked, from both
    Aggressive files
  - back to Standard: both come back, so the level really switches the
    lists off again

Usage: python smoke_aggressive.py
"""

import sys
import tempfile

from drive import Browser
from smoke_local import (
    HTML,
    JS,
    TEST_SITE,
    THIRD_PARTY,
    Checks,
    Pages,
    browser_args,
    hidden_expr,
    list_folder,
    set_profile_pref,
    shown_expr,
    wait_for,
)

PREF = "boring.adblock.level"

LISTS = {
    "easylist.txt": (
        "[Adblock Plus 2.0]\n! Title: boring aggressive smoke test\n"
        "##.boring-control-ad\n"
    ),
    "ubo.txt": "! Title: boring aggressive smoke test, nothing here\n",
    "cookies.txt": "! Title: boring aggressive smoke test, no cookie rules\n",
    "aggressive-ubo.txt": (
        "! Title: boring aggressive smoke test, annoyances\n"
        f"{TEST_SITE}##.boring-newsletter-popup\n"
    ),
    "aggressive-fanboy.txt": (
        "[Adblock Plus 2.0]\n! Title: boring aggressive smoke test, social\n"
        f"||{THIRD_PARTY}/share-widget.js^$script\n"
    ),
}

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>aggressive test</title>
<div class="boring-control-ad">control ad</div>
<div class="boring-newsletter-popup">Sign up for our newsletter</div>
<p id="content">The article.</p>
"""

WIDGET = "window.boringWidgetRan = true;\n"

# Loads the widget script and answers "loaded" or "blocked".
LOAD_WIDGET = """
var done = arguments[1];
var s = document.createElement('script');
s.src = arguments[0] + '?t=' + Date.now();
s.onload = function() { done('loaded'); };
s.onerror = function() { done('blocked'); };
document.head.appendChild(s);
"""


def engine_running(b):
    return wait_for(b, hidden_expr(".boring-control-ad"), timeout_ms=30000)


def widget(b, pages):
    return b.run_async(LOAD_WIDGET, [pages.url(THIRD_PARTY, "/share-widget.js")])


def main():
    check = Checks()
    pages = Pages(
        {"/page.html": (PAGE, HTML), "/share-widget.js": (WIDGET, JS)}
    )
    page = pages.url(TEST_SITE, "/page.html")
    try:
        with (
            list_folder(LISTS) as lists,
            tempfile.TemporaryDirectory(prefix="aggressive-") as profile,
        ):
            args = browser_args(lists)
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running", engine_running(b))
                check(
                    "Standard: the annoyance shows",
                    not wait_for(
                        b, hidden_expr(".boring-newsletter-popup"), timeout_ms=3000
                    ),
                )
                result = widget(b, pages)
                check("Standard: the widget script loads", result == "loaded", result)

            set_profile_pref(profile, PREF, 1)
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running on Aggressive", engine_running(b))
                # The Aggressive engine is built when the profile first
                # asks, so give it a few loads to arrive.
                hidden = False
                for _ in range(10):
                    b.get(page)
                    if wait_for(
                        b, hidden_expr(".boring-newsletter-popup"), timeout_ms=2000
                    ):
                        hidden = True
                        break
                check("Aggressive: the annoyance is hidden (uBO list)", hidden)
                result = widget(b, pages)
                check(
                    "Aggressive: the widget script is blocked (Fanboy list)",
                    result == "blocked",
                    result,
                )
                check(
                    "Aggressive: the article stays",
                    b.run(f"return {shown_expr('#content')}"),
                )

            set_profile_pref(profile, PREF, 0)
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running back on Standard", engine_running(b))
                check(
                    "back on Standard: the annoyance shows",
                    not wait_for(
                        b, hidden_expr(".boring-newsletter-popup"), timeout_ms=3000
                    ),
                )
                result = widget(b, pages)
                check(
                    "back on Standard: the widget script loads",
                    result == "loaded",
                    result,
                )
    finally:
        pages.close()
    return check.result("Aggressive adds its lists, and only when it is on")


if __name__ == "__main__":
    sys.exit(main())
