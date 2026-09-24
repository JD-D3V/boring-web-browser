#!/usr/bin/env python3
"""Check "Turn off blocking on this site" in the built browser.

Everything is local. A small HTTP server on 127.0.0.1 plays three parts:
the site blocking is turned off for (http://127.0.0.1:PORT), a control
site that keeps blocking (http://localhost:PORT), and the ad and tracker
servers, whose real names are pointed at it with --host-resolver-rules.
So the filter lists see the real ad and tracker addresses and nothing
leaves the machine.

Turning a site off is written into the profile between runs, the way
smoke_popups.py sets its exception: the shield's menu is a native menu,
which WebDriver cannot open without synthetic input. The shield's state
is read from its accessible name through UI Automation, which only reads
our own window and sends no input. Checked:

  - on the site that is off, ad and tracker scripts load, an ad frame
    loads, and a third party frame on it can load an ad too
  - on the control site all of that is still blocked, including a frame
    from the site that is off, because the page in the tab decides
  - the shield says blocking is off on that site and on elsewhere
  - the Protection page lists the site, and its button takes it off the
    list, which brings blocking back without restarting the browser
"""

import ctypes
import json
import os
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from capture_native import frame_window
from drive import CHROME, Browser, free_port

AD_HOST = "pagead2.googlesyndication.com"
# Not google-analytics.com: Chromium's HSTS preload list forces that
# host to https, which the local server cannot answer, so its script
# fails whatever the ad blocker decides. scorecardresearch.com is on
# the bundled list (||scorecardresearch.com^$third-party) and not
# preloaded.
TRACKER_HOST = "sb.scorecardresearch.com"
OFF_SITE = "127.0.0.1"
CONTROL_SITE = "localhost"

PAGE = b"""<!doctype html>
<meta charset="utf-8">
<title>site test</title>
<h1>site test</h1>
"""

# Loaded inside a frame. Says it is there, then fetches whatever script
# address the page sends it and reports back.
FRAME = b"""<!doctype html>
<meta charset="utf-8">
<title>frame</title>
<script>
addEventListener('message', function(e) {
  var s = document.createElement('script');
  s.src = e.data + '?' + Math.random();
  s.onload = function() { parent.postMessage('loaded', '*'); };
  s.onerror = function() { parent.postMessage('blocked', '*'); };
  document.head.append(s);
});
parent.postMessage('ready', '*');
</script>
"""


class Handler(BaseHTTPRequestHandler):
    """Every .js is a small script, every .html a page or a frame."""

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.endswith(".js"):
            body, kind = b"/* test */", "text/javascript"
        elif path.endswith("frame.html"):
            body, kind = FRAME, "text/html; charset=utf-8"
        else:
            body, kind = PAGE, "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


# A script element, so the filter lists see a script request, the way
# ads and trackers really arrive. A blocked script fires onerror; the
# server answers every .js with a 200, so nothing else does.
LOAD_SCRIPT = """
var url = arguments[0];
var done = arguments[1];
var s = document.createElement('script');
s.src = url + '?' + Math.random();
s.onload = function() { done('loaded'); };
s.onerror = function() { done('blocked'); };
document.head.append(s);
"""

# A frame that says "ready" when its page arrived. A blocked frame gets
# an error page instead and never says it.
LOAD_FRAME = """
var src = arguments[0];
var done = arguments[1];
var f = document.createElement('iframe');
var timer = setTimeout(function() { f.remove(); done('blocked'); }, 8000);
addEventListener('message', function(e) {
  if (e.source !== f.contentWindow || e.data !== 'ready') return;
  clearTimeout(timer);
  f.remove();
  done('loaded');
});
f.src = src;
document.body.append(f);
"""

# A frame from another site that then loads a script itself.
SCRIPT_IN_FRAME = """
var src = arguments[0];
var script = arguments[1];
var done = arguments[2];
var f = document.createElement('iframe');
var timer = setTimeout(function() { f.remove(); done('timeout'); }, 15000);
addEventListener('message', function handler(e) {
  if (e.source !== f.contentWindow) return;
  if (e.data === 'ready') {
    f.contentWindow.postMessage(script, '*');
    return;
  }
  clearTimeout(timer);
  removeEventListener('message', handler);
  f.remove();
  done(e.data);
});
f.src = src;
document.body.append(f);
"""


def wait_for(b, condition, timeout_ms=8000):
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


