#!/usr/bin/env python3
"""Run every check against the built browser and print a summary.

Usage: python smoke_all.py
"""

import os
import subprocess
import sys

from drive import OUT

HERE = os.path.dirname(os.path.abspath(__file__))

# A check that does not apply to this build. See smoke_widevine.py.
NOT_APPLICABLE = 3

CHECKS = [
    # First, because everything else is only worth checking in a
    # browser whose sandbox is still on.
    ("sandbox and site isolation", "smoke_sandbox.py"),
    ("ad and tracker blocking", "smoke_adblock.py"),
    ("scam warning and Senior Safe Mode", "smoke_scam.py"),
    ("Protection page", "smoke_protection.py"),
    ("blocking list updates", "smoke_lists.py"),
    ("new tab page", "smoke_newtab.py"),
    ("welcome page and settings links", "smoke_welcome.py"),
    ("About page credits upstream", "smoke_about.py"),
    ("sponsored search results", "smoke_serp.py"),
    ("pop-up blocking", "smoke_popups.py"),
    ("per site blocking off", "smoke_siteoff.py"),
    ("import from Chrome and Edge", "smoke_import.py"),
    ("Web Store installs and bundled Chromium Web Store", "smoke_webstore.py"),
    ("spellcheck with the bundled dictionary", "smoke_spellcheck.py"),
    ("privacy defaults and search choice", "smoke_privacy.py"),
    ("reader view", "smoke_reader.py"),
    ("AI settings page", "smoke_ai.py"),
    ("AI consent and result UI", "smoke_ai_ui.py"),
    ("Widevine streaming", "smoke_widevine.py"),
    ("password manager", "smoke_passwords.py"),
]


def stop_browsers():
    # Only the copies from our build folder. Killing every chrome.exe by
    # name would also close the Google Chrome someone is using.
    script = (
        "Get-Process chrome, chromedriver -ErrorAction SilentlyContinue"
        " | Where-Object { $_.Path -and $_.Path.StartsWith($env:BORING_OUT,"
        " [StringComparison]::OrdinalIgnoreCase) }"
        " | Stop-Process -Force"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        env={**os.environ, "BORING_OUT": OUT},
    )


def main():
    results = []
    for label, script in CHECKS:
        path = os.path.join(HERE, script)
        if not os.path.exists(path):
            results.append((label, "no test yet"))
            continue
        print("\n=== " + label + " ===")
        stop_browsers()
        result = subprocess.run([sys.executable, path], cwd=HERE)
        # 3 means a check that does not apply to this build, and it is
        # not a pass: a capability we deliberately left out should read
        # as absent in the summary, not as working.
        if result.returncode == 0:
            outcome = "pass"
        elif result.returncode == NOT_APPLICABLE:
            outcome = "n/a"
        else:
            outcome = "FAIL"
        results.append((label, outcome))
    stop_browsers()

    print("\n\nSummary")
    print("-------")
    failed = 0
    for label, outcome in results:
        print(f"{label:<38} {outcome}")
        if outcome == "FAIL":
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
