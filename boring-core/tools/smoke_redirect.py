#!/usr/bin/env python3
"""Check $redirect: a matching script gets uBO's stub instead.

A local page loads three scripts from a third party host on this
machine. The server's real scripts each announce themselves, so the
page can tell which one it got:

  - /player/noop-me.js       $redirect=noop.js
    the stub loads (onload, not onerror) and the real script never runs
  - /pagead/adsbygoogle.js   $redirect=googlesyndication_adsbygoogle.js
    the stub runs: window.adsbygoogle is uBO's {loaded: true} object
  - /player/plain.js         no rule, the real script runs

The stubs come from the shipped resources.json.

Usage: python smoke_redirect.py
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
    list_folder,
    resources_shipped,
    wait_for,
)

# "^" after the host, not "/": the local server's port sits between
# the two, and "||host/" would never match "host:port/".
LISTS = {
    "easylist.txt": (
        "[Adblock Plus 2.0]\n"
        "! Title: boring redirect smoke test\n"
        f"||{THIRD_PARTY}^*/noop-me.js$script,redirect=noop.js\n"
    ),
    "ubo.txt": (
        "! Title: boring redirect smoke test, uBO syntax\n"
        f"||{THIRD_PARTY}^*/adsbygoogle.js$script,"
        "redirect=googlesyndication_adsbygoogle.js\n"
    ),
    "cookies.txt": "! Title: boring redirect smoke test, no cookie rules\n",
}

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>redirect test</title>
<h1>redirect test</h1>
"""

# Loads one script and says how it went: "loaded" or "error".
LOAD = """
var url = arguments[0];
var done = arguments[1];
var s = document.createElement('script');
s.src = url + '?' + Math.random();
s.onload = function() { done('loaded'); };
s.onerror = function() { done('error'); };
document.head.append(s);
"""


def main():
    check = Checks()
    if not resources_shipped(check):
        return check.result("")
    pages = Pages(
        {
            "/page.html": (PAGE, HTML),
            "/player/noop-me.js": ("window.boringRealNoop = true;", JS),
            "/pagead/adsbygoogle.js": (
                "window.adsbygoogle = {real: true, loaded: false};",
                JS,
            ),
            "/player/plain.js": ("window.boringRealPlain = true;", JS),
        }
    )
    try:
        with (
            list_folder(LISTS) as lists,
            tempfile.TemporaryDirectory(prefix="redirect-") as profile,
            Browser(user_data_dir=profile, args=browser_args(lists)) as b,
        ):
            b.get(pages.url(TEST_SITE, "/page.html"))

            plain = b.run_async(LOAD, [pages.url(THIRD_PARTY, "/player/plain.js")])
            check(
                "a script no rule names loads for real",
                plain == "loaded" and b.run("return window.boringRealPlain === true"),
                plain,
            )

            # The engine loads in the background at startup; retry
            # until the real script stops getting through.
            noop = "error"
            for _ in range(15):
                b.get(pages.url(TEST_SITE, "/page.html"))
                noop = b.run_async(LOAD, [pages.url(THIRD_PARTY, "/player/noop-me.js")])
                if noop == "loaded" and not b.run("return !!window.boringRealNoop"):
                    break
                wait_for(b, "false", timeout_ms=1000)
            check("the redirected script loads, it is not an error", noop == "loaded")
            check(
                "the real script did not run",
                not b.run("return !!window.boringRealNoop"),
            )

            ads = b.run_async(LOAD, [pages.url(THIRD_PARTY, "/pagead/adsbygoogle.js")])
            check("the adsbygoogle stub loads", ads == "loaded", ads)
            state = b.run(
                "var a = window.adsbygoogle;"
                "return a ? {loaded: a.loaded === true, real: a.real === true,"
                " push: typeof a.push} : null"
            )
            check(
                "the page sees the stub's behaviour",
                bool(state) and state["loaded"] and state["push"] == "function",
                str(state),
            )
            check(
                "and not the real script's",
                bool(state) and not state["real"],
                str(state),
            )
    finally:
        pages.close()
    return check.result("$redirect serves the stub, not the script and not an error")


if __name__ == "__main__":
    sys.exit(main())
