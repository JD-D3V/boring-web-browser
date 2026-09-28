#!/usr/bin/env python3
"""Check a person's own filter rules (boring.adblock.custom_rules).

Serves a local page with its own test lists (see smoke_local.py). The
main list hides one element and blocks one script; the custom rules
are written into the profile between runs, the way the Protection page
stores them. Checked:

  - with no custom rules, the list's hide and block apply, and an
    element nobody names shows
  - a custom hide rule hides that element
  - custom exceptions win over the lists: a #@# exception shows the
    element the list hides, and an @@ exception lets the script the
    list blocks load
  - taking the custom rules out again puts the lists back in charge

Usage: python smoke_custom_rules.py
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

PREF = "boring.adblock.custom_rules"

LISTS = {
    "easylist.txt": (
        "[Adblock Plus 2.0]\n! Title: boring custom rules smoke test\n"
        "##.boring-control-ad\n"
        f"{TEST_SITE}##.boring-listed\n"
        f"||{THIRD_PARTY}^*/tracker.js$script\n"
    ),
    "ubo.txt": "! Title: boring custom rules smoke test, nothing here\n",
    "cookies.txt": "! Title: boring custom rules smoke test, no cookie rules\n",
}

HIDE_RULES = f"! mine\n{TEST_SITE}##.boring-mine\n"
EXCEPTION_RULES = (
    f"{TEST_SITE}##.boring-mine\n"
    f"{TEST_SITE}#@#.boring-listed\n"
    f"@@||{THIRD_PARTY}^*/tracker.js$script\n"
)

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>custom rules test</title>
<div class="boring-control-ad">control ad</div>
<div class="boring-listed">hidden by the list</div>
<div class="boring-mine">hidden by my own rule</div>
<p id="content">The article.</p>
"""

LOAD_TRACKER = """
var done = arguments[1];
var s = document.createElement('script');
s.src = arguments[0] + '?t=' + Date.now();
s.onload = function() { done('loaded'); };
s.onerror = function() { done('blocked'); };
document.head.appendChild(s);
"""


def engine_running(b):
    return wait_for(b, hidden_expr(".boring-control-ad"), timeout_ms=30000)


def tracker(b, pages):
    return b.run_async(LOAD_TRACKER, [pages.url(THIRD_PARTY, "/tracker.js")])


def reload_until(b, page, condition, tries=10):
    """The custom rules engine is built in the background after start,
    so give it a few page loads to arrive."""
    for _ in range(tries):
        b.get(page)
        engine_running(b)
        if wait_for(b, condition, timeout_ms=1500):
            return True
    return False


def main():
    check = Checks()
    pages = Pages({"/page.html": (PAGE, HTML), "/tracker.js": ("window.t = 1;\n", JS)})
    page = pages.url(TEST_SITE, "/page.html")
    try:
        with (
            list_folder(LISTS) as lists,
            tempfile.TemporaryDirectory(prefix="custom-rules-") as profile,
        ):
            args = browser_args(lists)
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running", engine_running(b))
                check(
                    "the list hides its element",
                    wait_for(b, hidden_expr(".boring-listed")),
                )
                check(
                    "with no rules of my own, my element shows",
                    b.run(f"return {shown_expr('.boring-mine')}"),
                )
                result = tracker(b, pages)
                check("the list blocks its script", result == "blocked", result)

            set_profile_pref(profile, PREF, HIDE_RULES)
            with Browser(user_data_dir=profile, args=args) as b:
                check(
                    "my own hide rule hides my element",
                    reload_until(b, page, hidden_expr(".boring-mine")),
                )
                check(
                    "the list still hides its element",
                    b.run(f"return {hidden_expr('.boring-listed')}"),
                )
                check("the article stays", b.run(f"return {shown_expr('#content')}"))

            set_profile_pref(profile, PREF, EXCEPTION_RULES)
            with Browser(user_data_dir=profile, args=args) as b:
                check(
                    "my #@# exception shows what the list hides",
                    reload_until(
                        b,
                        page,
                        f"{shown_expr('.boring-listed')} && "
                        f"{hidden_expr('.boring-mine')}",
                    ),
                )
                result = tracker(b, pages)
                check(
                    "my @@ exception lets the list's blocked script load",
                    result == "loaded",
                    result,
                )

            set_profile_pref(profile, PREF, "")
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check("the engine is running again", engine_running(b))
                check(
                    "without my rules, the list hides its element again",
                    wait_for(b, hidden_expr(".boring-listed")),
                )
                check(
                    "and my element shows again",
                    b.run(f"return {shown_expr('.boring-mine')}"),
                )
                result = tracker(b, pages)
                check(
                    "and the list blocks its script again",
                    result == "blocked",
                    result,
                )
    finally:
        pages.close()
    return check.result("my own rules hide, and my exceptions win over the lists")


if __name__ == "__main__":
    sys.exit(main())
