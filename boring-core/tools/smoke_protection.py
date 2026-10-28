#!/usr/bin/env python3
"""Check the Protection page tells the truth and its switches work.

Opens chrome://boring-protection in a throwaway profile. Checks that
both protections report a real state, that the tab icon is the B, that
the three switches (Stop screen takeovers, No way past scam warnings,
Hide sponsored results) start at their defaults, turn on and off and
survive a reload, that turning off No way past scam warnings asks first,
and that Senior Safe Mode is nowhere on the page. Also that the Chrome
Web Store row
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
        "document.getElementById('my-filters').value.indexOf('boring-smoke-ad')>=0",
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
        "document.getElementById('memory-saver').checked==="
        + ("false" if was_on else "true"),
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
        "var d=getComputedStyle(document.getElementById('no-bypass'),'::before')"
        ".transitionDuration;"
        "return matchMedia('(prefers-reduced-motion: reduce)').matches ?"
        " /^0s/.test(d) : d.indexOf('0.18s')===0"
    )


def click(b, switch):
    b.run(f"document.getElementById('{switch}').click()")


def is_on(b, switch, want=True):
    """True once the switch reads `want` (the page answers a moment later)."""
    return wait_for(
        b, f"document.getElementById('{switch}').checked==={str(want).lower()}"
    )


def reload_page(b):
    """Open the page again and wait until it has been filled in. Before
    that every switch reads off, which would pass a check for off."""
    b.get("chrome://boring-protection")
    wait_for(b, "document.getElementById('ads-state').textContent==='On'")


def check_switches(b, checks):
    """Each switch moves, and the choice survives a reload.

    Turning off No way past scam warnings is the one change a scammer
    asks for, so it asks first.
    """
    click(b, "no-bypass")
    checks["no way past scam warnings turns on"] = is_on(b, "no-bypass")

    click(b, "no-bypass")
    checks["turning it off asks first"] = b.run(
        "return document.getElementById('no-bypass').checked && "
        "!document.getElementById('confirm-off').classList"
        ".contains('hidden') && "
        "document.activeElement.id==='keep-on'"
    )
    b.screenshot(str(OUT / "protection-confirm-off.png"))
    b.run("document.getElementById('keep-on').click()")
    checks["keep it on keeps it on"] = b.run(
        "return document.getElementById('no-bypass').checked && "
        "document.getElementById('confirm-off').classList"
        ".contains('hidden')"
    )

    reload_page(b)
    checks["no way past scam warnings survives a reload"] = is_on(b, "no-bypass")

    click(b, "no-bypass")
    b.run("document.getElementById('turn-off').click()")
    checks["turn it off turns it off"] = is_on(b, "no-bypass", False)

    # The other two ask nothing: they just move, and stay moved.
    for switch, start in (("stop-takeovers", True), ("hide-ads", False)):
        click(b, switch)
        checks[f"{switch} switches"] = is_on(b, switch, not start)
        reload_page(b)
        checks[f"{switch} survives a reload"] = is_on(b, switch, not start)
        click(b, switch)
        checks[f"{switch} switches back"] = is_on(b, switch, start)


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
                "return document.getElementById('webstore-state').textContent==='On'",
                40,
            )
            checks["no Senior Safe Mode on the page"] = b.run(
                "return !/senior/i.test(document.body.innerText) && "
                "!document.getElementById('senior')"
            )
            # Each switch has one plain line saying what it does.
            checks["switch labels and lines"] = b.run(
                "function t(id){var l=document.getElementById(id).labels[0];"
                "return [l.querySelector('strong').textContent,"
                "l.querySelector('p').textContent.replace(/\\s+/g,' ').trim()];}"
                "return JSON.stringify([t('stop-takeovers'),t('no-bypass'),"
                "t('hide-ads')])===JSON.stringify(["
                "['Stop screen takeovers','Stops a page from locking your "
                "screen or keyboard with fake alerts.'],"
                "['No way past scam warnings','Takes away the continue anyway "
                "link on a scam warning.'],"
                "['Hide sponsored results','Removes paid results from Google "
                "and Bing searches.']])"
            )
            checks["switch text has no em dash"] = b.run(
                "return !/\\u2014/.test(document.body.innerText)"
            )
            checks["stop takeovers starts on"] = b.run(
                "return document.getElementById('stop-takeovers').checked"
            )
            checks["no way past scam warnings starts off"] = b.run(
                "return !document.getElementById('no-bypass').checked"
            )
            checks["hide sponsored results starts off"] = b.run(
                "return !document.getElementById('hide-ads').checked"
            )
            icon = b.run_async(ICON_LOADS)
            checks["tab icon brand.svg loads"] = icon == "ok"
            if icon != "ok":
                print("  icon:", icon)
            checks["switches are still real checkboxes"] = b.run(
                "return ['stop-takeovers','no-bypass','hide-ads','fingerprint',"
                "'strip-params']"
                ".every(function(id){"
                "var e=document.getElementById(id);"
                "return e.type==='checkbox' && e.labels.length===1;})"
            )
            b.screenshot(str(OUT / "protection-light.png"))
            check_new_sections(b, checks)
            b.get("chrome://boring-protection")
            wait_for(b, "document.getElementById('ads-state').textContent==='On'")

            check_switches(b, checks)

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

    (OUT / "protection-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
