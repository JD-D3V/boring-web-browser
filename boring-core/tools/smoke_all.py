#!/usr/bin/env python3
"""Run every check against the built browser and print a summary.

Usage: python smoke_all.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

CHECKS = [
    ("ad and tracker blocking", "smoke_adblock.py"),
    ("scam warning and Senior Safe Mode", "smoke_scam.py"),
    ("sponsored search results", "smoke_serp.py"),
    ("reader view", "smoke_reader.py"),
    ("AI settings page", "smoke_ai.py"),
    ("Widevine streaming", "smoke_widevine.py"),
    ("password manager", "smoke_passwords.py"),
]


def stop_browsers():
    for name in ("chrome.exe", "chromedriver.exe"):
        subprocess.run(["taskkill", "/F", "/IM", name],
                       capture_output=True)


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
        results.append((label, "pass" if result.returncode == 0 else "FAIL"))
    stop_browsers()

    print("\n\nSummary")
    print("-------")
    failed = 0
    for label, outcome in results:
        print("%-38s %s" % (label, outcome))
        if outcome == "FAIL":
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
