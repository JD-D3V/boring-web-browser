#!/usr/bin/env python3
"""Save a pristine copy of a Chromium file before editing it.

Usage: python snapshot.py chrome/browser/some_file.cc
"""

import os
import shutil
import sys

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get("BORING_SRC", r"E:\ung\build\src")
PRISTINE = os.path.join(CORE, ".pristine")


def main():
    for relpath in sys.argv[1:]:
        relpath = relpath.replace("/", os.sep)
        orig = os.path.join(SRC, relpath)
        keep = os.path.join(PRISTINE, relpath)
        if not os.path.exists(orig):
            sys.exit("no such file: " + orig)
        if os.path.exists(keep):
            print("already saved:", relpath)
            continue
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        shutil.copy2(orig, keep)
        print("saved:", relpath)


if __name__ == "__main__":
    main()
