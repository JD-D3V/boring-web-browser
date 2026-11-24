#!/usr/bin/env python3
"""Check the Look (compiled UI ledger item 2) in light and dark.

For each Look (Soft white, the default; Slate; Dusk) the profile pref
boring.appearance.look is written into a new profile before the browser
starts, and the colours the browser's own colour provider hands out are
read back as resolved CSS variables from chrome://theme/colors.css, which
comes from the same provider the native views use (as smoke_ui_polish.py
does). They must be the palettes of boring_color_mixer.cc: the frame band,
the toolbar, the address bar's fill and its edge, the ink; the edge colour
id (kColorBoringEdge) and the ok green (kColorBoringOk); and, where the
Look draws an edge of its own, text fields, outline buttons and off
switches in that edge.

Dusk is always dark (ledger item 23): on a light system, and with the
browser's own Light or dark set to Light, the window, Settings and the new
tab page draw Dusk's dark colours, and the Light choice stays in its pref.

Then a new Look must repaint at once: Soft white is changed to Slate the
way the Settings control writes it (chrome.settingsPrivate.setPref) and
the frame band must follow without a restart. Until Settings lists the
pref (compiled UI item 9), setPref refuses it and that check is reported
as NOT CHECKED, which fails the run.

The accent (ledger item 20, the pref boring.appearance.accent): under
each Look, light and dark, a profile holding Rose (white ink on it), a
pale yellow (black ink on it) or a value that is not "#rrggbb" (the
Look's own accent) must hand out that accent as kColorSysPrimary, the
readable ink on it as kColorSysOnPrimary, a focus ring at 3 to 1 on the
toolbar, and the Look's own frame band, so the palette stays ours. Then
the accent is changed to Teal the way the Settings control writes it and
must follow at once (NOT CHECKED until Settings lists the pref, item 9).

Release 2's colour choices (ledger item 61, steps marked [cui-old-colours]):
profiles seeded with what the old Customize colour picker wrote (Green
exactly as Release 2 stored it, grey, "Default", device colours) must draw
the Look's palette with the accent, Settings must show that Look, and the
stored colour state must be a new profile's afterwards; old Green also
gets the accent row's green, and picking Slate repaints. With
BORING_ALLOW_HEADFUL=1 the Customize side panel must show no Appearance
card and no swatches (else that step is skipped and says so).

With BORING_ALLOW_HEADFUL=1 it also photographs the new tab page of each
Look, light and dark, by PrintWindow of our own window. With --captures (or
BORING_CAPTURES) each picture is also saved as
<folder>/colours/c01-<look>-light.png and c02-<look>-dark.png, the real
capture on the left and the compiled screen (c01 for light, c02 for dark)
on the right. Sends no mouse or keys to the desktop.

    python smoke_colours.py            # expects "PASS: colours"
    python smoke_colours.py --no-live  # skip the live changes
    python smoke_colours.py --captures E:/tmp/cui-captures

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests).
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import page_checks
from drive import CHROME, Browser, headful_allowed

PREF = "boring.appearance.look"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "cui-colours"
# The compiled screen of the new tab page, light and dark. design/ is not in
# git: page_checks finds the main checkout's, or BORING_DESIGN names it.
SCREEN = {False: "c01", True: "c02"}

# Look, dark -> colour as boring_color_mixer.cc sets it. Dusk is always
# dark (ledger item 23): its one palette on a light system too. Slate has
# no edge of its own: its edge is its line, and text fields, buttons and
# switches keep Chromium's colours there.
SOFT_LIGHT = {"frame": "eceae6", "toolbar": "ffffff", "field": "f4f3ef",
              "ink": "1f1e1c", "edge": "8a867d"}
SOFT_DARK = {"frame": "111110", "toolbar": "1c1c1a", "field": "121211",
             "ink": "ecebe7", "edge": "77756d"}
SLATE_LIGHT = {"frame": "d3d6e3", "toolbar": "ffffff", "field": "eef0f6",
               "ink": "23242e", "edge": "d9dbe6"}
SLATE_DARK = {"frame": "0a0b0f", "toolbar": "1d1e28", "field": "0f1015",
              "ink": "dcdde6", "edge": "2c2d3a"}
DUSK_DARK = {"frame": "0f1017", "toolbar": "1b1d2b", "field": "262838",
             "ink": "e6e7f0", "edge": "7c809c"}
EXPECT = {
    ("soft_white", False): SOFT_LIGHT,
    ("soft_white", True): SOFT_DARK,
    ("slate", False): SLATE_LIGHT,
    ("slate", True): SLATE_DARK,
    ("dusk", False): DUSK_DARK,
    ("dusk", True): DUSK_DARK,
}
OK = {False: "1a7f55", True: "4cc38a"}
DRAWN_EDGE = {"soft_white", "dusk"}

# Palette field -> the CSS variables of the ids the mixer gives it.
VARS = {
    "frame": ["--color-frame-active"],
    "toolbar": ["--color-toolbar", "--color-info-bar-background"],
    "field": ["--color-location-bar-background"],
    "ink": ["--color-omnibox-text", "--color-info-bar-foreground"],
    "edge": ["--color-location-bar-border", "--color-boring-edge"],
}
EDGE_CONTROLS = [
    "--color-textfield-outline",
    "--color-button-border",
    "--color-toggle-button-track-off",
]
OK_VAR = "--color-boring-ok"

RESOLVE = r"""
  const out = {};
  const p = document.createElement('div');
  document.body.appendChild(p);
  for (const n of arguments[0]) {
    p.style.color = 'var(' + n + ')';
    out[n] = getComputedStyle(p).color;
  }
  return out;