# UI Automation, by hand through ctypes so nothing needs installing. It
# reads the accessible names of our own window's controls and does not
# move the mouse, press keys or look at the screen. Method numbers are
# vtable slots from UIAutomationClient.h in the Windows SDK.
ole32 = ctypes.WinDLL("ole32")
oleaut32 = ctypes.WinDLL("oleaut32")
oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, text):
        super().__init__()
        ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(self))


CLSID_CUIAutomation = "{ff48dba4-60ef-4201-aa87-54103eef594e}"
IID_IUIAutomation = "{30cbe57d-d9d0-452a-ab13-7ac5ac4825ee}"
TREE_SCOPE_DESCENDANTS = 4


def _call(obj, slot, *args):
    """Call method number `slot` on a COM pointer; raise on failure.

    Every argument here is a small int, a handle or an address, given as
    a Python int. Each fits a pointer sized argument on x64.
    """
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
    types = [ctypes.c_void_p] * (len(args) + 1)
    method = ctypes.WINFUNCTYPE(ctypes.HRESULT, *types)(vtable[0][slot])
    method(obj, *args)


def _release(obj):
    if obj:
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[0][2])(obj)


def control_names(hwnd):
    """The accessible name of every control in the window."""
    ole32.CoInitializeEx(None, 0x2)  # apartment threaded
    automation = ctypes.c_void_p()
    ole32.CoCreateInstance(
        ctypes.byref(GUID(CLSID_CUIAutomation)),
        None,
        0x1,  # in process server
        ctypes.byref(GUID(IID_IUIAutomation)),
        ctypes.byref(automation),
    )
    if not automation:
        raise RuntimeError("UI Automation is not available")
    window = ctypes.c_void_p()
    condition = ctypes.c_void_p()
    found = ctypes.c_void_p()
    names = []
    try:
        _call(automation, 6, hwnd, ctypes.addressof(window))
        _call(automation, 21, ctypes.addressof(condition))
        _call(
            window,
            6,
            TREE_SCOPE_DESCENDANTS,
            condition.value,
            ctypes.addressof(found),
        )
        count = ctypes.c_int()
        _call(found, 3, ctypes.addressof(count))
        for i in range(count.value):
            element = ctypes.c_void_p()
            _call(found, 4, i, ctypes.addressof(element))
            name = ctypes.c_void_p()
            try:
                _call(element, 23, ctypes.addressof(name))
                if name:
                    names.append(ctypes.wstring_at(name.value))
            except OSError:
                pass
            finally:
                if name:
                    oleaut32.SysFreeString(name)
                _release(element)
    finally:
        for obj in (found, condition, window, automation):
            _release(obj)
    return names


