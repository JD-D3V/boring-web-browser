#!/usr/bin/env python3
r"""Does "Fingerprint noise" make challenge pages loop? Measure it.

Visits public pages that show a bot challenge or a bot verdict, each in a
fresh temporary profile (made for the visit, deleted after it), once per
arm:

  on        the default: boring.fingerprint_noise on
  off       the same build with the switch off (the baseline: plain Chromium)
  on-realgl switch on, but WebGL reports one ordinary Chrome card name
            (ungoogled's SpoofWebGLInfo feature wins over ours), to test
            the WebGL-name theory on a build without the fix
  only-canvas, only-text, only-rects
            switch off, one of its three renderer switches passed by hand,
            to find which part of the protection a check reacts to

and records per visit: was a challenge shown, did it clear by itself, did
it come back (a loop) or stay, the page's own verdict where it shows one,
a local consistency probe, and a picture of our own window.

Modes:
  headless  chromedriver, headless (default). Public pages load without
            software GL (--enable-unsafe-swiftshader widens the GPU process
            attack surface), so WebGL may be missing on them; only the
            local probe on about:blank gets SwiftShader. Use window mode
            for pages that need WebGL.
  window    chromedriver with a real window. Needs BORING_ALLOW_HEADFUL=1.
  plain     chrome.exe started directly, no chromedriver and no automation
            switches, the way a person starts it. Reads only the window
            title (Win32) and a PrintWindow picture; no page script runs.
            Needs BORING_ALLOW_HEADFUL=1. This is the mode that answers
            "does a person get a loop".

Rules this keeps: it only navigates and reads. It never clicks, types
into, or solves a captcha, never submits a form, and sends no input to the
desktop. Pictures are PrintWindow of our own window or WebDriver page
shots, never screen grabs. Every browser is quit in a finally block.
Pages in the "ordinary" group are skipped when their robots.txt disallows
the path, and also when it cannot be read: only a 200 answer or a 404/410
(no robots.txt) lets a visit go ahead. A 403, a 5xx or a timeout skips the
page; the reason goes to skips.jsonl under --out.

    python challenge_check.py --chrome E:\ung-157\build\src\out\Default\chrome.exe
    set BORING_ALLOW_HEADFUL=1
    python challenge_check.py --chrome ... --mode plain --reps 5 --groups challenge,ordinary

Writes visits.jsonl, skips.jsonl, summary.json and pictures under --out.
"""

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from pathlib import Path

# The WebGL name the on-realgl arm reports, and the fix in
# fingerprint-uniform.patch reports. Turnstile passed with it in
# ungoogled-chromium issue 3226.
REAL_GL_VENDOR = "Google Inc. (Intel)"
REAL_GL_RENDERER = (
    "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (0x00009A49) "
    "Direct3D11 vs_5_0 ps_5_0, D3D11)"
)

ARMS = ("on", "off", "on-realgl", "only-canvas", "only-text", "only-rects")

# Isolation arms: the pref is off and one of the three switches the pref
# would add is passed by hand (bromite hands them on to the renderers).
# only-rects also brings every uniform value of fingerprint-uniform.patch
# (cores, touch, screen, WebGL, WebGPU), which key off that switch.
ONE_SWITCH = {
    "only-canvas": "--fingerprinting-canvas-image-data-noise",
    "only-text": "--fingerprinting-canvas-measuretext-noise",
    "only-rects": "--fingerprinting-client-rects-noise",
}

