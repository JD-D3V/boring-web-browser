#!/usr/bin/env python3
"""Check that ad blocking works in the built browser.

From a real page, loads a known ad script as a <script> and fetches a
normal page. The ad script must not come from the ad server; the normal
page must load.

"Not from the ad server" is either blocked, or replaced by uBO's inert
stub. uBO's own lists stub AdSense's loader everywhere
(adsbygoogle.js$script,xhr,redirect=googlesyndication_adsbygoogle.js),
so pages that check for it find it and carry on, and the real file is
never requested. A stub is served inside the browser, so its resource
timing has no network protocol and no bytes transferred; the real file
comes over h2 or h3 with tens of KB. Google sends Timing-Allow-Origin
for this file, which is what makes those numbers readable here.
"""

import sys
import time

from drive import PROFILE, Browser

SCRIPT = """
var url = arguments[0] + '?t=' + Date.now();
var done = arguments[1];
var s = document.createElement('script');
s.src = url;
s.onload = function() {
  setTimeout(function() {
    var e = performance.getEntriesByName(url)[0] || {};
    var stub = !e.nextHopProtocol && !e.transferSize;
    done(stub ? 'stubbed' : 'loaded from ' + e.nextHopProtocol);
  }, 200);
};
s.onerror = function() { done('blocked'); };
document.head.appendChild(s);
"""

FETCH = """
var url = arguments[0];
var done = arguments[1];
fetch(url, {mode: 'no-cors', cache: 'no-store'}).then(
  function() { done('loaded or stubbed'); },
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
        # until the ad script starts getting blocked.
        ad = ""
        for _ in range(20):
            ad = b.run_async(SCRIPT, [AD_URL])
            if ad in ("blocked", "stubbed"):
                break
            time.sleep(2)
        fetched = b.run_async(FETCH, [AD_URL])
        ok = b.run_async(FETCH, [OK_URL])
        print("ad script:", ad)
        print("ad server fetch (not judged):", fetched)
        print("normal request:", ok)
        if ad in ("blocked", "stubbed") and ok != "blocked":
            print("PASS: ads are blocked, normal traffic passes")
            return 0
        print("FAIL")
        return 1


if __name__ == "__main__":
    sys.exit(main())
