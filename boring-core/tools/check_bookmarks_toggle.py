#!/usr/bin/env python3
"""Check, in a real window, that Settings, Appearance, "Show bookmarks bar"
really shows and hides the bar (ledger 114, Release 3).

A fresh profile shows the bar with "Bookmarks you add show here". The switch
is clicked in the page (WebDriver), then the browser window is read through
UI Automation on our own window: the hint must go, and come back when the
switch is put back. The preference bookmark_bar.show_on_all_tabs follows.

Usage: python check_bookmarks_toggle.py
Needs BORING_OUT and BORING_ALLOW_HEADFUL=1. The window is off screen. Sends
no mouse or keys to the desktop.
"""

import sys
import tempfile
import time

from drive import Browser
from smoke_r3_fixes import FIND
from smoke_site_panel import Window, browser_windows

HINT = "Bookmarks you add show here"

FIND_TOGGLE = (
    FIND
    + r"""
function all(root, out) {
  root.querySelectorAll('settings-toggle-button').forEach(t => out.push(t));
  root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) all(e.shadowRoot, out); });
  return out;
}
const t = all(document, []).find(x => (x.label || '').indexOf('bookmarks bar') >= 0
                                      && (x.label || '').indexOf('tab groups') < 0);
"""
)
READ = (
    FIND_TOGGLE + "return t ? {label: t.label, checked: !!t.checked, "
    "pref: t.pref ? t.pref.value : null} : null;"
)
CLICK = FIND_TOGGLE + "if (t) t.click(); return !!t;"


def hint_visible(driver_pid):
    for hwnd in browser_windows(driver_pid):
        with Window(hwnd) as w:
            if any(HINT in n for n in w.names()):
                return True
    return False


def wait_hint(driver_pid, want, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if hint_visible(driver_pid) == want:
            return True
        time.sleep(0.5)
    return False


def main():
    failures = []

    def check(name, ok, detail=""):
        print(
            ("PASS: " if ok else "FAIL: ") + name + (f" ({detail})" if detail else "")
        )
        if not ok:
            failures.append(name)

    with (
        tempfile.TemporaryDirectory(prefix="r3-bmtoggle-") as profile,
        Browser(user_data_dir=profile, headful=True) as b,
    ):
        pid = b.proc.pid
        b.get("chrome://settings/appearance")
        time.sleep(3)
        state = b.run(READ)
        check(
            "the page has a Show bookmarks bar switch, on",
            bool(state and state["checked"]),
            str(state),
        )
        check("the bar shows its hint in the window", wait_hint(pid, True))
        b.run(CLICK)
        time.sleep(1)
        state = b.run(READ)
        check(
            "clicked: the switch is off and its pref is false",
            bool(state) and not state["checked"] and state["pref"] is False,
            str(state),
        )
        check("clicked: the bar is gone from the window", wait_hint(pid, False))
        b.run(CLICK)
        time.sleep(1)
        state = b.run(READ)
        check(
            "clicked again: the switch is on and its pref is true",
            bool(state) and state["checked"] and state["pref"] is True,
            str(state),
        )
        check("clicked again: the bar is back", wait_hint(pid, True))
    print(f"\n{'FAIL' if failures else 'PASS'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
