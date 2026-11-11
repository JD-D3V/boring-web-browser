#!/usr/bin/env python3
"""Deleted sessions stay deleted in the encrypted session copies (ledger 124).

Chromium 157 turns EncryptSessionStorage on: every session and recently
closed file in Default/Sessions gets an encrypted twin in
Default/Sessions_Encrypted. "Forget this session" deletes the last session
and the recently closed list through SessionService::DeleteLastSession and
the TabRestoreService (pending reset, then DeleteLastSession), and
CommandStorageManager mirrors each of those to the encrypted twin. This
checks that it does, in the browser, headless:

  1. a session with one open and one closed tab, then a normal quit
  2. control: a copy of the profile with the clear Sessions folder moved
     away, opened with the stage that reads the encrypted copy first,
     lists both tabs; so the twin holds them and the browser can read it
  3. the deletion, through the browsing data remover with history (the
     native Forget this session dialog needs a real window; this reaches
     the same session and tab restore calls)
  4. the same encrypted-only view of the profile lists neither tab, and
     neither does an ordinary next start

Usage: python smoke_session_copies.py
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from drive import CHROME
from smoke_local import Checks
from smoke_memory import Cdp

PREFER_ENCRYPTED = (
    "--enable-features=EncryptSessionStorage:stage/write_both_read_prefer_encrypted"
)
STARTUP_PREF = "session.restore_on_startup"
NEW_TAB_PAGE = 5

EXTENSION = {
    "manifest.json": json.dumps(
        {
            "manifest_version": 3,
            "name": "smoke_session_copies driver",
            "version": "1.0",
            "permissions": ["tabs", "sessions", "browsingData"],
            "background": {"service_worker": "bg.js"},
        }
    ),
    "bg.js": "self.addEventListener('install', () => {});\n",
    "page.html": "<!doctype html><title>driver</title>",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        name = (self.headers.get("Host") or "").split(":")[0].split(".")[0]
        data = f"<!doctype html><title>{name}</title><p>{name}</p>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def launch(profile, extension, extra=()):
    port_file = profile / "DevToolsActivePort"
    if port_file.exists():
        port_file.unlink()
    proc = subprocess.Popen(
        [
            CHROME,
            f"--user-data-dir={profile}",
            "--remote-debugging-port=0",
            "--headless=new",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-boring-updates",
            "--disable-boring-list-updates",
            f"--load-extension={extension}",
            *extra,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 60
    while not port_file.exists() or port_file.stat().st_size == 0:
        if time.monotonic() > deadline or proc.poll() is not None:
            proc.kill()
            raise RuntimeError("the browser did not open DevTools")
        time.sleep(0.1)
    port, path = port_file.read_text().split()[:2]
    return proc, Cdp(f"ws://127.0.0.1:{port}{path}")


def close(proc, cdp):
    with contextlib.suppress(Exception):
        cdp.send("Browser.close")
    with contextlib.suppress(Exception):
        cdp.close()
    try:
        proc.wait(40)
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True
        )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(15)


def driver_page(cdp, timeout=30):
    """A tab of the driver extension, where chrome.sessions is available."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for t in cdp.send("Target.getTargets")["targetInfos"]:
            url = t["url"]
            if url.startswith("chrome-extension://") and url.endswith("/bg.js"):
                tab = cdp.open_tab(url[: -len("bg.js")] + "page.html", background=True)
                session = cdp.attach(tab)
                cdp.wait_for(session, "!!(window.chrome && chrome.sessions)")
                return session
        time.sleep(0.3)
    raise RuntimeError("the driver extension did not load")


def recently_closed(cdp, session):
    return (
        cdp.evaluate(
            session,
            "chrome.sessions.getRecentlyClosed({maxResults: 25})"
            ".then(r => JSON.stringify(r))",
        )
        or ""
    )


def set_pref(cdp, name, value):
    tab = cdp.open_tab("chrome://settings/", background=True)
    session = cdp.attach(tab)
    try:
        cdp.wait_for(session, "!!(window.chrome && chrome.settingsPrivate)")
        cdp.evaluate(
            session,
            f"new Promise(r => chrome.settingsPrivate.setPref("
            f"'{name}', {json.dumps(value)}, '', r))",
        )
        return cdp.evaluate(
            session,
            f"new Promise(r => chrome.settingsPrivate.getPref('{name}', p => r(p.value)))",
        )
    finally:
        cdp.detach(session)
        cdp.send("Target.closeTarget", targetId=tab)


