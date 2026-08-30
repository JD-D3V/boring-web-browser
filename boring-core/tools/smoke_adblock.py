#!/usr/bin/env python3
"""Check that ad blocking works in the built browser.

From a real page, tries to fetch a known ad script and a normal page.
The ad request must fail, the normal one must pass. Uses no-cors mode so
a rejection can only mean the request was blocked, not a CORS rule.
"""

import sys
import time

from drive import Browser

PROFILE = r"E:\ung\testprofile"

FETCH = """
var url = arguments[0];
var done = arguments[1];
fetch(url, {mode: 'no-cors', cache: 'no-store'}).then(
  function() { done('loaded'); },
  function(e) { done('blocked'); });
"""

AD_URL = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"
OK_URL = "https://example.com/"


def main():
    with Browser(user_data_dir=PROFILE) as b:
        b.get("https://example.com")
        title = b.run("return document.title")
        print("page loads:", title)
        if "Example" not in title:
            print("FAIL: page did not load")
            return 1

        # The filter lists load in the background at startup, so retry
        # until the ad request starts getting blocked.
        ad = ""
        for _ in range(20):
            ad = b.run_async(FETCH, [AD_URL])
            if ad == "blocked":
                break
            time.sleep(2)
        ok = b.run_async(FETCH, [OK_URL])
        print("ad request:", ad)
        print("normal request:", ok)
        if ad == "blocked" and ok == "loaded":
            print("PASS: ads are blocked, normal traffic passes")
            return 0
        print("FAIL")
        return 1


if __name__ == "__main__":
    sys.exit(main())
