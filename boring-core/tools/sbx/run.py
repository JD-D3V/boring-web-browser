"""Clean-machine test: Release 2 installed, updated to Release 3 through the
real update path, run inside Windows Sandbox.

Writes one PASS/FAIL/INFO line per check to C:\\out\\results.txt and detail
to C:\\out\\run.log. Everything happens inside the Sandbox VM.

Derived from E:\\tmp\\sbx\\in\\run.py (the Release 1 to 2 run of 2026-09-28)
with these changes for 154 -> 157:
  1  go.cmd sets BORING_ALLOW_HEADFUL=1 (inside the Sandbox only)
  2  A is the Release 2 installer (154.0.8037.57.1)
  3  two chromedrivers: A's (154) until the update, B's (157) after
  4  "no Chromium in the uninstall entry" is INFO for A, a check for the
     updated entry
  5  the smokes run AFTER the update, on the updated copy only (this
     repo's smokes are 157's and do not describe an R2 browser)
  6  --real-version 157.0.8103.38.1 and --installed-release 1
  7  the old profile C:\\p1 (made by A) is reopened by B and must keep its
     settings and open a tab
  8  the version B reports is read from DevTools, not guessed

Kept in boring-core/tools/sbx since Release 4 (copied from
E:\\tmp\\sbx-r3\\in\\run.py on 2026-11-11). The one change is the two
login stages of login_stages.py (ledger item 4): a person signed in
under A is still signed in under B. For the Release 3 to 4 run, A, B,
their versions, the dll hashes and the two chromedrivers are set the way
the Release 3 runbook sets them; the stages need nothing else.
"""

import glob
import hashlib
import json
import os
import platform
import runpy
import shutil
import subprocess
import sys
import time
import traceback
import urllib.request
import winreg
from pathlib import Path

IN = Path(r"C:\in")
OUT = Path(r"C:\out")
BC = Path(r"C:\bc")
TOOLS = BC / "tools"
# login_site.py and sbx/login_stages.py come from the staged boring-core.
sys.path[:0] = [str(TOOLS), str(TOOLS / "sbx")]
import login_stages  # noqa: E402
A = IN / "A" / "BoringBrowser_154.0.8037.57.1_installer_x64.exe"
B = IN / "B" / "mini_installer_B.exe"
DRIVER_A = IN / "chromedriver_A.exe"
DRIVER_B = IN / "chromedriver.exe"
DRIVER = DRIVER_A  # switched to B's after the update
B_DLL_SHA = (IN / "B" / "chrome_dll.sha256").read_text().split()[0].lower()
A_DLL_SHA = (IN / "A" / "chrome_dll.sha256").read_text().split()[0].lower()
A_VERSION = "154.0.8037.57"
B_VERSION = "157.0.8103.38"
B_FEED_VERSION = B_VERSION + ".1"
LOCAL = Path(os.environ["LOCALAPPDATA"])
APPDIR = LOCAL / "BoringBrowser" / "Application"
CHROME = APPDIR / "chrome.exe"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"

sys.path.insert(0, str(TOOLS))
results = []
log_f = open(OUT / "run.log", "a", encoding="utf-8")


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    log_f.write(s + "\n")
    log_f.flush()


def result(word, name, detail=""):
    line = f"{word}: {name}" + (f" ({detail})" if detail else "")
    results.append(line)
    log(line)
    with open(OUT / "results.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def check(name, ok, detail=""):
    result("PASS" if ok else "FAIL", name, detail)
    return ok


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def http(url, method="GET", body=None, timeout=30):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw) if raw.strip() else None


