#!/usr/bin/env python3
r"""Check "Warn about scam tricks" in the real build.

Two guards, one switch on the Protection page:
  - remote access guard: a download of a remote control tool (AnyDesk,
    TeamViewer) is held and a bar asks first, with "Don't download" as the
    main button. An ordinary download, even an .exe, is left alone.
  - ClickFix guard: a page that copies a PowerShell or cmd one-liner to
    the clipboard gets a harmless line there instead, and a quiet bar. An
    ordinary copy, even an "npm install" command, works.

Test pages are served from a *.localhost name (HTTPS-Only is on, and
localhost names are the plain-http ones it leaves alone). The browser runs
headless, so a page that goes fullscreen cannot cover a real display, and
input goes through DevTools, never to the desktop.

A bar is native browser UI, which WebDriver cannot see, so the browser is
started with logging on and each bar says its wording in the log. The
answers to a question bar come from --boring-guards-test-answer, a switch
that does nothing unless given. Copies from pages are logged and dropped
by --boring-guards-test-clipboard, so the real Windows clipboard is never
touched, and the text a copy would have put there is read from the log.

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
WORK = Path(os.environ.get("TMP", r"E:\tmp")) / "feat-scam-guards" / "smoke"
GET_ME_OUT = "chrome://boring-takeover/"
BAR = "boring-guards: bar: "
CLIP = "boring-guards: clipboard: "

# The wording, as decided. A change here is a change to what people read.
ASK = (
    "Scammers ask people to install this so they can control the computer. "
    "Only continue if you started this yourself."
)
ASK_STRONG = (
    "This tab looked like a scam. Scammers ask people to install this so "
    "they can control the computer. Do not continue."
)
NOTICE = (
    "This page tried to copy a command. Real sites do not ask you to "
    "paste commands into Windows."
)
NOTICE_STRONG = (
    "This page tried to copy a command, and it looks like a scam. Do not "
    "paste it. Close the tab."
)
REPLACEMENT = "Blocked: this page tried to copy a command."
ORDINARY = "See you at 5pm, bring the report"
DOCS = "npm install --save-dev typescript"

EXE = b"MZ" + b"\0" * 4094


class Handler(http.server.SimpleHTTPRequestHandler):
    """testdata/ as it is, plus a few files that are downloads."""

    files = {
        "/AnyDesk.exe": ("application/octet-stream", EXE, "AnyDesk.exe"),
        "/files/tool.bin": ("application/octet-stream", EXE, None),
        "/NotepadPlus-setup.exe": (
            "application/octet-stream",
            EXE,
            "NotepadPlus-setup.exe",
        ),
        "/report.csv": ("text/csv", b"a,b\n1,2\n", "report.csv"),
    }

    def do_GET(self):
        entry = self.files.get(self.path.split("?")[0])
        if not entry:
            return super().do_GET()
        kind, body, name = entry
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        if name:
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args, **kwargs):
        pass


def serve():
    handler = functools.partial(Handler, directory=str(DATA))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# --- clicks, through DevTools: a real user gesture, nothing on the desktop

def cdp(b, cmd, params):
    return b._req(
        "POST", f"/session/{b.sid}/goog/cdp/execute", {"cmd": cmd, "params": params}
    )


def click(b, x, y):
    for kind in ("mousePressed", "mouseReleased"):
        cdp(
            b,
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
        )


def click_id(b, element):
    x, y = b.run(
        "var r = document.getElementById(arguments[0]).getBoundingClientRect();"
        "return [r.x + r.width / 2, r.y + r.height / 2]",
        [element],
    )
    click(b, x, y)


# --- one browser, with its own profile, download folder and log --------


class Session:
    def __init__(self, name, port, answer=None, remote=False):
        # remote: the pages are on a name that is not localhost, to show the
        # test switches do nothing there.
        self.base = f"http://{'guards.example' if remote else 'guards.localhost'}:{port}"
        self.root = WORK / name
        shutil.rmtree(self.root, ignore_errors=True)
        self.dl = self.root / "dl"
        self.log = self.root / "chrome.log"
        profile = self.root / "profile"
        (profile / "Default").mkdir(parents=True)
        self.dl.mkdir()
        prefs = {
            "download": {"default_directory": str(self.dl), "prompt_for_download": False},
            "savefile": {"default_directory": str(self.dl)},
        }
        if remote:
            # Plain http on a non-localhost name needs HTTPS-Only off.
            prefs["https_only_mode_enabled"] = False
            prefs["https_first_balanced_mode_enabled"] = False
        (profile / "Default" / "Preferences").write_text(json.dumps(prefs))
        args = [
            "--headless=new",
            "--enable-logging",
            "--log-level=0",
            f"--log-file={self.log}",
            "--boring-guards-test-clipboard",
        ]
        if answer:
            args.append(f"--boring-guards-test-answer={answer}")
        if remote:
            args.append("--host-resolver-rules=MAP guards.example 127.0.0.1")
        self.seen = 0
        self.b = Browser(user_data_dir=str(profile), args=args)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.b.quit()

    def click_id(self, element):
        click_id(self.b, element)

    def open_tab(self):
        h = self.b._req(
            "POST", f"/session/{self.b.sid}/window/new", {"type": "tab"}
        )["value"]["handle"]
        self.b._req("POST", f"/session/{self.b.sid}/window", {"handle": h})

    def accept_alert(self):
        try:
            self.b._req("POST", f"/session/{self.b.sid}/alert/accept", {})
        except RuntimeError:
            pass

    def bars(self):
        """What the bars have said so far, in order."""
        try:
            text = self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [
            line.split(BAR, 1)[1].strip() for line in text.splitlines() if BAR in line
        ]

    def saved(self):
        return sorted(p.name for p in self.dl.iterdir())

    def copies(self):
        """What copies from pages would have put on the clipboard, in order.
        The browser logs them and drops them (--boring-guards-test-clipboard),
        so the real clipboard is never touched."""
        try:
            text = self.log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        return [
            json.loads(line.split(CLIP, 1)[1])
            for line in text.splitlines()
            if CLIP in line
        ]

    def read_clipboard(self):
        """The text of the copy just made, from the log."""
        wait(lambda: len(self.copies()) > self.seen, timeout=5)
        copies = self.copies()
        if len(copies) <= self.seen:
            return None
        self.seen = len(copies)
        return copies[-1]

    def copy_on(self, mode):
        """Opens the clipboard page in `mode` and presses its button."""
        self.seen = len(self.copies())
        self.b.get(f"{self.base}/scam_guards_clickfix.html?mode={mode}")
        wait(lambda: self.b.run("return !!document.getElementById('copy')"))
        self.click_id("copy")
        return wait(
            lambda: self.b.run("return document.title").startswith(("wrote", "error")),
            timeout=10,
        )

    def download(self, link):
        self.b.get(f"{self.base}/scam_guards_downloads.html")
        wait(lambda: self.b.run("return !!document.getElementById('anydesk')"))
        self.click_id(link)

    def diagnose(self, label):
        print(f"DIAG {label}: saved={self.saved()} bars={self.bars()}")


def wait(fn, timeout=15, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except RuntimeError:
            pass
        time.sleep(step)
    return False


def steady(fn, seconds=4):
    """True if `fn` stays true for `seconds`: for 'it did not happen'."""
    end = time.time() + seconds
    while time.time() < end:
        if not fn():
            return False
        time.sleep(0.25)
    return True


# --- the scenarios ------------------------------------------------------


def downloads_and_copies(s, checks):
    """The switch on, no one answering the bars."""
    # Ordinary downloads: no bar, and they land.
    s.download("ordinary-csv")
    checks["ordinary file downloads"] = wait(lambda: "report.csv" in s.saved())
    s.download("ordinary-exe")
    checks["ordinary .exe downloads"] = wait(
        lambda: "NotepadPlus-setup.exe" in s.saved()
    )
    checks["ordinary downloads show no bar"] = not s.bars()
    if not checks["ordinary file downloads"] or not checks["ordinary .exe downloads"]:
        s.diagnose("ordinary downloads")

    # A remote tool, by the name in the address.
    s.download("anydesk")
    checks["AnyDesk download shows the bar"] = wait(lambda: ASK in s.bars())
    checks["AnyDesk is held, not saved"] = steady(
        lambda: not any(n.startswith("AnyDesk") for n in s.saved()), seconds=4
    )
    # And by the download attribute.
    s.download("teamviewer")
    checks["TeamViewer download shows the bar"] = wait(
        lambda: s.bars().count(ASK) >= 2
    )
    checks["the bar is not the strong one"] = ASK_STRONG not in s.bars()
    if not checks["AnyDesk download shows the bar"]:
        s.diagnose("AnyDesk")

    # Copies.
    checks["an ordinary copy finishes"] = s.copy_on("ordinary")
    checks["an ordinary copy works"] = s.read_clipboard() == ORDINARY
    checks["an npm command copies"] = (
        s.copy_on("docs") and s.read_clipboard() == DOCS
    )
    checks["ordinary copies show no ClickFix bar"] = NOTICE not in s.bars()

    checks["a command copy finishes"] = s.copy_on("command")
    clip = s.read_clipboard()
    checks["the command is replaced on the clipboard"] = clip == REPLACEMENT
    checks["ClickFix bar shows"] = wait(lambda: NOTICE in s.bars())
    if clip != REPLACEMENT:
        print("DIAG clipboard after command copy:", repr(clip))
    checks["execCommand copy is replaced too"] = (
        s.copy_on("exec") and s.read_clipboard() == REPLACEMENT
    )

    # From a fullscreen page: stronger, and the page is taken out of it.
    s.b.get(f"{s.base}/scam_guards_clickfix.html?mode=fullscreen")
    wait(lambda: s.b.run("return !!document.getElementById('copy')"))
    s.click_id("copy")
    checks["fullscreen page goes fullscreen"] = wait(
        lambda: s.b.run("return !!document.fullscreenElement")
    )
    s.click_id("copy")
    checks["fullscreen copy: strong bar"] = wait(lambda: NOTICE_STRONG in s.bars())
    checks["fullscreen copy: page leaves fullscreen"] = wait(
        lambda: not s.b.run("return !!document.fullscreenElement"), timeout=8
    )
    checks["fullscreen copy: replaced"] = s.read_clipboard() == REPLACEMENT


def switch_off(s, checks):
    """The Protection switch turns both guards off, live."""
    s.b.get("chrome://boring-protection")
    checks["Protection has the switch"] = wait(
        lambda: s.b.run("return !!document.getElementById('warn-scam-tricks')")
    )
    if not checks["Protection has the switch"]:
        return
    checks["the switch is on by default"] = wait(
        lambda: s.b.run("return document.getElementById('warn-scam-tricks').checked")
    )
    label = s.b.run(
        "var l = document.querySelector('label[for=warn-scam-tricks]');"
        "return l ? l.textContent : ''"
    )
    checks["the switch says 'Warn about scam tricks'"] = (
        "Warn about scam tricks" in label
    )
    s.b.run("document.getElementById('warn-scam-tricks').click()")
    s.b.get("chrome://boring-protection")
    checks["the switch stays off after a reload"] = wait(
        lambda: s.b.run("return document.getElementById('warn-scam-tricks').checked")
        is False
    )

    bars_before = len(s.bars())
    checks["switch off: command copy finishes"] = s.copy_on("command")
    clip = s.read_clipboard() or ""
    checks["switch off: command is copied as it is"] = (
        "powershell" in clip and "iex" in clip and clip != REPLACEMENT
    )
    s.download("anydesk")
    checks["switch off: AnyDesk downloads"] = wait(lambda: "AnyDesk.exe" in s.saved())
    checks["switch off: no bar"] = steady(lambda: len(s.bars()) == bars_before, 2)
    if not checks["switch off: AnyDesk downloads"]:
        s.diagnose("switch off")


def answers(port, checks):
    """Both answers to the question bar."""
    with Session("stop", port, answer="safe") as s:
        s.download("anydesk")
        checks["Don't download: bar shows"] = wait(lambda: ASK in s.bars())
        time.sleep(6)
        checks["Don't download: nothing is saved"] = not any(
            n.startswith("AnyDesk") for n in s.saved()
        )
        if not checks["Don't download: nothing is saved"]:
            s.diagnose("stop")
    with Session("keep", port, answer="risk") as s:
        s.download("anydesk")
        checks["Download anyway: bar shows"] = wait(lambda: ASK in s.bars())
        checks["Download anyway: the file is saved"] = wait(
            lambda: "AnyDesk.exe" in s.saved(), timeout=30
        )
        if not checks["Download anyway: the file is saved"]:
            s.diagnose("keep")


def remote_page(port, checks):
    """The answer switch does nothing for a page that is not on localhost.
    (The clipboard switch is not driven here: without it a copy would reach
    the real clipboard. clipboard_guard.cc has the same localhost limit.)"""
    with Session("remote", port, answer="risk", remote=True) as s:
        s.download("anydesk")
        checks["not localhost: the question bar shows"] = wait(lambda: ASK in s.bars())
        time.sleep(6)
        checks["not localhost: nothing answers the bar"] = not any(
            n.startswith("AnyDesk") for n in s.saved()
        )
        if not checks["not localhost: nothing answers the bar"]:
            s.diagnose("remote")


def tripped_tab(port, checks):
    """A tab that tripped the takeover detector gets the strong wording."""
    with Session("strong", port, answer="safe") as s:
        s.open_tab()
        s.b.get(f"{s.base}/takeover_scam.html?mode=all")
        click(s.b, 200, 200)

        def tripped():
            s.accept_alert()
            return s.b.current_url().startswith(GET_ME_OUT)

        checks["takeover page trips"] = wait(tripped, timeout=30, step=0.4)
        if not checks["takeover page trips"]:
            return
        s.download("anydesk")
        checks["tripped tab: download bar is strong"] = wait(
            lambda: ASK_STRONG in s.bars()
        )
        checks["tripped tab: not the plain wording"] = ASK not in s.bars()
        s.copy_on("command")
        checks["tripped tab: copy bar is strong"] = wait(
            lambda: NOTICE_STRONG in s.bars()
        )


def main():
    checks = {}
    srv = serve()
    port = srv.server_address[1]
    try:
        with Session("main", port) as s:
            downloads_and_copies(s, checks)
            switch_off(s, checks)
        answers(port, checks)
        remote_page(port, checks)
        tripped_tab(port, checks)
    finally:
        srv.shutdown()

    ok = all(checks.values())
    for name, passed in checks.items():
        print(("PASS " if passed else "FAIL ") + name)
    print("smoke_scam_guards:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
