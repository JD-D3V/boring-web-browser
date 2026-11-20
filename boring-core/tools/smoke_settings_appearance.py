#!/usr/bin/env python3
"""Smoke test for Settings, Appearance as drawn (ledger items 9 and 17,
cui-settings.patch; screen C10 of design/v12-compiled).

Checks, on chrome://settings/appearance in a fresh profile:
- each control is there, in the drawn order: Light or dark (Light, Dark,
  Match system), Look (Soft white, Slate, Dusk), Accent (eight dots and
  Custom), Tabs (Top, Side), Bookmarks (Bar on top, Off), Toolbar buttons
  (Customize);
- each control writes its pref: Light or dark switches the page's colour
  scheme, Look writes boring.appearance.look, Accent writes
  boring.appearance.accent as "#rrggbb" (Custom too), Tabs writes
  vertical_tabs.enabled, Bookmarks writes bookmark_bar.show_on_all_tabs,
  Customize opens the Customize toolbar panel;
- Spacing is not there (dropped from Release 3);
- in dark, the dots under 3 to 1 on the card carry an edge ring; in light
  they do not; also with Dark picked in our own Light or dark on a light
  system, not only with --force-dark-mode;
- no Theme row (a store theme would switch our palette off);
- with Dusk picked and Light chosen, the page and the card are Dusk's dark,
  Light or dark says "Dusk is always dark." with its buttons off and Light
  still pressed, and picking Soft white brings Light back.
Then it photographs the window in light and dark (PrintWindow of our own
window, which sits off screen). With --captures (or BORING_CAPTURES) each
picture is also saved as <folder>/settings/c10-light.png and c10-dark.png:
the real capture on the left, the compiled screen on the right.

    python smoke_settings_appearance.py [--captures FOLDER]

Needs the built browser (BORING_OUT as for the other smokes) with
cui-colours.patch and the Accent work applied (they register the two
prefs). Pictures need BORING_ALLOW_HEADFUL=1; without it the checks run
headless and the pictures are skipped. design/ is not in git: run from the
main checkout or point BORING_DESIGN at design/v12-compiled/shots-final.
Sends no mouse or keys to the desktop.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import page_checks
from drive import CHROME, Browser, headful_allowed
from smoke_r3_fixes import FIND

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "cui-settings"
EDGE_DARK = "rgb(119, 117, 109)"  # the edge token, dark TOKENS row
# The page and the card on it (TOKENS page and surface), light and dark.
PAGE_BG = {False: "rgb(248, 247, 244)", True: "rgb(21, 21, 20)"}
CARD_BG = {False: "rgb(255, 255, 255)", True: "rgb(28, 28, 26)"}
ROWS = ["colorSchemeModeRow", "boringLookRow", "boringAccentRow",
        "tabsRow", "bookmarksRow", "toolbarRow"]
MODES = ["Light", "Dark", "Match system"]
ACCENTS = ["#4f46e5", "#2563c9", "#0f766e", "#1a7f55",
           "#a16207", "#be2d5a", "#7c3aed", "#4b5160"]
# Under 3 to 1 on a dark card: charcoal's, or Dusk's for Blue and Rose.
LOW_IN_DARK = {"#4f46e5", "#2563c9", "#be2d5a", "#7c3aed", "#4b5160"}

PAGE = FIND + """
var p = find(document, 'settings-appearance-page');
var r = p && p.shadowRoot;
"""
STATE = PAGE + """
if (!r) return null;
function menu(sel) {
  var m = r.querySelector(sel);
  var s = m && m.shadowRoot && m.shadowRoot.querySelector('select');
  // Only the options a person can see: Chromium keeps a disabled "Custom"
  // option in every drop-down and hides it with CSS while the value matches.
  return s ? {value: s.value, options: Array.from(s.options).filter(
      o => !o.disabled && !o.hidden && getComputedStyle(o).display !== 'none').map(
      o => [o.value, o.textContent.trim()])} : null;
}
var all = Array.from(r.querySelectorAll('*'));
var ids = arguments[0];
var mine = ids.map(id => r.querySelector('#' + id)).filter(e => e);
return {
  subline: (r.querySelector('.boring-subline') || {textContent: ''}).textContent.trim(),
  modes: Array.from(r.querySelectorAll('#colorSchemeModeButtons .cui-mode')).map(
      b => [b.textContent.trim(), b.getAttribute('aria-pressed')]),
  looks: Array.from(r.querySelectorAll('#boringLookRow .cui-look')).map(
      b => [b.dataset.value, b.querySelector('.cui-title').textContent.trim(), b.getAttribute('aria-pressed')]),
  dots: Array.from(r.querySelectorAll('#boringAccentRow .cui-dot')).map(
      b => [b.dataset.value, b.getAttribute('aria-label'), b.getAttribute('aria-pressed'), getComputedStyle(b).boxShadow]),
  custom: !!r.querySelector('#boringAccentRow input#boringAccentCustom[type=color]'),
  customText: (r.querySelector('#boringAccentRow .cui-custom') || {textContent: ''}).textContent.trim(),
  tabs: menu('#tabStripPosition'),
  bookmarks: menu('#showBookmarksBar'),
  customize: (r.querySelector('#customizeToolbar') || {textContent: ''}).textContent.trim(),
  order: ids.map(id => all.indexOf(r.querySelector('#' + id))),
  oldSelect: !!r.querySelector('#colorSchemeModeSelect'),
  themeRow: !!r.querySelector('#themeRow, #useDefault, #themesSecondaryActions'),
  duskNote: (r.querySelector('#duskAlwaysDark') || {textContent: ''}).textContent.trim(),
  modesDisabled: Array.from(r.querySelectorAll('#colorSchemeModeButtons .cui-mode')).map(b => b.disabled),
  text: r.textContent,
  rowsText: mine.map(e => e.textContent).join(' '),
  dark: matchMedia('(prefers-color-scheme: dark)').matches,
  pageBg: getComputedStyle(document.querySelector('settings-ui')).backgroundColor,
  cardBg: getComputedStyle(p).backgroundColor,
  cardRadius: getComputedStyle(p).borderTopLeftRadius,
};
"""
CLICK = PAGE + "var e = r && r.querySelector(arguments[0]); if (e) e.click(); return !!e;"
CHOOSE = PAGE + """
var m = r && r.querySelector(arguments[0]);
var s = m && m.shadowRoot.querySelector('select');
if (!s) return false;
s.value = arguments[1];
s.dispatchEvent(new Event('change'));
return true;
"""
CUSTOM = PAGE + """
var i = r && r.querySelector('#boringAccentCustom');
if (!i) return false;
i.value = arguments[0];
i.dispatchEvent(new Event('change'));
return true;
"""
GET_PREF = """
const done = arguments[arguments.length - 1];
chrome.settingsPrivate.getPref(arguments[0], p => done(p ? p.value : null));
"""
BAD_WORDS = ("Chrome", "Chromium", "\u2014", "\u2013")


class Checks:
    def __init__(self):
        self.items = {}

    def __call__(self, name, ok, seen=""):
        self.items[name] = (bool(ok), str(seen)[:300])
        print(("PASS: " if ok else "FAIL: ") + name + (f" (saw {seen})" if seen and not ok else ""))


def wait(fn, timeout=10.0):
    end = time.time() + timeout
    while True:
        got = fn()
        if got or time.time() > end:
            return got
        time.sleep(0.3)


def state(b):
    return b.run(STATE, [ROWS])


def pressed(s):
    return dict((m[0], m[1]) for m in s["modes"]) if s else {}


def pref(b, key):
    return b.run_async(GET_PREF, [key])


def wait_pref(b, key, want):
    return wait(lambda: pref(b, key) == want, 8), pref(b, key)


def panel_open(b):
    """True once a Customize toolbar panel target is there."""
    def look():
        try:
            res = b._req("POST", f"/session/{b.sid}/goog/cdp/execute",
                          {"cmd": "Target.getTargets", "params": {}})
        except Exception as e:  # noqa: BLE001 - reported as a failure below
            print("Target.getTargets failed:", e)
            return False
        infos = (res.get("value") or {}).get("targetInfos", [])
        return any("customize-chrome-side-panel" in t.get("url", "") for t in infos)
    return wait(look, 15)


def check_page(b, check, dark):
    mode = "dark" if dark else "light"
    b.get("chrome://settings/appearance")
    s = wait(lambda: state(b), 20)
    check(f"{mode}: the Appearance page loads", s, s)
    if not s:
        return
    check(f"{mode}: the page is the design's page colour", s["pageBg"] == PAGE_BG[dark], s["pageBg"])
    check(f"{mode}: Appearance is a card in the surface colour",
          s["cardBg"] == CARD_BG[dark] and s["cardRadius"] == "10px", f"{s['cardBg']} {s['cardRadius']}")
    check(f"{mode}: the line under the heading",
          s["subline"] == "How the browser looks. Changes apply straight away.", s["subline"])
    check(f"{mode}: Light or dark offers Light, Dark, Match system",
          [m[0] for m in s["modes"]] == MODES, s["modes"])
    check(f"{mode}: Look offers Soft white, Slate, Dusk",
          [(x[0], x[1]) for x in s["looks"]]
          == [("soft_white", "Soft white"), ("slate", "Slate"), ("dusk", "Dusk")], s["looks"])
    check(f"{mode}: Accent has the eight dots and Custom",
          [d[0] for d in s["dots"]] == ACCENTS and s["custom"] and s["customText"] == "Custom",
          (s["dots"], s["custom"], s["customText"]))
    check(f"{mode}: Tabs offers Top and Side",
          s["tabs"] and s["tabs"]["options"] == [["false", "Top"], ["true", "Side"]], s["tabs"])
    check(f"{mode}: Bookmarks offers Bar on top and Off",
          s["bookmarks"] and s["bookmarks"]["options"] == [["true", "Bar on top"], ["false", "Off"]],
          s["bookmarks"])
    check(f"{mode}: Toolbar buttons has Customize", s["customize"] == "Customize", s["customize"])
    check(f"{mode}: the rows come in the drawn order",
          all(i >= 0 for i in s["order"]) and s["order"] == sorted(s["order"]), s["order"])
    check(f"{mode}: no Spacing row",
          all(w not in s["text"] for w in ("Spacing", "Compact", "Comfortable")))
    check(f"{mode}: the old colour scheme menu is gone", not s["oldSelect"])
    check(f"{mode}: no Theme row (a store theme would switch our palette off)",
          not s["themeRow"], s["themeRow"])
    bad = [w for w in BAD_WORDS if w in s["rowsText"]]
    check(f"{mode}: no Chrome, Chromium or long dash in the new rows", not bad, bad)
    for value, name, is_pressed, shadow in s["dots"]:
        if is_pressed == "true":
            continue  # the selected dot keeps its drawn selection ring
        if dark and value in LOW_IN_DARK:
            check(f"dark: the {name} dot has an edge ring", EDGE_DARK in shadow, shadow)
        else:
            check(f"{mode}: the {name} dot has no ring", shadow == "none", shadow)


def check_writes(b, check):
    for label, want_dark in (("Dark", True), ("Light", False)):
        b.run(CLICK, ["#colorSchemeModeButtons .cui-mode:nth-child(%d)" % (MODES.index(label) + 1)])
        s = wait(lambda: (lambda st: st if st and st["dark"] == want_dark else None)(state(b)), 8)
        s = s or state(b)
        check(f"Light or dark: {label} is pressed and the page turns {label.lower()}",
              s and pressed(s).get(label) == "true" and s["dark"] == want_dark,
              (pressed(s), s and s["dark"]))
    b.run(CLICK, ["#colorSchemeModeButtons .cui-mode:nth-child(3)"])
    s = wait(lambda: (lambda st: st if pressed(st).get("Match system") == "true" else None)(state(b)), 8)
    check("Light or dark: Match system is pressed", s)

    for value in ("slate", "dusk", "soft_white"):
        b.run(CLICK, [f'#boringLookRow .cui-look[data-value="{value}"]'])
        ok, seen = wait_pref(b, "boring.appearance.look", value)
        check(f"Look: {value} writes boring.appearance.look", ok, seen)

    for value in ACCENTS:
        b.run(CLICK, [f'#boringAccentRow .cui-dot[data-value="{value}"]'])
        ok, seen = wait_pref(b, "boring.appearance.accent", value)
        check(f"Accent: {value} writes boring.appearance.accent", ok, seen)
    b.run(CUSTOM, ["#12a4b6"])
    ok, seen = wait_pref(b, "boring.appearance.accent", "#12a4b6")
    check("Accent: Custom writes its own colour", ok, seen)

    for value, want in (("true", True), ("false", False)):
        b.run(CHOOSE, ["#tabStripPosition", value])
        ok, seen = wait_pref(b, "vertical_tabs.enabled", want)
        check(f"Tabs: {'Side' if want else 'Top'} writes vertical_tabs.enabled", ok, seen)
    for value, want in (("false", False), ("true", True)):
        b.run(CHOOSE, ["#showBookmarksBar", value])
        ok, seen = wait_pref(b, "bookmark_bar.show_on_all_tabs", want)
        check(f"Bookmarks: {'Bar on top' if want else 'Off'} writes "
              "bookmark_bar.show_on_all_tabs", ok, seen)

    b.run(CLICK, ["#customizeToolbar"])
    check("Toolbar buttons: Customize opens the Customize toolbar panel", panel_open(b))


# boring: fix-look (ledger items 23, 31, 35)
# Dusk's page, card (its bar) and edge (boring_color_mixer.cc, kDuskDark).
DUSK_PAGE_BG = "rgb(20, 21, 32)"
DUSK_CARD_BG = "rgb(27, 29, 43)"
DUSK_EDGE = "rgb(124, 128, 156)"


def seed(prof, look=None, scheme=None):
    """A new profile holding the Look and the browser's own Light or dark
    (browser.theme.color_scheme2: 0 match system, 1 light, 2 dark)."""
    prefs = {}
    if look:
        prefs["boring"] = {"appearance": {"look": look}}
    if scheme is not None:
        prefs["browser"] = {"theme": {"color_scheme2": scheme}}
    default = Path(prof) / "Default"
    default.mkdir(parents=True, exist_ok=True)
    (default / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")


def check_rings(check, tag, s, edge):
    for value, name, is_pressed, shadow in s["dots"]:
        if is_pressed != "true" and value in LOW_IN_DARK:
            check(f"{tag}: the {name} dot has an edge ring", edge in shadow, shadow)


def check_dark_by_setting(check):
    """Dark picked in our own Light or dark, on a light system (no
    --force-dark-mode): the page, the card and the dots' rings are dark."""
    tag = "Dark picked on a light system"
    with tempfile.TemporaryDirectory(prefix="cui-settings-dark-", dir=os.environ.get("TMP")) as prof:
        seed(prof, scheme=2)
        with Browser(user_data_dir=prof, args=["--window-size=1280,800"]) as b:
            b.get("chrome://settings/appearance")
            s = wait(lambda: state(b), 20)
    check(f"{tag}: the page loads", s, s)
    if not s:
        return
    check(f"{tag}: Dark is pressed and the page is dark",
          pressed(s).get("Dark") == "true" and s["dark"], (pressed(s), s["dark"]))
    check(f"{tag}: the card is the dark surface", s["cardBg"] == CARD_BG[True], s["cardBg"])
    check_rings(check, tag, s, EDGE_DARK)