# group: challenge  a Cloudflare interstitial or widget we wait on
#        detector   a page that prints a bot or consistency verdict
#        ordinary   an everyday site behind Cloudflare (robots.txt checked)
PAGES = [
    {"name": "turnstile-demo", "group": "challenge", "kind": "widget",
     "url": "https://demo.turnstile.workers.dev/"},
    {"name": "nowsecure", "group": "challenge", "kind": "interstitial",
     "url": "https://nowsecure.nl/"},
    {"name": "recaptcha-v3", "group": "detector", "kind": "recaptcha",
     "url": "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php"},
    {"name": "hcaptcha-demo", "group": "challenge", "kind": "widget-hcaptcha",
     "url": "https://accounts.hcaptcha.com/demo"},
    {"name": "creepjs", "group": "detector", "kind": "creepjs",
     "url": "https://abrahamjuliot.github.io/creepjs/"},
    {"name": "sannysoft", "group": "detector", "kind": "sannysoft",
     "url": "https://bot.sannysoft.com/"},
    {"name": "botd", "group": "detector", "kind": "botd",
     "url": "https://fingerprintjs.github.io/BotD/main/"},
    {"name": "browserleaks-webgl", "group": "detector", "kind": "browserleaks",
     "url": "https://browserleaks.com/webgl"},
    {"name": "browserleaks-canvas", "group": "detector", "kind": "browserleaks",
     "url": "https://browserleaks.com/canvas"},
    {"name": "cloudflare-home", "group": "ordinary", "kind": "interstitial",
     "url": "https://www.cloudflare.com/"},
    {"name": "discord", "group": "ordinary", "kind": "interstitial",
     "url": "https://discord.com/"},
    {"name": "g2", "group": "ordinary", "kind": "interstitial",
     "url": "https://www.g2.com/"},
    {"name": "indeed", "group": "ordinary", "kind": "interstitial",
     "url": "https://www.indeed.com/"},
    {"name": "crunchbase", "group": "ordinary", "kind": "interstitial",
     "url": "https://www.crunchbase.com/"},
]

# Titles Cloudflare's interstitial uses (English profile).
CHALLENGE_TITLES = ("just a moment", "attention required", "one more step",
                    "verify you are human", "checking your browser")

FAILED = ("looped", "stuck", "unsolved")


# ---- pure parts (tested in tests/test_challenge_check.py) ----

