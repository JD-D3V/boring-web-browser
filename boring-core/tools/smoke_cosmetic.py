#!/usr/bin/env python3
"""Check cosmetic filtering: rules that hide parts of a page.

Serves a local page with its own test lists (see smoke_local.py) and
checks, in the built browser:

  - a site rule (site##selector) hides its element
  - a generic rule (##.class) hides one on any site
  - a procedural rule (:has-text) hides one
  - the same rules work inside a same-site frame and a third party frame
  - an element no rule names stays visible
  - with blocking turned off for the site, nothing on it is hidden,
    while a site that keeps blocking still has its element hidden

Usage: python smoke_cosmetic.py
"""

import sys
import tempfile

from drive import Browser
from smoke_local import (
    HTML,
    OTHER_SITE,
    TEST_SITE,
    THIRD_PARTY,
    Checks,
    Pages,
    browser_args,
    hidden_expr,
    list_folder,
    set_profile_pref,
    shown_expr,
    wait_for,
)

# Specific rules for the test site and the third party frame, a generic
# one that applies everywhere, and a procedural one. The class names are
# ours alone, so no real list could be the thing hiding them.
LISTS = {
    "easylist.txt": (
        "[Adblock Plus 2.0]\n"
        "! Title: boring cosmetic smoke test\n"
        f"{TEST_SITE}###boring-specific\n"
        "##.boring-generic-ad\n"
    ),
    "ubo.txt": (
        "! Title: boring cosmetic smoke test, uBO syntax\n"
        f"{TEST_SITE}##.boring-card:has-text(Boring sponsored)\n"
        f"{THIRD_PARTY}###boring-in-frame\n"
    ),
    "cookies.txt": "! Title: boring cosmetic smoke test, no cookie rules\n",
}

BODY = """
<div id="boring-specific">specific</div>
<div class="boring-generic-ad">generic</div>
<div class="boring-card" id="card-ad"><p>Boring sponsored post</p></div>
<div class="boring-card" id="card-ok"><p>An ordinary post</p></div>
<div id="boring-keep">keep</div>
"""

PAGE = f"""<!doctype html>
<meta charset="utf-8">
<title>cosmetic test</title>
<h1>cosmetic test</h1>
{BODY}
<iframe id="same" src="/frame.html"></iframe>
<iframe id="third"></iframe>
<script>
  // The third party frame's address depends on the port.
  document.getElementById('third').src =
      location.protocol + '//{THIRD_PARTY}:' + location.port + '/third.html';
</script>
"""

FRAME = f"""<!doctype html>
<meta charset="utf-8">
<title>frame</title>
{BODY}
"""

# Answers the parent with what it sees, since a third party frame's
# document cannot be read from the page.
THIRD = """<!doctype html>
<meta charset="utf-8">
<title>third party frame</title>
<div id="boring-in-frame">in frame</div>
<div class="boring-generic-ad">generic in frame</div>
<div id="boring-keep">keep</div>
<script>
function hidden(sel) {
  var e = document.querySelector(sel);
  var s = getComputedStyle(e);
  return e.getClientRects().length === 0 || s.display === 'none' ||
      s.visibility === 'hidden';
}
addEventListener('message', function(e) {
  parent.postMessage({
    specific: hidden('#boring-in-frame'),
    generic: hidden('.boring-generic-ad'),
    keep: hidden('#boring-keep'),
  }, '*');
});
</script>
"""

# Asks the frame five times a second until both rules show, or ten
# seconds pass, and hands back the last answer either way.
ASK_THIRD = """
var done = arguments[0];
var f = document.getElementById('third');
var last = null;
var tries = 0;
function finish(value) {
  clearInterval(timer);
  removeEventListener('message', handler);
  done(value);
}
function handler(e) {
  if (e.source !== f.contentWindow) return;
  last = e.data;
  if (last.specific && last.generic) finish(last);
}
addEventListener('message', handler);
var timer = setInterval(function() {
  if (++tries > 50) { finish(last); return; }
  f.contentWindow.postMessage('state', '*');
}, 200);
"""

SAME = "document.getElementById('same').contentDocument"


def check_page(b, check, where):
    check(
        f"site rule hides its element ({where})",
        wait_for(b, hidden_expr("#boring-specific")),
    )
    check(
        f"generic rule hides ({where})", wait_for(b, hidden_expr(".boring-generic-ad"))
    )
    check(
        f":has-text rule hides the matching card ({where})",
        wait_for(b, hidden_expr("#card-ad")),
    )
    check(
        f":has-text rule leaves the other card ({where})",
        b.run(f"return {shown_expr('#card-ok')}"),
    )
    check(
        f"unlisted element stays ({where})",
        b.run(f"return {shown_expr('#boring-keep')}"),
    )


def main():
    check = Checks()
    pages = Pages(
        {
            "/page.html": (PAGE, HTML),
            "/frame.html": (FRAME, HTML),
            "/third.html": (THIRD, HTML),
        }
    )
    try:
        with (
            list_folder(LISTS) as lists,
            tempfile.TemporaryDirectory(prefix="cosmetic-") as profile,
        ):
            args = browser_args(lists)
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(pages.url(TEST_SITE, "/page.html"))
                check_page(b, check, "page")
                check(
                    "site rule hides inside a same-site frame",
                    wait_for(b, hidden_expr("#boring-specific", SAME)),
                )
                check(
                    "generic rule hides inside a same-site frame",
                    wait_for(b, hidden_expr(".boring-generic-ad", SAME)),
                )
                third = b.run_async(ASK_THIRD)
                check(
                    "rules apply inside a third party frame",
                    bool(third) and third["specific"] and third["generic"],
                    str(third),
                )
                check(
                    "an unlisted element in that frame stays",
                    bool(third) and not third["keep"],
                    str(third),
                )

                b.get(pages.url(OTHER_SITE, "/page.html"))
                check(
                    "generic rule hides on another site",
                    wait_for(b, hidden_expr(".boring-generic-ad")),
                )
                check(
                    "site rule does not reach another site",
                    b.run(f"return {shown_expr('#boring-specific')}"),
                )

            # Blocking off for the test site, the way the shield does it.
            set_profile_pref(profile, "boring.blocking_off_sites", [TEST_SITE])
            with Browser(user_data_dir=profile, args=args) as b:
                # First prove the engine is up, on a site that still blocks.
                b.get(pages.url(OTHER_SITE, "/page.html"))
                check(
                    "blocking still hides on a site that is not off",
                    wait_for(b, hidden_expr(".boring-generic-ad")),
                )
                b.get(pages.url(TEST_SITE, "/page.html"))
                # Give the injection every chance to (wrongly) happen.
                hidden_any = wait_for(
                    b,
                    " || ".join(
                        hidden_expr(s)
                        for s in ("#boring-specific", ".boring-generic-ad", "#card-ad")
                    ),
                    timeout_ms=4000,
                )
                check("nothing is hidden on a site with blocking off", not hidden_any)
                check(
                    "nothing is hidden in its frame either",
                    b.run(
                        "return "
                        + shown_expr("#boring-specific", SAME)
                        + " && "
                        + shown_expr(".boring-generic-ad", SAME)
                    ),
                )
    finally:
        pages.close()
    return check.result("cosmetic filtering works, and stays off where it is off")


if __name__ == "__main__":
    sys.exit(main())
