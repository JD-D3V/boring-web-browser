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
  "Go back to safety" leaves the page for the one before it;
  "Continue anyway" is there, and works, when "No way past scam warnings"
    is off, and is gone when it is on (today that switch is Senior Safe
    Mode: --senior-safe-mode, see ScamBlockingPage::Create);
  a listed host's subdomains are blocked and its parent is not (CERT
    Polska's rule);
  the page follows the window's colours: Cool and Green, light and dark;
  the Protection page names the scam row as on.

Usage: python smoke_scam.py
"""

import os
import sys
import tempfile

from drive import Browser
from smoke_local import Pages, HTML, list_folder, wait_for

LISTED = "bad.parent.test"
SUB = "login.bad.parent.test"
PARENT = "parent.test"
SAFE_PAGE = "<title>Local test page</title><p id=ok>local test page</p>"

SCAM_LIST = (
    "# boring scam blocklist, test copy\n"
    f"{LISTED}\n"
    "# --- test entries below this line, not protection ---\n"
    "boring-scam-test.invalid\n"
)

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

                    b.get(f"http://{PARENT}:{pages.port}/")
                    check("the parent of a listed host opens", wait_for(b, "!!document.getElementById('ok')"))
                    safe_url = b.current_url()

                    open_url(b, f"http://{LISTED}:{pages.port}/")
                    shown = wait_for(b, "document.body && document.body.innerText.includes('This site looks dangerous')")
                    check("a listed host shows the warning", shown)
                    text = b.run("return document.body.innerText")
                    check("the warning names the host", LISTED in text)
                    check("the warning is not a not-found page", "ERR_" not in text and "can’t be reached" not in text)
                    check("Go back to safety is the main action", bool(b.run(f"return !!({GO_BACK})")) and bool(b.run("return !!document.querySelector('button.primary')")))
                    check("Continue anyway is offered", bool(b.run(f"return !!({CONTINUE})")))

                    b.run(f"({GO_BACK}).click()")
                    went_back = wait_for(b, "!!document.getElementById('ok')", 10000)
                    check("Go back to safety leaves the warning", went_back, b.current_url())

                    open_url(b, f"http://{SUB}:{pages.port}/")
                    check(
                        "a subdomain of a listed host is blocked",
                        wait_for(b, "document.body && document.body.innerText.includes('This site looks dangerous')"),
                    )

                    open_url(b, f"http://{LISTED}:{pages.port}/")
                    wait_for(b, "document.body && document.body.innerText.includes('This site looks dangerous')")
                    b.run(f"({CONTINUE}).click()")
                    check("Continue anyway opens the site", wait_for(b, "!!document.getElementById('ok')", 10000), b.current_url())

            # "No way past scam warnings" on.
            with tempfile.TemporaryDirectory(prefix="scam-", dir=os.environ.get("TMP") or None) as profile:
                with Browser(user_data_dir=profile, args=args_for(lists, pages, ["--senior-safe-mode"])) as b:
                    wait_until_list_is_loaded(b)
                    open_url(b, f"http://{LISTED}:{pages.port}/")
                    check(
                        "the warning still shows with no way past",
                        wait_for(b, "document.body && document.body.innerText.includes('This site looks dangerous')"),
                    )
                    check("Continue anyway is hidden", not b.run(f"return !!({CONTINUE})"))
                    check("Go back to safety is still there", bool(b.run(f"return !!({GO_BACK})")))

            # The colour choices.
            for name, extra, paper, accent in VARIANTS:
                with tempfile.TemporaryDirectory(prefix="scam-", dir=os.environ.get("TMP") or None) as profile:
                    with Browser(user_data_dir=profile, args=args_for(lists, pages, extra)) as b:
                        wait_until_list_is_loaded(b)
                        open_url(b, f"http://{LISTED}:{pages.port}/")
                        wait_for(b, "document.body && document.body.innerText.includes('This site looks dangerous')")
                        got = b.run(
                            "return [getComputedStyle(document.body).backgroundColor,"
                            " getComputedStyle(document.querySelector('button.primary')).backgroundColor]"
                        )
                        check(f"{name}: page colour", got[0] == paper, f"{got[0]} != {paper}")
                        check(f"{name}: main button colour", got[1] == accent, f"{got[1]} != {accent}")
    finally:
        pages.close()

    if failures:
        print(f"{len(failures)} failed")
        return 1
    print("all scam warning checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
