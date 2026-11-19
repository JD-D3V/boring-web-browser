#!/usr/bin/env python3
"""Check the scam warning page as drawn (ledger item 10, screen C12).

One card: the shield symbol, "This site is not safe", a sentence that
names the site in bold, the calm line "Your computer is fine. Nothing was
sent, and you do not need to call anyone.", the main button Go back to
safety, Why was this blocked, and a footer with Continue anyway, not
advised. With "No way past scam warnings" on there is no way past: no
Continue and no Why, and the footer says so. The colours are the TOKENS
rows of the compiled design, light and dark; outlines use the edge token.

The setup is smoke_scam.py's: a temporary list of our own and local names
mapped to 127.0.0.1, so nothing leaves the machine. smoke_scam.py keeps
the checks of the warning's behaviour across the colour choices and the
list size; this one is the look and the words.

Light and dark photographs of our own window (PrintWindow) are written to
artifacts/ui-implemented next to the compiled design's picture C12. They
need a native window: set BORING_ALLOW_HEADFUL=1, otherwise that part is
skipped and said so.

Usage: python smoke_warning_page.py
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import page_checks
from drive import Browser, headful_allowed
from smoke_local import HTML, Pages, list_folder, wait_for
from smoke_scam import (
    CONTINUE,
    GO_BACK,
    LISTED,
    PARENT,
    SAFE_PAGE,
    SCAM_LIST,
    args_for,
    go_back_to,
    open_url,
    switch_on,
    wait_until_list_is_loaded,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/ui-implemented"
WARNING_CC = Path(__file__).resolve().parents[1] / "components/boring/scam/warning_page.cc"

HEADING = "This site is not safe"
CALM = "Your computer is fine. Nothing was sent, and you do not need to call anyone."
SENTENCE = (
    "Boring Browser stopped {host} from opening. It is on a list of sites "
    "that pretend to be real companies to take passwords or card details."
)
WHY = "Its address matched the list on this computer. Lists can be wrong."
NO_WAY = (
    "No way past scam warnings is on. This site cannot be opened from this warning."
)

# TOKENS rows of Window.dc.html, as the page computes them.
LIGHT = {
    "page": "rgb(248, 247, 244)",
    "surface": "rgb(255, 255, 255)",
    "solid": "rgb(26, 28, 34)",
    "solid_ink": "rgb(255, 255, 255)",
    "edge": "rgb(138, 134, 125)",
    "tint": "rgb(251, 230, 227)",
    "bad": "rgb(163, 39, 28)",
}
DARK = {
    "page": "rgb(21, 21, 20)",
    "surface": "rgb(28, 28, 26)",
    "solid": "rgb(232, 233, 237)",
    "solid_ink": "rgb(20, 21, 26)",
    "edge": "rgb(119, 117, 109)",
    "tint": "rgb(59, 28, 26)",
    "bad": "rgb(255, 154, 143)",
}


def shown(b):
    return wait_for(
        b,
        f"document.body && document.body.innerText.includes({HEADING!r})",
        15000,
    )


def static_checks(checks):
    """The page as written in the C++ source: its words, its escaping, and
    a script that parses."""
    text = WARNING_CC.read_text(encoding="utf-8")
    bottom = page_checks.raw_string(text, "kPageBottom")
    checks["page source is found"] = bottom is not None
    if bottom is None:
        return
    checks["the calm line is in the page source"] = (
        f'<p class="calm">{CALM}</p>' in bottom
    )
    checks["the site name and every text are escaped before they go in"] = all(
        needle in text
        for needle in (
            "base::EscapeForHTML(text.address)",
            "base::EscapeForHTML(text.what)",
            "base::EscapeForHTML(text.heading)",
            "base::EscapeForHTML(text.why)",
            "base::EscapeForHTML(text.no_bypass)",
        )
    ) and "innerHTML" not in text
    blocks = page_checks.script_blocks(bottom)
    if not page_checks.have_node():
        print("SKIP: warning page script syntax (node is not installed)")
    else:
        checks["warning page script parses"] = bool(blocks) and all(
            page_checks.js_syntax_error(js) is None for js in blocks
        )


FACTS = r"""
  var q = s => document.querySelector(s);
  var cs = (e, p) => getComputedStyle(e)[p];
  var words = [...document.querySelectorAll('.words p')].map(p => p.textContent);
  var host = q('.words .host');
  var primary = q('button.primary');
  var secondary = q('button.secondary');
  var card = q('.warning-page');
  var sym = q('.warning-symbol');
  return {
    heading: q('h1') && q('h1').textContent,
    headings: document.querySelectorAll('h1').length,
    title: document.title,
    words: words,
    host: host && host.textContent,
    hostWeight: host && cs(host, 'fontWeight'),
    hostChildren: host ? host.childElementCount : -1,
    hostBox: !!q('.host-box'),
    why: q('#why') && q('#why').textContent,
    whyHidden: q('#why') ? q('#why').hidden : null,
    primary: primary && primary.textContent.trim(),
    secondary: secondary && secondary.textContent.trim(),
    footer: q('.footer') ? q('.footer').innerText.trim() : null,
    footerLinks: [...document.querySelectorAll('.footer button, .footer a')]
        .map(e => e.textContent.trim()),
    note: q('.footer .panel-note') && q('.footer .panel-note').textContent,
    eyebrow: !!q('.eyebrow'),
    page: cs(document.body, 'backgroundColor'),
    surface: cs(card, 'backgroundColor'),
    cardWidth: Math.round(card.getBoundingClientRect().width),
    cardPadding: cs(card, 'paddingTop'),
    cardRadius: cs(card, 'borderTopLeftRadius'),
    symbol: [Math.round(sym.getBoundingClientRect().width),
             Math.round(sym.getBoundingClientRect().height)],
    symbolBg: cs(sym, 'backgroundColor'),
    symbolInk: cs(sym, 'color'),
    solid: primary && cs(primary, 'backgroundColor'),
    solidInk: primary && cs(primary, 'color'),
    primaryHeight: primary && Math.round(primary.getBoundingClientRect().height),
    secondaryHeight: secondary && Math.round(secondary.getBoundingClientRect().height),
    secondaryEdge: secondary && cs(secondary, 'boxShadow'),
  };