"""


def rgb(hex6):
    return "rgb({}, {}, {})".format(*(int(hex6[i:i + 2], 16) for i in (0, 2, 4)))


def all_vars():
    names = [n for group in VARS.values() for n in group]
    return names + EDGE_CONTROLS + [OK_VAR]


def seed_profile(path, look, accent=None, scheme=None):
    """A new profile holding the Look, as Settings would have left it, and
    the browser's own Light or dark when `scheme` is given (the pref
    ThemeService keeps it in: 0 match system, 1 light, 2 dark)."""
    appearance = {k: v for k, v in (("look", look), ("accent", accent)) if v is not None}
    if not appearance and scheme is None:
        return
    default = Path(path) / "Default"
    default.mkdir(parents=True, exist_ok=True)
    prefs = {"boring": {"appearance": appearance}} if appearance else {}
    if scheme is not None:
        prefs["browser"] = {"theme": {"color_scheme2": scheme}}
    (default / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")


def resolve(b):
    b.get("chrome://theme/colors.css?sets=ui,chrome")
    css = b.run("return document.documentElement.innerText")
    have = set(re.findall(r"(--color-[a-z0-9-]+):", css))
    b.get("chrome://settings/help")
    time.sleep(1.0)
    return have, b.run(RESOLVE, [all_vars()])


def expect_rows(look, dark):
    want = EXPECT[(look, dark)]
    rows = [(n, want[field]) for field, names in VARS.items() for n in names]
    rows.append((OK_VAR, OK[dark or look == "dusk"]))
    if look in DRAWN_EDGE:
        rows += [(n, want["edge"]) for n in EDGE_CONTROLS]
    return rows


def check_look(look, dark, checks):
    tag = f"{look} {'dark' if dark else 'light'}"
    args = ["--window-size=1200,700"] + (["--force-dark-mode"] if dark else [])
    with tempfile.TemporaryDirectory(prefix="colours-", dir=os.environ.get("TMP")) as prof:
        # Soft white is the default: its light and dark runs write no pref.
        seed_profile(prof, None if look == "soft_white" else look)
        with Browser(user_data_dir=prof, args=args) as b:
            have, got = resolve(b)
    for name, hex6 in expect_rows(look, dark):
        checks[f"{tag}: {name} is #{hex6}"] = (
            name in have and got.get(name) == rgb(hex6),
            got.get(name),
        )


# boring: fix-look, Dusk is always dark (ledger item 23)
DARK_QUERY = "return matchMedia('(prefers-color-scheme: dark)').matches"


def check_dusk_always_dark(checks):
    """Dusk with the browser's own Light or dark set to Light, on a light
    system: the window and our pages are Dusk's dark colours, and the
    person's Light choice is still in its pref afterwards."""
    tag = "dusk with Light picked"
    with tempfile.TemporaryDirectory(prefix="colours-dusk-", dir=os.environ.get("TMP")) as prof:
        seed_profile(prof, "dusk", scheme=1)
        with Browser(user_data_dir=prof, args=["--window-size=1200,700"]) as b:
            have, got = resolve(b)
            settings_dark = b.run(DARK_QUERY)
            b.get("chrome://newtab")
            time.sleep(1.0)
            newtab_dark = b.run(DARK_QUERY)
            page = b.run(RESOLVE, [["--color-new-tab-page-background"]])
        saved = json.loads((Path(prof) / "Default" / "Preferences").read_text(encoding="utf-8"))
    for name, hex6 in expect_rows("dusk", True):
        checks[f"{tag}: {name} is #{hex6}"] = (
            name in have and got.get(name) == rgb(hex6), got.get(name))
    checks[f"{tag}: Settings draws dark"] = (settings_dark is True, settings_dark)
    checks[f"{tag}: the new tab page draws dark"] = (newtab_dark is True, newtab_dark)
    bg = page.get("--color-new-tab-page-background")
    checks[f"{tag}: the new tab page is Dusk's page #141520"] = (bg == rgb("141520"), bg)
    kept = saved.get("browser", {}).get("theme", {}).get("color_scheme2")
    checks[f"{tag}: the Light choice is kept in its pref"] = (kept == 1, kept)