def profile_prefs(arm):
    """The Preferences a fresh profile starts with for this arm, or None."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}")
    if arm == "off" or arm in ONE_SWITCH:
        return {"boring": {"fingerprint_noise": False}}
    return None


def spoof_feature(vendor, renderer):
    """--enable-features value for ungoogled's SpoofWebGLInfo.

    Commas end a feature in --enable-features and slashes split the
    params, so every value is percent-escaped; Chromium unescapes them.
    """
    q = lambda v: urllib.parse.quote(v, safe="")
    return f"SpoofWebGLInfo:vendor/{q(vendor)}/renderer/{q(renderer)}"


def arm_switches(arm):
    if arm == "on-realgl":
        return ["--enable-features=" + spoof_feature(REAL_GL_VENDOR, REAL_GL_RENDERER)]
    if arm in ONE_SWITCH:
        return [ONE_SWITCH[arm]]
    return []


def is_challenge(sample):
    title = (sample.get("title") or "").lower()
    url = sample.get("url") or ""
    return (bool(sample.get("cf"))
            or "__cf_chl" in url
            or any(t in title for t in CHALLENGE_TITLES))


def classify(samples, kind="interstitial"):
    """Outcome of one visit from its timeline of samples.

    widget kinds: solved (a token appeared) or unsolved.
    interstitial: none (never challenged), passed (challenged once, then
    the site), looped (challenged, cleared, challenged again, or the
    challenge page reloaded itself three or more times), stuck
    (challenged until the end, without visible reloads).
    """
    # A read that failed mid-navigation says nothing either way.
    samples = [s for s in samples if "error" not in s]
    if not samples:
        return "no-data"
    if kind.startswith("widget"):
        return "solved" if any(s.get("token") for s in samples) else "unsolved"
    flags = [is_challenge(s) for s in samples]
    if not any(flags):
        return "none"
    episodes = sum(1 for i, f in enumerate(flags) if f and (i == 0 or not flags[i - 1]))
    loads = {s.get("origin") for s, f in zip(samples, flags) if f and s.get("origin")}
    if episodes >= 2 or len(loads) >= 3:
        return "looped"
    return "stuck" if flags[-1] else "passed"


def _num(pattern, text, cast=float):
    m = re.search(pattern, text or "", re.I)
    return cast(m.group(1)) if m else None


def parse_verdict(kind, text, counts=None):
    """The detector's own verdict from the page text (best effort).

    Each value is None when the page did not show it; the raw text is
    kept beside it in visits.jsonl, so a changed page is visible.
    """
    text = text or ""
    if kind == "creepjs":
        return {
            "like_headless_pct": _num(r"(\d+(?:\.\d+)?)%\s+like headless", text),
            "headless_pct": _num(r"(\d+(?:\.\d+)?)%\s+headless", text),
            "stealth_pct": _num(r"(\d+(?:\.\d+)?)%\s+stealth", text),
            "lies": _num(r"lies\s*\((\d+)\)", text, int),
        }
    if kind == "recaptcha":
        return {"score": _num(r'"score"\s*:\s*([0-9.]+)', text)}
    if kind == "botd":
        m = re.search(r'"bot"\s*:\s*(true|false)', text, re.I)
        bot = None if not m else m.group(1).lower() == "true"
        if bot is None and re.search(r"\bnot a bot\b", text, re.I):
            bot = False
        elif bot is None and re.search(r"\byou are a bot\b|\bbot detected\b", text, re.I):
            bot = True
        return {"bot": bot}
    if kind == "sannysoft":
        counts = counts or {}
        return {"failed": counts.get("failed"), "passed": counts.get("passed")}
    if kind == "browserleaks":
        m = re.search(r"Unmasked Renderer\s*[:\t ]*([^\n]+)", text)
        u = re.search(r"Uniqueness\s*[:\t ]*([^\n]+)", text)
        return {"renderer": m.group(1).strip() if m else None,
                "uniqueness": u.group(1).strip() if u else None}
    return {}


def robots_allows(robots_txt, url, agent="*"):
    rp = urllib.robotparser.RobotFileParser()
    rp.parse((robots_txt or "").splitlines())
    return rp.can_fetch(agent, url)


def arm_order(rep, arms):
    """Alternate which arm goes first, so drift over a run hits both."""
    arms = list(arms)
    return arms if rep % 2 == 0 else arms[::-1]


def compare(on, off):
    """Verdict for one page from the outcomes of two arms."""
    f_on = sum(o in FAILED for o in on)
    f_off = sum(o in FAILED for o in off)
    if not on or not off:
        return "not run"
    if f_off * 2 > len(off):
        return "plain Chromium fails too"
    if f_on * 2 > len(on) and f_on - f_off >= 2:
        return "noise causes it"
    if f_on == 0 and f_off == 0:
        return "no trouble"
    return "inconclusive"


def summarize(visits):
    by_page = {}
    for v in visits:
        page = by_page.setdefault(v["page"], {})
        page.setdefault(v["arm"], []).append(v)
    out = {}
    for name, arms in sorted(by_page.items()):
        row = {a: [v["outcome"] for v in vs] for a, vs in arms.items()}
        entry = {"outcomes": row}
        if "on" in row and "off" in row:
            entry["on_vs_off"] = compare(row["on"], row["off"])
        if "on-realgl" in row and "off" in row:
            entry["realgl_vs_off"] = compare(row["on-realgl"], row["off"])
        scores = {}
        for a, vs in arms.items():
            for key in ("score", "like_headless_pct", "lies", "failed"):
                vals = [v["verdict"].get(key) for v in vs
                        if isinstance(v.get("verdict", {}).get(key), (int, float))]
                if vals:
                    scores.setdefault(a, {})[key] = statistics.median(vals)
        if scores:
            entry["median_verdicts"] = scores
        out[name] = entry
    return out


# ---- browser parts ----

# One sample of the page, read through WebDriver. No input, no clicks.
SAMPLE_JS = r"""
var tok = document.querySelector('[name="cf-turnstile-response"],[name="h-captcha-response"]');
return {title: document.title, url: location.href,
        origin: String(performance.timeOrigin),
        cf: !!(window._cf_chl_opt || document.getElementById('challenge-form')
               || document.querySelector('#challenge-running,#cf-challenge-running')),
        token: !!(tok && tok.value)};
