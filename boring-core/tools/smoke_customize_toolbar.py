#!/usr/bin/env python3
"""Smoke test: the Customize toolbar panel in the compiled design's finish
(ledger 7, screen C11). Look only: the rows and what they do are Chromium's
(smoke_quick_buttons.py checks those).

For light and then dark, a new profile, the panel opened the way
smoke_quick_buttons.py opens it, and its computed styles read over DevTools:

  - the cards are flat on the panel (no card fill, no corners);
  - the intro text is 13px, the headings 11.5px semibold in the quiet ink;
  - a row is 36 high with 18 at the sides, its icon 16;
  - a switch's track is 34 by 20 with a 16 knob, off in the edge colour
    (the edge token: #8a867d light, #77756d dark), on in the accent;
  - the "Forget this session" row the toolbar patch added is there;
  - the separators between the categories are gone, the one between the
    cards is a 1px hairline.

Then the browser's window is photographed with PrintWindow and the compiled
screen (design/v12-compiled/shots-final c11, light or dark) is copied beside
it. Only DevTools and PrintWindow of our own window; no input to the OS.

    python smoke_customize_toolbar.py [--out E:\\tmp\\cui-menu\\shots]

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import contextlib
import ctypes
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from smoke_local import Checks
from smoke_memory import close, launch
from smoke_quick_buttons import CHROME, TOOLBAR_JS, open_picker, rows, shoot

FORGET_ROW = "Forget this session"
EDGE = {"light": "rgb(138, 134, 125)", "dark": "rgb(119, 117, 109)"}
DESIGN = Path(__file__).resolve().parents[2] / "design" / "v12-compiled" / "shots-final"
DESIGN_SHOT = "c11-customizetoolbar.png"

# The computed styles the checks read, in one go.
STYLES = (
    "(() => { const tb = " + TOOLBAR_JS + "; if (!tb || !tb.shadowRoot) return null;"
    " const r = tb.shadowRoot; const cs = e => e ? getComputedStyle(e) : null;"
    " const card = cs(r.querySelector('#pinningSelectionCard'));"
    " const intro = cs(r.querySelector('.intro-text'));"
    " const head = cs(r.querySelector('.category-title'));"
    " const rowEl = r.querySelector('.toggle-container');"
    " const row = cs(rowEl);"
    " const icon = rowEl && rowEl.querySelector('.toggle-icon');"
    " const toggles = [...r.querySelectorAll('cr-toggle')];"
    " const bar = t => t && t.shadowRoot && t.shadowRoot.querySelector('#bar');"
    " const knob = t => t && t.shadowRoot && t.shadowRoot.querySelector('#knob');"
    " const off = toggles.find(t => !t.checked), on = toggles.find(t => t.checked);"
    " const hrs = [...r.querySelectorAll('.sp-hr')].filter(h => h.offsetHeight > 0).length;"
    " const sep = cs(r.querySelector('hr.sp-cards-separator'));"
    " return {"
    "  cardBg: card && card.backgroundColor, cardRadius: card && card.borderTopLeftRadius,"
    "  introSize: intro && intro.fontSize,"
    "  headSize: head && head.fontSize, headWeight: head && head.fontWeight,"
    "  headColor: head && head.color, quiet: getComputedStyle(tb).getPropertyValue('--cr-secondary-text-color').trim(),"
    "  rowHeight: rowEl && rowEl.getBoundingClientRect().height,"
    "  rowPad: row && row.paddingLeft,"
    "  icon: icon && [icon.getBoundingClientRect().width, icon.getBoundingClientRect().height],"
    "  bar: bar(off) && [bar(off).getBoundingClientRect().width, bar(off).getBoundingClientRect().height],"
    "  knob: knob(off) && knob(off).getBoundingClientRect().width,"
    "  offColor: bar(off) && getComputedStyle(bar(off)).backgroundColor,"
    "  onColor: bar(on) && getComputedStyle(bar(on)).backgroundColor,"
    "  accent: getComputedStyle(tb).getPropertyValue('--color-sys-primary').trim(),"
    "  visibleHrs: hrs, sepTop: sep && sep.borderTopWidth };"
    " })()"
)


def norm(color):
    """A CSS colour as the browser computes it, for an rgb() comparison."""
    color = (color or "").strip().lower()
    if color.startswith("#") and (len(color) == 7 or (len(color) == 9 and color.endswith("ff"))):
        r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
        return f"rgb({r}, {g}, {b})"
    return color


def check_styles(checks, scheme, s):
    """The checks of one scheme on the styles STYLES read."""
    if not s:
        checks(f"{scheme}: the panel's styles could be read", False, "no panel")
        return
    checks(f"{scheme}: the cards are flat", s["cardBg"] in ("rgba(0, 0, 0, 0)", "transparent") and s["cardRadius"] == "0px", f"{s['cardBg']} {s['cardRadius']}")
    checks(f"{scheme}: the intro text is 13px", s["introSize"] == "13px", str(s["introSize"]))
    checks(f"{scheme}: headings are 11.5px semibold", s["headSize"] == "11.5px" and s["headWeight"] == "600", f"{s['headSize']} {s['headWeight']}")
    checks(f"{scheme}: headings are the quiet ink", not s["quiet"] or norm(s["headColor"]) == norm(s["quiet"]), f"{s['headColor']} {s['quiet']}")
    checks(f"{scheme}: rows are 36 high with 18 at the sides", round(s["rowHeight"] or 0) == 36 and s["rowPad"] == "18px", f"{s['rowHeight']} {s['rowPad']}")
    checks(f"{scheme}: row icons are 16", [round(v) for v in s["icon"]] == [16, 16], str(s["icon"]))
    checks(f"{scheme}: a switch is 34 by 20 with a 16 knob", [round(v) for v in s["bar"]] == [34, 20] and round(s["knob"]) == 16, f"{s['bar']} {s['knob']}")
    checks(f"{scheme}: an off switch is the edge colour", norm(s["offColor"]) == EDGE[scheme], str(s["offColor"]))
    checks(f"{scheme}: an on switch is the accent", s["onColor"] is None or not s["accent"] or norm(s["onColor"]) == norm(s["accent"]), f"{s['onColor']} {s['accent']}")
    checks(f"{scheme}: no separators between categories", s["visibleHrs"] == 0, str(s["visibleHrs"]))
    checks(f"{scheme}: the cards' separator is a hairline", s["sepTop"] == "1px", str(s["sepTop"]))


def beside(out, scheme):
    """Copies the compiled screen next to this run's picture."""
    design = DESIGN / ("dark" if scheme == "dark" else "") / DESIGN_SHOT
    if design.exists():
        shutil.copyfile(design, out / f"compiled-c11-{scheme}.png")
    else:
        print("no compiled screen to put beside it:", design)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\tmp\cui-menu\shots", help="folder for the pictures")
    args = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    checks = Checks()
    work = Path(tempfile.mkdtemp(prefix="boring-ct-", dir=os.environ.get("TMP", r"E:\tmp")))
    proc = cdp = None
    try:
        for scheme, extra in (("light", []), ("dark", ["--force-dark-mode"])):
            profile = work / scheme
            profile.mkdir()
            proc, cdp = launch(CHROME, profile, ["--disable-features=CalculateNativeWinOcclusion", *extra], ("about:blank",))
            time.sleep(3)
            panel = open_picker(cdp)
            checks(f"{scheme}: the panel opens", panel is not None)
            if panel is not None:
                names = [r["name"] for r in rows(cdp, panel)]
                checks(f"{scheme}: the {FORGET_ROW} row is there", FORGET_ROW in names, json.dumps(names))
                time.sleep(0.5)
                check_styles(checks, scheme, cdp.evaluate(panel, STYLES))
                shoot(out / f"customize-toolbar-{scheme}.png")
                beside(out, scheme)
            close(proc, cdp)
            proc = cdp = None
        return checks.result("customize toolbar")
    finally:
        if proc:
            close(proc, cdp)
        with contextlib.suppress(Exception):
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
