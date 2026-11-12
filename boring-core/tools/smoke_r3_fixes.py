#!/usr/bin/env python3
"""Check the 157 fixes found in the first real-window run (ledger 113 to
122) in the build, headless.

  - Settings, Protection: each of the four switches shows its pref's real
    value; switching one in the page writes the pref; a pref changed
    elsewhere moves the switch. Page summaries shows its note. (118)
  - The features this build keeps off are off: the contextual tasks page
    is not there even when --enable-features asks for it (113), the
    action based browser commands are off so our menu commands can be
    enabled (119), Settings reports the old bookmarks bar switch (114).
  - A fresh profile pins no add-on to the toolbar (115) and its side tabs
    do not expand on hover (122).
  - Chromium's "pin to your taskbar" infobar feature (SeparateDefaultAndPinPrompt)
    is off, read from the effective command line (Q52). The CDP feature
    state call only knows a short fixed list, so this is the one proof.

What only a real window shows (the app menu rows enabled, the bookmarks
bar drawn, no restore infobar) is left to the real-window pass.

Usage: python smoke_r3_fixes.py
Needs BORING_OUT, as the other smoke tests do.
"""

import json
import os
import sys
import tempfile
import time

from drive import Browser
from smoke_local import wait_for

FIND = r"""
function find(root, sel) {
  var hit = root.querySelector(sel);
  if (hit) return hit;
  var all = root.querySelectorAll('*');
  for (var i = 0; i < all.length; i++) {
    if (all[i].shadowRoot) {
      hit = find(all[i].shadowRoot, sel);
      if (hit) return hit;
    }
  }
  return null;
}
"""

TOGGLES = {
    "stopTakeoversToggle": "boring.protection.stop_takeovers",
    "noScamBypassToggle": "boring.protection.no_scam_bypass",
    "hideSponsoredToggle": "boring.hide_sponsored_results",
    "listUpdatesToggle": "boring.list_updates",
}

READ_TOGGLES = FIND + r"""
var out = {};
var ids = arguments[0];
for (var i = 0; i < ids.length; i++) {
  var t = find(document, 'settings-toggle-button#' + ids[i]);
  out[ids[i]] = t ? {checked: !!t.checked,
                     pref: t.pref ? t.pref.value : null} : 'missing';
}
return out;
"""

GET_PREF = """
const [key, done] = arguments;
chrome.settingsPrivate.getPref(key).then(p => done(p.value), e => done('error ' + e));
"""

SET_PREF = """
const [key, value, done] = arguments;
chrome.settingsPrivate.setPref(key, value).then(ok => done(ok), e => done('error ' + e));
"""

COMMAND_LINE = r"""
var el = document.getElementById('command_line');
return el ? el.innerText : '';
"""


def feature_list(command_line, switch):
    out = []
    for part in command_line.split():
        part = part.strip('"')
        if part.startswith(switch + "="):
            out.extend(n.lstrip("*").split("<")[0].split(":")[0]
                       for n in part.split("=", 1)[1].split(","))
    return out


def raw_list(command_line, switch):
    """The entries of every `switch=` on the command line, as written."""
    out = []
    for part in command_line.split():
        part = part.strip('"')
        if part.startswith(switch + "="):
            out.extend(part.split("=", 1)[1].split(","))
    return out


def base_name(entry):
    return entry.lstrip("*").split("<")[0].split(":")[0]


