#!/usr/bin/env python3
r"""Check the generic readings of "Fingerprint noise" in the real build.

With the switch on (the default) every page reads the same core count,
touch points, WebGL graphics card name and one of a few common screen sizes:
  hardwareConcurrency  8, in a page and in a worker
  maxTouchPoints       0
  WebGL                UNMASKED_VENDOR "Google Inc.", UNMASKED_RENDERER
                       "ANGLE (generic)", for webgl and webgl2
  WebGPU               adapter info vendor and architecture are "" (skipped
                       when the run has no navigator.gpu or no adapter)
  screen               the smallest common size that holds the real screen;
                       availWidth/availHeight match width/height

What must not change: media queries and layout still use the real display
(device-width is the real one, a min-width query at the window width is exact),
and a video still plays and goes fullscreen at the real size.

With the switch off, the real values come back.

Test pages are served from a *.localhost name (HTTPS-Only is on, and
localhost names are the plain-http ones it leaves alone). The browser runs
headless; input goes through DevTools, never to the desktop.

Needs BORING_OUT, as the other smoke tests do.
"""

import functools
import http.server
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from drive import Browser, free_port

DATA = Path(__file__).resolve().parent / "testdata"
WORK = Path(os.environ.get("TMP", r"E:\tmp")) / "feat-fingerprint" / "smoke"

CORES = 8
TOUCH = 0
VENDOR = "Google Inc."
RENDERER = "ANGLE (generic)"
# Must match kUniformScreenSizes in patches/fingerprint-uniform.patch.
SIZES = [(1366, 768), (1536, 864), (1600, 900), (1920, 1080), (2560, 1440), (3840, 2160)]

PROBE = """
function gl(kind) {
  var g = document.createElement('canvas').getContext(kind);
  if (!g) return null;
  var e = g.getExtension('WEBGL_debug_renderer_info');
  if (!e) return {none: true};
  return {vendor: g.getParameter(e.UNMASKED_VENDOR_WEBGL),
          renderer: g.getParameter(e.UNMASKED_RENDERER_WEBGL)};
}
// The real display size, as a media query sees it.
function dim(prop) {
  var lo = 0, hi = 16384;
  while (lo < hi) {
    var m = (lo + hi + 1) >> 1;
    if (matchMedia('(min-device-' + prop + ':' + m + 'px)').matches) lo = m;
    else hi = m - 1;
  }
  return lo;
}
return {
  cores: navigator.hardwareConcurrency, touch: navigator.maxTouchPoints,
  gl1: gl('webgl'), gl2: gl('webgl2'),
  sw: screen.width, sh: screen.height, aw: screen.availWidth, ah: screen.availHeight,
  rw: dim('width'), rh: dim('height'),
  iw: innerWidth, ih: innerHeight, dpr: devicePixelRatio,
  exact: matchMedia('(min-width:' + innerWidth + 'px)').matches &&
         !matchMedia('(min-width:' + (innerWidth + 1) + 'px)').matches
};
"""

WORKER = """
var done = arguments[arguments.length - 1];
var w = new Worker(URL.createObjectURL(new Blob(
    ['postMessage(navigator.hardwareConcurrency)'], {type: 'text/javascript'})));
w.onmessage = function(e) { done(e.data); };
w.onerror = function() { done(-1); };
"""