# boring: end fix-look


def set_pref(b, value, pref=PREF):
    """Write the pref the way the Settings control does, and read it back."""
    b.get("chrome://settings/appearance")
    time.sleep(1.5)
    return b.run_async(
        "const done = arguments[arguments.length - 1];"
        "chrome.settingsPrivate.setPref(arguments[0], arguments[1], '', ok => {"
        "  chrome.settingsPrivate.getPref(arguments[0], p => done([ok, p && p.value]));"
        "});",
        [pref, value],
    )


def check_live(checks):
    with tempfile.TemporaryDirectory(prefix="colours-live-", dir=os.environ.get("TMP")) as prof:
        with Browser(user_data_dir=prof, args=["--window-size=1200,700"]) as b:
            _, before = resolve(b)
            ok, value = set_pref(b, "slate")
            if not ok or value != "slate":
                checks["live: Settings can write the Look"] = (
                    None, "NOT CHECKED: settingsPrivate refused the pref (item 9)")
                return
            _, after = resolve(b)
    frame = "--color-frame-active"
    checks["live: Soft white before the change"] = (
        before.get(frame) == rgb(SOFT_LIGHT["frame"]), before.get(frame))
    checks["live: Slate at once, no restart"] = (
        after.get(frame) == rgb(SLATE_LIGHT["frame"]), after.get(frame))


# boring: cui-accent
ACCENT_PREF = "boring.appearance.accent"
# The Look's own accent (boring_color_mixer.cc), shown for the default and
# for anything that is not "#rrggbb".
OWN_ACCENT = {False: "4f46e5", True: "9d9aff"}
OWN_ACCENT_SOFT_DARK = "9b98ff"
# Pref value -> (accent, ink on it). Rose takes white; the pale yellow
# fails 4.5 to 1 with white, so it takes black.
ACCENTS = {"#be2d5a": ("be2d5a", "ffffff"), "#f5e663": ("f5e663", "000000"),
           "be2d5a": (None, None)}
