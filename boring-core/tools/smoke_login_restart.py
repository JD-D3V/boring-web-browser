#!/usr/bin/env python3
"""A person stays signed in across a plain restart (Release 4, ledger item 4).

Headless, on a fresh profile, against login_site.py's local site:

  1. sign in: a session cookie and a 30 day cookie, plus a value in
     localStorage and one in IndexedDB; the site says signed in (control)
  2. a normal quit with the site's tab still open
  3. on disk: both cookies are in Network/Cookies, the session one too
     (Chromium writes it so "Continue where you left off" can restore it),
     sealed with the DPAPI-wrapped key in Local State (v10), not app-bound
     (v20), which a per-user install cannot use
  4. the next start, on its own: the tab comes back, the site still says
     signed in through both cookies, both storage values are there, and
     the key in Local State is the one the cookies were sealed with

The update case (Release N signs in, Release N+1 checks) is the same check
in the Windows Sandbox run, tools/sbx/login_stages.py.

Usage: python smoke_login_restart.py
"""

import base64
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from login_site import (
    SIGN_IN_JS,
    STATE_JS,
    LoginSite,
    cookie_rows,
    key_state,
    signed_in_checks,
)
from smoke_local import Checks
from smoke_session_copies import EXTENSION, close, launch

RESTORE_PREF = "session.restore_on_startup"
CONTINUE = 1  # SessionStartupPref::kPrefValueLast

PREF_JS = (
    "new Promise(r => chrome.settingsPrivate.getPref("
    f"'{RESTORE_PREF}', p => r(JSON.stringify(p))))"
)


def page_session(cdp, url, open_it):
    """A DevTools session on the site's tab: a new one, or the restored one."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if open_it:
            tab = cdp.open_tab(url, background=False)
        else:
            tab = next(
                (
                    t["targetId"]
                    for t in cdp.send("Target.getTargets")["targetInfos"]
                    if t["type"] == "page" and t["url"].startswith(url)
                ),
                None,
            )
        if tab:
            session = cdp.attach(tab)
            cdp.wait_for(session, "document.readyState === 'complete'")
            return session
        time.sleep(0.5)
    return None


def restore_pref(cdp):
    tab = cdp.open_tab("chrome://settings/", background=True)
    session = cdp.attach(tab)
    try:
        cdp.wait_for(session, "!!(window.chrome && chrome.settingsPrivate)")
        return json.loads(cdp.evaluate(session, PREF_JS))
    finally:
        cdp.detach(session)
        cdp.send("Target.closeTarget", targetId=tab)


def main():
    check = Checks()
    work = Path(tempfile.mkdtemp(prefix="boring-login-", dir=os.environ.get("TMP")))
    profile = work / "profile"
    extension = work / "driver"
    extension.mkdir()
    for name, text in EXTENSION.items():
        (extension / name).write_text(text, encoding="utf-8")
    site = LoginSite().start()

    # --- 1 and 2: sign in, then quit with the tab open
    proc, cdp = launch(profile, extension)
    try:
        pref = restore_pref(cdp)
        print(f"  {RESTORE_PREF}: {json.dumps(pref)}")
        check(
            "the default is Continue where you left off",
            pref.get("value") == CONTINUE,
            json.dumps(pref),
        )
        session = page_session(cdp, site.url, open_it=True)
        check("the site opens", bool(session))
        signed = json.loads(cdp.evaluate(session, SIGN_IN_JS))
        check("signing in works", signed.get("status") == 200, json.dumps(signed))
        for name, ok, detail in signed_in_checks(cdp.evaluate(session, STATE_JS)):
            check("before the restart: " + name, ok, detail)
        # The session file is written a few seconds after a navigation.
        time.sleep(5)
    finally:
        close(proc, cdp)

    # --- 3: what is on disk
    rows = cookie_rows(profile / "Default" / "Network" / "Cookies")
    print(f"  cookies on disk: {rows}")
    names = {name: (persistent, prefix) for name, persistent, prefix in rows}
    check("the session cookie is on disk", names.get("sid", (None,))[0] is False, str(rows))
    check("the 30 day cookie is on disk", names.get("remember", (None,))[0] is True, str(rows))
    check(
        "both are sealed with the Local State key (v10), not app-bound (v20)",
        {p for _, p in names.values()} == {"v10"},
        str(rows),
    )
    key = key_state(profile / "Local State")
    raw = base64.b64decode(key["encrypted_key"] or "")
    check("Local State holds a DPAPI-wrapped key", raw.startswith(b"DPAPI"))
    check("and no app-bound key", not key["app_bound"])

    # --- 4: the next start
    proc, cdp = launch(profile, extension)
    try:
        session = page_session(cdp, site.url, open_it=False)
        check("the site's tab comes back on its own", bool(session))
        if not session:
            session = page_session(cdp, site.url, open_it=True)
        for name, ok, detail in signed_in_checks(cdp.evaluate(session, STATE_JS)):
            check("after the restart: " + name, ok, detail)
    finally:
        close(proc, cdp)
    check(
        "the cookie key is the same after the restart",
        key_state(profile / "Local State") == key,
    )
    site.stop()
    sys.exit(check.result("signed in, with site data, after a restart"))


if __name__ == "__main__":
    main()
