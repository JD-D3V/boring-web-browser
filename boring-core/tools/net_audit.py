#!/usr/bin/env python3
r"""Record everywhere the browser goes when nobody asks it to go anywhere.

"Nothing phones home" is a claim, and a claim about network behaviour is
only worth what a packet log says. This runs the browser in a profile of
its own, with Chromium's own net log on, does one scenario, then reads
the log back and lists every host that was contacted and every name that
was looked up.

The raw net log stays under E:\tmp and is deleted at the end unless
--keep is given. Only the host list is written to the report, so nothing
from a page and no credential can reach the artifacts folder. The
capture mode is the default one, which already leaves out cookies,
authentication headers and response bodies.

Scenarios:
  first-run   start with a brand new profile and sit on the welcome page
  idle        start on the new tab page and wait, touching nothing
  lists       force a blocking list check. Silent while the build has no
              list publishing key, the one request we make once it does
  opt-out     list updates and AI off, then wait

Usage:
  python net_audit.py --scenario idle --seconds 120
  python net_audit.py --all
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from drive import OFFSCREEN, Browser

OUT = Path(__file__).resolve().parents[2] / "artifacts/release-readiness/network"
TMP = Path(os.environ.get("TMP", r"E:\tmp"))
# The same environment variable drive.py reads, so a capture and a smoke
# run can never end up pointed at different builds.
CHROME = (
    Path(os.environ.get("BORING_OUT", r"E:\ung\build\src\out\Default")) / "chrome.exe"
)

# Hosts that are the machine talking to itself, not the browser talking
# to anyone. Windows looks for a proxy configuration on every network.
LOCAL_NAMES = {"wpad", "localhost", "127.0.0.1", "::1"}

# Hosts the browser reaches by design, with what for. Listed so the
# report names the purpose, never so they are hidden: they are still
# printed among the hosts reached. Anything not here is unexplained.
KNOWN_PURPOSES = {
    "dns.quad9.net": (
        "secure DNS (the default resolver, replacing the system one; it "
        "answers name lookups the browser was going to make anyway)"
    ),
    "jd-d3v.github.io": (
        "browser update feed, once a day, installed copies with an update key only"
    ),
    "github.com": "blocking list feed, only with a list signing key",
}

SCENARIOS = {
    # The positive control, and it runs first for a reason. A capture
    # that silently sees nothing and a browser that sends nothing write
    # the same empty report, so every other result here is worthless
    # until this one has shown that traffic of a known shape is
    # actually observed. It is the only scenario that fails by being
    # quiet.
    "control": {
        "args": ["--no-first-run"],
        "urls": ["https://example.com/"],
        "first_run": False,
        "is_control": True,
        "expect_traffic": True,
        "expect_host": "example.com",
    },
    "first-run": {
        "args": [],
        "urls": ["chrome://boring-welcome"],
        "first_run": True,
    },
    "idle": {
        "args": ["--no-first-run"],
        "urls": ["chrome://boring-newtab"],
        "first_run": False,
    },
    "lists": {
        "args": ["--no-first-run", "--boring-check-lists-now"],
        "urls": ["chrome://boring-newtab"],
        "first_run": False,
        # The updater runs when a tab is created, and a URL on the
        # command line becomes a tab during startup, which does not
        # trigger it. Without this the scenario reported "no traffic"
        # about a code path it never reached, which is worse than not
        # testing it, because it looked like evidence. Opening the tab
        # through the driver does reach it: verified by hand, the
        # marker reads outcome=network and the feed path is in the log.
        #
        # A build that trusts no real publishing key does not look for
        # lists at all (ListUpdater::CanUpdate), so here even a forced
        # check must stay silent. Once the real key is in, put back
        # "expect_traffic": True and "expect_host": "github.com".
        "use_driver": True,
    },
    "opt-out": {
        "args": [
            "--no-first-run",
            "--disable-boring-list-updates",
        ],
        "urls": ["chrome://boring-newtab"],
        "first_run": False,
    },
}


def hosts_in(netlog_path: Path) -> tuple[Counter, Counter]:
    """Every host a request went to, and every name that was resolved.

    A net log from a browser that was killed rather than closed is cut
    off mid array, so the tail is repaired. Repair only after a real
    parse failure, though: a browser closed cleanly writes a complete
    log, and patching a closing bracket onto that turns something valid
    into "Extra data" and loses the whole run.
    """
    text = netlog_path.read_text(encoding="utf-8", errors="replace")
    try:
        log = json.loads(text)
    except ValueError:
        try:
            log = json.loads(text.rstrip().rstrip(",") + "]}")
        except ValueError as e:
            sys.exit(f"could not read {netlog_path}: {e}")

    requested = Counter()
    resolved = Counter()
    for event in log.get("events", []):
        params = event.get("params") or {}
        url = params.get("url")
        if isinstance(url, str) and "://" in url:
            scheme = urlsplit(url).scheme
            host = urlsplit(url).hostname
            # chrome:// and data: are the browser drawing its own
            # pages. They never leave the process.
            if host and scheme in ("http", "https", "ws", "wss"):
                requested[host] += 1
        name = params.get("host")
        if isinstance(name, str):
            # Usually "host:port", but the resolver logs the secure DNS
            # server's own lookup as a URL ("https://dns.quad9.net"),
            # which a plain split turned into a host called "https".
            if "://" in name:
                name = urlsplit(name).hostname or ""
            else:
                name = name.split(":")[0]
            if name:
                resolved[name] += 1
    return requested, resolved


def run_scenario(name: str, seconds: int, keep: bool) -> dict:
    spec = SCENARIOS[name]
    profile = Path(tempfile.mkdtemp(prefix=f"netaudit-{name}-", dir=TMP))
    netlog = profile / "net-log.json"
    args = [
        str(CHROME),
        f"--user-data-dir={profile}",
        f"--log-net-log={netlog}",
        "--net-log-capture-mode=Default",
        "--no-default-browser-check",
        "--window-size=1200,900",
        # Off every real monitor. This audit runs a browser for a
        # couple of minutes per scenario, and it is not entitled to
        # put windows on the screen of whoever is using the machine.
        # Same position and same override as drive.py, so there is one
        # answer to "where do our windows go".
        "--window-position=" + os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN),
        *spec["args"],
        *spec["urls"],
    ]
    print(f"\n=== {name}: {seconds}s ===")

    if spec.get("use_driver"):
        # Everything the raw launch would have passed, minus the URL and
        # the profile, which the driver supplies itself.
        driver_args = [a for a in args[1:] if not a.startswith("--user-data-dir=")]
        driver_args = [a for a in driver_args if a not in spec["urls"]]
        print(" ", " ".join(driver_args))
        with Browser(user_data_dir=str(profile), args=driver_args) as b:
            for url in spec["urls"]:
                b.get(url)
            time.sleep(seconds)
        return _read_result(name, spec, seconds, profile, netlog, keep)

    print(" ", " ".join(args[1:]))
    process = subprocess.Popen(args)
    try:
        time.sleep(seconds)
    finally:
        # Closed, not killed, so Chromium finishes writing the log.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T"],
            capture_output=True,
        )
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
            )
            process.wait(timeout=30)

    return _read_result(name, spec, seconds, profile, netlog, keep)


def _read_result(name, spec, seconds, profile, netlog, keep) -> dict:
    """Read the net log back and summarise it. Shared by both launchers."""
    if not netlog.exists():
        sys.exit(f"{name}: the browser wrote no net log")
    requested, resolved = hosts_in(netlog)
    expect_traffic = bool(spec.get("expect_traffic"))
    expect_host = spec.get("expect_host")
    result = {
        "scenario": name,
        "seconds": seconds,
        "is_control": bool(spec.get("is_control")),
        "expect_traffic": expect_traffic,
        "requests_by_host": dict(requested.most_common()),
        "names_looked_up": dict(resolved.most_common()),
        "offmachine_hosts": sorted(
            host
            for host in set(requested) | set(resolved)
            if host not in LOCAL_NAMES and not host.endswith(".local")
        ),
    }
    if keep:
        kept = TMP / f"net-log-{name}.json"
        shutil.copy2(netlog, kept)
        result["netlog"] = str(kept)
        print("  kept the raw log at", kept)
    shutil.rmtree(profile, ignore_errors=True)

    if expect_traffic:
        # Two separate things have to be seen: a request, and a name
        # resolved. They come from different parts of the log, so one
        # working does not vouch for the other.
        saw_request = expect_host in requested
        saw_lookup = expect_host in resolved
        result["capture_proven"] = bool(saw_request and saw_lookup)
        result["capture_detail"] = (
            f"{expect_host}: {requested.get(expect_host, 0)} request(s), "
            f"{resolved.get(expect_host, 0)} lookup(s)"
        )
        print("  capture check:", result["capture_detail"])

    print("  hosts contacted:", result["offmachine_hosts"] or "none")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seconds", type=int, default=90)
    ap.add_argument(
        "--keep",
        action="store_true",
        help="keep the raw net log under E:\\tmp for a closer look",
    )
    args = ap.parse_args()
    if not args.all and not args.scenario:
        ap.error("give --scenario NAME or --all")
    if not CHROME.exists():
        sys.exit(f"no browser at {CHROME}")

    OUT.mkdir(parents=True, exist_ok=True)
    if args.all:
        # Control first, so a broken capture is known before eight
        # minutes are spent collecting evidence that would not mean
        # anything.
        names = ["control"] + [n for n in sorted(SCENARIOS) if n != "control"]
    else:
        names = [args.scenario]
    results = [run_scenario(name, args.seconds, args.keep) for name in names]

    controls = [r for r in results if r.get("is_control")]
    # Every scenario that must produce traffic, not just the control.
    unproven = [
        r for r in results if r.get("expect_traffic") and not r.get("capture_proven")
    ]

    report = OUT / "net-audit.json"
    report.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("\nwrote", report)

    # The control is not one result among several. It decides whether
    # the rest of them are evidence at all.
    if controls:
        if unproven:
            print("\nCAPTURE NOT PROVEN")
            for r in unproven:
                print(
                    "  "
                    + r["scenario"]
                    + ": "
                    + r.get("capture_detail", "no traffic seen")
                )
            print(
                "\nA scenario that must produce traffic produced none. For "
                "the control that means the capture cannot observe traffic, so "
                "no other result here is evidence of anything. For any other "
                "scenario it means the code path it exists to exercise was "
                "never reached, so its silence says nothing. Either way, fix "
                "it before reading the rest."
            )
            return 1
        print("\ncapture proven: expected traffic was observed")

    audited = [r for r in results if not r.get("is_control")]
    everywhere = sorted({h for r in audited for h in r["offmachine_hosts"]})
    names_run = ", ".join(r["scenario"] for r in audited)
    print("\nHosts reached in the audited scenarios (" + names_run + "):")
    for host in everywhere or ["none"]:
        purpose = KNOWN_PURPOSES.get(host, "UNEXPLAINED" if everywhere else "")
        print("  " + host + ("  -- " + purpose if purpose else ""))
    print(
        "\nThis reads as: in these scenarios, over "
        + str(args.seconds)
        + "s each, the browser reached "
        + ("only the hosts above" if everywhere else "no host at all")
        + ". It is not a guarantee about every code path, every setting, "
        "or a longer run."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