ACCENT_VARS = ["--color-frame-active", "--color-toolbar", "--color-sys-primary",
               "--color-sys-on-primary", "--color-sys-state-focus-ring"]


def parse_rgb(css):
    m = re.match(r"rgba?\((\d+), (\d+), (\d+)", css or "")
    return tuple(int(v) for v in m.groups()) if m else None


def contrast(a, b):
    def lum(c):
        lin = [(v / 255) / 12.92 if v / 255 <= 0.04045 else ((v / 255 + 0.055) / 1.055) ** 2.4
               for v in c]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def read_accent(b):
    have, _ = resolve(b)
    got = b.run(RESOLVE, [ACCENT_VARS])
    return have, got


def check_accent(look, dark, value, checks):
    tag = f"accent {value!r} {look} {'dark' if dark else 'light'}"
    args = ["--window-size=1200,700"] + (["--force-dark-mode"] if dark else [])
    want_fill, want_on = ACCENTS[value]
    if want_fill is None:
        # Dusk, always dark, has the design's dark accent as Soft white has.
        design_dark = (look, dark) == ("soft_white", True) or look == "dusk"
        want_fill = OWN_ACCENT_SOFT_DARK if design_dark else OWN_ACCENT[dark]
    with tempfile.TemporaryDirectory(prefix="colours-accent-", dir=os.environ.get("TMP")) as prof:
        seed_profile(prof, None if look == "soft_white" else look, value)
        with Browser(user_data_dir=prof, args=args) as b:
            have, got = read_accent(b)
    frame = EXPECT[(look, dark)]["frame"]
    checks[f"{tag}: frame stays the Look's #{frame}"] = (
        got.get("--color-frame-active") == rgb(frame), got.get("--color-frame-active"))
    checks[f"{tag}: accent is #{want_fill}"] = (
        "--color-sys-primary" in have and got.get("--color-sys-primary") == rgb(want_fill),
        got.get("--color-sys-primary"))
    if want_on:
        checks[f"{tag}: ink on the accent is #{want_on}"] = (
            got.get("--color-sys-on-primary") == rgb(want_on), got.get("--color-sys-on-primary"))
    fill, on = parse_rgb(got.get("--color-sys-primary")), parse_rgb(got.get("--color-sys-on-primary"))
    ring, bar = parse_rgb(got.get("--color-sys-state-focus-ring")), parse_rgb(got.get("--color-toolbar"))
    checks[f"{tag}: ink on the accent at 4.5 to 1"] = (
        bool(fill and on) and contrast(fill, on) >= 4.5, got.get("--color-sys-on-primary"))
    checks[f"{tag}: focus ring at 3 to 1 on the toolbar"] = (
        bool(ring and bar) and contrast(ring, bar) >= 3, got.get("--color-sys-state-focus-ring"))


def check_accent_live(checks):
    with tempfile.TemporaryDirectory(prefix="colours-accent-live-", dir=os.environ.get("TMP")) as prof:
        with Browser(user_data_dir=prof, args=["--window-size=1200,700"]) as b:
            ok, value = set_pref(b, "#0f766e", ACCENT_PREF)
            if not ok or value != "#0f766e":
                checks["live: Settings can write the accent"] = (
                    None, "NOT CHECKED: settingsPrivate refused the pref (item 9)")
                return
            _, after = read_accent(b)
    checks["live: Teal at once, no restart"] = (
        after.get("--color-sys-primary") == rgb("0f766e"), after.get("--color-sys-primary"))
    checks["live: frame stays Soft white"] = (
        after.get("--color-frame-active") == rgb(SOFT_LIGHT["frame"]),
        after.get("--color-frame-active"))
# boring: end cui-accent


