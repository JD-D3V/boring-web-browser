"""Signed in across the update: two stages for the Windows Sandbox update
test (tools/sbx/run.py), Release 4 ledger item 4.

Release N signs in to login_site.py's local site on its own profile
(C:\\p4): a session cookie, a 30 day cookie, localStorage and IndexedDB.
It quits with the site's tab open, the way a person closes the window,
starts again and must still be signed in (a plain restart, so a failure
after the update is the update's), and quits again the same way. Release
N+1, on its first start on that profile after the update, must bring the
tab back and still be signed in, with both cookies, both storage values,
and the same cookie key in Local State.

run.py binds the module to itself (bind) and lists login_before_update
before the update and login_after_update after it. The site runs in the
harness's own process on 127.0.0.1, so it remembers who signed in across
the update. Nothing here is run on the host.
"""

import json
from pathlib import Path

import login_site

PROFILE = Path(r"C:\p4")
PORT = 8766
H = None  # the harness module (run.py)
SITE = None
BEFORE = {}


def bind(harness):
    global H
    H = harness


def _site():
    global SITE
    if SITE is None:
        SITE = login_site.LoginSite(port=PORT).start()
        H.log("login test site on", SITE.url)
    return SITE


def _start(port, label):
    """Start the browser on the profile and wait for the site's tab to be
    there (restored), or for any tab on the very first start."""
    site = _site()
    c = H.Chrome(PROFILE, port=port)
    restored = H.wait_for(
        lambda: any(t["url"].startswith(site.url) for t in c.tabs()), 40
    )
    H.log(f"p4 tabs, {label}:", [(t["url"], t["title"]) for t in c.tabs()])
    return c, restored


def _signed_in(c, label):
    """The site's answer and the page's storage, on an attached browser."""
    c.get(_site().url)
    state = c.run_async(login_site.for_webdriver(login_site.STATE_JS))
    H.log(f"p4 state, {label}:", state)
    for name, ok, detail in login_site.signed_in_checks(state):
        H.check(f"{label}: {name}", ok, detail)


def _quit_with_tab_open(c, label):
    """Like tabs_before_update: the driver goes, then WM_CLOSE to the
    window, so the session is saved with the tab in it."""
    try:
        H.http(f"{c.wd}/session/{c.sid}", "DELETE")
    except Exception:
        pass
    c.drv.kill()
    n = H.post_wm_close(c.proc.pid)
    gone = H.wait_for(lambda: c.proc.poll() is not None, 40)
    if not gone:
        H.subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(c.proc.pid)], capture_output=True
        )
    H.check(f"{label}: quits on window close with the tab open", gone and n > 0)
    H.wait_for(
        lambda: "chrome.exe"
        not in H.subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True,
            text=True,
        ).stdout,
        20,
    )


def _disk(label):
    rows = login_site.cookie_rows(PROFILE / "Default" / "Network" / "Cookies")
    key = login_site.key_state(PROFILE / "Local State")
    H.log(f"p4 on disk, {label}:", rows, "app-bound key:", key["app_bound"])
    names = {name: (persistent, prefix) for name, persistent, prefix in rows}
    H.check(
        f"{label}: both cookies are on disk, the session one too",
        names.get("sid", (None,))[0] is False and names.get("remember", (None,))[0] is True,
        str(rows),
    )
    H.result("INFO", f"cookie sealing {label}", ",".join(sorted({p for _, p in names.values()})))
    H.check(
        f"{label}: the cookies are not app-bound (per-user install)",
        "v20" not in {p for _, p in names.values()} and not key["app_bound"],
        str(rows),
    )
    return key


def login_before_update():
    """Release N: sign in, quit, restart, still signed in, quit."""
    c, _ = _start(9336, "Release N, first start")
    H.result("INFO", "version that signs in", c.version())
    c.attach()
    c.get(_site().url)
    signed = json.loads(c.run_async(login_site.for_webdriver(login_site.SIGN_IN_JS)))
    H.check("Release N: signing in to the local site works", signed.get("status") == 200, json.dumps(signed))
    _signed_in(c, "Release N, signed in")
    # The session file is written a few seconds after a navigation.
    H.time.sleep(10)
    _quit_with_tab_open(c, "Release N")

    c, restored = _start(9337, "Release N, restart")
    H.check("Release N restart: the site's tab comes back", restored)
    c.attach()
    _signed_in(c, "Release N after a plain restart")
    H.time.sleep(5)
    _quit_with_tab_open(c, "Release N after the restart")
    BEFORE["key"] = _disk("before the update")


def login_after_update():
    """Release N+1, first start on the profile Release N signed in on."""
    c, restored = _start(9338, "Release N+1, first start")
    version = c.version()
    H.result("INFO", "version that checks the sign-in", version)
    H.check("the sign-in is checked by the updated browser", version.endswith("/" + H.B_VERSION), version)
    H.check("after the update: the site's tab comes back", restored)
    c.attach()
    _signed_in(c, "after the update")
    H.time.sleep(5)
    _quit_with_tab_open(c, "Release N+1")
    key = _disk("after the update")
    H.check(
        "after the update: the cookie key in Local State is the one from before",
        bool(BEFORE.get("key")) and key == BEFORE["key"],
    )
