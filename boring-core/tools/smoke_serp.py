#!/usr/bin/env python3
"""Check that the sponsored result marker runs on search pages.

Opens a Bing search page and checks that our script ran (it marks the
page root). If ad blocks are present, checks they carry our label or
are hidden. Ads are not always served, so only the injection check is
strict.
"""

import sys

from drive import Browser

PROFILE = r"E:\ung\testprofile"


def main():
    with Browser(user_data_dir=PROFILE) as b:
        b.get("https://www.bing.com/search?q=vpn+deal")
        ran = b.run("return document.documentElement.dataset.boringSerp || ''")
        labeled = b.run(
            "return document.querySelectorAll('[data-boring-labeled]').length")
        print("script ran:", ran == "1")
        print("labeled ad blocks on this load:", labeled)
        if ran == "1":
            print("PASS: sponsored result marker is active on search pages")
            return 0
        print("FAIL: marker script did not run")
        return 1


if __name__ == "__main__":
    sys.exit(main())