# boring: cui-old-colours (ledger 61). Release 2's colour choices are retired:
# a stored Chromium user colour never picks the palette or switches the Look
# or the accent off, and the startup migration puts it back to a new
# profile's (boring_prefs.cc ResetRetiredColourPrefs).
# How ThemeService stored Release 2's Green swatch (opaque 0x1f8a72) in
# browser.theme.user_color2, and its variant (BrowserColorVariant kTonalSpot).
GREEN_SEED_INT = 0xFF1F8A72 - (1 << 32)
TONAL_SPOT = 1
ACCENT_GREEN = "#1a7f55"  # the Green dot of the accent row in Settings
# Release 2's Green palette, which must not come back (Cool surfaces with a
# green accent): its accent, light.
OLD_GREEN_ACCENT = "176b5b"
# Pref -> what a new profile has: absent, or the stated value.
FRESH = {
    ("browser", "theme", "user_color2"): None,
    ("browser", "theme", "color_variant2"): None,
    ("browser", "theme", "is_grayscale2"): False,
    ("browser", "theme", "follows_system_colors"): False,
    ("extensions", "theme", "id"): "",
}
# name -> (browser.theme prefs as the old picker wrote them, theme id, Look,
# accent, Look's light frame expected, accent expected).
OLD_STATES = {
    # SetUserColorAndBrowserColorVariant(Green, kTonalSpot), then
    # UseDeviceTheme(false): exactly what picking Green in Release 2 wrote.
    "old Green": ({"user_color2": GREEN_SEED_INT, "color_variant2": TONAL_SPOT,
                   "follows_system_colors": False}, "user_color_theme_id",
                  None, None, SOFT_LIGHT["frame"], ACCENT_GREEN[1:]),
    # The grey swatch: SetIsGrayscale(true).
    "old grey": ({"is_grayscale2": True, "follows_system_colors": False}, "",
                 "slate", "#be2d5a", SLATE_LIGHT["frame"], "be2d5a"),
    # The picker's "Default": SetUserColor(nullopt) stores transparent.
    "old Default": ({"user_color2": 0, "follows_system_colors": False}, "",
                    "slate", "#0f766e", SLATE_LIGHT["frame"], "0f766e"),
    # Follow device colours on.
    "old device colours": ({"follows_system_colors": True}, "",
                           None, None, SOFT_LIGHT["frame"], OWN_ACCENT[False]),
}


def seed_old_state(path, theme, theme_id, look=None, accent=None):
    default = Path(path) / "Default"
    default.mkdir(parents=True, exist_ok=True)
    prefs = {"browser": {"theme": dict(theme)}, "extensions": {"theme": {"id": theme_id}}}
    appearance = {k: v for k, v in (("look", look), ("accent", accent)) if v is not None}
    if appearance:
        prefs["boring"] = {"appearance": appearance}
    (default / "Preferences").write_text(json.dumps(prefs), encoding="utf-8")


def dig(prefs, keys):
    for k in keys:
        if not isinstance(prefs, dict) or k not in prefs:
            return None
        prefs = prefs[k]
    return prefs


