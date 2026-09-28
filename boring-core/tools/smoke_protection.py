#!/usr/bin/env python3
"""Check the Protection page tells the truth and its switches work.

Opens chrome://boring-protection in a throwaway profile. Checks that
both protections report a real state, that the tab icon is the B, that
Senior Safe Mode turns on,
asks before it turns off, and survives a reload, and that turning it on
forces sponsored results hidden. Also that the Chrome Web Store row
follows the bundled extension (the copy smoke_webstore.py checks) as it
is turned off and on, and when it is not installed, and that a fresh
profile has no sites with blocking off. Also the blocking level
(Standard or Aggressive, surviving a reload), My filters (saved, and a
line the engine cannot use listed as not used), and the Memory section:
Memory Saver on and off with Chromium's three levels, Balanced by
default, and the Never sleep list with working Remove buttons. The
switches move for 180 ms, or not at all with reduced motion.
Screenshots go to artifacts/ui-implemented.
"""

import json
import os
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


# A rule adblock-rust refuses: an option it does not know.
BAD_RULE = "||example.com^$boringnotanoption"
GOOD_RULE = "example.com##.boring-smoke-ad"
NEVER_SLEEP_SITE = "https://example.com"


def write_never_sleep(profile, sites):
    """Put sites on the Never sleep list while the browser is closed.

    Adding one happens from the shield, which WebDriver cannot press, so
    the list is written the way the browser stores it.
    """
    path = os.path.join(profile, "Default", "Preferences")
    with open(path, encoding="utf-8") as f:
        prefs = json.load(f)
    prefs.setdefault("boring", {}).setdefault("performance", {})[
        "never_sleep_sites"
    ] = sites
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def check_new_sections(b, checks):
    """Blocking level, My filters and Memory on a fresh profile."""
    checks["level is two real radio buttons, Standard first"] = b.run(
        "var s=document.getElementById('level-standard'),"
        "a=document.getElementById('level-aggressive');"
        "return s.type==='radio' && a.type==='radio' && s.labels.length===1 &&"
        " a.labels.length===1 && s.checked && !a.checked"
    )
    b.run("document.getElementById('level-aggressive').click()")
    b.get("chrome://boring-protection")
    checks["aggressive level survives a reload"] = wait_for(
        b, "document.getElementById('level-aggressive').checked"
    )
    b.run("document.getElementById('level-standard').click()")

    checks["My filters is a labelled text box with Save"] = b.run(
        "var t=document.getElementById('my-filters');"
        "return t.tagName==='TEXTAREA' && t.labels.length===1 && "
        "document.getElementById('save-filters').textContent==='Save'"
    )
    b.run(
        "document.getElementById('my-filters').value=arguments[0];"
        "document.getElementById('save-filters').click()",
        [GOOD_RULE + "\n" + BAD_RULE],
    )
    checks["a line that did not parse is listed"] = wait_for(
        b,
        "!document.getElementById('filter-problems').hidden && "
        "document.getElementById('filter-problems-list').textContent"
        ".indexOf('boringnotanoption')>=0 && "
        "document.getElementById('filter-problems-list').textContent"
        ".indexOf('boring-smoke-ad')<0 && "
        "document.getElementById('my-filters-status').textContent"
        ".indexOf('Saved')===0",
        10000,
    )
    b.get("chrome://boring-protection")
    checks["My filters survives a reload"] = wait_for(
        b,
        "document.getElementById('my-filters').value.indexOf("
        "'boring-smoke-ad')>=0",
    )

    checks["Memory Saver is a real switch with three levels"] = b.run(
        "var m=document.getElementById('memory-saver');"
        "var r=document.querySelectorAll('input[name=memory-level]');"
        "return m.type==='checkbox' && m.labels.length===1 && r.length===3 &&"
        " Array.from(r).every(function(x){return x.labels.length===1;})"
    )
    checks["Memory Saver level is Balanced by default"] = b.run(
        "return document.getElementById('memory-balanced').checked"
    )
    was_on = b.run("return document.getElementById('memory-saver').checked")
    b.run("document.getElementById('memory-saver').click()")
    checks["Memory Saver switches"] = wait_for(
        b,
        "document.getElementById('memory-saver').checked===" +
        ("false" if was_on else "true"),
    )
    if not was_on:
        b.run("document.getElementById('memory-maximum').click()")
        checks["Memory Saver level changes"] = wait_for(
            b, "document.getElementById('memory-maximum').checked"
        )
        b.run("document.getElementById('memory-balanced').click()")
        b.run("document.getElementById('memory-saver').click()")
    checks["no sites on the Never sleep list in a fresh profile"] = wait_for(
        b,
        "document.getElementById('never-sleep-state').textContent==='None' "
        "&& !document.querySelector('#never-sleep li')",
    )
    checks["switches move calmly, or not at all with reduced motion"] = b.run(
        "var d=getComputedStyle(document.getElementById('senior'),'::before')"
        ".transitionDuration;"
        "return matchMedia('(prefers-reduced-motion: reduce)').matches ?"
        " /^0s/.test(d) : d.indexOf('0.18s')===0"
    )


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
            check_new_sections(b, checks)
            b.get("chrome://boring-protection")
            wait_for(b, "document.getElementById('ads-state').textContent==='On'")

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

        write_never_sleep(profile, [NEVER_SLEEP_SITE])
        with Browser(user_data_dir=profile, args=["--window-size=1360,900"]) as b:
            b.get("chrome://boring-protection")
            checks["Never sleep list shows its site"] = wait_for(
                b,
                "document.getElementById('never-sleep-state').textContent"
                "==='1 site' && document.querySelector('#never-sleep li span')"
                ".textContent===" + json.dumps(NEVER_SLEEP_SITE),
            )
            b.run("document.querySelector('#never-sleep button').click()")
            checks["Remove takes a site off the Never sleep list"] = wait_for(
                b,
                "document.getElementById('never-sleep-state').textContent"
                "==='None' && !document.querySelector('#never-sleep li')",
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