# WebGPU adapter info: 'none' when there is no navigator.gpu or no adapter
# (a headless run may have neither); that case is skipped, not failed.
GPU = """
var done = arguments[arguments.length - 1];
if (!navigator.gpu) { done('none'); return; }
navigator.gpu.requestAdapter().then(function(a) {
  if (!a) { done('none'); return; }
  Promise.resolve(a.info).then(function(i) {
    done({vendor: i.vendor, architecture: i.architecture});
  });
}, function() { done('none'); });
"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):
        pass


def serve():
    handler = functools.partial(Handler, directory=str(DATA))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def wait(fn, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def cdp(b, cmd, params):
    return b._req(
        "POST", f"/session/{b.sid}/goog/cdp/execute", {"cmd": cmd, "params": params}
    )


def click_id(b, element):
    x, y = b.run(
        "var r = document.getElementById(arguments[0]).getBoundingClientRect();"
        "return [r.x + r.width / 2, r.y + r.height / 2]",
        [element],
    )
    for kind in ("mousePressed", "mouseReleased"):
        cdp(
            b,
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
        )


def expected_screen(rw, rh):
    """What the patch should report for a real screen of rw x rh."""
    for w, h in SIZES:
        if w >= rw and h >= rh:
            return w, h
    return rw, rh


class Session:
    def __init__(self, name, port, noise=True):
        self.base = f"http://fp.localhost:{port}"
        root = WORK / name
        shutil.rmtree(root, ignore_errors=True)
        profile = root / "profile"
        (profile / "Default").mkdir(parents=True)
        if not noise:
            (profile / "Default" / "Preferences").write_text(
                json.dumps({"boring": {"fingerprint_noise": False}})
            )
        # SwiftShader gives the headless browser a WebGL context to read.
        self.b = Browser(
            user_data_dir=str(profile),
            args=["--headless=new", "--enable-unsafe-swiftshader"],
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.b.quit()

    def probe(self):
        self.b.get(f"{self.base}/fingerprint.html")
        wait(lambda: self.b.run("return window.ready"))
        return self.b.run(PROBE)


def generic_checks(s, checks):
    p = s.probe()
    print("generic:", json.dumps(p))
    checks["core count is 8"] = p["cores"] == CORES
    checks["core count is 8 in a worker"] = s.b.run_async(WORKER) == CORES
    checks["no touch points"] = p["touch"] == TOUCH
    for key, label in (("gl1", "webgl"), ("gl2", "webgl2")):
        g = p[key]
        checks[f"{label}: vendor is generic"] = bool(g) and g.get("vendor") == VENDOR
        checks[f"{label}: renderer is generic"] = bool(g) and g.get("renderer") == RENDERER
    gpu = s.b.run_async(GPU)
    print("webgpu:", json.dumps(gpu))
    if gpu != "none":
        checks["webgpu: vendor and architecture are blank"] = gpu == {
            "vendor": "",
            "architecture": "",
        }
    want = expected_screen(p["rw"], p["rh"])
    checks[f"screen is {want[0]}x{want[1]} for a real {p['rw']}x{p['rh']}"] = (
        (p["sw"], p["sh"]) == want
    )
    checks["available screen matches"] = (p["aw"], p["ah"]) == (p["sw"], p["sh"])
    # Layout and media queries are the real ones: the window is not wider
    # than the real display, and a width query at the window width is exact.
    checks["window fits the real display"] = p["iw"] <= p["rw"]
    checks["width media query is exact"] = p["exact"]


def video_checks(s, checks):
    b = s.b
    b.get(f"{s.base}/fingerprint.html")
    checks["video ready"] = wait(lambda: b.run("return window.ready"))
    real = b.run(PROBE)["rw"]
    click_id(b, "fs")
    checks["video goes fullscreen"] = wait(
        lambda: b.run("return !!document.fullscreenElement")
    )
    time.sleep(0.5)
    state = b.run(
        "var v = document.getElementById('v'); var t = v.currentTime;"
        "return {t: t, w: v.clientWidth, iw: innerWidth, paused: v.paused,"
        "        exact: matchMedia('(min-width:' + innerWidth + 'px)').matches &&"
        "               !matchMedia('(min-width:' + (innerWidth + 1) + 'px)').matches}"
    )
    time.sleep(0.6)
    later = b.run("return document.getElementById('v').currentTime")
    print("fullscreen:", json.dumps(state), "later", later, "real", real)
    checks["fullscreen video keeps playing"] = not state["paused"] and later != state["t"]
    checks["fullscreen video fills the real window"] = state["w"] == state["iw"]
    checks["fullscreen window is not larger than the real display"] = state["iw"] <= real
    checks["fullscreen width media query is exact"] = state["exact"]
    b.run("document.exitFullscreen()")
    checks["video leaves fullscreen"] = wait(
        lambda: not b.run("return !!document.fullscreenElement")
    )


def real_checks(s, checks):
    p = s.probe()
    print("real:", json.dumps(p))
    checks["off: core count is the real one"] = p["cores"] == os.cpu_count()
    for key, label in (("gl1", "webgl"), ("gl2", "webgl2")):
        g = p[key]
        checks[f"off: {label} renderer is the real one"] = (
            bool(g) and g.get("renderer") not in (None, RENDERER)
        )
    checks["off: screen is the real one"] = (p["sw"], p["sh"]) == (p["rw"], p["rh"])


def main():
    checks = {}
    srv = serve()
    port = srv.server_address[1]
    try:
        with Session("on", port) as s:
            generic_checks(s, checks)
            video_checks(s, checks)
        with Session("off", port, noise=False) as s:
            real_checks(s, checks)
    finally:
        srv.shutdown()

    ok = all(checks.values())
    for name, passed in checks.items():
        print(("PASS " if passed else "FAIL ") + name)
    print("smoke_fingerprint:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