"""

VERDICT_JS = r"""
return {text: (document.body ? document.body.innerText : '').slice(0, 20000),
        counts: {failed: document.querySelectorAll('td.failed').length,
                 passed: document.querySelectorAll('td.passed').length}};
"""

# The inconsistencies a detector can see, checked locally on about:blank.
PROBE_JS = r"""
var r = {};
function draw(c) { var x = c.getContext('2d'); x.font = '16px Arial';
  x.fillStyle = '#f60'; x.fillRect(5, 5, 90, 30); x.fillStyle = '#069';
  x.fillText('Boring check 1.0 <canvas>', 4, 40); return c; }
var c = draw(Object.assign(document.createElement('canvas'), {width: 220, height: 60}));
r.canvas_repeat_differs = c.toDataURL() !== c.toDataURL();
var blank = Object.assign(document.createElement('canvas'), {width: 16, height: 16});
r.blank_canvas_modified = Math.max.apply(null,
    blank.getContext('2d').getImageData(0, 0, 16, 16).data) > 0;
var m = c.getContext('2d').measureText('');
r.measuretext_not_integer = [m.fontBoundingBoxAscent, m.fontBoundingBoxDescent]
    .some(function (v) { return v !== Math.round(v); });
var d = document.createElement('div');
d.style.cssText = 'position:absolute;left:0;top:0;width:100px;height:50px';
document.body.appendChild(d);
var b = d.getBoundingClientRect();
r.rect_vs_offset_differs = b.width !== d.offsetWidth || b.height !== d.offsetHeight;
var f = document.createElement('iframe'); document.body.appendChild(f);
var d2 = f.contentDocument.createElement('div');
d2.style.cssText = d.style.cssText; f.contentDocument.body.appendChild(d2);
r.iframe_rect_differs = d2.getBoundingClientRect().width !== b.width;
r.screen = [screen.width, screen.height, screen.availWidth, screen.availHeight];
r.window = [outerWidth, outerHeight, innerWidth, innerHeight, devicePixelRatio];
r.screen_vs_media_differs = !matchMedia('(device-width: ' + screen.width +
    'px) and (device-height: ' + screen.height + 'px)').matches;
r.avail_equals_full = screen.availWidth === screen.width &&
    screen.availHeight === screen.height;
r.cores = navigator.hardwareConcurrency; r.touch = navigator.maxTouchPoints;
r.touch_mismatch = navigator.maxTouchPoints === 0 &&
    (matchMedia('(any-pointer: coarse)').matches || 'ontouchstart' in window);
var g = document.createElement('canvas').getContext('webgl');
var e = g && g.getExtension('WEBGL_debug_renderer_info');
r.gl_vendor = e ? g.getParameter(e.UNMASKED_VENDOR_WEBGL) : null;
r.gl_renderer = e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : null;
r.gl_renderer_chrome_shape = !!(r.gl_renderer &&
    /^ANGLE \([^,]+, .+, [^,]+\)$/.test(r.gl_renderer));
