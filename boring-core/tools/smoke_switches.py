#!/usr/bin/env python3
"""Check that three plain switches replaced Senior Safe Mode, and that a
profile which had it on keeps every protection it covered.

The old mode was one pref, boring.senior_safe_mode. It is gone from the
browser. Starting a profile that has it set must:

  - turn on all three switches (Stop screen takeovers, No way past scam
    warnings, Hide sponsored results), as the Protection page and the
    Welcome page report them,
  - clear the old pref from the profile's Preferences file, and store the
    three new ones,
  - run once only: a switch turned off afterwards stays off on the next
    start.

A fresh profile starts at the defaults (takeovers on, the other two off)
and carries no old pref. A profile with the old pref present but off
starts at the defaults too, with the old pref cleared.

Each profile is made the way a real one is: the browser starts once and
quits, then the Preferences file is edited while it is closed, then the
browser starts again.
"""

import json
import os
import sys
import tempfile
import time

from drive import Browser

PROTECTION_URL = "chrome://boring-protection"
WELCOME_URL = "chrome://boring-welcome"
OLD = "senior_safe_mode"

# Every switch as the Protection page shows it, once the page has been
# filled in. Before that all of them read off, which would pass a check
# for off, so the page is asked a question only the answer can fix first.
READ_SWITCHES = """
  return {
    takeovers: document.getElementById('stop-takeovers').checked,
    bypass: document.getElementById('no-bypass').checked,
    hide: document.getElementById('hide-ads').checked
  };
"""


def prefs_path(profile):
    return os.path.join(profile, "Default", "Preferences")


def read_prefs(profile):
    with open(prefs_path(profile), encoding="utf-8") as f:
        return json.load(f)


def write_prefs(profile, change):
    prefs = read_prefs(profile)
    change(prefs.setdefault("boring", {}))
    with open(prefs_path(profile), "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def stored(profile):
    """The three new prefs and the old one, as the file holds them."""
    boring = read_prefs(profile).get("boring", {})
    protection = boring.get("protection", {})
    return {
        "takeovers": protection.get("stop_takeovers"),
        "bypass": protection.get("no_scam_bypass"),
        "hide": boring.get("hide_sponsored_results"),
        "old": boring.get(OLD),
    }


def wait_filled(b):
    """Wait for the Protection page to be filled in, then read it."""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if b.run("return document.getElementById('ads-state').textContent") == "On":
            break
        time.sleep(0.2)
    return b.run(READ_SWITCHES)


def start(profile, then=None):
    """Start the browser on the profile, read the page, quit."""
    with Browser(user_data_dir=profile) as b:
        b.get(PROTECTION_URL)
        seen = wait_filled(b)
        if then:
            then(b)
        return seen


def welcome_state(b):
    """Which of the two Welcome switches say they are already on."""
    b.get(WELCOME_URL)
    time.sleep(1.5)
    return b.run(
        "return ['no-bypass','hide-sponsored'].map(function(id){"
        "return !document.getElementById(id+'-done').classList"
        ".contains('hidden');})"
    )


def check(checks, name, passed, detail=None):
    checks[name] = bool(passed)
    if not passed and detail is not None:
        print(f"  {name}: {detail}")


def main():
    checks = {}
    tmp = os.environ.get("TMP") or None
    with tempfile.TemporaryDirectory(
        prefix="switches-", dir=tmp, ignore_cleanup_errors=True
    ) as root:
        defaults = {"takeovers": True, "bypass": False, "hide": False}
        on = {"takeovers": True, "bypass": True, "hide": True}

        # 1. A fresh profile: the defaults, and no old pref anywhere.
        fresh = os.path.join(root, "fresh")
        seen = start(fresh)
        check(checks, "fresh profile starts at the defaults", seen == defaults, seen)
        check(
            checks,
            "fresh profile has no old pref",
            stored(fresh)["old"] is None,
            stored(fresh),
        )

        # 2. The old mode on: all three on, old pref cleared, once only.
        old_on = os.path.join(root, "old-on")
        start(old_on)
        write_prefs(old_on, lambda boring: boring.update({OLD: True}))
        welcome = []
        seen = start(old_on, lambda b: welcome.append(welcome_state(b)))
        check(checks, "old mode on: all three switches start on", seen == on, seen)
        check(
            checks,
            "old mode on: Welcome shows both of its switches on",
            welcome == [[True, True]],
            welcome,
        )
        after = stored(old_on)
        check(checks, "old mode on: old pref cleared from the profile", after["old"] is None, after)
        check(
            checks,
            "old mode on: the three new prefs are stored on",
            after["bypass"] is True
            and after["hide"] is True
            and after["takeovers"] in (True, None),
            after,
        )

        # Migration runs once: a switch the person turns off stays off.
        def turn_hide_off(b):
            b.run("document.getElementById('hide-ads').click()")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if not b.run("return document.getElementById('hide-ads').checked"):
                    break
                time.sleep(0.2)

        start(old_on, turn_hide_off)
        seen = start(old_on)
        check(
            checks,
            "old mode on: a switch turned off later stays off",
            seen == {"takeovers": True, "bypass": True, "hide": False},
            seen,
        )

        # 3. The old pref present but off: the defaults, old pref cleared.
        old_off = os.path.join(root, "old-off")
        start(old_off)
        write_prefs(old_off, lambda boring: boring.update({OLD: False}))
        seen = start(old_off)
        check(checks, "old mode off: the switches start at the defaults", seen == defaults, seen)
        check(
            checks,
            "old mode off: old pref cleared from the profile",
            stored(old_off)["old"] is None,
            stored(old_off),
        )

    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
