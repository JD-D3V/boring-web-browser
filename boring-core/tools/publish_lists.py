#!/usr/bin/env python3
"""Build the list bundle the browser downloads to keep its blocking fresh.

The filter list and the scam blocklist are baked in when the browser is
built, so on an installed copy they only get older. This writes the same
two files plus a small manifest into a folder, ready to be uploaded to
the release host. The browser reads the manifest, compares it with what
it already has, and downloads only the files that changed.

The manifest looks like this:

    {
      "version": 260,
      "updated": "2026-09-17",
      "files": [{"name": "easylist.txt", "size": 123, "sha256": "..."}]
    }

The version only ever goes up, so an older bundle served from a cache
can never talk a browser into going backwards.

Usage: python publish_lists.py --out DIR [--version N]
"""

import argparse
import datetime
import hashlib
import json
import os

from get_filterlists import build_filter_list
from get_scamlist import build_scam_list, count_hosts

# The version is days since this date, which keeps it going up on its
# own without anything having to remember the last one.
VERSION_EPOCH = datetime.date(2026, 1, 1)

MANIFEST_NAME = "lists.json"


def version_for(day: datetime.date) -> int:
    return (day - VERSION_EPOCH).days


def write_file(directory: str, name: str, text: str) -> dict:
    """Writes one list and returns its entry for the manifest."""
    path = os.path.join(directory, name)
    data = text.encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    return {
        "name": name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="folder to write the bundle into")
    ap.add_argument(
        "--version",
        type=int,
        default=None,
        help="manifest version; defaults to days since 2026-01-01",
    )
    args = ap.parse_args()

    today = datetime.date.today()
    version = args.version if args.version is not None else version_for(today)

    os.makedirs(args.out, exist_ok=True)

    filters = build_filter_list()
    scam = build_scam_list()

    # A bundle that is missing either list would turn protection off on
    # every browser that downloaded it, so refuse to publish one.
    if not filters.strip():
        raise SystemExit("the filter list came back empty, not publishing")
    if count_hosts(scam) == 0:
        raise SystemExit("the scam blocklist came back empty, not publishing")

    files = [
        write_file(args.out, "easylist.txt", filters),
        write_file(args.out, "scamlist.txt", scam),
    ]
    manifest = {
        "version": version,
        "updated": today.isoformat(),
        "files": files,
    }
    manifest_path = os.path.join(args.out, MANIFEST_NAME)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")

    print("bundle version", version)
    for entry in files:
        print(" ", entry["name"], entry["size"], "bytes", entry["sha256"][:12])
    print("wrote", manifest_path)


if __name__ == "__main__":
    main()
