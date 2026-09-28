#!/usr/bin/env python3
"""Check tab freezing and sleeping: what is frozen, what never is, and
that a tab put to sleep comes back still logged in.

Freezing: a background tab stops running after a few minutes and wakes
at once when shown (components/boring/performance/idle_tab_freezer.h).
Sleeping: Chromium's Memory Saver unloads a tab after a long time in the
background, or under memory pressure. Neither may touch a tab that plays
sound, has a half-filled form, is pinned, or is on a site kept awake.

Everything is on this machine: the pages are served from 127.0.0.1 under
*.localhost names, which Chromium resolves to loopback itself. The
browser is driven over the DevTools protocol only, never OS input, with
the window off screen. Test tabs are not attached to DevTools while they
are judged, because Chromium protects a tab with DevTools open from
sleeping.

Test-only switches, all Chromium's own, none added by us:
  --enable-features=CPUMeasurementInFreezingPolicy:
      freezing_visible_protection_time/5s/freezing_audio_protection_time/5s
        wait 5 seconds in the background before freezing, not 5 minutes
  --enable-features=AllowDevtoolsConnectedDiscard
        belt and braces, in case a DevTools client is still attached
  --load-extension=<a tiny extension written by this test>
        pins the tab on pinned.localhost, as nothing else here can pin
chrome://discards is used to read each tab's state and to ask for a
sleep the way Memory Saver asks (a "proactive" discard, which respects
every protection).

Usage: python smoke_memory.py   (BORING_OUT picks the build, see drive.py)
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from drive import CHROME, OFFSCREEN
from measure_startup import DevTools
from smoke_local import Checks, set_profile_pref

# chrome/browser/resource_coordinator/lifecycle_unit_state.mojom
FROZEN = 3
DISCARDED = 5
PROACTIVE = 2
# chrome/browser/ui/webui/discards/discards.mojom, CanFreeze
CAN_FREEZE_NO = 2

PROTECTION_SECONDS = 5
LOADED_WHO = "document.readyState === 'complete' && !!document.getElementById('who')"
FREEZE_TIMEOUT = 60

IDLE_PAGE = """<!doctype html><title>idle</title>
<p id="n">0</p>
<script>
  sessionStorage.setItem('froze', '0');
  sessionStorage.setItem('resumed', '0');
  document.addEventListener('freeze', () => sessionStorage.setItem('froze', '1'));
  document.addEventListener('resume', () => sessionStorage.setItem('resumed', '1'));
  let n = 0;
  setInterval(() => { document.getElementById('n').textContent = ++n; }, 100);
</script>"""

AUDIO_PAGE = """<!doctype html><title>audio</title>
<script>
  const ctx = new AudioContext();
  const tone = ctx.createOscillator();
  const gain = ctx.createGain();
  gain.gain.value = 0.05;
  tone.connect(gain).connect(ctx.destination);
  tone.start();
  ctx.resume();
</script>"""

FORM_PAGE = """<!doctype html><title>form</title>
<form><label>Your name <input id="name" autofocus></label></form>"""

PLAIN_PAGE = """<!doctype html><title>{title}</title><p>{title}</p>"""

# Pins any tab on pinned.localhost as soon as it has loaded.
PIN_EXTENSION = {
    "manifest.json": json.dumps(
        {
            "manifest_version": 3,
            "name": "smoke_memory pinner",
            "version": "1.0",
            "permissions": ["tabs"],
            "background": {"service_worker": "pin.js"},
        }
    ),
    "pin.js": (
        "chrome.tabs.onUpdated.addListener((id, change, tab) => {\n"
        "  if (change.status === 'complete' && tab.url &&\n"
        "      new URL(tab.url).hostname === 'pinned.localhost' && !tab.pinned) {\n"
        "    chrome.tabs.update(id, {pinned: true});\n"
        "  }\n"
        "});\n"
    ),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        host = (self.headers.get("Host") or "").split(":")[0]
        path = self.path.split("?", 1)[0]
        cookie = self.headers.get("Cookie") or ""
        if host == "login.localhost" and path == "/login":
            # A session cookie, the kind that is lost if sleeping ever
            # meant closing the tab's session.
            self.send_response(302)
            self.send_header("Set-Cookie", "session=smoke-user; Path=/; HttpOnly")
            self.send_header("Location", "/account")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if host == "login.localhost":
            who = "smoke-user" if "session=smoke-user" in cookie else None
            body = (
                f"<!doctype html><title>account</title><p id=who>Logged in as {who}</p>"
                if who
                else "<!doctype html><title>account</title><p id=who>Logged out</p>"
            )
        else:
            name = host.split(".")[0]
            body = {
                "idle": IDLE_PAGE,
                "audio": AUDIO_PAGE,
                "form": FORM_PAGE,
            }.get(name, PLAIN_PAGE.format(title=name))
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class Cdp(DevTools):
    """The browser target, with flat sessions for the tabs it attaches to."""

    def send(self, method, session=None, **params):
        self.next_id += 1
        message = {"id": self.next_id, "method": method, "params": params}
        if session:
            message["sessionId"] = session
        self._send(json.dumps(message))
        while True:
            reply = json.loads(self._read_message())
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})

    def attach(self, target_id):
        return self.send("Target.attachToTarget", targetId=target_id, flatten=True)[
            "sessionId"
        ]

    def detach(self, session):
        self.send("Target.detachFromTarget", sessionId=session)

    def evaluate(self, session, expression):
        result = self.send(
            "Runtime.evaluate",
            session,
            expression=expression,
            awaitPromise=True,
            returnByValue=True,
        )
        if "exceptionDetails" in result:
            raise RuntimeError(json.dumps(result["exceptionDetails"])[:400])
        return result["result"].get("value")

    def open_tab(self, url, background):
        return self.send("Target.createTarget", url=url, background=background)[
            "targetId"
        ]

    def find_tab(self, url_prefix):
        """A tab's target by its address, which outlives a sleep."""
        for target in self.send("Target.getTargets")["targetInfos"]:
            if target["type"] == "page" and target["url"].startswith(url_prefix):
                return target["targetId"]
        raise RuntimeError(f"no tab at {url_prefix}")

    def show(self, target_id):
        self.send("Target.activateTarget", targetId=target_id)

    def wait_for(self, session, expression, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.evaluate(session, expression):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.2)
        return False