def check_old_state(name, checks):
    """A profile seeded with an old picker state: the window draws the
    Look's palette with the accent, Settings shows the Look drawn, and the
    stored colour state is a new profile's after the run. For old Green
    also: the accent is the row's green and picking Slate repaints."""
    from smoke_settings_appearance import CLICK, state, wait, wait_pref

    theme, theme_id, look, accent, frame, want_accent = OLD_STATES[name]
    tag = f"[cui-old-colours] {name}"
    with tempfile.TemporaryDirectory(prefix="colours-old-", dir=os.environ.get("TMP")) as prof:
        seed_old_state(prof, theme, theme_id, look, accent)
        with Browser(user_data_dir=prof, args=["--window-size=1200,700"]) as b:
            _, got = read_accent(b)
            b.get("chrome://settings/appearance")
            s = wait(lambda: state(b), 20)
            slate = None
            if name == "old Green" and s:
                b.run(CLICK, ['#boringLookRow .cui-look[data-value="slate"]'])
                if wait_pref(b, PREF, "slate")[0]:
                    _, slate = read_accent(b)
        saved = json.loads((Path(prof) / "Default" / "Preferences").read_text(encoding="utf-8"))
    seen_frame = got.get("--color-frame-active")
    checks[f"{tag}: the window draws the Look's frame #{frame}"] = (
        seen_frame == rgb(frame), seen_frame)
    seen_accent = got.get("--color-sys-primary")
    checks[f"{tag}: the accent applies, #{want_accent}"] = (
        seen_accent == rgb(want_accent), seen_accent)
    drawn = look or "soft_white"
    looks = (s or {}).get("looks") or []
    shown = [v for v, _title, on in looks if on == "true"]
    checks[f"{tag}: Settings shows the Look drawn ({drawn})"] = (shown == [drawn], shown)
    for keys, fresh in FRESH.items():
        value = dig(saved, keys)
        checks[f"{tag}: {'.'.join(keys)} is a new profile's"] = (
            value is None or value == fresh, value)
    if name == "old Green":
        checks[f"{tag}: not the old Green palette"] = (
            seen_accent != rgb(OLD_GREEN_ACCENT) and seen_frame != rgb(SLATE_LIGHT["frame"]),
            (seen_frame, seen_accent))
        kept = dig(saved, ("boring", "appearance", "accent"))
        checks[f"{tag}: the accent pref is the row's green {ACCENT_GREEN}"] = (
            kept == ACCENT_GREEN, kept)
        dots = [v for v, _label, on, _ring in ((s or {}).get("dots") or []) if on == "true"]
        checks[f"{tag}: Settings shows the green dot picked"] = (dots == [ACCENT_GREEN], dots)
        slate_frame = (slate or {}).get("--color-frame-active")
        checks[f"{tag}: picking Slate repaints at once"] = (
            slate_frame == rgb(SLATE_LIGHT["frame"]), slate_frame)
        slate_accent = (slate or {}).get("--color-sys-primary")
        checks[f"{tag}: and keeps the green accent"] = (
            slate_accent == rgb(ACCENT_GREEN[1:]), slate_accent)


# The Customize side panel's overview, read through every shadow root.
SIDE_PANEL = r"""(() => {
  const app = document.querySelector('customize-chrome-app');
  const r = app && app.shadowRoot;
  if (!r) return null;
  const vis = e => !!e && e.checkVisibility();
  const ap = r.querySelector('customize-chrome-appearance');
  const aps = ap && ap.shadowRoot;
  const picker = aps && aps.querySelector('cr-theme-color-picker');
  const ps = picker && picker.shadowRoot;
  const swatches = ps ? [...ps.querySelectorAll('*')].filter(
      e => /^CR-THEME-COLOR|^CR-THEME-HUE/.test(e.tagName) && vis(e)).length : 0;
  return {
    appearance: vis(r.querySelector('#appearance')),
    picker: vis(picker),
    swatches: swatches,
    follow: vis(aps && aps.querySelector('#followThemeToggle')),
    reset: vis(aps && aps.querySelector('#setClassicChromeButton')),
    toolbar: vis(r.querySelector('#toolbarButton')),
    sections: [...r.querySelectorAll('#overviewPage > .section')].filter(vis).map(e => e.id),
  };
})()"""


