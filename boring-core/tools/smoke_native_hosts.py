#!/usr/bin/env python3
"""Check "Apps on this computer" on the Protection page and the block
behind it, in the real build.

A tiny echo host is registered under HKCU for this test only (one under
the Chromium key, one under the Google\\Chrome key), and an unpacked test
add-on with nativeMessaging calls it:

  - A new profile (no Preferences file yet, so chromedriver does not start
    it) blocks the host: the add-on gets Chromium's own "disabled by the
    system administrator" error, as for a policy block, and the Protection
    page lists the host with its add-on and a switch that is off.
  - The switch on lets the call through (the host echoes), the switch off
    blocks it again, and the other host stays blocked throughout.
  - A profile that existed before (a Preferences file is already there)
    starts with the registered hosts on, and the call works.

The registration, the host script and the profiles are removed in a
finally block, also when a check fails.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import winreg

from drive import CHROME, Browser, free_port

URL = "chrome://boring-protection"
TMP = os.environ.get("TMP", r"E:\tmp")
ROOT = os.path.join(TMP, "feat-native-hosts")
ADDON_NAME = "Boring Test Native Caller"
HOST = "com.boring_test.echo"
HOST_GOOGLE = "com.boring_test.echo_google"
HOST_DESCRIPTION = "Boring test echo"
HOST_GOOGLE_DESCRIPTION = "Boring test echo (Google key)"
# What an add-on is told when the browser blocks the host.
BLOCKED = "disabled by the system administrator"
# Where each test host is registered, per user. The browser reads both.
REGISTERED = {
    HOST: r"SOFTWARE\Chromium\NativeMessagingHosts",
    HOST_GOOGLE: r"SOFTWARE\Google\Chrome\NativeMessagingHosts",
}

ECHO_HOST = '''import json
import struct
import sys

length = struct.unpack("<I", sys.stdin.buffer.read(4))[0]
message = json.loads(sys.stdin.buffer.read(length))
reply = json.dumps({"echo": message}).encode()
sys.stdout.buffer.write(struct.pack("<I", len(reply)) + reply)
sys.stdout.buffer.flush()
'''

# Put in front of the echo host when it is written: one line per start, with
# the arguments the browser gave it, so a test can tell a start that went
# through (an origin and a reconnect command) from one that is an error
# report (the origin and --extension-not-installed).
LAUNCH_LOG = '''import sys
try:
    with open(r"__LOG__", "a", encoding="utf-8") as _log:
        _log.write(repr(sys.argv[1:]) + "\\n")
except OSError:
    pass
'''

# A second add-on, for the launch from the native side: it lists the hosts as
# natively connectable and counts the connections the browser hands it.
LAUNCHER_NAME = "Boring Test Native Launcher"
LAUNCHER_WORKER = """
chrome.runtime.onConnectNative.addListener(function(port) {
  chrome.storage.local.get({connections: 0}, function(r) {
    chrome.storage.local.set({connections: r.connections + 1});
  });
});
"""
# The error report the browser starts a host with when it will not connect.
NOT_INSTALLED = "--extension-not-installed"

CALL = """
  const [host, done] = arguments;
  chrome.runtime.sendNativeMessage(host, {hello: 'world'}, function(reply) {
    const err = chrome.runtime.lastError;
    done({reply: reply || null, error: err ? err.message : null});
  });
"""

EXT_IDS = """
  var done = arguments[arguments.length - 1];
  chrome.developerPrivate.getExtensionsInfo(
      {includeDisabled: true, includeTerminated: true}, function(list) {
    var out = {};
    list.forEach(function(e) { out[e.name] = e.id; });
    done(out);
  });
"""

READ_HOSTS = """
  var rows = {};
  document.querySelectorAll('#connections-hosts .setting-row').forEach(
      function(r) {
    var sw = r.querySelector('input.switch');
    rows[sw.id] = {text: r.innerText, on: sw.checked, disabled: sw.disabled};
  });
  var box = document.getElementById('connections-hosts');
  return {rows: rows, text: box.innerText,
          intro: (document.getElementById('hosts-intro') || {}).innerText};