def check_dusk(check):
    """Dusk with Light picked, on a light system: Settings is Dusk's dark,
    its card is Dusk's card, Light or dark says it does not apply and keeps
    the person's Light; picking Soft white brings Light back."""
    tag = "Dusk with Light picked"
    with tempfile.TemporaryDirectory(prefix="cui-settings-dusk-", dir=os.environ.get("TMP")) as prof:
        seed(prof, look="dusk", scheme=1)
        with Browser(user_data_dir=prof, args=["--window-size=1280,800"]) as b:
            b.get("chrome://settings/appearance")
            s = wait(lambda: state(b), 20)
            check(f"{tag}: the page loads", s, s)
            if not s:
                return
            check(f"{tag}: the page is dark", s["dark"], s["dark"])
            check(f"{tag}: the page is Dusk's page", s["pageBg"] == DUSK_PAGE_BG, s["pageBg"])
            check(f"{tag}: the card is Dusk's card", s["cardBg"] == DUSK_CARD_BG, s["cardBg"])
            check(f"{tag}: Light or dark says Dusk is always dark",
                  s["duskNote"] == "Dusk is always dark.", s["duskNote"])
            check(f"{tag}: Light or dark does not apply (its buttons are off)",
                  s["modesDisabled"] == [True, True, True], s["modesDisabled"])
            check(f"{tag}: the person's Light is still the one pressed",
                  pressed(s).get("Light") == "true", pressed(s))
            check_rings(check, tag, s, DUSK_EDGE)
            b.run(CLICK, ['#boringLookRow .cui-look[data-value="soft_white"]'])
            s = wait(lambda: (lambda st: st if st and not st["dark"] else None)(state(b)), 8)
            s = s or state(b)
            check("Soft white picked after Dusk: Light applies again, no note, buttons on",
                  s and not s["dark"] and not s["duskNote"]
                  and s["modesDisabled"] == [False, False, False],
                  s and (s["dark"], s["duskNote"], s["modesDisabled"]))


