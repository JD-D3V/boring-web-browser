#!/usr/bin/env python3
"""Check scriptlets: ##+js rules that change a page's own script.

A local page plays a video player whose inline script decides, as the
page loads, whether to play an ad first. It asks twice, the two ways
real players do: a global flag, and ad slots in a JSON response. Two
uBO scriptlets from the shipped resources.json have to get there
before that script runs:

  - set-constant turns the flag off
  - json-prune takes the ad slots out of the parsed JSON

The same page on a site without the rules still plays its ad, which
proves the page itself works and it is the scriptlets that stop it.

Usage: python smoke_scriptlet.py
"""

import sys
import tempfile

from drive import Browser
from smoke_local import (
    HTML,
    OTHER_SITE,
    TEST_SITE,
    Checks,
    Pages,
    browser_args,
    list_folder,
    resources_shipped,
    wait_for,
)

LISTS = {
    "easylist.txt": "[Adblock Plus 2.0]\n! Title: boring scriptlet smoke test\n",
    # In ubo.txt, the list trusted with every scriptlet, as real uBO
    # rules are. Neither scriptlet needs trust, so this is not what
    # makes them run.
    "ubo.txt": (
        "! Title: boring scriptlet smoke test\n"
        f"{TEST_SITE}##+js(set-constant, boringShowPlayerAd, false)\n"
        f"{TEST_SITE}##+js(json-prune, adPlacements)\n"
    ),
    "cookies.txt": "! Title: boring scriptlet smoke test, no cookie rules\n",
}

# The player, all inline and all at load, the way an ad decision is
# made before a video starts.
PAGE = """<!doctype html>
<meta charset="utf-8">
<title>player test</title>
<script>
  window.boringShowPlayerAd = true;
  var response = JSON.parse(
      '{"video": "clip", "adPlacements": [{"kind": "preroll"}]}');
  window.playerState = {
    flagAd: window.boringShowPlayerAd === true,
    jsonAd: Array.isArray(response.adPlacements),
    video: response.video,
  };
</script>
<div id="player"></div>
<script>
  document.getElementById('player').textContent =
      (playerState.flagAd || playerState.jsonAd) ? 'AD PLAYING' : 'VIDEO';
</script>
"""

STATE = "return window.playerState || null"


def main():
    check = Checks()
    if not resources_shipped(check):
        return check.result("")
    pages = Pages({"/player.html": (PAGE, HTML)})
    try:
        with (
            list_folder(LISTS) as lists,
            tempfile.TemporaryDirectory(prefix="scriptlet-") as profile,
            Browser(user_data_dir=profile, args=browser_args(lists)) as b,
        ):
            # The control: no rules for this site, so the ad plays.
            b.get(pages.url(OTHER_SITE, "/player.html"))
            state = b.run(STATE)
            check(
                "the page plays its ad where no rule applies",
                bool(state) and state["flagAd"] and state["jsonAd"],
                str(state),
            )

            # The engine loads in the background at startup, so load
            # the page again until the scriptlets are in, or give up.
            state = None
            for _ in range(15):
                b.get(pages.url(TEST_SITE, "/player.html"))
                state = b.run(STATE)
                if state and not state["flagAd"] and not state["jsonAd"]:
                    break
                wait_for(b, "false", timeout_ms=1000)
            check(
                "set-constant stops the flagged ad",
                bool(state) and not state["flagAd"],
                str(state),
            )
            check(
                "json-prune stops the ad in the JSON",
                bool(state) and not state["jsonAd"],
                str(state),
            )
            check(
                "the video itself is untouched",
                bool(state) and state["video"] == "clip",
                str(state),
            )
            check(
                "the player shows the video, not the ad",
                b.run("return document.getElementById('player').textContent")
                == "VIDEO",
            )
    finally:
        pages.close()
    return check.result("scriptlets run before the page's own script")


if __name__ == "__main__":
    sys.exit(main())
