#!/usr/bin/env python3
"""Check the ad block engine cache.

The main engine is built from easylist.txt and ubo.txt, then saved,
serialized, in engine-cache\\main.dat beside the downloaded lists; a
start with the same lists loads that instead of parsing them again. The
browser runs with --boring-adblock-cache-report=FILE, which makes it
note "<engine> cache" or "<engine> text" for every engine it makes.
Checked, with local test lists (see smoke_local.py):

  - first start: built from the lists, the cache file is written, and
    blocking works
  - second start, same lists: loaded from the cache, file untouched,
    blocking works, and scriptlets still run (resources are given to a
    loaded engine too)
  - lists changed: the cache is ignored, the engine is built from the
    new lists (their new rule works) and the cache is rewritten
  - a damaged cache file is ignored and replaced, and blocking works

Usage: python smoke_engine_cache.py
"""

import os
import sys
import tempfile
import time

from drive import Browser
from smoke_local import (
    HTML,
    TEST_SITE,
    Checks,
    Pages,
    browser_args,
    hidden_expr,
    list_folder,
    resources_shipped,
    wait_for,
    write_lists,
)

LISTS = {
    "easylist.txt": (
        "[Adblock Plus 2.0]\n! Title: boring engine cache smoke test\n"
        "##.boring-control-ad\n"
    ),
    "ubo.txt": (
        "! Title: boring engine cache smoke test, uBO syntax\n"
        f"{TEST_SITE}##+js(set-constant, boringCacheScriptlet, true)\n"
    ),
    "cookies.txt": "! Title: boring engine cache smoke test, no cookie rules\n",
}

CHANGED = {
    "easylist.txt": LISTS["easylist.txt"] + "##.boring-new-rule\n",
}

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>engine cache test</title>
<div class="boring-control-ad">control ad</div>
<div class="boring-new-rule">only the changed list hides this</div>
"""


def report_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


def wait_for_report(path, count, timeout=30):
    """The report once it has at least `count` lines, or what it has."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lines = report_lines(path)
        if len(lines) >= count:
            return lines
        time.sleep(0.2)
    return report_lines(path)


def run(check, args, page, label, new_rule_hidden=False):
    """One browser start: opens the page and checks blocking works."""
    with Browser(args=args) as b:
        b.get(page)
        check(
            f"{label}: blocking works",
            wait_for(b, hidden_expr(".boring-control-ad"), 30000),
        )
        check(
            f"{label}: the uBO list's scriptlet ran",
            wait_for(b, "window.boringCacheScriptlet === true", 5000),
        )
        if new_rule_hidden:
            check(
                f"{label}: the changed list's new rule works",
                wait_for(b, hidden_expr(".boring-new-rule"), 5000),
            )


def main():
    check = Checks()
    if not resources_shipped(check):
        return check.result("")
    pages = Pages({"/page.html": (PAGE, HTML)})
    page = pages.url(TEST_SITE, "/page.html")
    try:
        with (
            list_folder(LISTS) as lists,
            tempfile.TemporaryDirectory(prefix="engine-cache-") as work,
        ):
            cache = os.path.join(lists, "engine-cache", "main.dat")
            report = os.path.join(work, "report.txt")
            args = browser_args(
                lists, extra=[f"--boring-adblock-cache-report={report}"]
            )

            run(check, args, page, "first start")
            lines = wait_for_report(report, 1)
            check("first start builds from the lists", "main text" in lines, lines)
            check("the cache file is written", os.path.isfile(cache), cache)
            written = os.stat(cache).st_mtime_ns if os.path.isfile(cache) else 0

            os.remove(report)
            run(check, args, page, "second start")
            lines = wait_for_report(report, 1)
            check("second start loads the cache", "main cache" in lines, lines)
            check(
                "and does not rewrite it",
                os.path.isfile(cache) and os.stat(cache).st_mtime_ns == written,
            )

            os.remove(report)
            write_lists(lists, CHANGED)
            run(check, args, page, "lists changed", new_rule_hidden=True)
            lines = wait_for_report(report, 1)
            check(
                "changed lists are built from text, not the old cache",
                "main text" in lines and "main cache" not in lines,
                lines,
            )
            check(
                "and the cache is rewritten",
                os.path.isfile(cache) and os.stat(cache).st_mtime_ns != written,
            )

            os.remove(report)
            with open(cache, "r+b") as f:
                f.seek(-64, os.SEEK_END)
                f.write(b"\0" * 64)
            run(check, args, page, "damaged cache", new_rule_hidden=True)
            lines = wait_for_report(report, 1)
            check(
                "a damaged cache is ignored and rebuilt from the lists",
                "main text" in lines,
                lines,
            )
    finally:
        pages.close()
    return check.result("the engine cache is written, reused, and dropped when stale")


if __name__ == "__main__":
    sys.exit(main())
