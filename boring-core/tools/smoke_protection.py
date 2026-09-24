#!/usr/bin/env python3
"""Check the Protection page tells the truth and its switches work.

Opens chrome://boring-protection in a throwaway profile. Checks that
both protections report a real state, that the tab icon is the B, that
Senior Safe Mode turns on,
asks before it turns off, and survives a reload, and that turning it on
forces sponsored results hidden. Also that the Chrome Web Store row
follows the bundled extension (the copy smoke_webstore.py checks) as it
is turned off and on, and when it is not installed, and that a fresh
profile has no sites with blocking off. Screenshots go to
artifacts/ui-implemented.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

import get_chromium_web_store as cws
from drive import Browser
from smoke_newtab import ICON_LOADS

OUT = Path(__file__).resolve().parents[2] / "artifacts/ui-implemented"


def wait_for(b, condition, timeout_ms=5000):
    """True once the JavaScript expression holds, false at the timeout."""
    return b.run_async(
        """
      const [condition, limit, done] = arguments;
      const deadline = performance.now() + limit;
      function check() {
        const ok = !!eval(condition);
        if (ok || performance.now() > deadline) done(ok);
        else setTimeout(check, 50);
      }
      check();
    """,
        [condition, timeout_ms],
    )


def poll(b, script, seconds):
    """True once the synchronous script returns true, false after `seconds`."""
    deadline = time.monotonic() + seconds
    while True:
        if b.run(script):
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.5)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="protection-", dir=OUT) as profile:
        with Browser(user_data_dir=profile, args=["--window-size=1360,900"]) as b:
            b.get("chrome://boring-protection")
            # No scam list ships in this version. Known dangerous sites
            # are refused by Quad9 secure DNS instead, and the row has to
            # say exactly that, including that there is no warning page.
            checks["dangerous sites report Quad9, no warning page"] = wait_for(
                b,
                "document.getElementById('scam-state').textContent==='On' && "
                "document.getElementById('scam-desc').textContent"
                ".indexOf('Quad9')>=0 && "
                "document.getElementById('scam-desc').textContent"
                ".indexOf('no warning page')>=0",
            )
            checks["ad blocking reports on"] = wait_for(
                b, "document.getElementById('ads-state').textContent==='On'"
            )
            checks["no sites with blocking off in a fresh profile"] = wait_for(
                b,
                "document.getElementById('off-sites-state').textContent"
                "==='None' && !document.querySelector('#off-sites li')",
            )
            # The bundled store extension installs itself into a new
            # profile shortly after startup, so give it up to 40 seconds.
            # Polled with short synchronous reads: an async script that is
            # still waiting while the extension installs never returns to
            # chromedriver (seen on 153), and the run would end with a
            # script timeout instead of a result.
            checks["web store row reports on"] = poll(
                b,
                "return document.getElementById('webstore-state')"
                ".textContent==='On'",
                40,
            )
            checks["senior mode text says only what it does"] = b.run(
                "return document.getElementById('senior-why').textContent"
                "==='Keeps sponsored search results hidden.'"
            )
            checks["senior mode starts off"] = b.run(
                "return !document.getElementById('senior').checked"
            )
            icon = b.run_async(ICON_LOADS)
            checks["tab icon brand.svg loads"] = icon == "ok"
            if icon != "ok":
                print("  icon:", icon)
            checks["switches are still real checkboxes"] = b.run(
                "return ['senior','hide-ads','fingerprint','strip-params']"
                ".every(function(id){"
                "var e=document.getElementById(id);"
                "return e.type==='checkbox' && e.labels.length===1;})"
            )
            b.screenshot(str(OUT / "protection-light.png"))

            b.run("document.getElementById('senior').click()")
            checks["senior mode turns on"] = wait_for(
                b,
                "document.getElementById('senior').checked && "
                "document.getElementById('hide-ads').checked && "
                "document.getElementById('hide-ads').disabled",
            )

            b.run("document.getElementById('senior').click()")
            checks["turning off asks first"] = b.run(
                "return document.getElementById('senior').checked && "
                "!document.getElementById('confirm-off').classList"
                ".contains('hidden') && "
                "document.activeElement.id==='keep-on'"
            )
            b.screenshot(str(OUT / "protection-confirm-off.png"))
            b.run("document.getElementById('keep-on').click()")
            checks["keep it on keeps it on"] = b.run(
                "return document.getElementById('senior').checked && "
                "document.getElementById('confirm-off').classList"
                ".contains('hidden')"
            )

            b.get("chrome://boring-protection")
            checks["senior mode survives a reload"] = wait_for(
                b, "document.getElementById('senior').checked"
            )

            b.run("document.getElementById('senior').click()")
            b.run("document.getElementById('turn-off').click()")
            checks["turn it off turns it off"] = wait_for(
                b,
                "!document.getElementById('senior').checked && "
                "!document.getElementById('hide-ads').disabled",
            )

            # Turn the store extension off and on again the way
            # chrome://extensions does, and check the row follows. Removing
            # it from there needs a native confirm dialog, which WebDriver
            # cannot answer, so the removed state is checked below with
            # extensions not loaded at all.
            for step, enabled, want in (
                ("off", "false", "Off"),
                ("back on", "true", "On"),
            ):
                b.get("chrome://extensions")
                result = b.run_async(
                    "var done = arguments[arguments.length - 1];"
                    f"chrome.management.setEnabled(arguments[0], {enabled})"
                    ".then(function() { done('ok'); },"
                    " function(e) { done('error: ' + e.message); });",
                    [cws.EXTENSION_ID],
                )
                if result != "ok":
                    print(f"  web store {step}:", result)
                b.get("chrome://boring-protection")
                checks[f"web store row reports {step}"] = result == "ok" and wait_for(
                    b,
                    f"document.getElementById('webstore-state').textContent==='{want}'",
                )

        with Browser(
            user_data_dir=profile,
            args=["--disable-extensions", "--window-size=1360,900"],
        ) as b:
            b.get("chrome://boring-protection")
            checks["web store row reports removed when not installed"] = wait_for(
                b,
                "document.getElementById('webstore-state').textContent==='Removed'",
            )

        with Browser(
            user_data_dir=profile,
            args=["--senior-safe-mode", "--window-size=1360,900"],
        ) as b:
            b.get("chrome://boring-protection")
            checks["switch locks senior mode on"] = wait_for(
                b,
                "document.getElementById('senior').checked && "
                "document.getElementById('senior').disabled",
            )

    (OUT / "protection-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
