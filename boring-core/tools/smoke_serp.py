#!/usr/bin/env python3
"""Check what happens to sponsored search results.

Out of the box they are removed ("Hide sponsored results" is on). With
it turned off in Protection, they stay where the site put them and get a
quiet "Sponsored" chip in our palette, never a red outline.

The checks use a results page (our script only runs on Google, Bing and
DuckDuckGo) and add an ad shaped element to it, because a live search
does not always serve one. The MutationObserver in
components/boring/serp/serp_tab_helper.cc treats it like any other ad
block.

The pages are served from this machine. The real names www.bing.com and
duckduckgo.com are mapped to one small local server with
--host-resolver-rules (the way smoke_lookalike.py does), so the address
check the product makes is the real one, saved copies of the results pages
(testdata/serp_bing.html, testdata/serp_ddg.html) are what load, and
nothing leaves the machine: every other name fails to resolve. The
result no longer depends on DNS, the network or what Bing serves today.

Covered here:
  1. a default profile hides ad blocks
  2. Hide sponsored results off shows the chip, in our colours, with no outline
  3. a fresh profile still searches with DuckDuckGo

Optional, off by default: BORING_SMOKE_LIVE=1 also runs checks 1 to 3
against the real bing.com and duckduckgo.com, reported on their own
"live check" line. They need the internet and only count towards the exit
code when asked for.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from drive import Browser
from smoke_local import HTML, Pages, wait_for

BING_HOST = "www.bing.com"
DDG_HOST = "duckduckgo.com"
BING_PATH_AND_QUERY = "/search?q=vpn+deal"
DDG_PATH_AND_QUERY = "/?q=buy+running+shoes&ia=web"
LIVE_BING_URL = "https://www.bing.com" + BING_PATH_AND_QUERY
LIVE_DDG_URL = "https://duckduckgo.com" + DDG_PATH_AND_QUERY
LIVE_ENV = "BORING_SMOKE_LIVE"

DATA = Path(__file__).resolve().parent / "testdata"

# The chip tokens from components/boring/serp/serp_tab_helper.cc, as the
# page reports them. Either scheme is a pass; the browser follows the
# system setting.
CHIP_COLOURS = [
    {"background": "rgb(229, 241, 235)", "text": "rgb(93, 105, 102)"},
    {"background": "rgb(39, 63, 53)", "text": "rgb(173, 185, 178)"},
]

# Drop in an ad shaped block and report what our script did to it.
PLANT_AD = """
  var ad = document.createElement('div');
  ad.setAttribute('data-text-ad', '');
  ad.id = 'boring-test-ad';
  ad.textContent = 'Sample sponsored offer';
  document.body.prepend(ad);
  return true;
"""

READ_AD = """
  var ad = document.getElementById('boring-test-ad');
  if (!ad) return {missing: true};
  var adStyle = getComputedStyle(ad);
  var chip = ad.querySelector('.boring-sponsored-chip');
  var chipStyle = chip ? getComputedStyle(chip) : null;
  return {
    hidden: adStyle.display === 'none',
    outlineStyle: adStyle.outlineStyle,
    outlineWidth: adStyle.outlineWidth,
    inlineOutline: ad.style.outline || '',
    chip: chip ? chip.textContent : '',
    background: chipStyle ? chipStyle.backgroundColor : '',
    text: chipStyle ? chipStyle.color : '',
    radius: chipStyle ? chipStyle.borderTopLeftRadius : ''
  };
"""

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


# The browser is pointed at the local server and at nothing else. HTTPS-Only
# is on by default and would upgrade these plain http names, so the pages
# could not load: seed_profile turns it off, and this replaces drive.py's
# own --disable-features, so it carries that one too.
LOCAL_ARGS = [
    f"--host-resolver-rules=MAP {BING_HOST} 127.0.0.1, "
    f"MAP {DDG_HOST} 127.0.0.1, MAP * ~NOTFOUND",
    "--disable-features=CalculateNativeWinOcclusion,HttpsUpgrades,"
    "HttpsFirstBalancedMode",
]

# True once the ad block has been dealt with: hidden, or given its chip.
AD_HIDDEN = (
    "getComputedStyle(document.getElementById('boring-test-ad')).display === 'none'"
)
AD_CHIPPED = "!!document.querySelector('#boring-test-ad .boring-sponsored-chip')"
SCRIPT_RAN = "document.documentElement.dataset.boringSerp === '1'"


def seed_profile(profile):
    """Turns HTTPS-Only off in a new profile, before the browser starts.

    Only these two settings are written; everything the checks are about
    (Hide sponsored results, the default search engine) is left at what a
    new profile has.
    """
    folder = os.path.join(profile, "Default")
    os.makedirs(folder, exist_ok=True)
    prefs = {
        "https_only_mode_enabled": False,
        "https_first_balanced_mode_enabled": False,
    }
    with open(os.path.join(folder, "Preferences"), "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def plant_and_read(profile, url, args, settled):
    """Open a search page, add an ad block, and report how it was treated.

    Waits for the page's marker and then for the ad block to be dealt with
    (the expression `settled`), rather than for a fixed time. If neither
    happens the read still runs and the checks say what was missing.
    """
    with Browser(user_data_dir=profile, args=args) as b:
        b.get(url)
        wait_for(b, SCRIPT_RAN, 10000)
        ran = b.run("return document.documentElement.dataset.boringSerp || ''")
        b.run(PLANT_AD)
        wait_for(b, settled, 5000)
        return ran, b.run(READ_AD)


def set_hide_pref(profile, value):
    path = os.path.join(profile, "Default", "Preferences")
    with open(path, encoding="utf-8") as f:
        prefs = json.load(f)
    prefs.setdefault("boring", {})["hide_sponsored_results"] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def deep_text_has(b, needle, seconds=10):
    """Whether the page, shadow roots included, shows the text within a time."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if needle in b.run(DEEP_TEXT):
            return True
        time.sleep(0.25)
    return False