"""


def look_checks(b, checks, label, tokens, facts):
    f = facts
    checks[f"{label}: page, card and main button are the TOKENS colours"] = (
        f["page"] == tokens["page"]
        and f["surface"] == tokens["surface"]
        and f["solid"] == tokens["solid"]
        and f["solidInk"] == tokens["solid_ink"]
    )
    checks[f"{label}: Why was this blocked has the edge outline"] = bool(
        f["secondaryEdge"] and tokens["edge"] in f["secondaryEdge"]
    )
    checks[f"{label}: the symbol is the bad colour on its tint"] = (
        f["symbolBg"] == tokens["tint"] and f["symbolInk"] == tokens["bad"]
    )


def words_checks(b, checks, f):
    """The wording, exactly, and the card's shape."""
    checks["one heading: This site is not safe"] = (
        f["headings"] == 1 and f["heading"] == HEADING
    )
    checks["no eyebrow above the heading"] = not f["eyebrow"]
    checks["the sentence names the site"] = (
        len(f["words"]) == 2 and f["words"][0] == SENTENCE.format(host=LISTED)
    )
    checks["the site name is bold, in the sentence, as text"] = bool(
        f["host"] == LISTED
        and int(f["hostWeight"]) >= 600
        and f["hostChildren"] == 0
        and not f["hostBox"]
    )
    checks["the calm line is exact"] = len(f["words"]) == 2 and f["words"][1] == CALM
    checks["main button says Go back to safety"] = f["primary"] == "Go back to safety"
    checks["second button says Why was this blocked"] = (
        f["secondary"] == "Why was this blocked"
    )
    checks["the footer offers Continue anyway, not advised"] = (
        "Continue anyway, not advised" in f["footerLinks"]
    )
    checks["the card is 520 px wide with 32 px padding and 12 px corners"] = (
        f["cardWidth"] == 520 and f["cardPadding"] == "32px" and f["cardRadius"] == "12px"
    )
    checks["symbol is 44 px, buttons are 40 px high"] = (
        f["symbol"] == [44, 44] and f["primaryHeight"] == 40 and f["secondaryHeight"] == 40
    )


def why_checks(b, checks, f):
    checks["the reason starts hidden"] = f["whyHidden"] is True
    b.run("document.querySelector('button.secondary').click()")
    checks["Why was this blocked shows the reason"] = bool(
        b.run(
            "var w=document.getElementById('why');"
            "return !w.hidden && w.textContent===arguments[0] && "
            "document.querySelector('button.secondary').getAttribute('aria-expanded')==='true'",
            [WHY],
        )
    )
    b.run("document.querySelector('button.secondary').click()")
    checks["pressing it again hides the reason"] = bool(
        b.run("return document.getElementById('why').hidden")
    )