HOSTILE_ACCENT = "#000;background:red"
CUSTOM_STYLE = PAGE + """
var c = r && r.querySelector('#boringAccentRow .cui-custom');
return c ? [c.getAttribute('style'), c.querySelector('input').value] : null;
"""


def check_hostile_accent(check):
    """An accent pref that is not "#" and six hex digits (a hand-edited
    Preferences file) never reaches the style attribute: the default does."""
    with tempfile.TemporaryDirectory(prefix="cui-settings-accent-", dir=os.environ.get("TMP")) as prof:
        path = Path(prof) / "Default" / "Preferences"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"boring": {"appearance": {"accent": HOSTILE_ACCENT}}}),
                        encoding="utf-8")
        with Browser(user_data_dir=prof, args=["--window-size=1280,800"]) as b:
            b.get("chrome://settings/appearance")
            wait(lambda: state(b), 20)
            got = wait(lambda: b.run(CUSTOM_STYLE), 8)
    check("A bad accent pref puts the default accent in the style attribute",
          got and "background" not in (got[0] or "") and "#4f46e5" in (got[0] or "")
          and got[1] == "#4f46e5", got)
# boring: end fix-look


# boring: fix-3b (ledger item 46)
def check_theme_reset(check):
    """A profile on a theme that is not ours (with no web store here, the
    colour theme Chromium builds from autogenerated.theme.color: the same
    not-default path a store theme takes) is put back on our own colours
    when a Look is picked (theme_service.cc, cui-colours.patch), and also
    when the Look picked is the one already chosen (item 49: the pref does
    not change then, so the page resets the theme itself)."""
    for tag, look in (("Look picked on a profile with a theme", None),
                      ("Look already chosen picked again on a profile with a theme", "slate")):
        check_theme_reset_once(check, tag, look)


