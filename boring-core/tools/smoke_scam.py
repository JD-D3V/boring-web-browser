#!/usr/bin/env python3
"""Check that this version does not pretend to block scam sites.

v1 ships no scam blocklist. No feed gives permission to redistribute
one, so the capability is off (components/boring/core/boring_capabilities.h)
and the browser has to say so rather than imply protection it has not
got.

So this checks the opposite of what it used to: a listed host must NOT
be walled off, because there is no list, and the Protection page must
state plainly that scam blocking is not in this version. The warning
page itself is still built and still tested by its own unit tests; what
is missing is data, not code.

When a redistributable feed is in place, flip kScamBlockingAvailable and
this file goes back to checking the wall appears.
"""

import sys

from drive import PROFILE, Browser

BAD_URL = "http://boring-scam-test.invalid/"
PROTECTION_URL = "chrome://boring-protection"


def page_text(b):
    return b.run("return document.body ? document.body.innerText : ''")


def main():
    failures = []

    with Browser(user_data_dir=PROFILE) as b:
        # The host does not resolve, and with no blocklist to intercept
        # it the navigation fails outright. WebDriver reports a failed
        # navigation as an error, so that error is the pass: it means
        # nothing stepped in front of the request. A warning wall would
        # have committed a page and returned normally.
        blocked_by_us = False
        try:
            b.get(BAD_URL)
            text = page_text(b)
            if "dangerous" in text.lower():
                blocked_by_us = True
        except RuntimeError as e:
            if "ERR_NAME_NOT_RESOLVED" not in str(e):
                raise
            text = ""

        if blocked_by_us:
            failures.append(
                "a scam warning appeared, so a blocklist is present in a "
                "build that ships none: " + text[:200]
            )
        else:
            print("PASS: no warning wall, because no list ships")

        b.get(PROTECTION_URL)
        protection = page_text(b)
        # No list ships, so no warning page: the row must say that the
        # protection is Quad9's resolver and that nothing warns first.
        if "Quad9" in protection and "no warning page" in protection:
            print(
                "PASS: the Protection page credits Quad9 "
                "and says there is no warning page"
            )
        else:
            failures.append(
                "the Protection page does not say how dangerous sites are "
                "blocked in this version: " + protection[:300]
            )
        if "Scam & phishing sites" not in protection:
            failures.append("the Protection page no longer names the scam row at all")
        # Ads and trackers are unaffected and must still be claimed.
        if "Ads & trackers" in protection:
            print("PASS: ad and tracker blocking is still on the page")
        else:
            failures.append("the Protection page lost its ads and trackers row")

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("PASS: the browser is honest about having no scam list")
    return 0


if __name__ == "__main__":
    sys.exit(main())