def wait_for(cond, timeout, step=0.5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(step)
    return False


def uninstall_entries():
    found = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            root = winreg.OpenKey(hive, UNINSTALL)
        except OSError:
            continue
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            with winreg.OpenKey(root, sub) as k:
                vals = {}
                j = 0
                while True:
                    try:
                        n, v, _ = winreg.EnumValue(k, j)
                    except OSError:
                        break
                    vals[n] = v
                    j += 1
            name = str(vals.get("DisplayName", ""))
            if "boring" in name.lower() or "chromium" in name.lower() or "boring" in sub.lower():
                found.append((sub, vals))
    return found


def shortcuts():
    pats = [
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\**\*.lnk"),
        os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\**\*.lnk"),
        os.path.expandvars(r"%USERPROFILE%\Desktop\*.lnk"),
        os.path.expandvars(r"%PUBLIC%\Desktop\*.lnk"),
    ]
    out = []
    for p in pats:
        out += glob.glob(p, recursive=True)
    return [s for s in out if "boring" in s.lower() or "chromium" in s.lower()]


class Chrome:
    """The installed browser, started directly, with a DevTools port."""

    def __init__(self, profile, extra=(), port=9333):
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        args = [str(CHROME), f"--user-data-dir={profile}",
                f"--remote-debugging-port={port}"] + list(extra)
        log("launch:", " ".join(args))
        self.proc = subprocess.Popen(args)
        if not wait_for(lambda: http(self.base + "/json/version", timeout=3), 60):
            raise RuntimeError("DevTools port never answered")
        self.drv = None

    def version(self):
        """What the running browser says it is, e.g. Chrome/157.0.8103.38."""
        return http(self.base + "/json/version", timeout=10).get("Browser", "")

    def tabs(self):
        return [t for t in http(self.base + "/json/list") if t.get("type") == "page"]

    def attach(self):
        """chromedriver attached to the running browser; adds no switches.
        Uses the driver for the version that is installed right now."""
        port = 9515
        self.drv = subprocess.Popen([str(DRIVER), f"--port={port}"],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wd = f"http://127.0.0.1:{port}"
        wait_for(lambda: http(self.wd + "/status", timeout=3), 20)
        caps = {"capabilities": {"alwaysMatch": {"goog:chromeOptions": {
            "debuggerAddress": f"127.0.0.1:{self.port}"}}}}
        self.sid = http(self.wd + "/session", "POST", caps)["value"]["sessionId"]

    def get(self, url):
        http(f"{self.wd}/session/{self.sid}/url", "POST", {"url": url}, timeout=60)

    def run(self, script, args=()):
        return http(f"{self.wd}/session/{self.sid}/execute/sync", "POST",
                    {"script": script, "args": list(args)})["value"]

    def run_async(self, script, args=()):
        return http(f"{self.wd}/session/{self.sid}/execute/async", "POST",
                    {"script": script, "args": list(args)}, timeout=60)["value"]

    def close(self):
        """Close every tab through DevTools, the way a person closes the window."""
        if self.drv:
            try:
                http(f"{self.wd}/session/{self.sid}", "DELETE")
            except Exception:
                pass
            self.drv.kill()
        for t in self.tabs():
            try:
                urllib.request.urlopen(f"{self.base}/json/close/{t['id']}", timeout=5).read()
            except Exception:
                pass
        if not wait_for(lambda: self.proc.poll() is not None, 30):
            log("browser did not exit on its own after last tab closed; killing")
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                           capture_output=True)
            return False
        # Child processes let go of the profile a little after the main one.
        wait_for(lambda: "chrome.exe" not in subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"], capture_output=True,
            text=True).stdout, 20)
        return True


def stage(fn):
    log(f"\n===== {fn.__name__} =====")
    try:
        fn()
    except Exception as e:
        result("FAIL", fn.__name__, f"error: {e!r}")
        log(traceback.format_exc())


# ---------------------------------------------------------------- stages


def environment():
    k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
    def q(n):
        try:
            return winreg.QueryValueEx(k, n)[0]
        except OSError:
            return "?"
    ver = f"{q('ProductName')} {q('DisplayVersion')} build {q('CurrentBuild')}.{q('UBR')}"
    result("INFO", "windows", ver)
    result("INFO", "user", os.environ.get("USERNAME"))
    result("INFO", "headful allowed (sandbox only)", os.environ.get("BORING_ALLOW_HEADFUL"))
    result("INFO", "installer A (Release 2) sha256", sha256(A))
    result("INFO", "installer B (Release 3) sha256", sha256(B))