def listed(cdp, session, markers):
    """Which markers the browser still offers: recently closed or open."""
    text = recently_closed(cdp, session)
    urls = " ".join(
        t["url"]
        for t in cdp.send("Target.getTargets")["targetInfos"]
        if t["type"] == "page"
    )
    return [m for m in markers if m in text or m in urls]


def encrypted_only(work, profile, extension, label, markers):
    """What the browser lists from Sessions_Encrypted alone: a copy of the
    closed profile without its clear Sessions folder, read encrypted first
    (the fallback to the clear file then finds nothing)."""
    view = work / f"view-{label}"
    shutil.copytree(profile, view)
    clear = view / "Default" / "Sessions"
    if clear.exists():
        clear.rename(view / "Default" / "Sessions.moved-away")
    proc, cdp = launch(view, extension, [PREFER_ENCRYPTED])
    try:
        time.sleep(3)
        return listed(cdp, driver_page(cdp), markers)
    finally:
        close(proc, cdp)


def files(profile, folder):
    path = profile / "Default" / folder
    return sorted(p.name for p in path.glob("*")) if path.exists() else []


def main():
    check = Checks()
    work = Path(
        tempfile.mkdtemp(prefix="boring-sesscopies-", dir=os.environ.get("TMP"))
    )
    profile = work / "profile"
    extension = work / "driver"
    extension.mkdir()
    for name, text in EXTENSION.items():
        (extension / name).write_text(text, encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    tag = uuid.uuid4().hex[:6]
    kept_open, closed_tab = f"sessopen{tag}", f"sessclosed{tag}"
    markers = [kept_open, closed_tab]

    def url(name):
        return f"http://{name}.localhost:{server.server_port}/"

    try:
        # 1. The session to forget. A new tab page on start, so the next
        # runs list it as a recently closed window instead of reopening it
        # into their own session.
        proc, cdp = launch(profile, extension)
        try:
            time.sleep(2)
            set_pref(cdp, STARTUP_PREF, NEW_TAB_PAGE)
            cdp.open_tab(url(kept_open), background=False)
            tab = cdp.open_tab(url(closed_tab), background=False)
            time.sleep(2)
            cdp.send("Target.closeTarget", targetId=tab)
            time.sleep(7)  # the session is written a few seconds after a change
        finally:
            close(proc, cdp)
        twin = files(profile, "Sessions_Encrypted")
        check(
            "the session and the closed tab have encrypted copies",
            any(n.startswith("Session_") for n in twin)
            and any(n.startswith("Tabs_") for n in twin),
            str(twin),
        )

        # 2. Control.
        found = encrypted_only(work, profile, extension, "before", markers)
        check(
            "control: the browser reads both tabs back from the encrypted copy alone",
            set(found) == set(markers),
            str(found),
        )

        # 3. The deletion.
        proc, cdp = launch(profile, extension)
        try:
            time.sleep(3)
            session = driver_page(cdp)
            before = listed(cdp, session, markers)
            check(
                "before the delete both tabs are listed",
                set(before) == set(markers),
                str(before),
            )
            cdp.evaluate(
                session,
                "chrome.browsingData.remove({since: 0}, {history: true, cookies: true,"
                " localStorage: true, cache: true}).then(() => true)",
            )
            time.sleep(7)
            after = listed(cdp, session, markers)
            check("after the delete neither tab is listed", not after, str(after))
        finally:
            close(proc, cdp)

        # 4. Nothing comes back, from either copy.
        found = encrypted_only(work, profile, extension, "after", markers)
        check(
            "after the delete the encrypted copy gives neither tab back",
            not found,
            str(found),
        )
        proc, cdp = launch(profile, extension)
        try:
            time.sleep(3)
            found = listed(cdp, driver_page(cdp), markers)
            check("the next start lists neither tab", not found, str(found))
        finally:
            close(proc, cdp)
    finally:
        server.shutdown()
        shutil.rmtree(work, ignore_errors=True)

    print("FAILED: " + ", ".join(check.failures) if check.failures else "ALL PASS")
    return 1 if check.failures else 0


if __name__ == "__main__":
    sys.exit(main())
