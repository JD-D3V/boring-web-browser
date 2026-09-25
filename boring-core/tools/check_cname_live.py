#!/usr/bin/env python3
"""Check CNAME uncloaking against real cloaked trackers, over the internet.

Not part of smoke_all: it depends on hosts we do not control. Each host
below is a first party name that no list blocks, but whose DNS alias
points at a tracker the lists do block (found through AdGuard's
cname-trackers list on 2026-09-25). Expected:

  blocking off        the host answers (otherwise the host is skipped)
  strict secure DNS   blocked, because the alias is blocked (default)
  automatic DNS       answers: uncloaking only looks names up while
                      secure DNS is strict, so it stands aside here

A fetch in no-cors mode fails only when the browser refuses it or the
host does not answer at all, which is why a host must first be seen to
answer with blocking off.

Usage: python check_cname_live.py   (uses BORING_OUT like drive.py)
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from drive import Browser

FETCH = """
var done = arguments[1];
fetch(arguments[0] + '?t=' + Date.now(), {mode: 'no-cors', cache: 'no-store'})
    .then(() => done('loaded'), () => done('failed'));
"""

HOSTS = [
    "https://icmiwe.tacticalthreads.co.uk/",  # alias of dnsdelegation.io
    "https://metrics.secure.eurocard.com/",  # alias of *.sc.omtrdc.net
    "https://jtcqp.zjoxa.com/",  # alias of customers.xray-superpixel.com
]


def run(label, args=(), dns_mode=None):
    profile = Path(tempfile.mkdtemp(prefix="cname-", dir=os.environ.get("TMP")))
    if dns_mode:
        # Local State is read at startup, so this is the mode the
        # browser runs in, as if chosen on the settings page.
        state = {"dns_over_https": {"mode": dns_mode}}
        (profile / "Local State").write_text(json.dumps(state))
    with Browser(user_data_dir=str(profile), args=list(args)) as b:
        b.get("https://example.com/")
        time.sleep(6)  # let the lists load
        results = {host: b.run_async(FETCH, [host]) for host in HOSTS}
    print(label, json.dumps(results), flush=True)
    return results


def main():
    off = run("blocking off:", ["--disable-boring-adblock"])
    strict = run("secure DNS strict (default):")
    auto = run("secure DNS automatic:", dns_mode="automatic")
    passed = []
    for host in HOSTS:
        if off[host] != "loaded":
            print(f"SKIP {host}: does not answer even with blocking off")
            continue
        ok = strict[host] == "failed" and auto[host] == "loaded"
        passed.append(ok)
        word = "PASS" if ok else "FAIL"
        print(f"{word} {host}: strict={strict[host]} automatic={auto[host]}")
    if not passed:
        print("SKIP: no test host answered; find new ones before trusting this")
    return 0 if passed and all(passed) else 1


if __name__ == "__main__":
    sys.exit(main())