def behaviour_checks(b, pages, checks):
    """Go back and Continue anyway behave as they always did."""
    parent_url = f"http://{PARENT}:{pages.port}/"
    b.get(parent_url)
    wait_for(b, "!!document.getElementById('ok')")
    open_url(b, f"http://{LISTED}:{pages.port}/")
    shown(b)
    checks["Go back to safety returns to the previous page"] = go_back_to(
        b,
        f"location.href === {json.dumps(parent_url)} && document.getElementById('ok')",
    )
    open_url(b, f"http://{LISTED}:{pages.port}/")
    shown(b)
    b.run(f"({CONTINUE}).click()")
    checks["Continue anyway opens the site"] = wait_for(
        b, "!!document.getElementById('ok')", 10000
    )


def no_way_checks(profile, lists, pages, checks):
    """The switch on: the warning is the same, with no way past."""
    args = args_for(lists, pages, [])
    with Browser(user_data_dir=profile, args=args) as b:
        wait_until_list_is_loaded(b)
        b.get("chrome://boring-protection")
        wait_for(b, "document.getElementById('ads-state').textContent === 'On'", 10000)
        b.run("document.getElementById('no-bypass').click()")
        checks["the No way past switch turns on"] = switch_on(b, True)
    with Browser(user_data_dir=profile, args=args) as b:
        wait_until_list_is_loaded(b)
        open_url(b, f"http://{LISTED}:{pages.port}/")
        checks["no way past: the warning still shows"] = shown(b)
        f = b.run(FACTS)
        checks["no way past: no Continue and no Why was this blocked"] = bool(
            not b.run(f"return !!({CONTINUE})")
            and f["secondary"] is None
            and f["why"] is None
            and f["footerLinks"] == []
        )
        checks["no way past: the footer says so"] = f["note"] == NO_WAY
        checks["no way past: Go back to safety is still the main button"] = (
            f["primary"] == "Go back to safety"
        )
        checks["no way past: the calm line is still there"] = (
            len(f["words"]) == 2 and f["words"][1] == CALM
        )


def capture(lists, pages, checks):
    """Light and dark photographs of our own window, beside C12."""
    if not headful_allowed():
        print("SKIP: light and dark captures (set BORING_ALLOW_HEADFUL=1)")
        return
    import ctypes

    from capture_native import frame_window, grab
    from drive import CHROME

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    for name, extra, dark in (("light", [], False), ("dark", ["--force-dark-mode"], True)):
        with (
            tempfile.TemporaryDirectory(prefix="warn-", dir=os.environ.get("TMP") or None) as profile,
            Browser(
                user_data_dir=profile,
                args=args_for(lists, pages, extra),
                headful=True,
            ) as b,
        ):
            wait_until_list_is_loaded(b)
            open_url(b, f"http://{LISTED}:{pages.port}/")
            shown(b)
            time.sleep(1.5)
            hwnd = frame_window(CHROME, under=b.proc.pid)
            shot = OUT / f"scam-warning-{name}.png"
            grab(hwnd, str(shot))
            both = page_checks.beside(shot, "C12", OUT, dark=dark)
            print(f"saved {shot}" + (f" and {both}" if both else ", no design picture"))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    static_checks(checks)
    pages = Pages({"/": (SAFE_PAGE, HTML)})
    try:
        with list_folder({"scamlist.txt": SCAM_LIST}) as lists:
            with tempfile.TemporaryDirectory(prefix="warn-", dir=os.environ.get("TMP") or None) as profile:
                with Browser(user_data_dir=profile, args=args_for(lists, pages, [])) as b:
                    wait_until_list_is_loaded(b)
                    open_url(b, f"http://{LISTED}:{pages.port}/")
                    checks["a listed site shows the warning"] = shown(b)
                    facts = b.run(FACTS)
                    print("  facts:", json.dumps(facts)[:600])
                    words_checks(b, checks, facts)
                    look_checks(b, checks, "light", LIGHT, facts)
                    why_checks(b, checks, facts)
                    behaviour_checks(b, pages, checks)
                no_way_checks(profile, lists, pages, checks)
            with (
                tempfile.TemporaryDirectory(prefix="warn-", dir=os.environ.get("TMP") or None) as dark_profile,
                Browser(
                    user_data_dir=dark_profile,
                    args=args_for(lists, pages, ["--force-dark-mode"]),
                ) as b,
            ):
                wait_until_list_is_loaded(b)
                open_url(b, f"http://{LISTED}:{pages.port}/")
                shown(b)
                look_checks(b, checks, "dark", DARK, b.run(FACTS))
            capture(lists, pages, checks)
    finally:
        pages.close()

    (OUT / "warning-page-checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