def check_theme_reset_once(check, tag, look):
    with tempfile.TemporaryDirectory(prefix="cui-settings-theme-", dir=os.environ.get("TMP")) as prof:
        path = Path(prof) / "Default" / "Preferences"
        path.parent.mkdir(parents=True, exist_ok=True)
        prefs = {
            "extensions": {"theme": {"id": "autogenerated_theme_id"}},
            "autogenerated": {"theme": {"color": -16744448}},  # 0xFF008000
        }
        if look:
            prefs["boring"] = {"appearance": {"look": look}}
        path.write_text(json.dumps(prefs), encoding="utf-8")
        with Browser(user_data_dir=prof, args=["--window-size=1280,800"]) as b:
            b.get("chrome://settings/appearance")
            s = wait(lambda: state(b), 20)
            check(f"{tag}: the page loads", s, s)
            if not s:
                return
            before = pref(b, "extensions.theme.id")
            check(f"{tag}: the theme is on before", before == "autogenerated_theme_id", before)
            b.run(CLICK, ['#boringLookRow .cui-look[data-value="slate"]'])
            ok, seen = wait_pref(b, "extensions.theme.id", "")
            check(f"{tag}: picking a Look resets the theme to the default", ok, seen)
            ok, seen = wait_pref(b, "boring.appearance.look", "slate")
            check(f"{tag}: and the Look is written", ok, seen)
