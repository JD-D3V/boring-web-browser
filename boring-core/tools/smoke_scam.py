#!/usr/bin/env python3
"""Check the scam warning page in the real browser.

Scam blocking is on (components/boring/core/boring_capabilities.h), so a
listed site must be walled off with a full page warning, not shown as
"not found". The list here is a tiny one of our own in a temporary
--boring-list-dir folder, and the hosts in it are local names mapped to
127.0.0.1 with --host-resolver-rules, so nothing depends on a live scam
domain and nothing leaves the machine.

Checked:
  the warning shows, names the host, and has "Go back to safety";
  "Go back to safety" returns to the previous page or, with no history,
    opens the browser's New Tab page;
  "Continue anyway" is there, and works, when "No way past scam warnings"
    is off, and is gone when it is on (boring.protection.no_scam_bypass,
    turned on through the Protection page's own switch);
  a listed host's subdomains are blocked and its parent is not (CERT
    Polska's rule);
  the page follows the window's colours: Cool and Green, light and dark;
  the Protection page names the scam row as on;
  a list of fewer than 10 hosts is refused: the row reads Unavailable and a
    host on the list opens (ledger 93), while a list of exactly 10 works.

Usage: python smoke_scam.py
"""

import json
import os
import sys
import tempfile
import time

from drive import Browser
from smoke_local import Pages, HTML, list_folder, wait_for

# .localhost names: HTTPS-Only mode is on by default and upgrades any other
# plain http name, so a .test page would never load.
LISTED = "bad.parent.localhost"
SUB = "login.bad.parent.localhost"
PARENT = "parent.localhost"
SAFE_PAGE = "<title>Local test page</title><p id=ok>local test page</p>"

SCAM_LIST = (
    "# boring scam blocklist, test copy\n"
    f"{LISTED}\n"
    "# --- test entries below this line, not protection ---\n"
    "boring-scam-test.invalid\n"
    # The browser refuses a list with fewer than 10 hosts (kMinHosts).
    + "".join(f"boring-scam-pad-{i:02d}.invalid\n" for i in range(1, 12))
)



def scam_list(hosts):
    """A scam list with this many hosts, LISTED among them."""
    return (
        "# boring scam blocklist, test copy"
        + chr(10)
        + LISTED
        + chr(10)
        + "".join(f"boring-scam-pad-{i:02d}.invalid" + chr(10) for i in range(hosts - 1))
    )


def scam_row_settled(b):
    """Opens the Protection page and waits for the scam row to say On or
    Unavailable instead of Starting. Returns (state, description)."""
    b.get("chrome://boring-protection")
    wait_for(
        b,
        "['On', 'Unavailable'].includes(document.getElementById('scam-state').textContent)",
        20000,
    )
    return b.run(
        "return [document.getElementById('scam-state').textContent,"
        " document.getElementById('scam-desc').textContent]"
    )


def check_list_size(pages, check):
    """The floor is 10 hosts (kMinHosts). Under it the list is thrown out as
    a damaged one: no protection, and the page says so rather than "On"."""
    for hosts, works in ((9, False), (10, True)):
        with list_folder({"scamlist.txt": scam_list(hosts)}) as lists:
            with tempfile.TemporaryDirectory(prefix="scam-", dir=os.environ.get("TMP") or None) as profile:
                with Browser(user_data_dir=profile, args=args_for(lists, pages, [])) as b:
                    state, desc = scam_row_settled(b)
                    label = f"a list of {hosts} hosts"
                    if works:
                        check(f"{label}: the Protection page reads On", state == "On", f"{state}: {desc}")
                    else:
                        check(f"{label}: the Protection page reads Unavailable", state == "Unavailable", f"{state}: {desc}")
                        check(f"{label}: and says why", "too few hosts" in desc, desc)
                    open_url(b, f"http://{LISTED}:{pages.port}/")
                    time.sleep(1)
                    warned = bool(b.run("return !!document.body && document.body.innerText.includes('This site may be a scam')"))
                    opened = wait_for(b, "!!document.getElementById('ok')", 5000)
                    if works:
                        check(f"{label}: a host on it is blocked", warned and not opened)
                    else:
                        check(f"{label}: a host on it is not blocked", opened and not warned)


