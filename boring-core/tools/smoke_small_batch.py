#!/usr/bin/env python3
"""Check two small things in the real build.

  - Settings has no Chrome logo at the top and no Web Store link, and the
    Extensions page has no Web Store link either.
  - "Continue anyway" on a look-alike warning is remembered for that site
    in this profile (local pref, kept across a restart), other look-alikes
    still warn, and "No way past scam warnings" still wins over it.

Usage: python smoke_small_batch.py
Needs BORING_OUT, as the other smoke tests do. Pictures are taken by
capture_native.py, not here.
"""

import os
import sys
import tempfile
import time

from drive import Browser
from smoke_local import wait_for
from smoke_lookalike import (
    CONTINUE,
    PLAIN,
    RN,
    WARNED,
    Recorder,
    browser_args,
    open_url,
    seed_profile,
    switch_is,
    text,
)

# Anything on the page, shadow roots included, that is on screen and is a
# logo picture or a link to a web store.
VISIBLE_LOGO_AND_STORE = r"""
var found = [];
function visible(el) {
  var r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
}
function walk(root) {
  root.querySelectorAll('*').forEach(function(el) {
    if (el.shadowRoot) walk(el.shadowRoot);
    var tag = el.tagName.toLowerCase();
    var href = (el.getAttribute('href') || '') + ' ' + (el.getAttribute('src') || '');
    if ((tag === 'img' || tag === 'picture') && /logo/i.test(el.id + ' ' + el.className + ' ' + href +
        ' ' + (el.getAttribute('srcset') || '')) && visible(el)) {
      found.push('logo:' + el.id + ':' + tag);
    }
    if (/chromewebstore|chrome\.google|webstore/i.test(href) && visible(el)) {
      found.push('store link:' + href.trim());
    }
    if (!el.children.length && /web ?store/i.test(el.textContent) && visible(el)) {
      found.push('store text:' + el.textContent.trim().slice(0, 40));
    }
  });
}
walk(document);
return found;
"""


def main():
    failures = []

    def check(name, ok, detail=""):
        print(
            ("PASS: " if ok else "FAIL: ")
            + name
            + (f" ({detail})" if detail and not ok else "")
        )
        if not ok:
            failures.append(name)

    tmp = os.environ.get("TMP") or None

    # --- Settings and Extensions ------------------------------------------
    with Browser() as b:
        for page, label in (
            ("chrome://settings", "Settings"),
            ("chrome://extensions", "Extensions"),
        ):
            b.get(page)
            wait_for(b, "!!document.body", 10000)
            # Let the page build its shadow roots.
            wait_for(b, "document.readyState === 'complete'", 10000)
            time.sleep(2.5)
            found = b.run(VISIBLE_LOGO_AND_STORE)
            check(f"{label}: no Chrome logo or Web Store link", not found, str(found))
        b.get("chrome://settings")
        time.sleep(2)
        check(
            "Settings: the Extensions row is there",
            "Extensions" in b.run(
                "var out = [];"
                "function w(r){r.querySelectorAll('*').forEach(function(e){"
                "if(e.shadowRoot)w(e.shadowRoot);"
                "if(e.id==='extensionsLink')out.push(e.textContent);});}"
                "w(document); return out.join(' ');"
            ),
        )

    # --- Continue anyway is remembered ------------------------------------
    server = Recorder()

    def url(host):
        return f"http://{host}:{server.port}/"

    try:
        with tempfile.TemporaryDirectory(prefix="small-batch-", dir=tmp) as profile:
            seed_profile(profile)
            with Browser(user_data_dir=profile, args=browser_args()) as b:
                open_url(b, url(RN[0]))
                check("first visit warns", wait_for(b, WARNED))
                b.run(f"({CONTINUE}).click()")
                check(
                    "Continue anyway opens the site",
                    wait_for(b, "!!document.getElementById('ok')", 10000),
                    b.current_url(),
                )
            # A new run of the browser, the same profile.
            with Browser(user_data_dir=profile, args=browser_args()) as b:
                open_url(b, url(RN[0]))
                check(
                    "after a restart the same site opens with no warning",
                    wait_for(b, "!!document.getElementById('ok')", 10000)
                    and not b.run(f"return !!({WARNED})"),
                    b.current_url(),
                )
                open_url(b, url(PLAIN[0]))
                check(
                    "a different look-alike still warns",
                    wait_for(b, WARNED),
                    text(b)[:120],
                )
                b.get("chrome://boring-protection")
                wait_for(
                    b,
                    "document.getElementById('ads-state').textContent === 'On'",
                    10000,
                )
                b.run("document.getElementById('no-bypass').click()")
                check(
                    "No way past scam warnings turns on",
                    switch_is(b, "no-bypass", True),
                )
                open_url(b, url(RN[0]))
                shown = wait_for(b, WARNED)
                check("no way past wins: the remembered site warns again", shown)
                check(
                    "no way past wins: Continue anyway is gone",
                    not b.run(f"return !!({CONTINUE})"),
                )
    finally:
        server.close()

    print("smoke_small_batch:", "FAIL" if failures else "PASS")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