# boring: end fix-3b


def capture(b, dark, captures=None):
    from capture_native import frame_window, grab, user32
    from drive import OFFSCREEN

    name = "settings-appearance-" + ("dark" if dark else "light")
    hwnd = frame_window(CHROME, under=b.proc.pid)
    px, py = (int(v) for v in OFFSCREEN.split(","))
    user32.MoveWindow(hwnd, px, py, 1280, 800, True)
    time.sleep(1.0)
    grab(hwnd, str(OUT / f"{name}.png"))
    both = page_checks.save_capture(OUT / f"{name}.png", "settings", "c10", dark=dark, folder=captures)
    print("saved", OUT / f"{name}.png", "and", both or "no capture beside the design")


def run(dark, check, shoot, captures=None):
    args = ["--window-size=1280,800",
            "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion"]
    if dark:
        args.append("--force-dark-mode")
    with tempfile.TemporaryDirectory(prefix="cui-settings-", dir=os.environ.get("TMP")) as prof:
        with Browser(user_data_dir=prof, args=args, headful=shoot,
                     keep_switches=["enable-automation"]) as b:
            check_page(b, check, dark)
            if shoot:
                capture(b, dark, captures)
            if not dark:
                check_writes(b, check)


def main():
    ap = argparse.ArgumentParser()
    page_checks.add_captures_option(ap)
    opts = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    check = Checks()
    shoot = headful_allowed()
    if not shoot:
        print("pictures: not taken (set BORING_ALLOW_HEADFUL=1)")
    for dark in (False, True):
        run(dark, check, shoot, opts.captures)
    check_dark_by_setting(check)
    check_dusk(check)
    check_hostile_accent(check)
    check_theme_reset(check)
    failed = [n for n, (ok, _) in check.items.items() if not ok]
    (OUT / "results.json").write_text(json.dumps(check.items, indent=1), encoding="utf-8")
    print(f"\n{'FAIL' if failed else 'PASS'}: settings appearance, "
          f"{len(failed)} of {len(check.items)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
