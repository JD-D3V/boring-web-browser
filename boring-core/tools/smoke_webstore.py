#!/usr/bin/env python3
"""Check extension installs and the bundled Chromium Web Store (feature 12).

Two checks, neither of which goes near the real Chrome Web Store: every
host except 127.0.0.1 resolves to nothing for the whole run.

1. Chromium Web Store is installed into a new profile on its own, is
   enabled, is the version tools/get_chromium_web_store.py pinned, and
   has no update_url, so nothing but a browser release can change it.
   Read from chrome://extensions through developerPrivate.

2. A .crx served from localhost goes to the install prompt: not saved as
   a plain download, not refused as "cannot be added from this website",
   and not installed without asking. The test extension is packed by the
   build's own chrome.exe --pack-extension, the page link is clicked
   over WebDriver, and the prompt is found by the accessible names in
   our own browser's windows (UI Automation, read only: no mouse, keys
   or screen capture). The prompt is left unanswered; the browser quits.

Exit 0 pass, 1 fail.
"""

import contextlib
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import get_chromium_web_store as cws
from drive import CHROME, OUT, Browser, free_port

TEST_NAME = "Boring Smoke Test Extension"
PROMPT_TITLE = f'Add "{TEST_NAME}"?'
NO_NETWORK = "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"
ELEMENT = "element-6066-11e4-a52e-4f735466cecf"

EXTENSIONS_INFO = """
var done = arguments[arguments.length - 1];
chrome.developerPrivate.getExtensionsInfo(
    {includeDisabled: true, includeTerminated: true}).then(function(list) {
  done(JSON.stringify(list.map(function(e) {
    return {id: e.id, name: e.name, version: e.version, state: e.state,
            location: e.location, updateUrl: e.updateUrl,
            permissions: ((e.permissions || {}).simplePermissions || [])
                .map(function(p) { return p.message; })};
  })));
}, function(err) { done('error:' + err); });
"""


def scratch(prefix):
    base = r"E:\tmp" if os.path.isdir(r"E:\tmp") else os.environ.get("TMP")
    return tempfile.mkdtemp(prefix=prefix, dir=base)


def extensions_info(b):
    raw = b.run_async(EXTENSIONS_INFO)
    if raw.startswith("error:"):
        raise RuntimeError(raw)
    return json.loads(raw)


def wait_for_extension(b, predicate, timeout=45):
    deadline = time.time() + timeout
    found = []
    while time.time() < deadline:
        found = extensions_info(b)
        match = [e for e in found if predicate(e)]
        if match:
            return match[0], found
        time.sleep(1)
    return None, found


def check_bundled(check):
    profile = scratch("boring-webstore-")
    try:
        with Browser(user_data_dir=profile, args=[NO_NETWORK]) as b:
            b.get("chrome://extensions")
            ext, seen = wait_for_extension(b, lambda e: e["id"] == cws.EXTENSION_ID)
            check(
                "Chromium Web Store installed into a new profile",
                ext is not None,
                "" if ext else f"saw {[e['name'] for e in seen]}",
            )
            if not ext:
                return
            print("  ", json.dumps(ext))
            check("it is enabled", ext["state"] == "ENABLED", ext["state"])
            check(
                "it is the pinned version",
                ext["version"] == cws.VERSION,
                f"{ext['version']}, pinned {cws.VERSION}",
            )
            check(
                "it has no update_url",
                not ext.get("updateUrl"),
                ext.get("updateUrl") or "",
            )
    finally:
        shutil.rmtree(profile, ignore_errors=True)


# --- the test extension and the page that offers it -----------------------


def pack_test_extension(work):
    src = os.path.join(work, "smoke-ext")
    os.makedirs(src)
    with open(os.path.join(src, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"manifest_version": 3, "name": TEST_NAME, "version": "1.0"}, f)
    packer_profile = os.path.join(work, "packer-profile")
    subprocess.run(
        [
            CHROME,
            "--pack-extension=" + src,
            "--no-message-box",
            "--user-data-dir=" + packer_profile,
        ],
        timeout=120,
        check=False,
    )
    crx = src + ".crx"
    if not os.path.exists(crx):
        raise RuntimeError("chrome.exe --pack-extension made no .crx")
    return crx


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".crx": "application/x-chrome-extension",
    }

    def log_message(self, *args):
        pass