r.webdriver = navigator.webdriver;
return r;
"""


def _new_profile(arm):
    """A new, empty profile folder for one visit. mkdtemp never hands out
    a folder that exists, so no earlier visit's cookies or storage (such as
    cf_clearance) can be in it, whatever --out already holds. The caller
    deletes it with _drop_profile."""
    profile = Path(tempfile.mkdtemp(prefix="cc-profile-"))
    (profile / "Default").mkdir()
    prefs = profile_prefs(arm)
    if prefs is not None:
        (profile / "Default" / "Preferences").write_text(json.dumps(prefs))
    return profile


def _drop_profile(profile):
    shutil.rmtree(profile, ignore_errors=True)
    if profile.exists():  # a process may still hold a file for a moment
        time.sleep(2)
        shutil.rmtree(profile, ignore_errors=True)


def robots_decision(url, fetch=urllib.request.urlopen):
    """(visit, why): fails closed. Only a robots.txt that answers 200 and
    allows the path, or answers 404 or 410 (there is none), lets a visit
    go ahead. A 403 (Cloudflare often refuses a script), a 5xx, a timeout
    or any other error means the rules could not be read, so skip."""
    parts = urllib.parse.urlsplit(url)
    robots = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        req = urllib.request.Request(robots, headers={"User-Agent": "challenge-check"})
        with fetch(req, timeout=15) as resp:
            if resp.status != 200:
                return False, f"robots.txt answered {resp.status}"
            if robots_allows(resp.read().decode("utf-8", "replace"), url):
                return True, "robots.txt allows it"
            return False, "robots.txt disallows it"
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            return True, f"no robots.txt ({exc.code})"
        return False, f"robots.txt answered {exc.code}"
    except Exception as exc:
        return False, f"robots.txt could not be read ({type(exc).__name__})"


def run_probe(arm, headful):
    """The local consistency probe, on about:blank in a browser of its own.
    This is the only launch that gets --enable-unsafe-swiftshader (headless
    has no WebGL without it, and the probe reads WebGL names): software GL
    widens the GPU process attack surface, and no public page is loaded
    here, so nothing from the web can reach it."""
    from drive import Browser  # BORING_OUT is set by main before this import
    args = arm_switches(arm)
    if not headful:
        args.append("--enable-unsafe-swiftshader")
    profile = _new_profile(arm)
    try:
        b = Browser(user_data_dir=str(profile), args=args, headful=headful)
        try:
            b.get("about:blank")
            return b.run(PROBE_JS)
        finally:
            b.quit()
    finally:
        _drop_profile(profile)


def visit_webdriver(page, arm, root, chrome, seconds, headful, probe):
    from drive import Browser  # BORING_OUT is set by main before this import
    args = arm_switches(arm)  # no SwiftShader: public pages load here
    result = {"samples": []}
    if probe:
        result["probe"] = run_probe(arm, headful)
    profile = _new_profile(arm)
    try:
        b = Browser(user_data_dir=str(profile), args=args, headful=headful)
    except BaseException:
        _drop_profile(profile)
        raise
    try:
        b.get(page["url"])
        end = time.time() + seconds
        while time.time() < end:
            try:
                s = b.run(SAMPLE_JS)
                s["t"] = round(seconds - (end - time.time()), 1)
                result["samples"].append(s)
            except Exception as exc:  # navigation in progress
                result["samples"].append({"t": None, "error": str(exc)[:200]})
            time.sleep(1.0)
        try:
            v = b.run(VERDICT_JS)
            result["text"] = v["text"]
            result["counts"] = v["counts"]
        except Exception as exc:
            result["text"], result["counts"] = "", {}
            result["verdict_error"] = str(exc)[:200]
        pic = root / "window.png"
        if headful:
            from capture_native import frame_window, grab
            grab(frame_window(chrome, under=b.proc.pid), str(pic))
        else:
            b.screenshot(str(pic))
        result["picture"] = str(pic)
    finally:
        b.quit()
        _drop_profile(profile)
    return result


def visit_plain(page, arm, root, chrome, seconds):
    """chrome.exe as a person starts it; only the window title is read."""
    from drive import OFFSCREEN, require_headful
    from capture_native import grab, user32, windows_of
    import ctypes
    require_headful()
    profile = _new_profile(arm)
    cmd = [chrome, "--user-data-dir=" + str(profile), "--no-first-run",
           "--disable-fre", "--disable-backgrounding-occluded-windows",
           "--disable-features=CalculateNativeWinOcclusion",
           "--window-position=" + os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN),
           *arm_switches(arm), page["url"]]
    try:
        proc = subprocess.Popen(cmd)
    except BaseException:
        _drop_profile(profile)
        raise
    result = {"samples": []}
    try:
        end = time.time() + seconds
        hwnd = None
        while time.time() < end:
            if hwnd is None:
                found = windows_of({proc.pid})
                hwnd = found[0] if found else None
            if hwnd:
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                result["samples"].append(
                    {"t": round(seconds - (end - time.time()), 1), "title": buf.value})
            time.sleep(1.0)
        if hwnd:
            pic = root / "window.png"
            grab(hwnd, str(pic))
            result["picture"] = str(pic)
    finally:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        _drop_profile(profile)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chrome", required=True, help="path to the built chrome.exe")
    ap.add_argument("--mode", choices=("headless", "window", "plain"), default="headless")
    ap.add_argument("--arms", default="on,off")
    ap.add_argument("--groups", default="challenge,detector")
    ap.add_argument("--pages", default="", help="comma list of page names (default: all in groups)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--seconds", type=int, default=30, help="time watched per visit")
    ap.add_argument("--gap", type=float, default=5.0, help="pause between visits")
    ap.add_argument("--out", default=os.path.join(os.environ.get("TMP", r"E:\tmp"),
                                                   "challenge-check", time.strftime("%Y%m%d-%H%M%S")))
    a = ap.parse_args(argv)

    chrome = os.path.abspath(a.chrome)
    if not os.path.isfile(chrome):
        sys.exit(f"no chrome.exe at {chrome}")
    os.environ["BORING_OUT"] = os.path.dirname(chrome)
    headful = a.mode in ("window", "plain")
    if headful and os.environ.get("BORING_ALLOW_HEADFUL") != "1":
        sys.exit("window and plain modes open real windows: set BORING_ALLOW_HEADFUL=1")
    arms = [x for x in a.arms.split(",") if x]
    for arm in arms:
        profile_prefs(arm)  # rejects unknown arms before anything starts
    groups = set(a.groups.split(","))
    names = set(filter(None, a.pages.split(",")))
    pages = [p for p in PAGES if p["group"] in groups and (not names or p["name"] in names)]
    if a.mode == "plain":
        # Without page script only the title can be read: widgets and
        # detectors say nothing there, interstitials do.
        pages = [p for p in pages if p["kind"] == "interstitial"]

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    visits = []
    log = out / "visits.jsonl"
    for rep in range(a.reps):
        for page in pages:
            if page["group"] == "ordinary":
                go, why = robots_decision(page["url"])
                if not go:
                    print(f"skip {page['name']}: {why}")
                    with (out / "skips.jsonl").open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({"rep": rep, "page": page["name"],
                                             "why": why}) + "\n")
                    continue
            for i, arm in enumerate(arm_order(rep, arms)):
                root = out / f"r{rep}" / page["name"] / arm
                root.mkdir(parents=True, exist_ok=True)
                started = time.time()
                try:
                    if a.mode == "plain":
                        r = visit_plain(page, arm, root, chrome, a.seconds)
                    else:
                        r = visit_webdriver(page, arm, root, chrome, a.seconds,
                                            headful, probe=(page is pages[0]))
                    outcome = classify(r["samples"], page["kind"])
                except Exception as exc:
                    r, outcome = {"error": str(exc)[:500], "samples": []}, "error"
                v = {"rep": rep, "page": page["name"], "arm": arm, "mode": a.mode,
                     "outcome": outcome, "seconds": round(time.time() - started, 1),
                     "verdict": parse_verdict(page["kind"], r.get("text"), r.get("counts")),
                     **r}
                visits.append(v)
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(v) + "\n")
                print(f"rep {rep} {page['name']:<20} {arm:<10} {outcome:<9} {v['verdict']}")
                time.sleep(a.gap)
    summary = summarize(visits)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    for name, entry in summary.items():
        print(f"{name:<20} on/off: {entry.get('on_vs_off', '-'):<26} "
              f"realgl/off: {entry.get('realgl_vs_off', '-')}")
    print("written:", out)


if __name__ == "__main__":
    main()
