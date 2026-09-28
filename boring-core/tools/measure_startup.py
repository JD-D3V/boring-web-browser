#!/usr/bin/env python3
"""Measure startup: time to the first painted window and to the new tab page.

Reads Chromium's own startup histograms, which every Chromium build
records the same way, so our build and Google Chrome are measured by the
same code:

  Startup.BrowserWindow.FirstPaint             launch to first window paint
  Startup.FirstWebContents.NonEmptyPaint3      launch to the first page
                                               (the new tab page) painting

Both are milliseconds from process creation. They are read over the
DevTools protocol (Browser.getHistogram), so no automation flags change
how the browser starts. Each browser runs in a profile of its own under
TMP, never the person's real one.

Runs per browser:
  first   a brand new profile, launched once (includes profile creation)
  warm    the same profile launched again, several times

"Cold" in the sense of nothing in the disk cache needs a reboot, which a
script cannot do. The first run is the closest this gets; the report says
so rather than calling it cold.

Usage:
  python measure_startup.py --browser ours=E:\\...\\chrome.exe \\
      --browser chrome="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"

To keep a history, name the run and append it to a results file, one
JSON object per line, for example before and after a change:
  python measure_startup.py --browser ours=... --label "R2 startup deferral" \\
      --results artifacts/release-readiness/startup-history.jsonl
"""

import argparse
import base64
import json
import os
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

HISTOGRAMS = {
    "window": "Startup.BrowserWindow.FirstPaint",
    "newtab": "Startup.FirstWebContents.NonEmptyPaint3",
}
TIMEOUT = 60


class DevTools:
    """Just enough of a websocket client for the browser DevTools target."""

    def __init__(self, ws_url):
        parts = urlsplit(ws_url)
        self.sock = socket.create_connection((parts.hostname, parts.port), 10)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {parts.path} HTTP/1.1\r\nHost: {parts.netloc}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        reply = b""
        while b"\r\n\r\n" not in reply:
            reply += self.sock.recv(4096)
        if b" 101 " not in reply.split(b"\r\n", 1)[0]:
            raise RuntimeError("websocket handshake refused")
        self.buffer = reply.split(b"\r\n\r\n", 1)[1]
        self.next_id = 0

    def _recv(self, n):
        while len(self.buffer) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("DevTools closed")
            self.buffer += chunk
        data, self.buffer = self.buffer[:n], self.buffer[n:]
        return data

    def _send(self, text):
        payload = text.encode()
        mask = os.urandom(4)
        header = bytes([0x81])
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + n.to_bytes(2, "big")
        else:
            header += bytes([0x80 | 127]) + n.to_bytes(8, "big")
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def _read_message(self):
        message = b""
        while True:
            b0, b1 = self._recv(2)
            n = b1 & 0x7F
            if n == 126:
                n = int.from_bytes(self._recv(2), "big")
            elif n == 127:
                n = int.from_bytes(self._recv(8), "big")
            message += self._recv(n)
            if b0 & 0x80:
                return message.decode("utf-8", "replace")

    def call(self, method, **params):
        self.next_id += 1
        self._send(json.dumps({"id": self.next_id, "method": method, "params": params}))
        while True:
            reply = json.loads(self._read_message())
            if reply.get("id") == self.next_id:
                return reply

    def close(self):
        self.sock.close()


def histogram_ms(devtools, name):
    reply = devtools.call("Browser.getHistogram", name=name)
    histogram = reply.get("result", {}).get("histogram")
    if not histogram or not histogram.get("count"):
        return None
    return histogram["sum"] / histogram["count"]


def launch_once(exe, profile):
    port_file = profile / "DevToolsActivePort"
    if port_file.exists():
        port_file.unlink()
    proc = subprocess.Popen(
        [
            exe,
            f"--user-data-dir={profile}",
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
            # Off the desktop so nobody's work is interrupted. An
            # off-screen window counts as hidden and stops painting,
            # which would stop the paint being recorded, so these two keep
            # it drawing. Every browser measured gets the same flags.
            "--window-position=-32000,-32000",
            "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion",
            "chrome://newtab/",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + TIMEOUT
    while not port_file.exists() or port_file.stat().st_size == 0:
        if time.monotonic() > deadline:
            proc.kill()
            raise RuntimeError("no DevTools port")
        time.sleep(0.1)
    port, path = port_file.read_text().split()[:2]
    devtools = DevTools(f"ws://127.0.0.1:{port}{path}")
    result = {}
    try:
        while time.monotonic() < deadline and len(result) < len(HISTOGRAMS):
            for key, name in HISTOGRAMS.items():
                if key not in result:
                    value = histogram_ms(devtools, name)
                    if value is not None:
                        result[key] = value
            time.sleep(0.2)
        # Let the profile settle before closing, so the next launch is a
        # plain warm start rather than one racing a half-written profile.
        time.sleep(2)
        devtools.call("Browser.close")
    finally:
        devtools.close()
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True
        )
    time.sleep(2)
    return result


def summarise(values):
    values = [v for v in values if v is not None]
    if not values:
        return "n/a"
    return (
        f"median {statistics.median(values):.0f} ms "
        f"(min {min(values):.0f}, max {max(values):.0f}, n={len(values)})"
    )


def median_or_none(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values)) if values else None


def append_results(path, label, report):
    """Adds one line for this run, so runs can be compared later."""
    entry = {
        "label": label,
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "median_ms": {
            name: {
                f"{kind}_{key}": median_or_none(data[kind][key])
                for kind in ("first", "warm")
                for key in HISTOGRAMS
            }
            for name, data in report.items()
        },
        "raw": report,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", action="append", required=True, metavar="NAME=EXE")
    ap.add_argument("--warm-runs", type=int, default=5)
    ap.add_argument("--first-runs", type=int, default=3)
    ap.add_argument("--json", default=None, help="also write the numbers here")
    ap.add_argument(
        "--label", default="", help="a name for this run, kept with --results"
    )
    ap.add_argument(
        "--results",
        default=None,
        help="append this run, with its label and medians, to this file (JSON lines)",
    )
    args = ap.parse_args()
    report = {}
    for spec in args.browser:
        name, exe = spec.split("=", 1)
        first = {k: [] for k in HISTOGRAMS}
        warm = {k: [] for k in HISTOGRAMS}
        for _ in range(args.first_runs):
            profile = Path(
                tempfile.mkdtemp(prefix=f"startup-{name}-", dir=os.environ.get("TMP"))
            )
            r = launch_once(exe, profile)
            for k in HISTOGRAMS:
                first[k].append(r.get(k))
            if _ == 0:
                warm_profile = profile
            else:
                shutil.rmtree(profile, ignore_errors=True)
        for _ in range(args.warm_runs):
            r = launch_once(exe, warm_profile)
            for k in HISTOGRAMS:
                warm[k].append(r.get(k))
        shutil.rmtree(warm_profile, ignore_errors=True)
        report[name] = {"first": first, "warm": warm}
        print(f"{name}:")
        for label, data in (("first run, new profile", first), ("warm", warm)):
            print(f"  {label}:")
            print(f"    first painted window: {summarise(data['window'])}")
            print(f"    new tab page painted: {summarise(data['newtab'])}")
        sys.stdout.flush()
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1))
    if args.results:
        append_results(args.results, args.label, report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