def serve(directory):
    port = free_port()

    def handler(*args, **kwargs):
        return Handler(*args, directory=directory, **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def write_download_prefs(profile, downloads):
    """Downloads go to a scratch folder, not the Downloads folder."""
    default = os.path.join(profile, "Default")
    os.makedirs(default, exist_ok=True)
    with open(os.path.join(default, "Preferences"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "download": {
                    "default_directory": downloads,
                    "prompt_for_download": False,
                    "directory_upgrade": True,
                }
            },
            f,
        )


# --- reading our own windows, UI Automation through ctypes -----------------
# Read only: accessible names of controls in windows that belong to the
# chrome.exe under test. Vtable slots are from UIAutomationClient.h.

user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32")
ole32 = ctypes.WinDLL("ole32")
oleaut32 = ctypes.WinDLL("oleaut32")
oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]


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
TREE_SCOPE_SUBTREE = 7


def _call(obj, slot, *args):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
    types = [ctypes.c_void_p] * (len(args) + 1)
    method = ctypes.WINFUNCTYPE(ctypes.HRESULT, *types)(vtable[0][slot])
    method(obj, *args)


def _release(obj):
    if obj:
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[0][2])(obj)


def process_path(pid):
    handle = kernel32.OpenProcess(0x1000, False, pid)  # query limited info
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def our_windows():
    """Visible top-level windows of the chrome.exe under test."""
    want = os.path.normcase(os.path.abspath(CHROME))
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if os.path.normcase(process_path(pid.value)) == want:
                found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found


def control_names(hwnd):
    ole32.CoInitializeEx(None, 0x2)
    automation = ctypes.c_void_p()
    ole32.CoCreateInstance(
        ctypes.byref(GUID(CLSID_CUIAutomation)),
        None,
        0x1,
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
        _call(window, 6, TREE_SCOPE_SUBTREE, condition.value, ctypes.addressof(found))
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


def all_names():
    names = []
    for hwnd in our_windows():
        with contextlib.suppress(OSError):
            names.extend(control_names(hwnd))
    return names


def wait_for_name(predicate, timeout=30):
    deadline = time.time() + timeout
    names = []
    while time.time() < deadline:
        names = all_names()
        if any(predicate(n) for n in names):
            return True, names
        time.sleep(1)
    return False, names


def check_prompt(check):
    work = scratch("boring-crx-")
    server = None
    try:
        crx = pack_test_extension(work)
        site = os.path.join(work, "site")
        os.makedirs(site)
        shutil.copy(crx, os.path.join(site, "smoke.crx"))
        with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as f:
            f.write('<a id="get" href="/smoke.crx">Get the extension</a>')
        server, port = serve(site)

        profile = os.path.join(work, "profile")
        downloads = os.path.join(work, "downloads")
        os.makedirs(downloads)
        write_download_prefs(profile, downloads)

        with Browser(user_data_dir=profile, args=[NO_NETWORK]) as b:
            b.get(f"http://127.0.0.1:{port}/")
            # A real click, so the download has a user gesture behind it.
            link = b._req(
                "POST",
                f"/session/{b.sid}/element",
                {"using": "css selector", "value": "#get"},
            )["value"][ELEMENT]
            b._req("POST", f"/session/{b.sid}/element/{link}/click", {})

            shown, names = wait_for_name(lambda n: TEST_NAME in n)
            check(
                "a .crx from a web page gets the install prompt",
                shown,
                "" if shown else f"no {PROMPT_TITLE!r}; saw {sorted(set(names))[:40]}",
            )
            refused = [
                n for n in names if "cannot be added" in n or "can't be added" in n
            ]
            check("it is not refused as off-store", not refused, "; ".join(refused))

            # Nothing installed while the prompt waits for an answer.
            b._req("POST", f"/session/{b.sid}/window/new", {"type": "tab"})
            handles = b._req("GET", f"/session/{b.sid}/window/handles")["value"]
            b._req("POST", f"/session/{b.sid}/window", {"handle": handles[-1]})
            b.get("chrome://extensions")
            installed = [e["name"] for e in extensions_info(b)]
            check(
                "it is not installed without asking",
                TEST_NAME not in installed,
                f"installed: {installed}",
            )

    finally:
        if server:
            server.shutdown()
        shutil.rmtree(work, ignore_errors=True)


def main():
    if not os.path.exists(CHROME):
        print("no browser at", CHROME, "(set BORING_OUT)")
        return 1
    print("browser:", OUT)
    failures = []

    def check(name, ok, detail=""):
        print(
            f"{'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail else "")
        )
        if not ok:
            failures.append(name)

    check_bundled(check)
    check_prompt(check)
    print()
    print("FAIL" if failures else "PASS", f"{len(failures)} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
