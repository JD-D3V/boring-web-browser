#!/usr/bin/env python3
"""Test the browser updater end to end, offline, on this machine.

Meant for Windows Sandbox, with version A of the browser already
installed from its installer (the updater stays off in a copy unpacked
from the zip). Nothing leaves the machine: the feed and the "installer"
are served from 127.0.0.1, and the key is a throwaway one made here with
winsparkle-tool and deleted afterwards. It is never our publisher key and
is never installed anywhere; the browser is told to trust it for one run
with --boring-update-key, which it honours only for a localhost feed.

Each case starts the installed browser with a fresh profile and with
HKCU\\Software\\Boring Browser\\Updates (WinSparkle's settings) reset to
a known state, so the startup check runs at once. The script only
watches: the requests the local server gets, whether a window that is
not Chrome's own appears in the browser's process, whether the offered
file ran, and whether the browser still answers on its DevTools port.
It never clicks or types.

Cases that need a person to click "Install update" in WinSparkle's
window are marked [click] below and in the output. Run with
--no-interactive to do only the others.

  older_not_offered        a feed offering an older version shows nothing
  feed_unreachable         a feed nobody answers leaves the browser working
  non_local_http_ignored   an http feed on a host that is not localhost is
                           never asked, and its test key is not trusted
  tampered_refused [click] an installer changed after signing never runs
  wrong_key_refused [click] an installer signed by another key never runs
  newer_offered [click]    a newer, correctly signed installer is offered,
                           downloaded and run
  update_a_to_b [click]    only with --real-installer: the real installer
                           of version B, signed with the test key, updates
                           this copy. Runs last, it replaces the browser.

The offered "installer" in the first click cases is a copy of cmd.exe,
run by WinSparkle with sparkle:installerArguments that write a marker
file. So "it ran" is a file on disk, not a guess, and the positive case
proves the same detection works before the negative ones are believed.

Prints one PASS, FAIL or SKIP line per case and exits 1 if any case
failed, 2 if the setup was wrong, 0 otherwise.

Usage (inside Windows Sandbox):
  python test_update_local.py
  python test_update_local.py --no-interactive
  python test_update_local.py --real-installer C:\\b\\BoringBrowser_B.exe \\
      --real-version 153.0.8010.52.2
"""

import argparse
import contextlib
import ctypes
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import make_appcast  # noqa: E402
import rename_release  # noqa: E402

CORE = TOOLS.parent
DEFAULT_TOOL = make_appcast.DEFAULT_TOOL
DEFAULT_RELEASE_HEADER = rename_release.DEFAULT_RELEASE_HEADER

# Where WinSparkle keeps its settings for us, from browser_updater.cc.
UPDATES_KEY = r"Software\Boring Browser\Updates"

# What each case starts from. WinSparkle skips the automatic check on
# the very first run of an app (it only notes DidRunOnce), and skips it
# again when LastCheckTime is recent, so both are set up here and no
# LastCheckTime or SkipThisVersion is left. Strings, the way WinSparkle
# writes them.
SEEDED_SETTINGS = {"DidRunOnce": "1", "CheckForUpdates": "1"}

# The account Windows Sandbox runs as.
SANDBOX_USER = "WDAGUtilityAccount"

CONFIG_ERROR = 2

_PUBLIC_KEY_LINE = re.compile(r"Public key:\s*([A-Za-z0-9+/=]+)")


class SetupError(RuntimeError):
    """The machine or the arguments are not ready for this test."""


# --------------------------------------------------------------------------
# What a case saw, and what each case makes of it. Kept apart from the
# watching so the verdicts can be tested without a browser.


@dataclass
class Observation:
    feed_requests: int = 0
    download_started: bool = False
    download_complete: bool = False
    dialog_seen: bool = False
    installer_ran: bool = False
    browser_alive: bool = False
    # Only for the non-local case: whether this script could reach the
    # server by that name itself, so a pass means something.
    probe_reached: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str