def launch(exe, profile, extra):
    port_file = profile / "DevToolsActivePort"
    if port_file.exists():
        port_file.unlink()
    proc = subprocess.Popen(
        [
            exe,
            f"--user-data-dir={profile}",
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-boring-updates",
            "--disable-boring-list-updates",
            "--window-position=" + OFFSCREEN,
            "--window-size=1200,850",
            "--disable-backgrounding-occluded-windows",
            *extra,
            "about:blank",
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
    cdp.close()
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True
        )


TAB_INFOS = """(async () => {
  const m = await import('chrome://discards/discards.js');
  const {infos} = await m.getOrCreateDetailsProvider().getTabDiscardsInfo();
  return infos.map(i => ({url: i.tabUrl, id: i.id, state: i.state,
      canFreeze: i.canFreeze, freezeReasons: i.cannotFreezeReasons,
      discardReasons: i.cannotDiscardReasons}));
})()"""


def tab_infos(cdp, discards):
    # Keyed by the first label of the host: "idle" for idle.localhost.
    return {
        info["url"].split("/")[2].split(".")[0]: info
        for info in cdp.evaluate(discards, TAB_INFOS)
        if info["url"].startswith("http")
    }


def sleep_tab(cdp, discards, tab_id):
    cdp.evaluate(
        discards,
        "(async () => { const m = await import('chrome://discards/discards.js');"
        f" await m.getOrCreateDetailsProvider().discardById({tab_id}, {PROACTIVE});"
        " return true; })()",
    )


def main():
    checks = Checks()
    work = Path(tempfile.mkdtemp(prefix="boring-memory-", dir=os.environ.get("TMP")))
    profile = work / "profile"
    extension = work / "pinner"
    extension.mkdir()
    for name, text in PIN_EXTENSION.items():
        (extension / name).write_text(text, encoding="utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_port

    def url(host, path="/"):
        return f"http://{host}.localhost:{port}{path}"

    try:
        # A first run makes the profile, so the never-sleep site can be
        # written into it the way the shield would leave it.
        proc, cdp = launch(CHROME, profile, [])
        time.sleep(2)
        close(proc, cdp)
        set_profile_pref(
            profile,
            "boring.performance.never_sleep_sites",
            [f"http://keepawake.localhost:{port}"],
        )

        protection = f"{PROTECTION_SECONDS}s"
        proc, cdp = launch(
            CHROME,
            profile,
            [
                "--enable-features=CPUMeasurementInFreezingPolicy:"
                f"freezing_visible_protection_time/{protection}/"
                f"freezing_audio_protection_time/{protection},"
                "AllowDevtoolsConnectedDiscard",
                "--disable-features=CalculateNativeWinOcclusion",
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
                f"--load-extension={extension}",
            ],
        )
        try:
            run(cdp, url, checks)
        finally:
            close(proc, cdp)
    finally:
        server.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    return checks.result("freezing and sleeping behave, and logins survive")


def run(cdp, url, checks):
    # Memory Saver, as the settings page reads it.
    settings_tab = cdp.open_tab("chrome://settings/performance", background=False)
    settings = cdp.attach(settings_tab)
    cdp.wait_for(settings, "!!(window.chrome && chrome.settingsPrivate)")
    state, level = cdp.evaluate(
        settings,
        "Promise.all(['performance_tuning.high_efficiency_mode.state',"
        " 'performance_tuning.high_efficiency_mode.aggressiveness'].map(n =>"
        " new Promise(r => chrome.settingsPrivate.getPref(n, p => r(p.value)))))",
    )
    checks("Memory Saver is on by default", state == 2, f"state {state}")
    checks("Memory Saver defaults to balanced", level == 1, f"level {level}")
    cdp.detach(settings)
    cdp.send("Target.closeTarget", targetId=settings_tab)

    discards_tab = cdp.open_tab("chrome://discards", background=False)
    discards = cdp.attach(discards_tab)
    cdp.wait_for(discards, "document.readyState === 'complete'")

    # Tabs that start in the background.
    for host in ("idle", "audio", "keepawake", "pinned"):
        cdp.open_tab(url(host), background=True)

    # A half-filled form: typed into over DevTools while the tab is in
    # front, then left behind.
    form_tab = cdp.open_tab(url("form"), background=False)
    form = cdp.attach(form_tab)
    cdp.wait_for(form, "document.readyState === 'complete'")
    # The window is off screen and never gets Windows focus, so the page
    # is told it has focus, or the typing would go nowhere.
    cdp.send("Emulation.setFocusEmulationEnabled", form, enabled=True)
    cdp.evaluate(form, "document.getElementById('name').focus(), true")
    cdp.send("Input.insertText", form, text="Half a na")
    typed = cdp.evaluate(form, "document.getElementById('name').value")
    checks("the form was typed into", typed == "Half a na", repr(typed))
    cdp.detach(form)

    # Logged in, then left behind.
    login_tab = cdp.open_tab(url("login", "/login"), background=False)
    login = cdp.attach(login_tab)
    cdp.wait_for(login, LOADED_WHO)
    who = cdp.evaluate(login, "document.getElementById('who').textContent")
    checks("logged in on the local page", who == "Logged in as smoke-user", who)
    cdp.detach(login)

    cdp.show(discards_tab)

    # Wait for the idle tab to freeze.
    deadline = time.monotonic() + FREEZE_TIMEOUT
    infos = {}
    while time.monotonic() < deadline:
        infos = tab_infos(cdp, discards)
        if infos.get("idle", {}).get("state") == FROZEN:
            break
        time.sleep(1)
    checks(
        "an idle background tab freezes",
        infos.get("idle", {}).get("state") == FROZEN,
        json.dumps(infos.get("idle")),
    )
    # Give the others the same time again, and more.
    time.sleep(PROTECTION_SECONDS * 3)
    infos = tab_infos(cdp, discards)

    kept = {
        "audio": ("Tab is playing audio", "audible"),
        "form": ("Tab has form interactions", None),
        "pinned": ("Tab was pinned", None),
        "keepawake": ("Tab was opted out", "opted out"),
    }
    for host, (discard_reason, freeze_reason) in kept.items():
        info = infos.get(host)
        if not checks(f"{host} tab is listed", info is not None):
            continue
        checks(f"{host} tab is not frozen", info["state"] != FROZEN, str(info["state"]))
        if freeze_reason:
            checks(
                f"{host} tab cannot be frozen ({freeze_reason})",
                info["canFreeze"] == CAN_FREEZE_NO
                and any(freeze_reason in r for r in info["freezeReasons"]),
                json.dumps(info["freezeReasons"]),
            )
        checks(
            f"{host} tab is protected from sleeping",
            any(r.startswith(discard_reason) for r in info["discardReasons"]),
            json.dumps(info["discardReasons"]),
        )
        sleep_tab(cdp, discards, info["id"])
    time.sleep(2)
    infos = tab_infos(cdp, discards)
    for host in kept:
        state = infos.get(host, {}).get("state")
        checks(
            f"{host} tab stays awake when asked to sleep",
            state != DISCARDED,
            str(state),
        )

    # The logged-in tab goes to sleep and comes back logged in.
    login_info = infos.get("login")
    if checks("login tab is listed", login_info is not None):
        sleep_tab(cdp, discards, login_info["id"])
        time.sleep(2)
        state = tab_infos(cdp, discards).get("login", {}).get("state")
        checks(
            "an unprotected background tab can sleep", state == DISCARDED, str(state)
        )
        login_tab = cdp.find_tab(url("login"))
        cdp.show(login_tab)
        login = cdp.attach(login_tab)
        cdp.wait_for(login, LOADED_WHO)
        who = cdp.evaluate(login, "document.getElementById('who').textContent")
        reloaded = cdp.evaluate(login, "document.wasDiscarded")
        checks("the slept tab reloads when shown", reloaded is True, str(reloaded))
        checks("and is still logged in", who == "Logged in as smoke-user", who)
        cdp.detach(login)

    # The frozen tab wakes when shown and runs again.
    idle_target = cdp.find_tab(url("idle"))
    cdp.show(idle_target)
    idle = cdp.attach(idle_target)
    woke = cdp.wait_for(idle, "sessionStorage.getItem('resumed') === '1'", timeout=10)
    first = int(cdp.evaluate(idle, "document.getElementById('n').textContent"))
    time.sleep(1)
    second = int(cdp.evaluate(idle, "document.getElementById('n').textContent"))
    froze = cdp.evaluate(idle, "sessionStorage.getItem('froze')")
    checks("the frozen tab had its freeze event", froze == "1", str(froze))
    checks("the frozen tab wakes when shown", woke)
    checks("and its page runs again", second > first, f"{first} -> {second}")
    cdp.detach(idle)


if __name__ == "__main__":
    sys.exit(main())
