#!/usr/bin/env python3
"""Check that the sponsored result marker runs on search pages.

Opens a Bing and a DuckDuckGo search page and checks that our script ran
(it marks the page root). If ad blocks are present, counts them. Ads are
not always served, so only the injection check is strict. Also checks a
fresh profile searches with DuckDuckGo rather than "No Search".
"""

import sys
import tempfile
import time

from drive import Browser

PROFILE = r"E:\ung\testprofile"


# Settings pages live in shadow roots, which innerText does not enter.
DEEP_TEXT = """
  function walk(node) {
    var text = '';
    if (node.shadowRoot) text += walk(node.shadowRoot);
    node.childNodes.forEach(function(child) {
      text += child.nodeType === 3 ? child.textContent : walk(child);
    });
    return text;
  }
  return walk(document.body);
"""


def main():
    failures = []
    with Browser(user_data_dir=PROFILE) as b:
        for name, url in [
            ("Bing", "https://www.bing.com/search?q=vpn+deal"),
            ("DuckDuckGo", "https://duckduckgo.com/?q=buy+running+shoes&ia=web"),
        ]:
            b.get(url)
            time.sleep(4)
            ran = b.run("return document.documentElement.dataset.boringSerp || ''")
            labeled = b.run(
                "return document.querySelectorAll('[data-boring-labeled]').length"
            )
            print(f"{name}: script ran: {ran == '1'}, labeled ad blocks: {labeled}")
            if ran != "1":
                failures.append(f"marker script did not run on {name}")

    with tempfile.TemporaryDirectory() as fresh, Browser(user_data_dir=fresh) as b:
        b.get("chrome://settings/searchEngines")
        time.sleep(3)
        text = b.run(DEEP_TEXT)
        # "No Search" is still offered in the list, just not as the default.
        default = "DuckDuckGo (Default)" in text
        print("DuckDuckGo is the default engine:", default)
        if not default:
            failures.append("a fresh profile does not search with DuckDuckGo")

    for failure in failures:
        print("FAIL:", failure)
    if failures:
        return 1
    print("PASS: sponsored result marker is active, and search works out of the box")
    return 0


if __name__ == "__main__":
    sys.exit(main())
