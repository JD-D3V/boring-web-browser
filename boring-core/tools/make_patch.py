#!/usr/bin/env python3
"""Turn an edited Chromium file into a patch in patches/.

Usage: python make_patch.py <patch-name> <file> [<file> ...]
Each file path is relative to the build src root. A pristine copy must
exist (run snapshot.py before editing). Writes patches/<patch-name>.patch
and adds it to patches/series if missing.
"""

import difflib
import os
import sys

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.environ.get("BORING_SRC", r"E:\ung\build\src")
PRISTINE = os.path.join(CORE, ".pristine")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    name = sys.argv[1]
    if not name.endswith(".patch"):
        name += ".patch"
    chunks = []
    for relpath in sys.argv[2:]:
        rel = relpath.replace("\\", "/")
        keep = os.path.join(PRISTINE, rel.replace("/", os.sep))
        cur = os.path.join(SRC, rel.replace("/", os.sep))
        if not os.path.exists(keep):
            sys.exit("no pristine copy for " + rel + "; run snapshot.py first")
        with open(keep, encoding="utf-8", errors="surrogateescape") as f:
            a = f.readlines()
        with open(cur, encoding="utf-8", errors="surrogateescape") as f:
            b = f.readlines()
        diff = list(difflib.unified_diff(a, b, "a/" + rel, "b/" + rel))
        if diff:
            chunks.append("".join(diff))
    if not chunks:
        sys.exit("no changes found")
    out = os.path.join(CORE, "patches", name)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
        f.write("".join(chunks))
    series = os.path.join(CORE, "patches", "series")
    lines = []
    if os.path.exists(series):
        with open(series) as f:
            lines = [line.strip() for line in f if line.strip()]
    if name not in lines:
        lines.append(name)
        with open(series, "w", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