# What each colour choice must paint, from boring_color_mixer.cc: the
# page background and the main button.
VARIANTS = [
    ("cool-light", [], "rgb(255, 255, 255)", "rgb(79, 70, 229)"),
    ("cool-dark", ["--force-dark-mode"], "rgb(29, 30, 40)", "rgb(157, 154, 255)"),
    ("green-light", ["--boring-scheme=green"], "rgb(255, 255, 255)", "rgb(23, 107, 91)"),
    (
        "green-dark",
        ["--force-dark-mode", "--boring-scheme=green"],
        "rgb(29, 30, 40)",
        "rgb(79, 201, 174)",
    ),
]

GO_BACK = "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Go back to safety')"
CONTINUE = "[...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Continue anyway')"


def args_for(lists, pages, extra):
    hosts = (LISTED, SUB, PARENT)
    rules = ", ".join(f"MAP {h} 127.0.0.1" for h in hosts)
    return [
        f"--boring-list-dir={lists}",
        "--disable-boring-list-updates",
        f"--host-resolver-rules={rules}",
        "--window-size=1360,900",
        # Never on the desktop and never in front: see drive.py.
        "--window-position=-32000,-32000",
        *extra,
    ]


def open_url(b, url):
    """Navigates. A warning page is a blocked navigation, which WebDriver
    may report as an error, and that is not a failure here."""
    try:
        b.get(url)
    except RuntimeError as e:
        if "ERR_BLOCKED_BY_CLIENT" not in str(e):
            raise


def go_back_to(b, condition):
    b.run(f"({GO_BACK}).click()")
    deadline = time.monotonic() + 10
    # Poll from WebDriver so the predicate survives a change of document
    # and doesn't rely on eval, which the New Tab page's CSP disallows.
    while time.monotonic() < deadline:
        if b.run(f"return !!({condition})"):
            return True
        time.sleep(0.1)
    return False


def reset_warning_history(b):
    # Keep the committed warning and discard previous entries. Even a
    # fresh WebDriver tab can have an entry before its first test URL.
    path = f"/session/{b.sid}/goog/cdp/execute"
    b._req("POST", path, {"cmd": "Page.resetNavigationHistory", "params": {}})
    return b._req(
        "POST", path, {"cmd": "Page.getNavigationHistory", "params": {}}
    )["value"]


