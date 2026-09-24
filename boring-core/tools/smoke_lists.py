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

import base64
import hashlib
import json
import os
import shutil
import subprocess
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
# Served on purpose although this version ships no scam list: a feed
# can offer whatever it likes, and the browser has to refuse it.
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


class TestKey:
    """A throwaway signing key, made here and thrown away at the end.

    The browser only trusts a manifest signed by a key built into it, so
    a test that serves its own bundle has to hand the browser its own
    key. --boring-list-key is only honoured for a feed on this machine,
    which is what this test serves, so nothing about this arrangement
    works against the real release host.

    This key is for this test and nothing else. It is not a publisher
    key and it is never installed anywhere.
    """

    def __init__(self, directory):
        self.pem = directory / "test-signing-key.pem"
        run_openssl(["ecparam", "-name", "prime256v1", "-genkey", "-noout",
                     "-out", str(self.pem)])
        spki = run_openssl(["ec", "-in", str(self.pem), "-pubout",
                            "-outform", "DER"], capture=True)
        self.spki_base64 = base64.b64encode(spki).decode("ascii")
        self.id = hashlib.sha256(spki).hexdigest()[:16]

    def sign(self, path):
        """Writes <path>.sig over the file's exact bytes."""
        signature = run_openssl(
            ["dgst", "-sha256", "-sign", str(self.pem), str(path)],
            capture=True,
        )
        sig_file = path.with_suffix(path.suffix + ".sig")
        sig_file.write_text(
            json.dumps(
                {
                    "alg": "ecdsa-p256-sha256",
                    "key": self.id,
                    "sig": base64.b64encode(signature).decode("ascii"),
                }
            ),
            encoding="utf-8",
        )


# openssl signs the test bundles. It is not on the Windows PATH here,
# but Git ships one and so does the Chromium tree. A release gate that
# reports a product failure because a helper binary was not on PATH is
# worse than no gate: it fails for a reason nobody reads, and the suite
# said "blocking list updates FAIL" when the list updater was fine.
OPENSSL_CANDIDATES = [
    r"C:\Program Files\Git\usr\bin\openssl.exe",
    r"C:\Program Files (x86)\Git\usr\bin\openssl.exe",
    os.path.join(
        os.environ.get("BORING_SRC", r"E:\ung\build\src"),
        "third_party", "git", "usr", "bin", "openssl.exe",
    ),
]


def openssl_path():
    """Where openssl is, or None. PATH first, then the usual places."""
    found = shutil.which("openssl")
    if found:
        return found
    for candidate in OPENSSL_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def run_openssl(args, capture=False):
    exe = openssl_path()
    if not exe:
        raise RuntimeError("openssl not found")
    result = subprocess.run(
        [exe, *args],
        capture_output=True,
        check=True,
    )
    return result.stdout if capture else None


def write_bundle(directory, version, break_hash=False, key=None, sign=True):
    """Writes a bundle the browser can download, or a broken one."""
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
    path = directory / "lists.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    if key and sign:
        key.sign(path)


def wait_for_file(path, timeout=20):
    """True once the file turns up, false at the timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.2)
    return False


def run_check(feed_url, downloads, profile, key, screenshot=None):
    """Opens the Protection page, which is what starts a check."""
    with Browser(
        user_data_dir=str(profile),
        args=[
            f"--boring-list-url={feed_url}",
            f"--boring-list-dir={downloads}",
            f"--boring-list-key={key.spki_base64}",
            "--boring-check-lists-now",
            "--window-size=1360,900",
        ],
    ) as b:
        b.get("chrome://boring-protection")
        # The marker is written when a check finishes, whether or not it
        # saved anything, so waiting for it is how the test knows the
        # answer is in rather than still on its way.
        finished = wait_for_file(downloads / "last-check")
        landed = finished and (downloads / "easylist.txt").exists()
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

    if not openssl_path():
        print("FAIL: openssl is needed to sign the test bundles, and it is "
              "not on PATH, nor in Git's copy, nor in the Chromium tree's")
        return 1

    with tempfile.TemporaryDirectory(prefix="lists-") as work:
        work = Path(work)
        key = TestKey(work)

        # A bundle that is what it says it is.
        good = work / "good"
        good.mkdir()
        write_bundle(good, version=900, key=key)
        server, feed_url = serve(good)
        downloads = work / "downloads-good"
        profile = work / "profile-good"
        try:
            landed, shows_age, has_switch = run_check(
                feed_url, downloads, profile, key, OUT / "protection-lists.png"
            )
        finally:
            server.shutdown()

        checks["a newer list is downloaded"] = landed
        checks["the downloaded list is the one served"] = (
            landed and (downloads / "easylist.txt").read_text() == FILTERS
        )
        # The feed above offers a scamlist.txt as well. This version
        # ships no scam list and must not start using one an update
        # feed hands it, so the file must not be here.
        checks["a scam list offered by the feed is refused"] = not (
            downloads / "scamlist.txt"
        ).exists()
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
        write_bundle(bad, version=901, break_hash=True, key=key)
        server, feed_url = serve(bad)
        downloads = work / "downloads-bad"
        profile = work / "profile-bad"
        try:
            landed, _, _ = run_check(feed_url, downloads, profile, key)
        finally:
            server.shutdown()

        checks["a list that fails its hash is refused"] = not landed
        checks["a refused list leaves nothing behind"] = not list(
            downloads.glob("*.part")
        )

        # A bundle nobody signed. The hashes in it are perfectly
        # correct, which is the point: hashes say the file arrived
        # whole, not who wrote it. Anyone able to replace the files on
        # the release host can write matching hashes too.
        unsigned = work / "unsigned"
        unsigned.mkdir()
        write_bundle(unsigned, version=902, key=key, sign=False)
        server, feed_url = serve(unsigned)
        downloads = work / "downloads-unsigned"
        profile = work / "profile-unsigned"
        try:
            landed, _, _ = run_check(feed_url, downloads, profile, key)
        finally:
            server.shutdown()

        checks["an unsigned manifest is refused"] = not landed
        marker = downloads / "last-check"
        checks["the refused check is written down as a signature failure"] = (
            marker.exists() and "outcome=signature" in marker.read_text()
        )

        # A bundle signed by a key the browser does not trust. Same
        # shape as the real thing, wrong hands.
        wrong = work / "wrong-key"
        wrong.mkdir()
        # The key lives outside the folder being served, because the
        # folder being served is on a web server.
        other_key_dir = work / "other-key"
        other_key_dir.mkdir()
        other = TestKey(other_key_dir)
        write_bundle(wrong, version=903, key=other)
        server, feed_url = serve(wrong)
        downloads = work / "downloads-wrong"
        profile = work / "profile-wrong"
        try:
            landed, _, _ = run_check(feed_url, downloads, profile, key)
        finally:
            server.shutdown()

        checks["a manifest signed by the wrong key is refused"] = not landed

    (OUT / "lists-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
