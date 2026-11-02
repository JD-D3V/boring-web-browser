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

The hosts and what each is for come from connections.json, the same list
the Protection page shows. A host outside that list fails the run.

Scenarios:
  first-run   start with a brand new profile and sit on the welcome page
  idle        start on the new tab page and wait, touching nothing
  lists       force a blocking list check. Silent while the build has no
              list publishing key, the one request we make once it does
  opt-out     list updates and AI off, then wait
  all-off     every "On its own" switch off, as the Protection page writes
              them. Must reach no host at all

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

import focus_lock
from drive import CHROME as DRIVE_CHROME, OFFSCREEN, Browser

CHROME = Path(DRIVE_CHROME)

OUT = Path(__file__).resolve().parents[2] / "artifacts/release-readiness/network"
TMP = Path(os.environ.get("TMP", r"E:\tmp"))
# Hosts that are the machine talking to itself, not the browser talking
# to anyone. Windows looks for a proxy configuration on every network.
LOCAL_NAMES = {"wpad", "localhost", "127.0.0.1", "::1"}

# Everything the browser reaches by design, with what for, from the one
# list the Protection page also draws its rows from. Listed so the report
# names the purpose, never so they are hidden: they are still printed among
# the hosts reached. Anything not here is unexplained, and fails the run.
CONNECTIONS = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "components/boring/protection/connections.json"
    ).read_text(encoding="utf-8")
)["connections"]
KNOWN_PURPOSES = {
    host: entry["label"] + ": " + entry["why"]
    for entry in CONNECTIONS
    for host in entry["hosts"]
}


def all_off_seed():
    """The settings the Protection switches write when every connection
    is turned off, as the profile's Preferences and the machine's Local
    State. tools/smoke_connections.py checks that each switch really writes
    these values, so this scenario tests what a person who turned them all
    off gets. Switches with no file behind them (the updater lives in the
    registry, the store extension is a profile entry) have nothing to seed:
    a fresh profile has no store add-ons to check, and an unsigned build
    never looks for an update."""
    prefs, local_state = {}, {}
    for entry in CONNECTIONS:
        switch = entry["switch"]
        if switch["kind"] not in ("profile", "local_state"):
            continue
        target = prefs if switch["kind"] == "profile" else local_state
        node = target
        *path, leaf = switch["pref"].split(".")
        for part in path:
            node = node.setdefault(part, {})
        node[leaf] = switch["off"]
    return prefs, local_state


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
    # Every "On its own" switch on the Protection page turned off. It must
    # reach no host at all, not even a name lookup.
    "all-off": {
        "args": ["--no-first-run"],
        "urls": ["chrome://boring-newtab"],
        "first_run": False,
        "seed_all_off": True,
        "must_reach_nothing": True,
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
    if spec.get("seed_all_off"):
        prefs, local_state = all_off_seed()
        (profile / "Default").mkdir()
        (profile / "Default" / "Preferences").write_text(json.dumps(prefs), "utf-8")
        (profile / "Local State").write_text(json.dumps(local_state), "utf-8")
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
        "must_reach_nothing": bool(spec.get("must_reach_nothing")),
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
    elif args.scenario == "control":
        names = ["control"]
    else:
        # A single scenario still gets the control first: silence only
        # means something once the capture has been seen to work.
        names = ["control", args.scenario]
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
    unexplained = [h for h in everywhere if h not in KNOWN_PURPOSES]
    leaked = [r for r in audited if r["must_reach_nothing"] and r["offmachine_hosts"]]
    print(
        "\nThis reads as: in these scenarios, over "
        + str(args.seconds)
        + "s each, the browser reached "
        + ("only the hosts above" if everywhere else "no host at all")
        + ". It is not a guarantee about every code path, every setting, "
        "or a longer run."
    )
    failed = False
    if unexplained:
        print("\nFAIL: hosts that are not in connections.json:", ", ".join(unexplained))
        failed = True
    for r in leaked:
        print(
            "\nFAIL: "
            + r["scenario"]
            + " reached "
            + ", ".join(r["offmachine_hosts"])
            + " with every switch off"
        )
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    with focus_lock.hold():
        sys.exit(main())