def switch_on(b, want):
    """True once the Protection page's switch reads `want`, false after 5 s."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if b.run("return document.getElementById('no-bypass').checked") is want:
            return True
        time.sleep(0.2)
    return False


def check_switch(b, check):
    """The switch is off, turns on, and asks before it turns off."""
    b.get("chrome://boring-protection")
    wait_for(b, "document.getElementById('ads-state').textContent === 'On'", 10000)
    check("No way past scam warnings starts off", not b.run("return document.getElementById('no-bypass').checked"))
    b.run("document.getElementById('no-bypass').click()")
    check("No way past scam warnings turns on", switch_on(b, True))
    b.run("document.getElementById('no-bypass').click()")
    asked = b.run(
        "return document.getElementById('no-bypass').checked && "
        "!document.getElementById('confirm-off').classList.contains('hidden')"
    )
    check("turning it off asks first", bool(asked))
    b.run("document.getElementById('keep-on').click()")
    check("Keep it on keeps it on", switch_on(b, True))


def stored_pref(profile):
    with open(os.path.join(profile, "Default", "Preferences"), encoding="utf-8") as f:
        prefs = json.load(f)
    return prefs.get("boring", {}).get("protection", {}).get("no_scam_bypass")


def wait_until_list_is_loaded(b):
    b.get("chrome://boring-protection")
    return wait_for(
        b, "document.body.innerText.includes('blocked before they open')", 20000
    )


def main():
    failures = []

    def check(name, ok, detail=""):
        print(("PASS: " if ok else "FAIL: ") + name + (f" ({detail})" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    pages = Pages({"/": (SAFE_PAGE, HTML)})
    try:
        with list_folder({"scamlist.txt": SCAM_LIST}) as lists:
            # The default choice: the way past is offered.
            with tempfile.TemporaryDirectory(prefix="scam-", dir=os.environ.get("TMP") or None) as profile:
                with Browser(user_data_dir=profile, args=args_for(lists, pages, [])) as b:
                    check("the scam list loads", wait_until_list_is_loaded(b))
                    protection = b.run("return document.body.innerText")
                    check("the Protection page names the scam row", "Scam & phishing sites" in protection)
                    check(
                        "the Protection page no longer says scam blocking is absent",
                        "no warning page" not in protection,
                    )

                    parent_url = f"http://{PARENT}:{pages.port}/"
                    b.get(parent_url)
                    parent_ok = wait_for(b, "!!document.getElementById('ok')")
                    check("the parent of a listed host opens", parent_ok)
                    if not parent_ok:
                        print("  page was:", b.run("return [location.href, document.readyState, document.documentElement.outerHTML.slice(0, 300)]"))
                        print("  fetch gives:", b.run_async("const [done] = arguments; fetch(location.href).then(r => r.text()).then(t => done(t.slice(0, 120)), e => done('ERR ' + e))"))

                    open_url(b, f"http://{LISTED}:{pages.port}/")
                    shown = wait_for(b, "document.body && document.body.innerText.includes('This site may be a scam')")
                    check("a listed host shows the warning", shown)
                    text = b.run("return document.body.innerText")
                    check("the warning names the host", LISTED in text)
                    check("the warning is not a not-found page", "ERR_" not in text and "can’t be reached" not in text)
                    check("Go back to safety is the main action", bool(b.run(f"return !!({GO_BACK})")) and bool(b.run("return !!document.querySelector('button.primary')")))
                    check("Continue anyway is offered", bool(b.run(f"return !!({CONTINUE})")))

                    went_back = go_back_to(
                        b,
                        f"location.href === {json.dumps(parent_url)} && "
                        "document.getElementById('ok')",
                    )
                    check("Go back to safety returns to the previous page", went_back, b.current_url())

                    open_url(b, f"http://{SUB}:{pages.port}/")
                    check(
                        "a subdomain of a listed host is blocked",
                        wait_for(b, "document.body && document.body.innerText.includes('This site may be a scam')"),
                    )

                    open_url(b, f"http://{LISTED}:{pages.port}/")
                    wait_for(b, "document.body && document.body.innerText.includes('This site may be a scam')")
                    b.run(f"({CONTINUE}).click()")
                    check("Continue anyway opens the site", wait_for(b, "!!document.getElementById('ok')", 10000), b.current_url())
                    check_switch(b, check)
                    # The click-through above was made before the switch was
                    # on, in this same session. The switch clears it.
                    open_url(b, f"http://{LISTED}:{pages.port}/")
                    check(
                        "turning the switch on clears an earlier Continue anyway",
                        wait_for(b, "document.body && document.body.innerText.includes('This site may be a scam')"),
                    )
                check("the switch is stored for the warning page", stored_pref(profile) is True, repr(stored_pref(profile)))

                # Same profile, switch on: "No way past scam warnings".
                with Browser(user_data_dir=profile, args=args_for(lists, pages, [])) as b:
                    wait_until_list_is_loaded(b)
                    open_url(b, f"http://{LISTED}:{pages.port}/")
                    check(
                        "the warning still shows with no way past",
                        wait_for(b, "document.body && document.body.innerText.includes('This site may be a scam')"),
                    )
                    check("Continue anyway is hidden", not b.run(f"return !!({CONTINUE})"))
                    check("Go back to safety is still there", bool(b.run(f"return !!({GO_BACK})")))
                    history = reset_warning_history(b)
                    no_previous = history["currentIndex"] == 0 and len(history["entries"]) == 1
                    check("the warning is the only history entry", no_previous, repr(history))
                    if no_previous:
                        went_to_new_tab = go_back_to(
                            b,
                            "location.protocol === 'chrome:' && "
                            "location.host === 'boring-newtab' && document.title === 'New Tab'",
                        )
                        check(
                            "Go back to safety with no history opens New Tab",
                            went_to_new_tab,
                            b.current_url(),
                        )

            # The colour choices.
            for name, extra, paper, accent in VARIANTS:
                with tempfile.TemporaryDirectory(prefix="scam-", dir=os.environ.get("TMP") or None) as profile:
                    with Browser(user_data_dir=profile, args=args_for(lists, pages, extra)) as b:
                        wait_until_list_is_loaded(b)
                        open_url(b, f"http://{LISTED}:{pages.port}/")
                        wait_for(b, "document.body && document.body.innerText.includes('This site may be a scam')")
                        got = b.run(
                            "return [getComputedStyle(document.body).backgroundColor,"
                            " getComputedStyle(document.querySelector('button.primary')).backgroundColor]"
                        )
                        check(f"{name}: page colour", got[0] == paper, f"{got[0]} != {paper}")
                        check(f"{name}: main button colour", got[1] == accent, f"{got[1]} != {accent}")
        check_list_size(pages, check)
    finally:
        pages.close()

    if failures:
        print(f"{len(failures)} failed")
        return 1
    print("all scam warning checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