def check_side_panel(checks):
    """The Customize side panel offers no colour: its overview shows no
    Appearance card, no swatch, no follow device colours, no reset; the
    Toolbar card is still there. Opened the way Settings' Customize button
    opens it, then back to the overview (as smoke_quick_buttons.py does).
    Needs a headful launch (DevTools on chrome.exe)."""
    from smoke_memory import close, launch
    from smoke_quick_buttons import BACK, open_picker

    tag = "[cui-old-colours] side panel"
    work = Path(tempfile.mkdtemp(prefix="colours-panel-", dir=os.environ.get("TMP")))
    proc = cdp = None
    try:
        proc, cdp = launch(CHROME, work, ["--disable-features=CalculateNativeWinOcclusion"])
        panel = open_picker(cdp)
        checks[f"{tag}: the panel opens"] = (bool(panel), panel)
        if not panel:
            return
        cdp.evaluate(panel, BACK)
        cdp.wait_for(panel, "(" + SIDE_PANEL + " || {}).toolbar === true", 10)
        got = cdp.evaluate(panel, SIDE_PANEL) or {}
    finally:
        if proc:
            close(proc, cdp)
        shutil.rmtree(work, ignore_errors=True)
    checks[f"{tag}: no Appearance card"] = (got.get("appearance") is False, got)
    checks[f"{tag}: no colour swatches or hue"] = (
        got.get("picker") is False and got.get("swatches") == 0, got)
    checks[f"{tag}: no follow device colours, no reset"] = (
        got.get("follow") is False and got.get("reset") is False, got)
    checks[f"{tag}: the Toolbar card is still there and alone"] = (
        got.get("toolbar") is True and got.get("sections") == ["toolbarButton"], got)
# boring: end cui-old-colours


def capture(look, dark, captures=None):
    from capture_native import frame_window, grab, user32
    from drive import OFFSCREEN

    w, h = 1280, 800
    name = f"{look}-{'dark' if dark else 'light'}"
    args = [
        f"--window-size={w},{h}",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
    ] + (["--force-dark-mode"] if dark else [])
    with tempfile.TemporaryDirectory(prefix="colours-shot-", dir=os.environ.get("TMP")) as prof:
        seed_profile(prof, None if look == "soft_white" else look)
        with Browser(user_data_dir=prof, args=args, headful=True,
                     keep_switches=["enable-automation"]) as b:
            b.get("chrome://newtab")
            hwnd = frame_window(CHROME, under=b.proc.pid)
            px, py = (int(v) for v in OFFSCREEN.split(","))
            user32.MoveWindow(hwnd, px, py, w, h, True)
            time.sleep(1.0)
            grab(hwnd, str(OUT / f"{name}.png"))
    both = page_checks.save_capture(
        OUT / f"{name}.png", "colours", SCREEN[dark], dark=dark, folder=captures,
        label=f"{SCREEN[dark]}-{look.replace('_', '-')}")
    print("saved", OUT / f"{name}.png", "and", both or "no capture beside the design")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-live", action="store_true")
    page_checks.add_captures_option(parser)
    opts = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    for look in ("soft_white", "slate", "dusk"):
        for dark in (False, True):
            check_look(look, dark, checks)
    for look in ("soft_white", "slate", "dusk"):
        for dark in (False, True):
            for value in ACCENTS:
                check_accent(look, dark, value, checks)
    check_dusk_always_dark(checks)
    # boring: cui-old-colours
    for name in OLD_STATES:
        check_old_state(name, checks)
    if headful_allowed():
        check_side_panel(checks)
    else:
        print("[cui-old-colours] side panel: not checked (set BORING_ALLOW_HEADFUL=1)")
    # boring: end cui-old-colours
    if not opts.no_live:
        check_live(checks)
        check_accent_live(checks)
    if headful_allowed():
        for look in ("soft_white", "slate", "dusk"):
            for dark in (False, True):
                capture(look, dark, opts.captures)
    else:
        print("pictures: not taken (set BORING_ALLOW_HEADFUL=1)")

    failed = 0
    for name, (passed, seen) in checks.items():
        mark = "PASS" if passed else ("NOT CHECKED" if passed is None else "FAIL")
        failed += passed is not True
        print(f"{mark}: {name} (saw {seen})")
    (OUT / "results.json").write_text(json.dumps(checks, indent=1), encoding="utf-8")
    print("PASS: colours" if not failed else f"FAIL: colours ({failed} of {len(checks)})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
