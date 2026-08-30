#!/usr/bin/env python3
"""Download the filter lists the ad blocker uses.

Writes them into the build output folder (next to chrome.exe) in a
folder called boring. Run again any time to refresh the lists.

Usage: python get_filterlists.py [--out DIR]
"""

import argparse
import os
import urllib.request

LISTS = [
    ("https://easylist.to/easylist/easylist.txt", "easylist"),
    ("https://easylist.to/easylist/easyprivacy.txt", "easyprivacy"),
]

DEFAULT_OUT = r"E:\ung\build\src\out\Default"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    dest_dir = os.path.join(args.out, "boring")
    os.makedirs(dest_dir, exist_ok=True)
    parts = []
    for url, name in LISTS:
        print("downloading", name, "...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        text = urllib.request.urlopen(req).read().decode("utf-8", "replace")
        print(" ", len(text), "bytes")
        parts.append(text)
    # The engine takes one combined list, so join them.
    out_path = os.path.join(dest_dir, "easylist.txt")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(parts))
    print("wrote", out_path)


if __name__ == "__main__":
    main()
