#!/usr/bin/env python3
"""Check that the scam warning wall works.

Navigates to a host that is always on the test blocklist. The warning
page must appear instead of the site. Then checks that Senior Safe Mode
removes the continue link.
"""

import sys
import time

from drive import Browser

PROFILE = r"E:\ung\testprofile"
BAD_URL = "http://boring-scam-test.invalid/"


def wait_for_block(b):
    for _ in range(20):
        b.get(BAD_URL)
        text = b.run("return document.body ? document.body.innerText : ''")
        if "dangerous" in text:
            return text
        time.sleep(2)
    return text


def main():
    failures = []

    with Browser(user_data_dir=PROFILE) as b:
        text = wait_for_block(b)
        if "dangerous" in text:
            print("PASS: warning wall shows for a listed site")
        else:
            failures.append("no warning wall; page text: " + text[:200])
        if "continue anyway" in text:
            print("PASS: normal mode offers the continue link")
        else:
            failures.append("normal mode is missing the continue link")

    with Browser(user_data_dir=PROFILE, args=["--senior-safe-mode"]) as b:
        text = wait_for_block(b)
        if "dangerous" in text and "continue anyway" not in text:
            print("PASS: Senior Safe Mode hides the continue link")
        else:
            failures.append("senior mode text wrong: " + text[:200])

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("PASS: scam protection works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
