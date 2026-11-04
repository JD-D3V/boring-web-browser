#!/usr/bin/env python3
"""Small test driver for the built browser, using chromedriver.

Talks plain WebDriver HTTP, so it needs nothing installed. Tests use
headless Chromium unless they explicitly need and opt into native windows.

Usage as a library:
    from drive import Browser
    with Browser() as b:
        b.get("https://example.com")
        print(b.run("return document.title"))
"""

import atexit
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

OUT = os.environ.get("BORING_OUT", r"E:\ung-154\build\src\out\Default")
CHROME = os.path.join(OUT, "chrome.exe")
DRIVER = os.path.join(OUT, "chromedriver.exe")


def _scratch_profile():
    """A profile of this test's own, removed when it exits.

    Two things went wrong with one shared directory. A profile written
    by one Chromium version and handed to another migrates itself, and a
    browser busy upgrading a profile is not the browser the test meant
    to check. And every test sharing one profile means one test's
    leftovers decide what the next one sees: a switch still turned on,
    a dialog already dismissed, a list already cached. A suite whose
    result depends on the order it ran in is not measuring the browser.

    Each test process therefore gets its own, under TMP so it is on the
    build drive rather than C:. BORING_PROFILE still overrides it, for
    the times when keeping a profile to look at afterwards is the point.
    """
    chosen = os.environ.get("BORING_PROFILE")
    if chosen:
        return chosen
    path = tempfile.mkdtemp(prefix="boring-profile-", dir=os.environ.get("TMP") or None)
    # Chrome can still be letting go of files as the process exits, so a
    # failure to remove the directory is not worth failing a test over.
    atexit.register(shutil.rmtree, path, True)
    return path


PROFILE = _scratch_profile()

# Far enough left and up that no window lands on any real monitor.
OFFSCREEN = "-32000,-32000"


def free_port():
    """Pick a port nobody is listening on, and let the driver take it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def headful_allowed():
    return os.environ.get("BORING_ALLOW_HEADFUL") == "1"


def require_headful():
    if not headful_allowed():
        raise RuntimeError(
            "This check needs native browser windows. Run it in a dedicated "
            "Windows test session with BORING_ALLOW_HEADFUL=1."
        )


class Browser:
    def __init__(
        self, user_data_dir=None, args=None, keep_switches=None, *, headful=False
    ):
        # Moving a window off screen still lets it take the foreground.
        if headful:
            require_headful()
        args = list(args or ())
        # ChromeDriver sorts switches by name. An empty name would emit
        # a bare "--" before --headless, ending Chromium switch parsing.
        switch_names = [arg.removeprefix("--").split("=", 1)[0] for arg in args]
        if "" in switch_names:
            raise ValueError("ChromeDriver arguments must have a switch name")
        if not headful:
            args = [
                arg
                for arg, name in zip(args, switch_names, strict=True)
                if name != "headless"
            ]
            args.append("--headless=new")
        # A fixed port meant that a chromedriver left behind by another
        # session, with a different environment, kept the port and every
        # test silently talked to it instead. A whole run reported
        # failures that had nothing to do with the browser. One free
        # port per driver, so the only driver we can reach is ours.
        self.port = free_port()
        self.proc = subprocess.Popen(
            [DRIVER, f"--port={self.port}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.base = f"http://127.0.0.1:{self.port}"
        for _ in range(50):
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"chromedriver exited with {self.proc.returncode} "
                    f"before it accepted a connection on port {self.port}"
                )
            try:
                self._req("GET", "/status")
                break
            except Exception:
                time.sleep(0.2)
        else:
            self.proc.terminate()
            raise RuntimeError(
                f"chromedriver did not answer on port {self.port} in 10s"
            )
        position = (
            os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN)
            if headful
            else OFFSCREEN
        )
        chrome_args = [
            "--no-first-run",
            "--disable-fre",
            "--remote-allow-origins=*",
            # An offscreen window is treated as occluded and stops
            # painting, which photographs blank. These keep it drawing.
            "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion",
            "--window-position=" + position,
        ]
        if user_data_dir:
            chrome_args.append("--user-data-dir=" + user_data_dir)
        if args:
            chrome_args.extend(args)
        options = {"binary": CHROME, "args": chrome_args}
        if keep_switches:
            # chromedriver turns several browser features off before it
            # hands the window over, --disable-popup-blocking among
            # them. A test that is about one of those features has to
            # ask for it back, or it tests a browser nobody runs.
            options["excludeSwitches"] = list(keep_switches)
        caps = {"capabilities": {"alwaysMatch": {"goog:chromeOptions": options}}}
        try:
            self.sid = self._new_session(caps)
        except BaseException:
            self.proc.terminate()
            raise

    # chromedriver intermittently reports "chrome not reachable" when
    # sessions are started back to back, which is what a smoke suite
    # does. It is the driver's handshake rather than the browser:
    # launched directly with --remote-debugging-port the same binary
    # answers DevTools in under a second, every time, and a suite that
    # failed this way passes unchanged on the next run.
    #
    # Retrying is only honest because of that evidence. A browser that
    # genuinely would not start fails all three attempts and still
    # reports it, so this hides a flake without hiding a fault.
    SESSION_ATTEMPTS = 3
    SESSION_RETRY_DELAY = 2.0

    def _new_session(self, caps):
        for attempt in range(self.SESSION_ATTEMPTS):
            try:
                r = self._req("POST", "/session", caps)
                if attempt:
                    print(f"  (chromedriver needed {attempt + 1} attempts)")
                return r["value"]["sessionId"]
            except RuntimeError as e:
                last = e
                if "chrome not reachable" not in str(e):
                    raise
                if attempt + 1 < self.SESSION_ATTEMPTS:
                    time.sleep(self.SESSION_RETRY_DELAY)
        raise last

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            # WebDriver puts the actual reason in the body; keep it.
            detail = e.read().decode("utf-8", "replace")[:600]
            raise RuntimeError(f"{method} {path}: {e.code} {detail}") from e

    def get(self, url):
        return self._req("POST", f"/session/{self.sid}/url", {"url": url})

    def current_url(self):
        return self._req("GET", f"/session/{self.sid}/url")["value"]

    def run(self, script, args=None):
        """Run sync JavaScript in the page. Use a return statement."""
        body = {"script": script, "args": args or []}
        return self._req("POST", f"/session/{self.sid}/execute/sync", body)["value"]

    def run_async(self, script, args=None):
        """Run async JavaScript. The last argument is the done callback."""
        body = {"script": script, "args": args or []}
        return self._req("POST", f"/session/{self.sid}/execute/async", body)["value"]

    def screenshot(self, path):
        import base64

        b64 = self._req("GET", f"/session/{self.sid}/screenshot")["value"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))

    def quit(self):
        try:
            self._req("DELETE", f"/session/{self.sid}")
        finally:
            self.proc.terminate()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.quit()


if __name__ == "__main__":
    with Browser() as b:
        b.get("https://example.com")
        print("title:", b.run("return document.title"))