def install():
    check("nothing installed before", not CHROME.exists() and not uninstall_entries())
    # mini_installer unpacks next to itself, so run it from a writable
    # folder, the way a person runs it from Downloads.
    dl = Path(os.environ["USERPROFILE"]) / "Downloads"
    dl.mkdir(exist_ok=True)
    local_a = dl / A.name
    shutil.copyfile(A, local_a)
    t = time.monotonic()
    r = subprocess.run([str(local_a), "--do-not-launch-chrome"])
    log(f"installer exit {r.returncode} after {time.monotonic() - t:.0f}s")
    check("installer A exits 0", r.returncode == 0, f"exit {r.returncode}")
    check("chrome.exe installed per user", CHROME.exists(), str(CHROME))
    versions = [p.name for p in APPDIR.iterdir() if p.is_dir() and p.name[0].isdigit()]
    check("version folder with setup.exe", any((APPDIR / v / "Installer" / "setup.exe").exists() for v in versions), ",".join(versions))
    check("installed version is Release 2's Chromium", versions == [A_VERSION], ",".join(versions))
    dll = APPDIR / versions[0] / "chrome.dll"
    check("installed chrome.dll is build A", sha256(dll) == A_DLL_SHA)
    ents = uninstall_entries()
    for sub, vals in ents:
        log("uninstall entry", sub, {k: vals.get(k) for k in ("DisplayName", "DisplayVersion", "Publisher", "UninstallString", "DisplayIcon")})
    check("one uninstall entry", len(ents) == 1, str([s for s, _ in ents]))
    if ents:
        name = str(ents[0][1].get("DisplayName", ""))
        pub = str(ents[0][1].get("Publisher", ""))
        check("uninstall entry named Boring Browser", "boring" in name.lower(), name)
        # Release 2 predates ledger 5, so its publisher still reads "The
        # Chromium Authors". The same check is a real one on the updated entry.
        result("INFO", "Chromium in uninstall name/publisher (Release 2, expected)",
               f"{name} / {pub}")
    sc = shortcuts()
    log("shortcuts", sc)
    check("Start menu shortcut", any("start menu" in s.lower() for s in sc), str(sc))
    check("no Chromium-named shortcut", not any("chromium" in os.path.basename(s).lower() for s in sc), str(sc))


PROFILE = Path(r"C:\p1")


def first_run_and_browse():
    c = Chrome(PROFILE)
    ok = wait_for(lambda: c.tabs(), 20)
    tabs = c.tabs()
    log("first run tabs:", [(t["url"], t["title"]) for t in tabs])
    check("first run opens the welcome page", any("boring-welcome" in t["url"] for t in tabs), str([t["url"] for t in tabs]))
    result("INFO", "version reported by A", c.version())
    c.attach()
    c.get("https://example.com/")
    title = c.run("return document.title")
    check("browses to a real https site", "Example" in title, title)
    ua = c.run("return navigator.userAgent")
    result("INFO", "user agent", ua)
    c.close()


SET_PREFS = """
const done = arguments[arguments.length - 1];
chrome.settingsPrivate.setPref('browser.show_home_button', true, '', () => {
  chrome.settingsPrivate.setPref('homepage', 'https://example.org/', '', () => {
    chrome.settingsPrivate.setPref('homepage_is_newtabpage', false, '', () => done('ok'));
  });
});
"""
GET_PREFS = """
const done = arguments[arguments.length - 1];
chrome.settingsPrivate.getAllPrefs(ps => {
  const o = {};
  for (const p of ps) if (['browser.show_home_button','homepage','homepage_is_newtabpage'].includes(p.key)) o[p.key] = p.value;
  done(JSON.stringify(o));
});
"""
WANT_PREFS = {"browser.show_home_button": True, "homepage": "https://example.org/", "homepage_is_newtabpage": False}


