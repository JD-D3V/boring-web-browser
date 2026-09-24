#!/usr/bin/env python3
"""Check what happens to sponsored search results.

Out of the box they are removed. With hiding turned off in Protection,
they stay where the site put them and get a quiet "Sponsored" chip in
our palette, never a red outline.

The checks use a real search page (our script only runs on Google, Bing
and DuckDuckGo) and add an ad shaped element to it, because a live
search does not always serve one. The MutationObserver in
components/boring/serp/serp_tab_helper.cc treats it like any other ad
block.

Covered here:
  1. a default profile hides ad blocks
  2. hiding off shows the chip, in our colours, with no outline
  3. Senior Safe Mode forces hiding even with the pref off
  4. a fresh profile still searches with DuckDuckGo
"""

import json
import os
import sys
import tempfile
import time

from drive import Browser

SEARCH_URL = "https://www.bing.com/search?q=vpn+deal"
DDG_URL = "https://duckduckgo.com/?q=buy+running+shoes&ia=web"

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


def plant_and_read(profile, args=None):
    """Open a search page, add an ad block, and report how it was treated."""
    with Browser(user_data_dir=profile, args=args) as b:
        b.get(SEARCH_URL)
        time.sleep(4)
        ran = b.run("return document.documentElement.dataset.boringSerp || ''")
        b.run(PLANT_AD)
        time.sleep(1)
        return ran, b.run(READ_AD)


def set_hide_pref(profile, value):
    path = os.path.join(profile, "Default", "Preferences")
    with open(path, encoding="utf-8") as f:
        prefs = json.load(f)
    prefs.setdefault("boring", {})["hide_sponsored_results"] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def main():
    failures = []

    with tempfile.TemporaryDirectory() as profile:
        ran, ad = plant_and_read(profile)
        print("default profile: script ran:", ran == "1", "ad hidden:", ad.get("hidden"))
        if ran != "1":
            failures.append("the marker script did not run on a search page")
        if not ad.get("hidden"):
            failures.append("a default profile did not hide a sponsored result")

        # 2. Hiding off: the quiet chip, and nothing else.
        set_hide_pref(profile, False)
        ran, ad = plant_and_read(profile)
        print("hiding off:", json.dumps(ad, sort_keys=True))
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

        # 3. Senior Safe Mode overrides the pref.
        ran, ad = plant_and_read(profile, args=["--senior-safe-mode"])
        print("Senior Safe Mode: ad hidden:", ad.get("hidden"))
        if not ad.get("hidden"):
            failures.append("Senior Safe Mode did not force sponsored results hidden")

    # 4. The script still runs on DuckDuckGo, and search works out of the box.
    with tempfile.TemporaryDirectory() as fresh, Browser(user_data_dir=fresh) as b:
        b.get(DDG_URL)
        time.sleep(4)
        ran = b.run("return document.documentElement.dataset.boringSerp || ''")
        print("DuckDuckGo: script ran:", ran == "1")
        if ran != "1":
            failures.append("the marker script did not run on DuckDuckGo")

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
    print("PASS: sponsored results are hidden by default and marked quietly when not")
    return 0


if __name__ == "__main__":
    sys.exit(main())