def main():
    failures = []

    def check(name, ok, detail=""):
        print(("PASS: " if ok else "FAIL: ") + name + (f" ({detail})" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    tmp = os.environ.get("TMP") or None
    ids = list(TOGGLES)

    with tempfile.TemporaryDirectory(prefix="r3-fixes-", dir=tmp) as profile:
        with Browser(user_data_dir=profile) as b:
            # --- 118: Protection switches -----------------------------------
            b.get("chrome://settings/protection")
            wait_for(b, "document.readyState === 'complete'", 10000)
            found = wait_for(
                b, FIND + "; (function(){var t = find(document, "
                "'settings-toggle-button#stopTakeoversToggle'); return t && t.pref;})()",
                15000)
            check("protection: the switches get their prefs", found)
            prefs = {k: b.run_async(GET_PREF, [k]) for k in TOGGLES.values()}
            shown = b.run(READ_TOGGLES, [ids])
            check("protection: the prefs this build turns on are on",
                  prefs[TOGGLES["stopTakeoversToggle"]] is True
                  and prefs[TOGGLES["hideSponsoredToggle"]] is True
                  and prefs[TOGGLES["listUpdatesToggle"]] is True, str(prefs))
            for tid, key in TOGGLES.items():
                s = shown.get(tid)
                check(f"protection: {tid} shows {key} = {prefs[key]}",
                      isinstance(s, dict) and s["checked"] == prefs[key]
                      and s["pref"] == prefs[key], f"{s} vs {prefs[key]}")

            key = TOGGLES["stopTakeoversToggle"]
            before = prefs[key]
            b.run(FIND + "find(document, 'settings-toggle-button#stopTakeoversToggle')"
                  ".shadowRoot.querySelector('#control').click(); return 1")
            time.sleep(1.0)
            after = b.run_async(GET_PREF, [key])
            check("protection: switching in the page writes the pref",
                  after is (not before), f"{before} -> {after}")
            b.run_async(SET_PREF, [key, before])
            moved = wait_for(
                b, FIND + "find(document, 'settings-toggle-button#stopTakeoversToggle')"
                f".checked === {'true' if before else 'false'}", 5000)
            check("protection: a pref changed elsewhere moves the switch", moved)

            # --- 118: Page summaries note -----------------------------------
            b.get("chrome://settings/summaries")
            wait_for(b, "document.readyState === 'complete'", 10000)
            has_note = wait_for(
                b, FIND + "(function(){var n = find(document, 'boring-summaries-page');"
                "var box = n && n.shadowRoot.querySelector('.boring-information');"
                "return box && box.textContent.trim().length > 0;})()", 15000)
            note = b.run(FIND + "var n = find(document, 'boring-summaries-page');"
                         "return n ? n.shadowRoot.querySelector('.boring-information')"
                         ".textContent.trim() : '';")
            check("summaries: the note box says where summaries go", has_note, repr(note))

            # --- 114: Settings has the 154 bookmarks bar switch -------------
            b.get("chrome://settings/appearance")
            wait_for(b, "document.readyState === 'complete'", 10000)
            flag = b.run_async(
                "const done = arguments[0];"
                "import('chrome://resources/js/load_time_data.js').then("
                "m => done(m.loadTimeData.getBoolean("
                "'ntpSimplificationBookmarksBarEnabled')), e => done('error ' + e));")
            check("bookmarks bar: new-tab-only feature off, so the bar follows "
                  "bookmark_bar.show_on_all_tabs", flag is False, str(flag))

            # --- 114, 115, 122: fresh profile prefs -------------------------
            b.get("chrome://version")
            wait_for(b, "document.readyState === 'complete'", 10000)
            cl = b.run(COMMAND_LINE)
            disabled = feature_list(cl, "--disable-features")
            for name in ("UseActionsForBrowserCommands", "ExtensionsPinnedByDefault",
                         "NtpSimplificationBookmarkBar", "SessionRestoreInfobar",
                         "IPH_VerticalTabsExpandOnHoverFeature", "ContextualTasks",
                         "SeparateDefaultAndPinPrompt"):
                check(f"command line: {name} is off", name in disabled, cl[-400:])

        time.sleep(1.0)
        prefs_path = os.path.join(profile, "Default", "Preferences")
        try:
            with open(prefs_path, encoding="utf-8") as f:
                stored = json.load(f)
        except OSError as e:
            stored = {"error": str(e)}
        pinned = stored.get("extensions", {}).get("pinned_extensions", [])
        check("fresh profile: no add-on pinned to the toolbar", pinned == [], str(pinned))
        hover = stored.get("vertical_tabs", {}).get("expand_on_hover_enabled")
        check("fresh profile: side tabs do not expand on hover by default",
              hover in (None, False), str(hover))
        show = stored.get("bookmark_bar", {}).get("show_on_all_tabs")
        check("fresh profile: bookmarks bar not turned off", show in (None, True), str(show))

    # --- 113: asked for on the command line, still off ----------------------
    with tempfile.TemporaryDirectory(prefix="r3-fixes-", dir=tmp) as profile:
        with Browser(user_data_dir=profile,
                     args=["--enable-features=ContextualTasks,ContextualTasksSidePanel,"
                           "UseActionsForBrowserCommands,ExtensionsPinnedByDefault"]) as b:
            b.get("chrome://version")
            wait_for(b, "document.readyState === 'complete'", 10000)
            cl = b.run(COMMAND_LINE)
            enabled = feature_list(cl, "--enable-features")
            disabled = feature_list(cl, "--disable-features")
            for name in ("ContextualTasks", "ContextualTasksSidePanel",
                         "UseActionsForBrowserCommands"):
                check(f"forced on: {name} still off",
                      name not in enabled and name in disabled, cl[-400:])
            check("forced on: a default-off feature can still be turned on",
                  "ExtensionsPinnedByDefault" in enabled
                  and "ExtensionsPinnedByDefault" not in disabled, cl[-400:])
            b.get("chrome://contextual-tasks")
            time.sleep(2.0)
            body = b.run("return document.body ? document.body.innerText.slice(0, 200) : ''")
            url = b.current_url()
            app = b.run("return !!document.querySelector('contextual-tasks-app')")
            check("forced on: chrome://contextual-tasks does not open",
                  not app, f"{url} {body!r}")

    # --- 127: "*Name" (use the default), a trial or params, still off -------
    with tempfile.TemporaryDirectory(prefix="r3-fixes-", dir=tmp) as profile:
        with Browser(user_data_dir=profile,
                     args=["--disable-features=*UseActionsForBrowserCommands,"
                           "AppMenuGlowUp<Trial",
                           "--enable-features=ContextualTasks,"
                           "ContextualTasksSidePanel:param/value,"
                           "*AppMenuGlowUp"]) as b:
            b.get("chrome://version")
            wait_for(b, "document.readyState === 'complete'", 10000)
            cl = b.run(COMMAND_LINE)
            enabled = raw_list(cl, "--enable-features")
            disabled = raw_list(cl, "--disable-features")
            for name in ("UseActionsForBrowserCommands", "ContextualTasks",
                         "ContextualTasksSidePanel", "AppMenuGlowUp"):
                check(f"any form: {name} only as a plain disable",
                      not [e for e in enabled if base_name(e) == name]
                      and [e for e in disabled if base_name(e) == name] == [name],
                      cl[-400:])

    print("FAILED: " + ", ".join(failures) if failures else "ALL PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