"""


class NewProfileBrowser(Browser):
    """A browser on a profile that does not exist yet.

    chromedriver writes a Preferences file into the profile before it
    starts the browser, so through it every profile is one that existed
    before. This starts the browser itself, off screen like drive.py does,
    and lets chromedriver attach to it over the debugging port."""

    def _new_session(self, caps):
        options = caps["capabilities"]["alwaysMatch"]["goog:chromeOptions"]
        port = free_port()
        self.chrome = subprocess.Popen(
            [CHROME, "--remote-debugging-port=%d" % port] + options["args"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port).read()
                break
            except Exception:
                time.sleep(0.2)
        attach = {"goog:chromeOptions": {"debuggerAddress": "127.0.0.1:%d" % port}}
        return super()._new_session({"capabilities": {"alwaysMatch": attach}})

    def quit(self):
        try:
            super().quit()
        finally:
            self.chrome.terminate()


def register(manifest):
    for name, key in REGISTERED.items():
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + "\\" + name) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, manifest(name))


def unregister():
    """Remove both test keys. Safe when they are already gone."""
    for name, key in REGISTERED.items():
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key + "\\" + name)
        except OSError:
            pass


def write_host_files(work):
    """The echo host, its launcher and a manifest writer. Returns the
    manifest path for each host, a function that writes the manifests once
    the add-ons' ids are known, and the file every start of the host is
    written down in."""
    log = os.path.join(work, "host-starts.log")
    script = os.path.join(work, "echo_host.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(LAUNCH_LOG.replace("__LOG__", log) + ECHO_HOST)
    launcher = os.path.join(work, "echo_host.bat")
    with open(launcher, "w", encoding="utf-8", newline="\r\n") as f:
        f.write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, script))
    paths = {n: os.path.join(work, n + ".json") for n in REGISTERED}

    def write_manifests(*ext_ids):
        for name, path in paths.items():
            manifest = {
                "name": name,
                "path": launcher,
                "type": "stdio",
                "allowed_origins": ["chrome-extension://%s/" % i for i in ext_ids],
                "supports_native_initiated_connections": True,
            }
            # Chromium refuses a manifest without a description.
            manifest["description"] = (
                HOST_DESCRIPTION if name == HOST else HOST_GOOGLE_DESCRIPTION
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(manifest, f)

    return paths, write_manifests, log


def write_addon(work):
    root = os.path.join(work, "caller")
    os.makedirs(root, exist_ok=True)
    manifest = {
        "manifest_version": 3,
        "name": ADDON_NAME,
        "version": "1.0",
        "permissions": ["nativeMessaging"],
    }
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    with open(os.path.join(root, "call.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><title>call</title>")
    return root


def write_launcher_addon(work):
    """The add-on the host starts from the native side connect to. Needs the
    OnConnectNative feature, a natively_connectable list and the
    transientBackground permission."""
    root = os.path.join(work, "launcher")
    os.makedirs(root, exist_ok=True)
    manifest = {
        "manifest_version": 3,
        "name": LAUNCHER_NAME,
        "version": "1.0",
        "permissions": ["nativeMessaging", "transientBackground", "storage"],
        "natively_connectable": [HOST, HOST_GOOGLE],
        "background": {"service_worker": "worker.js"},
    }
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    with open(os.path.join(root, "worker.js"), "w", encoding="utf-8") as f:
        f.write(LAUNCHER_WORKER)
    with open(os.path.join(root, "state.html"), "w", encoding="utf-8") as f:
        f.write("<!doctype html><title>state</title>")
    return root


def connect_from_native(profile, ext_id, host):
    """What a native app does to start a host: runs the browser with the
    connect switches, which hands them to the browser already running on
    this profile (headless, with no window of its own, and gone at once)."""
    run = subprocess.run(
        [
            CHROME,
            "--headless=new",
            "--no-startup-window",
            "--user-data-dir=" + profile,
            "--profile-directory=Default",
            "--enable-features=OnConnectNative",
            "--native-messaging-connect-extension=" + ext_id,
            "--native-messaging-connect-host=" + host,
            "--native-messaging-connect-id=smoke1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=60,
    )
    return run.returncode


def host_starts(path):
    """The argument lists the host has been started with, in order."""
    try:
        with open(path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


def new_start(path, before, seconds=25):
    """The next start of the host after `before` earlier ones, or None."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        starts = host_starts(path)
        if len(starts) > before:
            return starts[before]
        time.sleep(0.4)
    return None