def shield_name(hwnd, want, timeout=10):
    """The shield's accessible name, once it contains `want`.

    Returns the last name seen when it never does, so a failure says
    what the shield said instead.
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        for name in control_names(hwnd):
            if name.startswith("Protection"):
                last = name
                if want in name:
                    return name
        time.sleep(0.5)
    return last


def preferences_path(profile):
    return os.path.join(profile, "Default", "Preferences")


def read_off_sites(profile):
    with open(preferences_path(profile), encoding="utf-8") as f:
        prefs = json.load(f)
    return prefs.get("boring", {}).get("blocking_off_sites", [])


def write_off_sites(profile, sites):
    path = preferences_path(profile)
    with open(path, encoding="utf-8") as f:
        prefs = json.load(f)
    prefs.setdefault("boring", {})["blocking_off_sites"] = sites
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def main():
    failures = []

    def check(name, ok, detail=""):
        print(
            f"{'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail else "")
        )
        if not ok:
            failures.append(name)

    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    off_page = f"http://{OFF_SITE}:{port}/page.html"
    control_page = f"http://{CONTROL_SITE}:{port}/page.html"
    ad_script = f"http://{AD_HOST}:{port}/pagead/js/adsbygoogle.js"
    tracker_script = f"http://{TRACKER_HOST}:{port}/beacon.js"
    ad_frame = f"http://{AD_HOST}:{port}/pagead/frame.html"
    args = [
        f"--host-resolver-rules=MAP {AD_HOST} 127.0.0.1, MAP {TRACKER_HOST} 127.0.0.1",
        "--window-size=1360,900",
    ]

    def run(b, script, arguments):
        return b.run_async(script, arguments)

    def wait_until_blocking(b):
        # The lists load in the background at startup.
        result = ""
        for _ in range(20):
            result = run(b, LOAD_SCRIPT, [ad_script])
            if result == "blocked":
                return True
            time.sleep(2)
        return False

    try:
        with tempfile.TemporaryDirectory(prefix="siteoff-") as profile:
            # A first run makes the profile, and shows the lists block
            # on both sites before anything is turned off.
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(off_page)
                check(
                    "ads blocked on the test site to begin with", wait_until_blocking(b)
                )

            if not os.path.exists(preferences_path(profile)):
                check("profile has a Preferences file", False)
                return 1
            write_off_sites(profile, [OFF_SITE])

            with Browser(user_data_dir=profile, args=args) as b:
                hwnd = frame_window(CHROME, under=b.proc.pid)

                b.get(control_page)
                check("lists loaded", wait_until_blocking(b))
                check(
                    "own scripts load on the control site",
                    run(b, LOAD_SCRIPT, [f"http://{CONTROL_SITE}:{port}/ok.js"])
                    == "loaded",
                )
                check(
                    "tracker blocked on the control site",
                    run(b, LOAD_SCRIPT, [tracker_script]) == "blocked",
                )
                check(
                    "ad frame blocked on the control site",
                    run(b, LOAD_FRAME, [ad_frame]) == "blocked",
                )
                framed = run(
                    b,
                    SCRIPT_IN_FRAME,
                    [f"http://{OFF_SITE}:{port}/frame.html", ad_script],
                )
                check(
                    "ad blocked in a frame from the off site on the control site",
                    framed == "blocked",
                    framed,
                )
                name = shield_name(hwnd, "Protection, on")
                check(
                    "shield says on for the control site",
                    name == "Protection, on",
                    name,
                )

                b.get(off_page)
                check(
                    "ad loads on the off site",
                    run(b, LOAD_SCRIPT, [ad_script]) == "loaded",
                )
                check(
                    "tracker loads on the off site",
                    run(b, LOAD_SCRIPT, [tracker_script]) == "loaded",
                )
                check(
                    "ad frame loads on the off site",
                    run(b, LOAD_FRAME, [ad_frame]) == "loaded",
                )
                framed = run(
                    b,
                    SCRIPT_IN_FRAME,
                    [f"http://{CONTROL_SITE}:{port}/frame.html", ad_script],
                )
                check(
                    "ad loads in a third party frame on the off site",
                    framed == "loaded",
                    framed,
                )
                want = f"Protection, blocking off for {OFF_SITE}"
                name = shield_name(hwnd, want)
                check("shield says blocking is off here", name == want, name)

                b.get("chrome://boring-protection")
                listed = wait_for(
                    b,
                    "document.getElementById('off-sites-state').textContent"
                    "==='1 site' && "
                    "[...document.querySelectorAll('#off-sites li span')]"
                    f".map(e=>e.textContent).join()==='{OFF_SITE}'",
                )
                check("Protection page lists the site", listed)
                label = b.run(
                    "var e=document.querySelector('#off-sites button');"
                    "return e ? e.getAttribute('aria-label') : ''"
                )
                check(
                    "its button names the site for screen readers",
                    label == f"Turn blocking back on for {OFF_SITE}",
                    label,
                )
                b.run("document.querySelector('#off-sites button').click()")
                check(
                    "the button takes the site off the list",
                    wait_for(
                        b,
                        "document.getElementById('off-sites-state').textContent"
                        "==='None' && "
                        "!document.querySelector('#off-sites li')",
                    ),
                )

                b.get(off_page)
                check(
                    "ads blocked again on the site after removal",
                    run(b, LOAD_SCRIPT, [ad_script]) == "blocked",
                )
                check(
                    "trackers blocked again on the site after removal",
                    run(b, LOAD_SCRIPT, [tracker_script]) == "blocked",
                )
                name = shield_name(hwnd, "Protection, on")
                check("shield says on again", name == "Protection, on", name)

            check("removal is saved in the profile", read_off_sites(profile) == [])
    finally:
        server.shutdown()

    print("\nNot checked here, needs a person: the shield's menu and the")
    print("reload it does, and tab-under blocking on a site that is off.")
    if failures:
        return 1
    print("PASS: blocking can be turned off per site and back on")
    return 0


if __name__ == "__main__":
    sys.exit(main())