def run_checks(bing_url, ddg_url, args=None, seed=False):
    """The three checks against these two addresses. Returns the failures."""
    failures = []

    with tempfile.TemporaryDirectory() as profile:
        if seed:
            seed_profile(profile)

        # 1. Out of the box: Hide sponsored results is on, so the block is gone.
        ran, ad = plant_and_read(profile, bing_url, args, AD_HIDDEN)
        print(
            "default profile: script ran:", ran == "1", "ad hidden:", ad.get("hidden")
        )
        if ran != "1":
            failures.append("the marker script did not run on a search page")
        if not ad.get("hidden"):
            failures.append("a default profile did not hide a sponsored result")

        # 2. Hide sponsored results off: the quiet chip, and nothing else.
        set_hide_pref(profile, False)
        ran, ad = plant_and_read(profile, bing_url, args, AD_CHIPPED)
        print("Hide sponsored results off:", json.dumps(ad, sort_keys=True))
        if ad.get("hidden"):
            failures.append("sponsored results were hidden with hiding turned off")
        if ad.get("chip") != "Sponsored":
            failures.append("no Sponsored chip on a marked ad block")
        # Style, not width. An outline with style none paints nothing
        # whatever its width says, and the width here comes from the
        # search page we planted the block into, not from us.
        if ad.get("outlineStyle") != "none":
            failures.append(
                "the ad block still has an outline: "
                f"{ad.get('outlineStyle')} {ad.get('outlineWidth')}"
            )
        if ad.get("inlineOutline"):
            failures.append("an inline outline is still set on the ad block")
        if not any(
            ad.get("background") == c["background"] and ad.get("text") == c["text"]
            for c in CHIP_COLOURS
        ):
            failures.append(
                "the chip is not in our palette: "
                f"{ad.get('background')} on {ad.get('text')}"
            )
        if ad.get("radius") != "6px":
            failures.append(f"the chip corner is {ad.get('radius')}, not 6px")

    # 3. The script still runs on DuckDuckGo, and search works out of the box.
    with tempfile.TemporaryDirectory() as fresh:
        if seed:
            seed_profile(fresh)
        with Browser(user_data_dir=fresh, args=args) as b:
            b.get(ddg_url)
            wait_for(b, SCRIPT_RAN, 10000)
            ran = b.run("return document.documentElement.dataset.boringSerp || ''")
            print("DuckDuckGo: script ran:", ran == "1")
            if ran != "1":
                failures.append("the marker script did not run on DuckDuckGo")

            b.get("chrome://settings/searchEngines")
            # Google is offered in the list too, just not as the default.
            default = deep_text_has(b, "DuckDuckGo (Default)")
            print("DuckDuckGo is the default engine:", default)
            if not default:
                failures.append("a fresh profile does not search with DuckDuckGo")

    return failures


def main():
    with (DATA / "serp_bing.html").open(encoding="utf-8") as f:
        bing_page = f.read()
    with (DATA / "serp_ddg.html").open(encoding="utf-8") as f:
        ddg_page = f.read()

    # One table for both names: Bing's results are at /search, DuckDuckGo's
    # at / with a query, which is also how the product tells them apart.
    server = Pages({"/search": (bing_page, HTML), "/": (ddg_page, HTML)})
    try:
        failures = run_checks(
            server.url(BING_HOST, BING_PATH_AND_QUERY),
            server.url(DDG_HOST, DDG_PATH_AND_QUERY),
            args=LOCAL_ARGS,
            seed=True,
        )
    finally:
        server.close()

    for failure in failures:
        print("FAIL:", failure)
    if not failures:
        print(
            "PASS: sponsored results are hidden by default and marked quietly when not"
        )

    # The same checks against the real sites. Optional and separate: they
    # need DNS and the network, and they are the only part that does.
    live_failures = None
    if os.environ.get(LIVE_ENV) == "1":
        try:
            live_failures = run_checks(LIVE_BING_URL, LIVE_DDG_URL)
        except Exception as e:  # noqa: BLE001 - a network fault is a result here
            live_failures = [f"{type(e).__name__}: {e}"]
        for failure in live_failures:
            print("FAIL (live):", failure)
        print("live check:", "FAIL" if live_failures else "PASS")
    else:
        print(
            f"live check: skipped (set {LIVE_ENV}=1 to run it against the real sites)"
        )

    return 1 if failures or live_failures else 0


if __name__ == "__main__":
    sys.exit(main())