def settings_persist():
    c = Chrome(PROFILE)
    tabs = c.tabs()
    log("second run tabs:", [(t["url"], t["title"]) for t in tabs])
    check("second run does not show the welcome page again", not any("boring-welcome" in t["url"] for t in tabs), str([t["url"] for t in tabs]))
    c.attach()
    c.get("chrome://settings/appearance")
    time.sleep(2)
    log("set:", c.run_async(SET_PREFS))
    before = json.loads(c.run_async(GET_PREFS))
    log("prefs before restart", before)
    check("browser closes cleanly", c.close())
    c = Chrome(PROFILE)
    c.attach()
    c.get("chrome://settings/appearance")
    time.sleep(2)
    after = json.loads(c.run_async(GET_PREFS))
    log("prefs after restart", after)
    c.close()
    check("settings persist across restart", after == WANT_PREFS, json.dumps(after))
    # Chromium keeps some settings, the homepage among them, in
    # "Secure Preferences" rather than "Preferences".
    disk = {}
    for f in ("Preferences", "Secure Preferences"):
        fp = PROFILE / "Default" / f
        if fp.exists():
            d = json.loads(fp.read_text(encoding="utf-8"))
            if "show_home_button" in d.get("browser", {}):
                disk["browser.show_home_button"] = (f, d["browser"]["show_home_button"])
            if "homepage" in d:
                disk["homepage"] = (f, d["homepage"])
    log("on disk:", disk)
    check("settings are in the profile on disk", disk.get("browser.show_home_button", (0, None))[1] is True and disk.get("homepage", (0, None))[1] == "https://example.org/", str(disk))


# ---- build 3 addition (ledger 29): tabs survive the update. Release 2 saves a
# session with two local pages before the update; the first start of the
# updated browser on that profile must bring both back.
TABS_PROFILE = Path(r"C:\p3")
TAB_PORT = 8765
TAB_PAGES = {"/alpha.html": "Restore test ALPHA", "/bravo.html": "Restore test BRAVO"}
TAB_URLS = [f"http://127.0.0.1:{TAB_PORT}{p}" for p in TAB_PAGES]
TAB_SERVER = None


def start_tab_server():
    """The harness's own local server: two pages, distinct titles, loopback only."""
    global TAB_SERVER
    if TAB_SERVER is not None:
        return
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            title = TAB_PAGES.get(self.path.split("?")[0])
            if title is None:
                self.send_response(404)
                self.end_headers()
                return
            body = f"<!doctype html><title>{title}</title><h1>{title}</h1>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    TAB_SERVER = http.server.ThreadingHTTPServer(("127.0.0.1", TAB_PORT), H)
    threading.Thread(target=TAB_SERVER.serve_forever, daemon=True).start()
    log("tab test server on 127.0.0.1:%d" % TAB_PORT)


