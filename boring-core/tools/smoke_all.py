#!/usr/bin/env python3
"""Run every check against the built browser and print a summary.

Usage: python smoke_all.py
Set BORING_ALLOW_HEADFUL=1 in a dedicated Windows test session for the
full suite. Without it, native checks are reported as blocked.
"""

import os
import subprocess
import sys

from drive import headful_allowed

HERE = os.path.dirname(os.path.abspath(__file__))

# A check that does not apply to this build. See smoke_widevine.py.
NOT_APPLICABLE = 3

CHECKS = [
    # First, because everything else is only worth checking in a
    # browser whose sandbox is still on.
    ("sandbox and site isolation", "smoke_sandbox.py"),
    ("ad and tracker blocking", "smoke_adblock.py"),
    ("element hiding", "smoke_cosmetic.py"),
    ("scriptlets", "smoke_scriptlet.py"),
    ("redirect stubs", "smoke_redirect.py"),
    ("cookie notices", "smoke_cookies.py"),
    ("page annoyances", "smoke_annoyances.py"),
    ("aggressive blocking level", "smoke_aggressive.py"),
    ("my filters (custom rules)", "smoke_custom_rules.py"),
    ("block this element", "smoke_picker.py"),
    ("blocking engine cache", "smoke_engine_cache.py"),
    ("scam warning and its switch", "smoke_scam.py"),
    ("protection switches and migration", "smoke_switches.py"),
    ("Protection page", "smoke_protection.py"),
    ("blocking list updates", "smoke_lists.py"),
    ("new tab page", "smoke_newtab.py"),
    ("search engine menu", "smoke_search_menu.py"),
    ("tab freezing and sleeping", "smoke_memory.py"),
    ("welcome page and settings links", "smoke_welcome.py"),
    ("About page credits upstream", "smoke_about.py"),
    ("sponsored search results", "smoke_serp.py"),
    ("pop-up blocking", "smoke_popups.py"),
    ("per site blocking off", "smoke_siteoff.py"),
    ("shield panel and site settings page", "smoke_site_panel.py"),
    ("stop screen takeovers", "smoke_takeover.py"),
    ("import from Chrome and Edge", "smoke_import.py"),
    ("Web Store installs and bundled Chromium Web Store", "smoke_webstore.py"),
    ("spellcheck with the bundled dictionary", "smoke_spellcheck.py"),
    ("privacy defaults and search choice", "smoke_privacy.py"),
    ("reader view", "smoke_reader.py"),
    ("AI settings page", "smoke_ai.py"),
    ("AI consent and result UI", "smoke_ai_ui.py"),
    ("Widevine streaming", "smoke_widevine.py"),
    ("password manager", "smoke_passwords.py"),
    ("Protection page connections", "smoke_connections.py"),
    ("Protection page apps you added", "smoke_apps_rows.py"),
    ("look-alike address warning", "smoke_lookalike.py"),
    ("warning for sites Quad9 blocks", "smoke_dns_warning.py"),
    ("small fixes (settings links, continue anyway)", "smoke_small_batch.py"),
    ("scam tricks guards", "smoke_scam_guards.py"),
    ("phone number banner", "smoke_phone_banner.py"),
    ("redirect and AMP skipping", "smoke_debounce.py"),
    ("forget this site", "smoke_forget.py"),
    ("tabs survive restart", "smoke_tabs.py"),
    ("side tabs", "smoke_vtabs.py"),
    ("colour scheme and layout fixes", "smoke_ui_polish.py"),
    ("assistance scripts", "smoke_assistance.py"),
    ("assistance gemini adapter", "smoke_assistance_gemini.py"),
    ("fingerprint protection", "smoke_fingerprint.py"),
    ("your own blocking lists", "smoke_own_lists.py"),
    ("apps on this computer (native hosts)", "smoke_native_hosts.py"),
    ("keep a copy in a folder", "smoke_folder_copy.py"),
    (
        "last batch (guest links, shared switches, new tab numbers)",
        "smoke_final_batch.py",
    ),
    ("157 fixes (Protection switches, features kept off)", "smoke_r3_fixes.py"),
    ("deleted sessions gone from the encrypted copies", "smoke_session_copies.py"),
]

# Every smoke_*.py that is not a check, with the reason. A new file must
# be in CHECKS or here (tests/test_smoke_all.py fails otherwise).
LEFT_OUT = {
    "smoke_all.py": "this runner",
    "smoke_local.py": "helpers shared by other checks, no test of its own",
}


NATIVE_CHECKS = {
    "smoke_memory.py",
    "smoke_siteoff.py",
    "smoke_site_panel.py",
    "smoke_webstore.py",
    "smoke_forget.py",
    "smoke_tabs.py",
    "smoke_vtabs.py",
}


def main():
    results = []
    allow_headful = headful_allowed()
    for label, script in CHECKS:
        path = os.path.join(HERE, script)
        if not os.path.exists(path):
            results.append((label, "no test yet"))
            continue
        if script in NATIVE_CHECKS and not allow_headful:
            results.append((label, "blocked (needs BORING_ALLOW_HEADFUL=1)"))
            continue
        print("\n=== " + label + " ===")
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
    print("\n\nSummary")
    print("-------")
    failed = 0
    for label, outcome in results:
        print(f"{label:<38} {outcome}")
        if outcome == "FAIL" or outcome.startswith("blocked"):
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