def connections(b, ext_id):
    """How many native connections the launcher add-on has been handed."""
    b.get("chrome-extension://%s/state.html" % ext_id)
    return b.run_async(
        "var done = arguments[arguments.length - 1];"
        "chrome.storage.local.get({connections: 0}, function(r) {"
        " done(r.connections); });"
    )


def wait_for(b, script, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if b.run(script):
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def addon_id(b, name=ADDON_NAME):
    b.get("chrome://extensions")
    for _ in range(40):
        try:
            ids = b.run_async(EXT_IDS)
            if name in ids:
                return ids[name]
        except Exception:
            pass
        time.sleep(0.5)
    return None


def call_host(b, ext_id, host):
    b.get("chrome-extension://%s/call.html" % ext_id)
    return b.run_async(CALL, [host])


def open_protection(b):
    b.get(URL)
    return wait_for(
        b, "return document.querySelectorAll('#connections-hosts .setting-row').length >= 2"
    )


def set_switch(b, host, on):
    """Click the row's switch and wait for the row to say it took."""
    b.run("document.getElementById('host-%s').click(); return 1" % host)
    state = "On." if on else "Blocked until you switch it on."
    return wait_for(
        b,
        "return document.getElementById('host-%s-state').innerText === %s"
        % (host, json.dumps(state)),
        8,
    )


def expect_blocked(failures, label, result):
    if result["reply"] is not None or BLOCKED not in (result["error"] or ""):
        failures.append("%s should be blocked: %r" % (label, result))


def expect_echo(failures, label, result):
    reply = result["reply"] or {}
    if result["error"] or (reply.get("echo") or {}).get("hello") != "world":
        failures.append("%s should echo: %r" % (label, result))


def main():
    failures = []
    os.makedirs(ROOT, exist_ok=True)
    work = tempfile.mkdtemp(prefix="run-", dir=ROOT)
    unregister()
    try:
        addon = write_addon(work)
        manifests, write_manifests, host_log = write_host_files(work)
        register(lambda name: manifests[name])
        args = ["--load-extension=" + addon]

        # 1. A new profile blocks every host until it is switched on.
        profile = os.path.join(work, "new")
        with NewProfileBrowser(user_data_dir=profile, args=args) as b:
            ext_id = addon_id(b)
            if not ext_id:
                failures.append("the test add-on did not load")
                return report(failures)
            write_manifests(ext_id)
            expect_blocked(failures, "new profile, host", call_host(b, ext_id, HOST))
            if not open_protection(b):
                failures.append("the host rows never appeared")
                return report(failures)
            seen = b.run(READ_HOSTS)
            print("new profile rows:", {k: v["text"].replace("\n", " / ") for k, v in seen["rows"].items()})
            row = seen["rows"].get("host-" + HOST)
            other = seen["rows"].get("host-" + HOST_GOOGLE)
            if not row or not other:
                failures.append("both test hosts should be listed (Chromium and Google\\Chrome keys)")
                return report(failures)
            for word in (HOST_DESCRIPTION, HOST, ADDON_NAME, "Blocked until you switch it on."):
                if word not in row["text"]:
                    failures.append("host row is missing %r: %r" % (word, row["text"]))
            if row["on"] or row["disabled"] or other["on"]:
                failures.append("a new profile should list hosts off and usable: %r" % seen["rows"])
            if "Apps on this computer" not in seen["text"] or "\u2014" in seen["text"]:
                failures.append("part heading missing or an em dash on the page")

            if not set_switch(b, HOST, True):
                failures.append("the host row did not read On after its switch")
            expect_echo(failures, "host switched on", call_host(b, ext_id, HOST))
            expect_blocked(failures, "second host, never switched", call_host(b, ext_id, HOST_GOOGLE))

            b.get(URL)
            wait_for(b, "return !!document.getElementById('host-%s')" % HOST)
            wait_for(b, "return document.getElementById('host-%s').checked" % HOST, 5)
            if not b.run("return document.getElementById('host-%s').checked" % HOST):
                failures.append("the switch did not stay on after the page was opened again")
            if not set_switch(b, HOST, False):
                failures.append("the host row did not read Blocked after its switch went off")
            expect_blocked(failures, "host switched off again", call_host(b, ext_id, HOST))

        # 2. A profile that existed before keeps the hosts registered now.
        profile = os.path.join(work, "old")
        os.makedirs(os.path.join(profile, "Default"))
        with open(os.path.join(profile, "Default", "Preferences"), "w", encoding="utf-8") as f:
            json.dump({}, f)
        with Browser(user_data_dir=profile, args=args) as b:
            ext_id = addon_id(b)
            if not ext_id:
                failures.append("the test add-on did not load in the old profile")
                return report(failures)
            expect_echo(failures, "updated profile, host", call_host(b, ext_id, HOST))
            if not open_protection(b):
                failures.append("the host rows never appeared in the old profile")
                return report(failures)
            seen = b.run(READ_HOSTS)
            for name in (HOST, HOST_GOOGLE):
                row = seen["rows"].get("host-" + name)
                if not row or not row["on"] or "On." not in row["text"]:
                    failures.append("updated profile should start with %s on: %r" % (name, row))

        # 3. A host started from the native side (ledger 62) obeys the same
        # switches. A native app starts the browser with the connect
        # switches. A host the person has not switched on is not connected:
        # the browser starts it only to tell it so (--extension-not-installed)
        # and the add-on is handed nothing. Switched on, the same call goes
        # through. The second half is what makes the first one mean anything,
        # since the browser reports that same error when the add-on is not
        # set up for the call.
        profile = os.path.join(work, "launch")
        launcher = write_launcher_addon(work)
        args = ["--load-extension=" + launcher, "--enable-features=OnConnectNative"]
        with NewProfileBrowser(user_data_dir=profile, args=args) as b:
            lid = addon_id(b, LAUNCHER_NAME)
            if not lid:
                failures.append("the launcher add-on did not load")
                return report(failures)
            write_manifests(lid)
            time.sleep(3)  # the add-on's worker has run and is listening
            seen = 0

            def from_native(label, host, goes_through):
                nonlocal seen
                code = connect_from_native(profile, lid, host)
                start = new_start(host_log, seen)
                print("native start, %s: exit %s, host args %s" % (label, code, start))
                if start is None:
                    failures.append("%s: the host was not started at all" % label)
                    return
                seen += 1
                error = NOT_INSTALLED in start
                if goes_through and error:
                    failures.append("%s should connect, got the error report: %s" % (label, start))
                if not goes_through and not error:
                    failures.append("%s should be refused, but the host was started to connect: %s" % (label, start))

            from_native("new profile, host not switched on", HOST, False)
            from_native("new profile, second host not switched on", HOST_GOOGLE, False)
            if not open_protection(b):
                failures.append("the host rows never appeared (native start)")
                return report(failures)
            if not set_switch(b, HOST, True):
                failures.append("the host row did not read On (native start)")
            from_native("host switched on", HOST, True)
            handed = connections(b, lid)
            if handed != 1:
                failures.append("the add-on should have been handed 1 connection, got %r" % handed)
            if not open_protection(b):
                failures.append("the host rows never appeared (native start, switch off)")
                return report(failures)
            if not set_switch(b, HOST, False):
                failures.append("the host row did not read Blocked (native start)")
            from_native("host switched off again", HOST, False)
            handed = connections(b, lid)
            if handed != 1:
                failures.append("a refused host should hand the add-on nothing, got %r connections" % handed)
    finally:
        unregister()
        shutil.rmtree(work, ignore_errors=True)
    return report(failures)


def report(failures):
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("ok: apps on this computer, blocked by default, switch on and off, kept on update")
    return 0


if __name__ == "__main__":
    sys.exit(main())