def verdict_older_not_offered(o: Observation) -> Verdict:
    if o.feed_requests == 0:
        return Verdict(False, "the browser never asked for the feed")
    if o.dialog_seen or o.download_started:
        return Verdict(False, "an older version was offered")
    if not o.browser_alive:
        return Verdict(False, "the browser stopped answering")
    return Verdict(True, "feed read, nothing offered, browser working")


def verdict_feed_unreachable(o: Observation) -> Verdict:
    if not o.browser_alive:
        return Verdict(False, "the browser stopped answering")
    if o.dialog_seen:
        return Verdict(False, "a window appeared for a feed nobody answers")
    return Verdict(True, "browser working, no window")


def verdict_non_local_http_ignored(o: Observation) -> Verdict:
    if not o.probe_reached:
        return Verdict(
            False,
            "inconclusive: this script could not reach its own server by "
            "host name, so silence proves nothing",
        )
    if o.feed_requests or o.download_started:
        return Verdict(False, "the browser asked a non-local http feed")
    if not o.browser_alive:
        return Verdict(False, "the browser stopped answering")
    return Verdict(True, "never asked, browser working")


def verdict_refused(o: Observation) -> Verdict:
    """For the tampered and wrong key cases."""
    if o.installer_ran:
        return Verdict(False, "THE INSTALLER RAN")
    if not o.dialog_seen:
        return Verdict(False, "inconclusive: the update was never offered")
    if not o.download_complete:
        return Verdict(
            False, "inconclusive: the installer was not downloaded (no click?)"
        )
    if not o.browser_alive:
        return Verdict(False, "refused, but the browser stopped answering")
    return Verdict(True, "downloaded, then refused")


def verdict_newer_offered(o: Observation) -> Verdict:
    if o.feed_requests == 0:
        return Verdict(False, "the browser never asked for the feed")
    if not o.dialog_seen:
        return Verdict(False, "a newer signed version was not offered")
    if not o.download_complete:
        return Verdict(False, "the installer was not downloaded (no click?)")
    if not o.installer_ran:
        return Verdict(False, "downloaded but never run")
    return Verdict(True, "offered, downloaded, checked and run")


# --------------------------------------------------------------------------
# Versions.


def installed_build_version(chromium: str, release: int) -> str:
    return rename_release.release_version(chromium, release)


def newer_version(chromium: str, release: int) -> str:
    return f"{chromium}.{release + 1}"


def older_version(chromium: str, release: int) -> str:
    """One Chromium major behind, which no reading can call newer."""
    major, rest = chromium.split(".", 1)
    return f"{int(major) - 1}.{rest}.{release}"


def split_build_version(build_version: str) -> tuple[str, int]:
    """153.0.8010.52.2 -> ("153.0.8010.52", 2), what make_appcast takes."""
    chromium, _, release = build_version.rpartition(".")
    return chromium, int(release)


# --------------------------------------------------------------------------
# Keys.


def parse_public_key(output: str) -> str:
    match = _PUBLIC_KEY_LINE.search(output)
    if not match or not make_appcast.is_ed25519_public_key(match.group(1)):
        raise SetupError("winsparkle-tool did not print a public key")
    return match.group(1)


