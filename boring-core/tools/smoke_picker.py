#!/usr/bin/env python3
"""Check the element picker ("Block this element" on the shield).

The picker is started the way the shield starts it, through
StartElementPicker in the browser. A test cannot click the shield, so
the browser runs with --boring-element-picker-test, and a page opened
at #boring-test-element-picker asks the browser to start the picker on
itself (components/boring/adblock/element_picker.h). Everything after
that is WebDriver in the page: pointer and key actions that Chromium
dispatches into the page, never input to the desktop.

Checked:

  - the picker comes up on request, and a click on an element does not
    reach the page (the link under it is not followed)
  - Block (pressed with Enter, where the focus goes after a pick) hides
    the element at once and leaves the rest of the page alone
  - the rule "host##selector" lands in boring.adblock.custom_rules
  - on the next visit, and after a restart, the element is still hidden
  - Escape cancels: nothing is hidden and no rule is added
  - without the test switch, the fragment does nothing

Usage: python smoke_picker.py
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

PREF = "boring.adblock.custom_rules"
TEST_SWITCH = "--boring-element-picker-test"
FRAGMENT = "#boring-test-element-picker"

LISTS = {
    "easylist.txt": (
        "[Adblock Plus 2.0]\n! Title: boring picker smoke test\n"
        "##.boring-control-ad\n"
    ),
    "ubo.txt": "! Title: boring picker smoke test, nothing here\n",
    "cookies.txt": "! Title: boring picker smoke test, no cookie rules\n",
}

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>picker test</title>
<style>
  body { margin: 0; font: 16px sans-serif; }
  .card { display: block; width: 300px; height: 120px; margin: 40px;
          background: #eee; }
</style>
<div class="boring-control-ad">control ad</div>
<a id="promo" class="card promo-card" href="/followed.html">Sponsored offer</a>
<div id="keep" class="card">Something to keep</div>
<div id="other" class="card">Something else to keep</div>
"""

FOLLOWED = "<!doctype html><title>followed</title><p>followed</p>"

# The picker's host: a div added to <html>, above everything. Its shadow
# root is closed, so the test only sees that it is there.
PICKER_UP = (
    "Array.from(document.documentElement.children).some(e => e.localName === "
    "'div' && e.style.zIndex === '2147483647')"
)

ENTER = ""
ESCAPE = ""


def actions(b, sources):
    b._req("POST", f"/session/{b.sid}/actions", {"actions": sources})
    b._req("DELETE", f"/session/{b.sid}/actions")


def click_at(b, selector):
    """A mouse click in the middle of the element, as page input."""
    rect = b.run(
        "var r = document.querySelector(arguments[0]).getBoundingClientRect();"
        "return [Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2)]",
        [selector],
    )
    actions(
        b,
        [
            {
                "type": "pointer",
                "id": "mouse",
                "parameters": {"pointerType": "mouse"},
                "actions": [
                    {"type": "pointerMove", "origin": "viewport", "x": rect[0],
                     "y": rect[1], "duration": 0},
                    {"type": "pause", "duration": 100},
                    {"type": "pointerDown", "button": 0},
                    {"type": "pointerUp", "button": 0},
                ],
            }
        ],
    )


def press(b, key):
    actions(
        b,
        [
            {
                "type": "key",
                "id": "keyboard",
                "actions": [
                    {"type": "keyDown", "value": key},
                    {"type": "keyUp", "value": key},
                ],
            }
        ],
    )


def rules(profile):
    return get_profile_pref(profile, PREF, "") or ""


def main():
    check = Checks()
    pages = Pages({"/page.html": (PAGE, HTML), "/followed.html": (FOLLOWED, HTML)})
    page = pages.url(TEST_SITE, "/page.html")
    try:
        with (
            list_folder(LISTS) as lists,
            tempfile.TemporaryDirectory(prefix="picker-") as profile,
        ):
            args = browser_args(lists, extra=[TEST_SWITCH])
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(page)
                check(
                    "the engine is running",
                    wait_for(b, hidden_expr(".boring-control-ad"), 30000),
                )

                # Escape first: cancelling must change nothing. A new
                # query each time, so the fragment is a fresh page load
                # and not a jump within the same page.
                b.get(page + "?pick=1" + FRAGMENT)
                check("the picker comes up", wait_for(b, PICKER_UP))
                click_at(b, "#other")
                press(b, ESCAPE)
                check("Escape closes the picker", wait_for(b, "!" + PICKER_UP))
                check(
                    "a cancelled pick hides nothing",
                    b.run(f"return {shown_expr('#other')}"),
                )

                b.get(page + "?pick=2" + FRAGMENT)
                check("the picker comes up again", wait_for(b, PICKER_UP))
                click_at(b, "#promo")
                check(
                    "the click did not reach the page (link not followed)",
                    not wait_for(b, "location.pathname === '/followed.html'", 1500)
                    and b.run("return location.pathname") == "/page.html",
                )
                press(b, ENTER)
                check(
                    "Block hides the element at once",
                    wait_for(b, hidden_expr("#promo")),
                )
                check("the picker closes", wait_for(b, "!" + PICKER_UP))
                check(
                    "the rest of the page stays",
                    b.run(
                        f"return {shown_expr('#keep')} && {shown_expr('#other')}"
                    ),
                )

                b.get(page)
                check(
                    "on the next visit it is still hidden",
                    wait_for(b, hidden_expr("#promo"), 15000),
                )

            saved = rules(profile)
            check(
                "the rule is saved as host##selector",
                any(
                    line.startswith(f"{TEST_SITE}##")
                    for line in saved.splitlines()
                ),
                repr(saved),
            )
            check(
                "only one rule was added (Escape added none)",
                len([ln for ln in saved.splitlines() if ln.strip()]) == 1,
                repr(saved),
            )

            with Browser(user_data_dir=profile, args=args) as b:
                hidden = False
                for _ in range(10):
                    b.get(page)
                    if wait_for(b, hidden_expr("#promo"), 2000):
                        hidden = True
                        break
                check("after a restart it is still hidden", hidden)
                check(
                    "and the rest still shows",
                    b.run(f"return {shown_expr('#keep')}"),
                )

            # Without the switch a page cannot start the picker.
            with Browser(user_data_dir=profile, args=browser_args(lists)) as b:
                b.get(page + "?pick=3" + FRAGMENT)
                check(
                    "without the test switch the fragment does nothing",
                    not wait_for(b, PICKER_UP, 3000),
                )
    finally:
        pages.close()
    return check.result("the element picker blocks what is picked, and saves it")


if __name__ == "__main__":
    sys.exit(main())
