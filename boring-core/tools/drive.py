#!/usr/bin/env python3
"""Small test driver for the built browser, using chromedriver.

Talks plain WebDriver HTTP, so it needs nothing installed. Used by the
smoke test scripts to open pages and run checks inside the real build.

Usage as a library:
    from drive import Browser
    with Browser() as b:
        b.get("https://example.com")
        print(b.run("return document.title"))
"""

import json
import os
import subprocess
import time
import urllib.request

OUT = os.environ.get("BORING_OUT", r"E:\ung\build\src\out\Default")
CHROME = os.path.join(OUT, "chrome.exe")
DRIVER = os.path.join(OUT, "chromedriver.exe")
PORT = 9515


class Browser:
    def __init__(self, user_data_dir=None, args=None):
        self.proc = subprocess.Popen(
            [DRIVER, "--port=%d" % PORT],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.base = "http://127.0.0.1:%d" % PORT
        for _ in range(50):
            try:
                self._req("GET", "/status")
                break
            except Exception:
                time.sleep(0.2)
        chrome_args = ["--no-first-run", "--disable-fre",
                       "--remote-allow-origins=*"]
        if user_data_dir:
            chrome_args.append("--user-data-dir=" + user_data_dir)
        if args:
            chrome_args.extend(args)
        caps = {"capabilities": {"alwaysMatch": {
            "goog:chromeOptions": {"binary": CHROME, "args": chrome_args}}}}
        r = self._req("POST", "/session", caps)
        self.sid = r["value"]["sessionId"]

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())

    def get(self, url):
        return self._req("POST", "/session/%s/url" % self.sid, {"url": url})

    def current_url(self):
        return self._req("GET", "/session/%s/url" % self.sid)["value"]

    def run(self, script, args=None):
        """Run sync JavaScript in the page. Use a return statement."""
        body = {"script": script, "args": args or []}
        return self._req("POST", "/session/%s/execute/sync" % self.sid,
                         body)["value"]

    def run_async(self, script, args=None):
        """Run async JavaScript. The last argument is the done callback."""
        body = {"script": script, "args": args or []}
        return self._req("POST", "/session/%s/execute/async" % self.sid,
                         body)["value"]

    def screenshot(self, path):
        import base64
        b64 = self._req("GET", "/session/%s/screenshot" % self.sid)["value"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(b64))

    def quit(self):
        try:
            self._req("DELETE", "/session/%s" % self.sid)
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
