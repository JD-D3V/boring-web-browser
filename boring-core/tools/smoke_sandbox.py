#!/usr/bin/env python3
"""Check that the Chromium sandbox and site isolation are still on.

Our patch layer must never weaken either. Reading args.gn only proves
nobody typed a switch; this asks the running browser what it actually
did, which is the thing that matters.

chrome://sandbox prints a JSON `policies:` block, one entry per
sandboxed process, and a process that never got a policy is simply not
in it. So the check is on the levels in that block, not on any
"Not Sandboxed" wording, which this Chromium does not print.

Usage: python smoke_sandbox.py
"""

import json
import os
import re
import sys
import tempfile
import time

from drive import Browser

# How long to let a chrome:// page finish filling itself in.
READY_TIMEOUT = 20.0
READY_POLL = 0.25


def text_when(b, url, pattern):
    """Open url and return its text once pattern appears in it.

    Both pages read here are WebUI that populate themselves from
    JavaScript after the document has loaded, so reading innerText the
    moment get() returns can catch a page that is still empty. That is
    what made this check report "site isolation not confirmed" on a
    browser whose site isolation was fine.

    Waiting for the thing we are about to assert on removes the race
    without softening the assertion: if the text never appears, this
    returns whatever was there at the deadline and the check fails
    exactly as it did before. A browser that really had lost site
    isolation still fails, it just takes twenty seconds to say so.
    """
    b.get(url)
    deadline = time.monotonic() + READY_TIMEOUT
    while True:
        text = b.run("return document.body ? document.body.innerText : ''")
        if re.search(pattern, text):
            return text
        if time.monotonic() >= deadline:
            return text
        time.sleep(READY_POLL)

# Levels chromium hands a renderer. Anything weaker than these in a
# release build means the sandbox was loosened somewhere.
STRONG_LOCKDOWN = {"Lockdown", "Limited"}
WEAK_LOCKDOWN = {"Unprotected", "Interactive"}


def main():
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, ok))
        print(("PASS: " if ok else "FAIL: ") + name + (f" ({detail})" if detail else ""))

    with tempfile.TemporaryDirectory(dir=os.environ.get("TMP")) as profile:
        with Browser(user_data_dir=profile) as b:
            raw = text_when(b, "chrome://sandbox", r"policies:")
            marker = raw.find("policies:")
            policies = []
            if marker != -1:
                try:
                    policies = json.loads(raw[marker + len("policies:") :])
                except json.JSONDecodeError:
                    policies = []

            check(
                "chrome://sandbox reports sandbox policies",
                len(policies) > 0,
                f"{len(policies)} policies",
            )

            levels = [p.get("lockdownLevel") for p in policies]
            check(
                "every sandboxed process is at a strong lockdown level",
                bool(levels) and all(lv in STRONG_LOCKDOWN for lv in levels),
                ", ".join(sorted(set(levels))) or "none",
            )
            check(
                "no process runs at a weak lockdown level",
                not any(lv in WEAK_LOCKDOWN for lv in levels),
                ", ".join(sorted(set(levels))) or "none",
            )

            # The renderers should be the untrusted integrity ones.
            untrusted = [
                p
                for p in policies
                if "Untrusted" in (p.get("desiredIntegrityLevel") or "")
            ]
            check(
                "renderers run at untrusted integrity",
                len(untrusted) >= 1,
                f"{len(untrusted)} of {len(policies)}",
            )

            # Require something after the colon, so a half drawn page
            # keeps us waiting rather than reporting an empty mode.
            text = text_when(
                b,
                "chrome://process-internals/#site-isolation",
                r"Site Isolation mode:\s*\S",
            )
            mode = re.search(r"Site Isolation mode:\s*(.+)", text)
            mode_text = mode.group(1).strip() if mode else ""
            check(
                "site isolation mode is reported",
                bool(mode_text),
                mode_text or "no 'Site Isolation mode:' line",
            )
            check(
                "site isolation is Site Per Process",
                mode_text == "Site Per Process",
                mode_text,
            )

            b.get("https://example.com/")
            title = b.run("return document.title")
            check("ordinary https page loads", bool(title), f"title {title!r}")

    failed = [c for c in checks if not c[1]]
    print()
    print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