def generate_key(tool: Path, key_file: Path) -> str:
    """Make a throwaway key pair, return the public half."""
    if key_file.exists():
        # generate-key overwrites without asking. Never let it near a
        # file this script did not just make.
        raise SetupError(f"{key_file} already exists")
    done = subprocess.run(
        [str(tool), "generate-key", "--file", str(key_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise SetupError("winsparkle-tool generate-key failed: " + done.stderr.strip())
    return parse_public_key(done.stdout)


# --------------------------------------------------------------------------
# The local server.


@dataclass
class Request:
    path: str
    complete: bool


class FeedServer:
    """Serves a few files from memory and writes down every request."""

    def __init__(self, host: str = "127.0.0.1") -> None:
        self.files: dict[str, bytes] = {}
        self.requests: list[Request] = []
        self._lock = threading.Lock()
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                body = server.files.get(path)
                record = Request(path, False)
                if path != "/probe":
                    with server._lock:
                        server.requests.append(record)
                if path == "/probe":
                    body = b"ok"
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                kind = "application/xml" if path.endswith(".xml") else None
                self.send_header("Content-Type", kind or "application/octet-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                with contextlib.suppress(OSError):
                    self.wfile.write(body)
                    self.wfile.flush()
                    record.complete = True

            def log_message(self, *args) -> None:
                pass

        self._httpd = http.server.ThreadingHTTPServer((host, 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self) -> "FeedServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def serve(self, files: dict[str, bytes]) -> None:
        with self._lock:
            self.files = dict(files)
            self.requests = []

    def count(self, path: str | None = None) -> int:
        with self._lock:
            return sum(1 for r in self.requests if path is None or r.path == path)

    def fetched(self, path: str) -> tuple[bool, bool]:
        """(started, completed) for one path."""
        with self._lock:
            hits = [r for r in self.requests if r.path == path]
        return bool(hits), any(r.complete for r in hits)


def closed_port() -> int:
    """A port nothing listens on, for the unreachable feed."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------
# Windows: the browser, its windows, its settings, running processes.


def default_browser_paths() -> list[Path]:
    local = os.environ.get("LOCALAPPDATA", "")
    programs = os.environ.get("PROGRAMFILES", r"C:\Program Files")
    return [
        Path(local) / "BoringBrowser" / "Application" / "chrome.exe",
        Path(programs) / "BoringBrowser" / "Application" / "chrome.exe",
    ]


def file_version(path: Path) -> str:
    """The four part file version of an exe, from its version resource."""
    version = ctypes.windll.version
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise SetupError(f"{path} has no version resource")
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        raise SetupError(f"could not read the version of {path}")
    fixed = ctypes.c_void_p()
    length = ctypes.c_uint()
    if not version.VerQueryValueW(
        buffer, "\\", ctypes.byref(fixed), ctypes.byref(length)
    ):
        raise SetupError(f"could not read the version of {path}")
    words = ctypes.cast(fixed, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
    ms, ls = words[2], words[3]
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def is_installed_copy(chrome: Path) -> bool:
    """The updater only runs where setup.exe sits in <version>\\Installer."""
    return any(chrome.parent.glob("*/Installer/setup.exe"))


def foreign_windows(pid: int) -> list[str]:
    """Visible top-level windows of pid that are not Chrome's own.

    Read only: class names and titles, nothing is sent to any window.
    WinSparkle's dialogs are wxWidgets windows inside the browser process.
    """
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [proc, wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    found: list[str] = []

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, 256)
            if not name.value.startswith("Chrome_"):
                title = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title, 256)
                found.append(f"{name.value}: {title.value}")
        return True

    user32.EnumWindows(proc(visit), 0)
    return found


def process_running(image_name: str) -> bool:
    done = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH", "/FO", "CSV"],
        capture_output=True,
        text=True,
        check=False,
    )
    return f'"{image_name.lower()}"' in done.stdout.lower()


def kill_image(image_name: str) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/IM", image_name], capture_output=True, check=False
    )


def kill_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False
    )


class UpdateSettings:
    """WinSparkle's HKCU settings: cleared before each case, put back after."""

    def __init__(self, keep: bool) -> None:
        import winreg

        self._winreg = winreg
        self._saved: list[tuple[str, object, int]] | None = None
        if keep:
            self._saved = self._read()

    def _read(self) -> list[tuple[str, object, int]] | None:
        winreg = self._winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UPDATES_KEY) as key:
                values = []
                index = 0
                while True:
                    try:
                        values.append(winreg.EnumValue(key, index))
                    except OSError:
                        return values
                    index += 1
        except FileNotFoundError:
            return None

    def clear(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._winreg.DeleteKey(self._winreg.HKEY_CURRENT_USER, UPDATES_KEY)

    def seed(self) -> None:
        """A clean slate on which the startup check runs at once."""
        self.clear()
        winreg = self._winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UPDATES_KEY) as key:
            for name, value in SEEDED_SETTINGS.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def restore(self) -> None:
        self.clear()
        if self._saved is None:
            return
        winreg = self._winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UPDATES_KEY) as key:
            for name, value, kind in self._saved:
                winreg.SetValueEx(key, name, 0, kind, value)


class Browser:
    """The installed browser with a throwaway profile."""

    def __init__(self, chrome: Path, work: Path, extra: list[str]) -> None:
        self.profile = Path(tempfile.mkdtemp(prefix="profile-", dir=work))
        self.proc = subprocess.Popen(
            [
                str(chrome),
                f"--user-data-dir={self.profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-port=0",
                *extra,
                "about:blank",
            ]
        )

    def devtools_port(self) -> int | None:
        try:
            first = (self.profile / "DevToolsActivePort").read_text().splitlines()[0]
            return int(first)
        except (OSError, ValueError, IndexError):
            return None

    def alive(self) -> bool:
        """Still running and still answering, which is what 'working' means."""
        if self.proc.poll() is not None:
            return False
        port = self.devtools_port()
        if port is None:
            return False
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=5
            ) as response:
                return "Browser" in json.load(response)
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def wait_ready(self, timeout: float) -> bool:
        return wait_for(self.alive, timeout)

    def close(self) -> None:
        if self.proc.poll() is None:
            kill_tree(self.proc.pid)
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(10)
        for _ in range(10):
            try:
                shutil.rmtree(self.profile)
                return
            except OSError:
                time.sleep(1)


def wait_for(condition: Callable[[], bool], timeout: float, step: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if condition():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(step)


# --------------------------------------------------------------------------
# The cases.


@dataclass(frozen=True)
class Case:
    name: str
    needs_click: bool
    what: str


CASES = [
    Case("older_not_offered", False, "a feed offering an older version shows nothing"),
    Case("feed_unreachable", False, "a feed nobody answers leaves the browser working"),
    Case(
        "non_local_http_ignored",
        False,
        "an http feed on a host that is not localhost is never asked",
    ),
    Case("tampered_refused", True, "an installer changed after signing never runs"),
    Case("wrong_key_refused", True, "an installer signed by another key never runs"),
    Case("newer_offered", True, "a newer signed installer is offered and run"),
    Case("update_a_to_b", True, "the real installer of version B updates this copy"),
]


class Harness:
    def __init__(self, args: argparse.Namespace, work: Path) -> None:
        self.args = args
        self.work = work
        self.tool = Path(args.winsparkle_tool)
        self.chrome = Path(args.browser)
        self.chromium = file_version(self.chrome)
        self.release = args.installed_release
        self.installed = installed_build_version(self.chromium, self.release)

        self.key = work / "test-update.key"
        self.other_key = work / "other.key"
        self.public_key = generate_key(self.tool, self.key)
        generate_key(self.tool, self.other_key)

        self.marker = work / "installer-ran.txt"
        self.server = FeedServer().start()
        self.settings = UpdateSettings(keep=args.outside_sandbox)

    def close(self) -> None:
        self.server.stop()
        self.settings.restore()

    # Payloads ------------------------------------------------------------

    def canary(self, version: str) -> tuple[str, Path]:
        """A harmless stand in for an installer: cmd.exe under its name."""
        name, _ = rename_release.release_names(*split_build_version(version))
        path = self.work / "payload" / name
        path.parent.mkdir(exist_ok=True)
        system = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"
        shutil.copyfile(system / "cmd.exe", path)
        return name, path

    def canary_arguments(self) -> str:
        return f'/c echo ran> "{self.marker}"'

    def feed_for(
        self,
        payload: Path,
        served: bytes,
        version: str,
        signature: str,
        installer_arguments: str | None,
    ) -> dict[str, bytes]:
        chromium, release = split_build_version(version)
        # The feed's length must match what is served, so a refusal can
        # only be the signature's doing.
        sized = self.work / "sized" / payload.name
        sized.parent.mkdir(exist_ok=True)
        sized.write_bytes(served)
        base = f"http://127.0.0.1:{self.server.port}/files"
        xml = make_appcast.render_feed(
            installer=str(sized),
            version=chromium,
            base_url=base,
            feed_url=self.feed_url(),
            release=release,
            ed_signature=signature,
            installer_arguments=installer_arguments,
        )
        return {"/appcast.xml": xml.encode(), f"/files/{payload.name}": served}

    def feed_url(self) -> str:
        return f"http://127.0.0.1:{self.server.port}/appcast.xml"

    def sign(self, key: Path, path: Path) -> str:
        return make_appcast.sign_installer(str(self.tool), str(key), str(path))

    # Watching ------------------------------------------------------------

    def launch(self, feed_url: str) -> Browser:
        self.settings.seed()
        with contextlib.suppress(FileNotFoundError):
            self.marker.unlink()
        return Browser(
            self.chrome,
            self.work,
            [
                f"--boring-update-url={feed_url}",
                f"--boring-update-key={self.public_key}",
            ],
        )

    def watch(
        self,
        browser: Browser,
        o: Observation,
        seconds: float,
        download: str | None,
        image: str | None,
        until: Callable[[], bool] | None = None,
    ) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            o.feed_requests = self.server.count("/appcast.xml")
            if download:
                o.download_started, o.download_complete = self.server.fetched(download)
            if browser.proc.poll() is None and foreign_windows(browser.proc.pid):
                o.dialog_seen = True
            if self.marker.exists() or (image and process_running(image)):
                o.installer_ran = True
            if until and until():
                return
            time.sleep(0.25)

    def ask(self, text: str) -> None:
        print(f"  ACTION: {text}", flush=True)

    # Cases ---------------------------------------------------------------

    def older_not_offered(self) -> Observation:
        version = older_version(self.chromium, self.release)
        name, path = self.canary(version)
        files = self.feed_for(
            path, path.read_bytes(), version, self.sign(self.key, path), None
        )
        self.server.serve(files)
        o = Observation()
        browser = self.launch(self.feed_url())
        try:
            browser.wait_ready(self.args.start_timeout)
            self.watch(
                browser,
                o,
                self.args.feed_timeout,
                f"/files/{name}",
                None,
                until=lambda: self.server.count("/appcast.xml") > 0,
            )
            self.watch(browser, o, self.args.quiet_window, f"/files/{name}", None)
            o.browser_alive = browser.alive()
        finally:
            browser.close()
        return o

    def feed_unreachable(self) -> Observation:
        o = Observation()
        browser = self.launch(f"http://127.0.0.1:{closed_port()}/appcast.xml")
        try:
            browser.wait_ready(self.args.start_timeout)
            self.watch(browser, o, self.args.quiet_window, None, None)
            o.browser_alive = browser.alive()
        finally:
            browser.close()
        return o

    def non_local_http_ignored(self) -> Observation:
        o = Observation()
        # A second server on every interface, reached by this machine's
        # own name, which the browser must not count as localhost.
        wide = FeedServer(host="0.0.0.0").start()
        try:
            host = socket.gethostname()
            version = newer_version(self.chromium, self.release)
            name, path = self.canary(version)
            wide.serve(
                self.feed_for(
                    path, path.read_bytes(), version, self.sign(self.key, path), None
                )
            )
            try:
                with urllib.request.urlopen(
                    f"http://{host}:{wide.port}/probe", timeout=5
                ) as response:
                    o.probe_reached = response.read() == b"ok"
            except (OSError, urllib.error.URLError):
                o.probe_reached = False
            browser = self.launch(f"http://{host}:{wide.port}/appcast.xml")
            try:
                browser.wait_ready(self.args.start_timeout)
                self.watch(browser, o, self.args.quiet_window, None, None)
                o.feed_requests = wide.count()
                o.download_started, _ = wide.fetched(f"/files/{name}")
                o.browser_alive = browser.alive()
            finally:
                browser.close()
        finally:
            wide.stop()
        return o

    def _clicked_case(
        self, served: bytes, path: Path, signature: str, version: str, prompt: str
    ) -> Observation:
        name = path.name
        self.server.serve(
            self.feed_for(path, served, version, signature, self.canary_arguments())
        )
        o = Observation()
        browser = self.launch(self.feed_url())
        try:
            browser.wait_ready(self.args.start_timeout)
            self.watch(
                browser,
                o,
                self.args.feed_timeout,
                f"/files/{name}",
                name,
                until=lambda: o.dialog_seen,
            )
            if o.dialog_seen:
                self.ask(prompt)
                self.watch(
                    browser,
                    o,
                    self.args.click_timeout,
                    f"/files/{name}",
                    name,
                    until=lambda: o.download_complete or o.installer_ran,
                )
                # Give it time to either run the file or refuse it.
                self.watch(
                    browser,
                    o,
                    self.args.quiet_window,
                    f"/files/{name}",
                    name,
                    until=lambda: o.installer_ran,
                )
            o.browser_alive = browser.alive()
        finally:
            browser.close()
            kill_image(name)
        return o

    def tampered_refused(self) -> Observation:
        version = newer_version(self.chromium, self.release)
        _, path = self.canary(version)
        signature = self.sign(self.key, path)
        served = path.read_bytes() + b"\0tampered after signing\0"
        return self._clicked_case(
            served,
            path,
            signature,
            version,
            "click Install update. Expect an error saying the update "
            "could not be validated; close it.",
        )

    def wrong_key_refused(self) -> Observation:
        version = newer_version(self.chromium, self.release)
        _, path = self.canary(version)
        signature = self.sign(self.other_key, path)
        return self._clicked_case(
            path.read_bytes(),
            path,
            signature,
            version,
            "click Install update. Expect an error saying the update "
            "could not be validated; close it.",
        )

    def newer_offered(self) -> Observation:
        version = newer_version(self.chromium, self.release)
        _, path = self.canary(version)
        return self._clicked_case(
            path.read_bytes(),
            path,
            self.sign(self.key, path),
            version,
            "click Install update, and Install update again if it asks. "
            "The browser will close; that is expected.",
        )

    def update_a_to_b(self) -> Observation:
        source = Path(self.args.real_installer)
        version = self.args.real_version or newer_version(self.chromium, self.release)
        name, _ = rename_release.release_names(*split_build_version(version))
        path = self.work / "payload" / name
        path.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, path)
        signature = self.sign(self.key, path)
        self.server.serve(
            self.feed_for(path, path.read_bytes(), version, signature, None)
        )
        o = Observation()
        browser = self.launch(self.feed_url())
        try:
            browser.wait_ready(self.args.start_timeout)
            self.watch(
                browser,
                o,
                self.args.feed_timeout,
                f"/files/{name}",
                name,
                until=lambda: o.dialog_seen,
            )
            if o.dialog_seen:
                self.ask(
                    "click Install update, and Install update again if it "
                    "asks. The browser closes and the installer runs."
                )
                self.watch(
                    browser,
                    o,
                    self.args.click_timeout,
                    f"/files/{name}",
                    name,
                    until=lambda: o.installer_ran,
                )
            o.browser_alive = True  # it is meant to close for this one
        finally:
            browser.close()
        # Let the installer finish before anything else looks at the copy.
        wait_for(lambda: not process_running(name), 300, step=1)
        o.notes.append(f"chrome.exe now reports {file_version(self.chrome)}")
        return o


VERDICTS: dict[str, Callable[[Observation], Verdict]] = {
    "older_not_offered": verdict_older_not_offered,
    "feed_unreachable": verdict_feed_unreachable,
    "non_local_http_ignored": verdict_non_local_http_ignored,
    "tampered_refused": verdict_refused,
    "wrong_key_refused": verdict_refused,
    "newer_offered": verdict_newer_offered,
    "update_a_to_b": verdict_newer_offered,
}


def result_line(case: Case, verdict: Verdict | None, skip_reason: str = "") -> str:
    tag = " [click]" if case.needs_click else ""
    if verdict is None:
        return f"SKIP {case.name}{tag}: {skip_reason}"
    word = "PASS" if verdict.passed else "FAIL"
    return f"{word} {case.name}{tag}: {verdict.reason}"


def selected_cases(args: argparse.Namespace) -> Iterator[tuple[Case, str]]:
    """Every case in order, with a reason to skip it or an empty string."""
    for case in CASES:
        if args.only and case.name not in args.only:
            continue
        if case.name == "update_a_to_b" and not args.real_installer:
            yield case, "no --real-installer given"
        elif case.needs_click and args.no_interactive:
            yield case, "needs a click, --no-interactive"
        else:
            yield case, ""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Test the updater end to end, offline.")
    ap.add_argument("--browser", default=None, help="installed chrome.exe")
    ap.add_argument(
        "--installed-release",
        type=int,
        default=None,
        help="kBoringRelease of the installed copy (default: from boring_release.h)",
    )
    ap.add_argument("--winsparkle-tool", default=str(DEFAULT_TOOL))
    ap.add_argument(
        "--real-installer",
        default=None,
        help="version B's installer, for update_a_to_b",
    )
    ap.add_argument(
        "--real-version",
        default=None,
        help="version B as the updater compares it, e.g. 153.0.8010.52.2",
    )
    ap.add_argument("--no-interactive", action="store_true")
    ap.add_argument("--only", nargs="*", default=None, metavar="CASE")
    ap.add_argument("--list", action="store_true", help="print the cases and stop")
    ap.add_argument(
        "--outside-sandbox",
        action="store_true",
        help="run on a normal machine; WinSparkle's settings are put back after",
    )
    ap.add_argument("--start-timeout", type=float, default=60)
    ap.add_argument("--feed-timeout", type=float, default=90)
    ap.add_argument("--quiet-window", type=float, default=20)
    ap.add_argument("--click-timeout", type=float, default=300)
    ap.add_argument(
        "--work-dir", default=None, help="for temporary files (default: TEMP)"
    )
    return ap


def check_setup(args: argparse.Namespace) -> None:
    if sys.platform != "win32":
        raise SetupError("this test runs on Windows only")
    if os.environ.get("USERNAME") != SANDBOX_USER and not args.outside_sandbox:
        raise SetupError(
            "this does not look like Windows Sandbox. It installs and runs "
            "things; pass --outside-sandbox if you mean it"
        )
    if not Path(args.winsparkle_tool).is_file():
        raise SetupError(f"no winsparkle-tool at {args.winsparkle_tool}")
    if args.browser is None:
        found = [p for p in default_browser_paths() if p.is_file()]
        if not found:
            raise SetupError("no installed browser found, pass --browser")
        args.browser = str(found[0])
    chrome = Path(args.browser)
    if not chrome.is_file():
        raise SetupError(f"no browser at {chrome}")
    if not is_installed_copy(chrome):
        raise SetupError(
            f"{chrome} has no <version>\\Installer\\setup.exe beside it, so its "
            "updater is off. Install version A from its installer first"
        )
    if args.installed_release is None:
        args.installed_release = rename_release.read_boring_release(
            DEFAULT_RELEASE_HEADER
        )
    if args.real_installer and not Path(args.real_installer).is_file():
        raise SetupError(f"no installer at {args.real_installer}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.list:
        for case in CASES:
            tag = " [click]" if case.needs_click else ""
            print(f"{case.name}{tag}: {case.what}")
        return 0
    try:
        check_setup(args)
    except (SetupError, OSError) as error:
        print(f"setup: {error}", file=sys.stderr)
        return CONFIG_ERROR

    failed = False
    work_root = args.work_dir or None
    with tempfile.TemporaryDirectory(prefix="boring-update-test-", dir=work_root) as w:
        try:
            harness = Harness(args, Path(w))
        except (SetupError, OSError) as error:
            print(f"setup: {error}", file=sys.stderr)
            return CONFIG_ERROR
        print(f"browser {harness.chrome}, compares as {harness.installed}")
        print(f"test key {harness.public_key} (throwaway, deleted after)")
        try:
            for case, skip in selected_cases(args):
                if skip:
                    print(result_line(case, None, skip), flush=True)
                    continue
                print(f"-- {case.name}: {case.what}", flush=True)
                try:
                    observation = getattr(harness, case.name)()
                    verdict = VERDICTS[case.name](observation)
                    for note in observation.notes:
                        print(f"  {note}")
                except (OSError, SetupError, make_appcast.SigningError) as error:
                    verdict = Verdict(False, f"error: {error}")
                failed |= not verdict.passed
                print(result_line(case, verdict), flush=True)
        finally:
            harness.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
