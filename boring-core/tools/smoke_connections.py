#!/usr/bin/env python3
"""Check "What the browser connects to", part "On its own", on the
Protection page.

  - There is one row for every connection in connections.json, showing its
    label, host and why line. The Secure DNS row says scam blocking gets
    weaker when it is off.
  - Each switch that can be used turns its connection off: the page reads
    off afterwards, and the file the browser wrote (Preferences or Local
    State) holds the value connections.json calls "off". That is the same
    value net_audit.py's all-off scenario starts a profile with, and that
    scenario then has to reach no host (run it after this, see
    net_audit.py --scenario all-off).
  - A switch that cannot do anything in this build (the updater, in a
    build with no update key) is disabled and says why.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from drive import Browser

CORE = Path(__file__).resolve().parents[1]
CONNECTIONS = json.loads(
    (CORE / "components/boring/protection/connections.json").read_text(encoding="utf-8")
)["connections"]
URL = "chrome://boring-protection"
TMP = os.environ.get("TMP", r"E:\tmp")


def wait_for(b, script, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if b.run(script):
            return True
        time.sleep(0.4)
    return False


READ_ROWS = """
  var out = {};
  document.querySelectorAll('#connections-own .setting-row').forEach(function(r) {
    var id = r.id.replace('conn-row-', '');
    var sw = document.getElementById('conn-' + id);
    out[id] = {text: r.innerText, on: sw.checked, disabled: sw.disabled};
  });
  return out;
"""


def read_file(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def dig(tree, dotted):
    for part in dotted.split("."):
        if not isinstance(tree, dict) or part not in tree:
            return None
        tree = tree[part]
    return tree


def main():
    failures = []
    profile = tempfile.mkdtemp(prefix="connections-", dir=TMP)
    clicked = []
    try:
        with Browser(user_data_dir=profile) as b:
            b.get(URL)
            n = len(CONNECTIONS)
            if not wait_for(
                b, f"return document.querySelectorAll('#connections-own .setting-row').length === {n}"
            ):
                failures.append(f"the section does not show {n} rows")
                raise SystemExit
            # The store extension arrives a moment after first start.
            wait_for(b, "return !document.getElementById('conn-web_store').disabled", 30)
            wait_for(
                b,
                "return document.getElementById('conn-detail-browser_updates').textContent !== ''",
                15,
            )
            rows = b.run(READ_ROWS)
            print("rows:", {k: (v["on"], v["disabled"]) for k, v in rows.items()})

            title = b.run("return document.getElementById('connections-title').textContent")
            if title != "What the browser connects to":
                failures.append(f"section title is {title!r}")

            for entry in CONNECTIONS:
                row = rows.get(entry["id"])
                if not row:
                    failures.append(f"{entry['id']}: no row")
                    continue
                for needle in [entry["label"], *entry["hosts"], entry["why"]]:
                    if needle not in row["text"]:
                        failures.append(f"{entry['id']}: row does not show {needle!r}")
                if entry.get("off_note") and entry["off_note"] not in row["text"]:
                    failures.append(f"{entry['id']}: row lacks its off note")
                if "\u2014" in row["text"]:
                    failures.append(f"{entry['id']}: em dash in row")
            if "scam blocking gets weaker" not in rows.get("secure_dns", {}).get("text", ""):
                failures.append("Secure DNS row does not say scam blocking gets weaker")
            if not rows.get("secure_dns", {}).get("on"):
                failures.append("Secure DNS is not on by default")

            # Turn off every switch that can be used.
            for entry in CONNECTIONS:
                row = rows.get(entry["id"])
                if not row:
                    continue
                if row["disabled"]:
                    detail = b.run(
                        "return document.getElementById('conn-detail-%s').textContent" % entry["id"]
                    )
                    if not detail:
                        failures.append(f"{entry['id']}: disabled with no reason shown")
                    print(f"{entry['id']}: switch disabled in this build: {detail}")
                    continue
                if not row["on"]:
                    failures.append(f"{entry['id']}: not on to start with")
                b.run(f"document.getElementById('conn-{entry['id']}').click(); return 1")
                clicked.append(entry["id"])
                if not wait_for(
                    b,
                    "var c = document.getElementById('conn-%s');"
                    "return c.checked === false" % entry["id"],
                    10,
                ):
                    failures.append(f"{entry['id']}: switch did not turn off")
                time.sleep(0.5)

            # The browser, not the page, must say they are off.
            b.get("about:blank")
            b.get(URL)
            wait_for(
                b, f"return document.querySelectorAll('#connections-own .setting-row').length === {n}"
            )
            time.sleep(1.5)
            after = b.run(READ_ROWS)
            for cid in clicked:
                if after[cid]["on"]:
                    failures.append(f"{cid}: reads on again after reload")
            print("after reload:", {k: v["on"] for k, v in after.items()})
    except SystemExit:
        pass
    finally:
        # The browser is closed now, so its files are complete.
        prefs = read_file(Path(profile) / "Default" / "Preferences")
        local_state = read_file(Path(profile) / "Local State")
        for entry in CONNECTIONS:
            sw = entry["switch"]
            if entry["id"] not in clicked or sw["kind"] not in ("profile", "local_state"):
                continue
            tree = prefs if sw["kind"] == "profile" else local_state
            got = dig(tree, sw["pref"])
            if got != sw["off"]:
                failures.append(
                    f"{entry['id']}: {sw['pref']} is {got!r} on disk, expected {sw['off']!r}"
                )
            else:
                print(f"{entry['id']}: {sw['pref']} = {got!r} on disk")

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("PASS: connections section: %d rows, %d switches turned off" % (len(CONNECTIONS), len(clicked)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
