#!/usr/bin/env python3
"""Check reader view.

Reader view used to need a command line switch. It should be on now.
Opens an article through the reader URL and checks our own look is
there: the reading time line, the Aa settings button, and the page
colours.
"""

import hashlib
import sys
import time
import urllib.parse
import uuid

from drive import Browser

PROFILE = r"E:\ung\testprofile"

# A plain article page that distills cleanly.
ARTICLE = "https://en.wikipedia.org/wiki/Web_browser"


def reader_url(url, title):
    """Build the same reader URL the browser builds for a page.

    The host is a random id, an underscore, then the sha256 of the page
    address. See components/dom_distiller/core/url_utils.cc.
    """
    digest = hashlib.sha256(url.encode()).hexdigest()
    host = str(uuid.uuid4()) + "_" + digest
    query = urllib.parse.urlencode({
        "title": title,
        "time": str(int(time.time() * 1000)),
        "url": url,
    })
    return "chrome-distiller://" + host + "/?" + query


def main():
    failures = []
    with Browser(user_data_dir=PROFILE) as b:
        b.get(ARTICLE)
        time.sleep(3)

        b.get(reader_url(ARTICLE, "Web browser"))
        time.sleep(8)

        title = b.run("return document.title")
        print("reader page title:", title)

        has_aa = b.run(
            "return !!document.querySelector('.boring-aa')")
        read_time = b.run(
            "var e = document.getElementById('boring-read-time');"
            "return e ? e.textContent : ''")
        body_bg = b.run(
            "return getComputedStyle(document.body).backgroundColor")
        width = b.run(
            "var e = document.getElementById('main-content');"
            "return e ? getComputedStyle(e).width : ''")

        words = b.run(
            "var e = document.getElementById('content');"
            "return e ? (e.innerText || '').split(/\\s+/).length : 0")

        print("settings button is ours (Aa):", has_aa)
        print("article words pulled out:", words)
        print("reading time:", repr(read_time))
        print("page background:", body_bg)
        print("text column width:", width)

        if not has_aa:
            failures.append("our reader look did not load")
        if words < 200:
            failures.append("the article text was not extracted")
        if "minute read" not in read_time:
            failures.append("no reading time shown")

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("PASS: reader view works and uses our look")
    return 0


if __name__ == "__main__":
    sys.exit(main())