def post_wm_close(pid):
    """WM_CLOSE to the browser's own top-level windows, like the X button
    (and like WinSparkle asking the browser to quit). Inside the Sandbox only."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        p = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u.IsWindowVisible(h):
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(h, cls, 64)
            if cls.value == "Chrome_WidgetWin_1":
                found.append(h)
        return True

    u.EnumWindows(cb, 0)
    for h in found:
        u.PostMessageW(h, 0x0010, 0, 0)
    return len(found)


def tabs_before_update():
    """Release 2: two local pages open, the three settings set, session saved,
    window closed with its tabs still open (not tab by tab)."""
    start_tab_server()
    c = Chrome(TABS_PROFILE, port=9334)
    wait_for(lambda: c.tabs(), 20)
    c.attach()
    c.get("chrome://settings/appearance")
    time.sleep(2)
    log("p3 set:", c.run_async(SET_PREFS))
    c.get(TAB_URLS[0])
    req = urllib.request.Request(f"{c.base}/json/new?{TAB_URLS[1]}", method="PUT")
    urllib.request.urlopen(req, timeout=10).read()
    try:
        http(f"{c.wd}/session/{c.sid}", "DELETE")
    except Exception:
        pass
    c.drv.kill()
    want = set(TAB_PAGES.values())
    ok = wait_for(lambda: want <= {t["title"] for t in c.tabs()}, 30)
    tabs = [(t["url"], t["title"]) for t in c.tabs()]
    log("p3 tabs before the update:", tabs)
    check("Release 2 has the two test pages open (distinct titles)", ok and len(tabs) == 2, str(tabs))
    # Let the session save: Chromium writes the session file a few seconds
    # after a navigation. Wait for the Sessions folder to hold data.
    sess = TABS_PROFILE / "Default" / "Sessions"
    wait_for(lambda: sess.exists() and any(p.stat().st_size > 0 for p in sess.iterdir()), 30)
    time.sleep(10)
    files = sorted((p.name, p.stat().st_size) for p in sess.iterdir()) if sess.exists() else []
    log("p3 Sessions folder before closing:", files)
    check("the session is saved on disk before the update", any(s > 0 for _, s in files), str(files))
    n = post_wm_close(c.proc.pid)
    log("WM_CLOSE sent to", n, "window(s)")
    gone = wait_for(lambda: c.proc.poll() is not None, 40)
    if not gone:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(c.proc.pid)], capture_output=True)
    check("Release 2 quits on window close with the tabs open", gone and n > 0, f"windows {n}")
    wait_for(lambda: "chrome.exe" not in subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq chrome.exe"], capture_output=True, text=True).stdout, 20)


def tabs_after_update():
    """Release 3, first start on the profile Release 2 saved: both tabs return."""
    c = Chrome(TABS_PROFILE, port=9335)
    want = set(TAB_PAGES.values())
    wait_for(lambda: want <= {t["title"] for t in c.tabs()}, 40)
    tabs = [(t["url"], t["title"]) for t in c.tabs()]
    log("p3 tabs after the update:", tabs)
    result("INFO", "version of the browser that restored the tabs", c.version())
    check("first start after the update brings back both tabs (urls)",
          all(u in [t[0] for t in tabs] for u in TAB_URLS), str(tabs))
    check("both restored tabs have their own titles", want <= {t[1] for t in tabs}, str(tabs))
    check("no welcome page and no extra tabs on the restored profile",
          len(tabs) == 2 and not any("boring-welcome" in t[0] for t in tabs), str(tabs))
    c.attach()
    c.get("chrome://settings/appearance")
    time.sleep(2)
    got = json.loads(c.run_async(GET_PREFS))
    log("p3 prefs after the update", got)
    check("the restored profile keeps its settings", got == WANT_PREFS, json.dumps(got))
    c.close()


def update_test():
    """Release 2 -> Release 3 through the real update path. test_update_local.py
    needs the headful permission, which go.cmd sets inside the Sandbox only.
    Do NOT run the repo's smokes against A here: they are 157's."""
    global DRIVER
    clicker = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(IN / "clicker.ps1"), "-Log", str(OUT / "clicker.log")])
    work = Path(r"C:\w")
    work.mkdir(exist_ok=True)
    global WATCHER
    # No listener on every interface (a Windows Firewall prompt for Python sat
    # on top of the Sandbox last night): the non-local case reaches its
    # loopback-only server by a name that is not localhost.
    try:
        hosts = Path(r"C:\Windows\System32\drivers\etc\hosts")
        with open(hosts, "a", encoding="ascii") as f:
            f.write("\n127.0.0.1 feed-nonlocal.test\n")
        log("hosts entry added: 127.0.0.1 feed-nonlocal.test")
    except OSError as e:
        log("hosts entry NOT added:", e)
    # Run 2 diagnostics: who starts the installer, who ends it, and when.
    WATCHER = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(IN / "procwatch.ps1"), "-Log", str(OUT / "procs.log")])
    try:
        r = subprocess.run(
            [sys.executable, str(TOOLS / "test_update_local.py"),
             "--browser", str(CHROME), "--work-dir", str(work),
             "--installed-release", "1",
             "--real-installer", str(B), "--real-version", B_FEED_VERSION,
             "--click-timeout", "240",
             "--non-local-name", "feed-nonlocal.test"],
            capture_output=True, text=True, timeout=3600)
    finally:
        clicker.kill()
    log(f"--- test_update_local.py exit {r.returncode}\n{r.stdout}\n{r.stderr}")
    (OUT / "test_update_local.txt").write_text(r.stdout + "\n" + r.stderr, encoding="utf-8")
    for line in r.stdout.splitlines():
        if line.startswith(("PASS ", "FAIL ", "SKIP ")):
            word, rest = line.split(" ", 1)
            result(word, "update: " + rest)
    check("test_update_local.py exits 0", r.returncode == 0, f"exit {r.returncode}")
    versions = [p.name for p in APPDIR.iterdir() if p.is_dir() and p.name[0].isdigit()]
    dlls = {v: sha256(APPDIR / v / "chrome.dll") for v in versions if (APPDIR / v / "chrome.dll").exists()}
    log("after update, version folders and chrome.dll:", dlls)
    result("INFO", "version folders after the update", ",".join(versions))
    check("after the update, the installed chrome.dll is build B", B_DLL_SHA in dlls.values(), str(dlls))
    check("the installed chrome.dll set no longer holds only A's", set(dlls.values()) != {A_DLL_SHA}, str(dlls))
    # From here on every tool that attaches to the browser is B's.
    DRIVER = DRIVER_B
    c = Chrome(Path(r"C:\p2"))
    c.attach()
    version = c.version()
    result("INFO", "version reported by the updated browser", version)
    check(f"the updated browser reports {B_VERSION}", version.endswith("/" + B_VERSION), version)
    c.get("https://example.com/")
    check("updated browser starts and browses", "Example" in c.run("return document.title"))
    c.close()


WATCHER = None


def update_diag():
    """Run 2 only. Collect what the installer left, then, if the update did not
    land, install B directly over A so the later stages are still meaningful.
    The direct install is NOT the update path and is labelled so."""
    if WATCHER is not None:
        time.sleep(3)
        WATCHER.kill()
    d = OUT / "diag"
    d.mkdir(exist_ok=True)
    for root in (Path(r"C:\t"), Path(r"C:\w"), LOCAL / "Temp", Path(os.environ["APPDATA"]) / "WinSparkle"):
        if not root.exists():
            continue
        log(f"diag listing {root}:", sorted(p.name for p in root.iterdir())[:80])
        for p in list(root.rglob("*.log")) + list(root.rglob("*.txt")):
            try:
                if p.stat().st_size < 3_000_000 and "installer-ran" not in p.name:
                    shutil.copyfile(p, d / (root.name + "__" + p.name))
            except OSError:
                pass
    tree = []
    for p in sorted(APPDIR.rglob("*")):
        if p.is_file() and p.stat().st_size > 1_000_000 or p.is_dir():
            tree.append(f"{p.relative_to(APPDIR)}")
    (d / "application-tree.txt").write_text("\n".join(tree), encoding="utf-8")
    versions = [p.name for p in APPDIR.iterdir() if p.is_dir() and p.name[0].isdigit()]
    if B_VERSION in versions:
        result("INFO", "update landed, no direct install needed", ",".join(versions))
        return
    result("INFO", "FALLBACK DIRECT INSTALL of B over A (this is not the update path)", ",".join(versions))
    dl = Path(os.environ["USERPROFILE"]) / "Downloads"
    local_b = dl / B.name
    shutil.copyfile(B, local_b)
    t = time.monotonic()
    r = subprocess.run([str(local_b), "--do-not-launch-chrome", "--verbose-logging"])
    log(f"direct B installer exit {r.returncode} after {time.monotonic() - t:.0f}s")
    result("INFO" if r.returncode == 0 else "FAIL", "direct installer B exit code", str(r.returncode))
    versions = [p.name for p in APPDIR.iterdir() if p.is_dir() and p.name[0].isdigit()]
    result("INFO", "version folders after direct install of B", ",".join(versions))
    for p in list(Path(r"C:\t").rglob("*.log")) + list(Path(os.environ["LOCALAPPDATA"]).glob("Temp/*.log")):
        try:
            shutil.copyfile(p, d / ("after-direct__" + p.name))
        except OSError:
            pass


def updated_entry():
    ents = uninstall_entries()
    check("one uninstall entry after the update", len(ents) == 1, str([s for s, _ in ents]))
    if not ents:
        return
    vals = ents[0][1]
    name = str(vals.get("DisplayName", ""))
    pub = str(vals.get("Publisher", ""))
    version = str(vals.get("DisplayVersion", ""))
    log("updated uninstall entry", {k: vals.get(k) for k in ("DisplayName", "DisplayVersion", "Publisher", "UninstallString")})
    check(f"updated entry says {B_VERSION}", version.startswith(B_VERSION), version)
    check("updated entry has no Chromium in name/publisher", "chromium" not in (name + pub).lower(), f"{name} / {pub}")
    sc = shortcuts()
    check("the shortcuts are still the Boring Browser ones", bool(sc) and not any("chromium" in os.path.basename(s).lower() for s in sc), str(sc))


def old_profile_in_new_browser():
    """The profile Release 2 made and used (C:\\p1) opened by Release 3."""
    c = Chrome(PROFILE)
    tabs = c.tabs()
    log("old profile, tabs in B:", [(t["url"], t["title"]) for t in tabs])
    check("the old profile opens a tab in the new browser", bool(tabs), str([t["url"] for t in tabs]))
    check("the old profile does not show the welcome page again", not any("boring-welcome" in t["url"] for t in tabs), str([t["url"] for t in tabs]))
    check("B opened it", c.version().endswith("/" + B_VERSION), c.version())
    c.attach()
    c.get("chrome://settings/appearance")
    time.sleep(2)
    got = json.loads(c.run_async(GET_PREFS))
    log("old profile prefs in B", got)
    check("the old profile keeps its settings in the new browser", got == WANT_PREFS, json.dumps(got))
    c.get("https://example.com/")
    check("the old profile browses", "Example" in c.run("return document.title"))
    check("the new browser closes the old profile cleanly", c.close())


def smokes():
    """The repo's own smoke checks, pointed at the UPDATED installed copy
    (B's chromedriver, B's browser). Run once, after the update."""
    for name in ("smoke_adblock.py", "smoke_scam.py", "smoke_sandbox.py"):
        code = (
            "import sys, runpy; sys.path.insert(0, r'%s'); import drive; "
            "drive.CHROME = r'%s'; drive.DRIVER = r'%s'; sys.argv = ['%s']; "
            "runpy.run_path(r'%s', run_name='__main__')"
        ) % (TOOLS, CHROME, DRIVER, name, TOOLS / name)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600)
        log(f"--- {name} exit {r.returncode}\n{r.stdout}\n{r.stderr}")
        tail = [l for l in r.stdout.splitlines() if l.strip()][-1:] or [""]
        check(f"{name} on the updated copy", r.returncode == 0, tail[0])


def uninstall():
    ents = uninstall_entries()
    if not ents:
        check("uninstall entry present", False)
        return
    cmd = str(ents[0][1]["UninstallString"]) + " --force-uninstall"
    log("uninstall:", cmd)
    r = subprocess.run(cmd, shell=True)
    log("uninstall exit", r.returncode)
    wait_for(lambda: not CHROME.exists(), 120)
    time.sleep(5)
    check("uninstall removes the program", not CHROME.exists(), str(list(APPDIR.parent.glob("*")) if APPDIR.parent.exists() else "folder gone"))
    check("uninstall removes the uninstall entry", not uninstall_entries())
    sc = shortcuts()
    check("uninstall removes shortcuts", not sc, str(sc))
    left = sorted(str(p) for p in (LOCAL / "BoringBrowser").rglob("*"))[:20] if (LOCAL / "BoringBrowser").exists() else []
    result("INFO", "left under %LOCALAPPDATA%\\BoringBrowser", f"{len(left)} shown: {left[:5]}" if left else "nothing")


# Release 4 addition (ledger item 4): signed in across the update, on its
# own profile C:\p4. See login_stages.py.
login_stages.bind(sys.modules[__name__])

STAGES = (environment, install, first_run_and_browse, settings_persist,
          tabs_before_update, login_stages.login_before_update,
          update_test, update_diag, updated_entry, old_profile_in_new_browser,
          tabs_after_update, login_stages.login_after_update, smokes, uninstall)

if __name__ == "__main__":
    for f in STAGES:
        stage(f)
    verdict = "PASS" if not any(r.startswith("FAIL") for r in results) else "FAIL"
    updated = any(r.startswith("PASS: update: update_a_to_b") for r in results)
    (OUT / "VERDICT.txt").write_text(
        f"{verdict}\nupdate_a_to_b passed: {updated}\n", encoding="utf-8")
    (OUT / "DONE").write_text("\n".join(results), encoding="utf-8")
