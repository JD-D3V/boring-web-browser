#!/usr/bin/env python3
"""Write Brave's debounce rules into the source tree as their own file.

Brave's brave-lists/debounce.json (github.com/brave/adblock-lists,
MPL-2.0) says which links are only a tracking hop and where they really
go. JSON has no comments and no header, so the file cannot carry its own
licence line. It goes into boring-core/components/boring/privacy/
debounce_brave.inc instead: a C++ raw string holding the upstream bytes
unchanged, under a header that names the source, the commit, the hash
and the licence. Rules of ours are kept apart, in debounce_boring.inc,
so no edit of ours ever lands inside the MPL file.

The commit is pinned and the download is checked against its hash, the
same as the other fetch tools here. To take newer rules, change
COMMIT and SHA256 together after reading the diff.

Usage:
  python get_debounce.py            write debounce_brave.inc from the pin
  python get_debounce.py --check    say whether the file on disk matches
"""

import argparse
import hashlib
import os
import sys
import urllib.request

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INC = os.path.join(CORE, "components", "boring", "privacy", "debounce_brave.inc")

COMMIT = "a28ed4807b1f92026c996b83b32c0c0f634a467e"
SHA256 = "fb2396985a78983c8f88ee701100c5cb4681731239ac6624e86da1212645dbf8"
URL = (
    "https://raw.githubusercontent.com/brave/adblock-lists/"
    f"{COMMIT}/brave-lists/debounce.json"
)

OPEN = b'R"JSON('
CLOSE = b')JSON"'


def header():
    return (
        "// This Source Code Form is subject to the terms of the Mozilla Public\n"
        "// License, v. 2.0. If a copy of the MPL was not distributed with this file,\n"
        "// You can obtain one at https://mozilla.org/MPL/2.0/.\n"
        "//\n"
        "// brave-lists/debounce.json from https://github.com/brave/adblock-lists,\n"
        f"// commit {COMMIT[:12]}, Copyright (c) The Brave Authors.\n"
        "// The text between the markers below is that file byte for byte\n"
        f"// (SHA-256 {SHA256}).\n"
        "// Written by boring-core/tools/get_debounce.py. Our own rules are in\n"
        "// debounce_boring.inc, never in this file. It is included by\n"
        "// debounce.cc and nothing else.\n"
    ).encode("ascii")


def wrap(upstream):
    """The .inc file's bytes for these upstream bytes."""
    return header() + OPEN + upstream + CLOSE + b"\n"


def unwrap(inc):
    """The upstream bytes inside an .inc file, or None when the shape is off."""
    inc = inc.replace(b"\r\n", b"\n")
    start = inc.find(OPEN)
    end = inc.rfind(CLOSE)
    if start < 0 or end < start:
        return None
    return inc[start + len(OPEN) : end]


def fetch():
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read()
    got = hashlib.sha256(data).hexdigest()
    if got != SHA256:
        raise SystemExit(f"debounce.json does not match the pin: {got}")
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        with open(INC, "rb") as f:
            have = unwrap(f.read())
        ok = have is not None and hashlib.sha256(have).hexdigest() == SHA256
        print("matches the pin" if ok else "does NOT match the pin")
        return 0 if ok else 1
    with open(INC, "wb") as f:
        f.write(wrap(fetch()))
    print("wrote", INC)
    return 0


if __name__ == "__main__":
    sys.exit(main())
