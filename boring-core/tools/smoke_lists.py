#!/usr/bin/env python3
"""Check the browser keeps its blocking lists up to date, and safely.

Serves a pretend release host on this machine, points the browser at it
with --boring-list-url, and opens the Protection page, which is what
sets a check going. Checks that a good bundle is downloaded and put in
place, that a bundle whose hash does not match is refused, and that the
page says how old the lists are.

Nothing outside the temporary folders is touched: --boring-list-dir
keeps the downloads away from the lists this machine really browses
with.

Usage: python smoke_lists.py
"""

import hashlib
import json
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from drive import Browser

OUT = Path(__file__).resolve().parents[2] / "artifacts/ui-implemented"

FILTERS = "! pretend filter list\n||lists-smoke-test.invalid^\n"
SCAM = "# pretend scam blocklist\nboring-lists-test.invalid\n"


def serve(directory):
    """Starts a web server on a spare port and returns it with its address."""
    handler = partial(QuietHandler, directory=str(directory))
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass


def write_bundle(directory, version, break_hash=False):
    """Writes a bundle the browser can download, or a corrupted one."""
    files = []
    for name, text in (("easylist.txt", FILTERS), ("scamlist.txt", SCAM)):
        data = text.encode("utf-8")
        (directory / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        if break_hash:
            # One flipped character is all it takes to fail the check.
            digest = ("0" if digest[0] != "0" else "1") + digest[1:]
        files.append({"name": name, "size": len(data), "sha256": digest})
    manifest = {"version": version, "updated": "2026-09-17", "files": files}
    (directory / "lists.json").write_text(json.dumps(manifest), encoding="utf-8")


def wait_for_file(path, timeout=20):
    """True once the file turns up, false at the timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.2)
    return False


def run_check(feed_url, downloads, profile, screenshot=None):
    """Opens the Protection page, which is what starts a check."""
    with Browser(
        user_data_dir=str(profile),
        args=[
            f"--boring-list-url={feed_url}",
            f"--boring-list-dir={downloads}",
            "--boring-check-lists-now",
            "--window-size=1360,900",
        ],
    ) as b:
        b.get("chrome://boring-protection")
        # The marker is written when a check finishes, whether or not it
        # saved anything, so waiting for it is how the test knows the
        # answer is in rather than still on its way.
        finished = wait_for_file(downloads / "last-check")
        landed = finished and (downloads / "scamlist.txt").exists()
        if screenshot:
            b.screenshot(str(screenshot))
        shows_age = b.run(
            "return !!document.getElementById('lists-age') && "
            "document.getElementById('lists-age').textContent.length > 0"
        )
        has_switch = b.run("return !!document.getElementById('list-updates')")
    return landed, shows_age, has_switch


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}

    with tempfile.TemporaryDirectory(prefix="lists-") as work:
        work = Path(work)

        # A bundle that is what it says it is.
        good = work / "good"
        good.mkdir()
        write_bundle(good, version=900)
        server, feed_url = serve(good)
        downloads = work / "downloads-good"
        profile = work / "profile-good"
        try:
            landed, shows_age, has_switch = run_check(
                feed_url, downloads, profile, OUT / "protection-lists.png"
            )
        finally:
            server.shutdown()

        checks["a newer list is downloaded"] = landed
        checks["the downloaded list is the one served"] = (
            landed and (downloads / "scamlist.txt").read_text() == SCAM
        )
        checks["both lists arrive"] = (downloads / "easylist.txt").exists()
        checks["the check is written down"] = (downloads / "last-check").exists()
        checks["the version is written down"] = (
            downloads / "last-check"
        ).exists() and "version=900" in (downloads / "last-check").read_text()
        checks["nothing half written is left behind"] = not list(
            downloads.glob("*.part")
        )
        checks["the page says how old the lists are"] = shows_age
        checks["the page has the updates switch"] = has_switch

        # A bundle whose hash does not match what arrived. This is the
        # one that matters: a list nobody can vouch for must not be used.
        bad = work / "bad"
        bad.mkdir()
        write_bundle(bad, version=901, break_hash=True)
        server, feed_url = serve(bad)
        downloads = work / "downloads-bad"
        profile = work / "profile-bad"
        try:
            landed, _, _ = run_check(feed_url, downloads, profile)
        finally:
            server.shutdown()

        checks["a list that fails its hash is refused"] = not landed
        checks["a refused list leaves nothing behind"] = not list(
            downloads.glob("*.part")
        )

    (OUT / "lists-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
