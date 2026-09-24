#!/usr/bin/env python3
r"""Where the untouched copies of Chromium's files are kept.

Several tools save a copy of a Chromium file before changing it, so the
change can be undone, diffed against, or recomputed from the original
rather than from something we already rewrote.

**One store per source tree.** This module exists because that was once
one shared store, and the failure it caused is worth remembering: the
151 tree's copy of `chromium_strings.grd` was handed to `rebrand.py`
while it was rebranding the 153 tree, so 153 was built with 151's
strings. Nothing complained. The build got 51,665 targets in and then
stopped on a string that Chromium had added in 152, because the file
that should have declared it was two versions old.

A copy taken from one Chromium version is not an original for another,
and a tool that treats it as one produces work that looks right.

`rebase_check.py` is the deliberate exception: it compares our whole
file copies against the version we branched from, so the old store is
exactly what it wants. It names it directly.
"""

import os

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The tree that has always been built here, and its store. Keeping the
# default unchanged means nothing about the old tree moves.
DEFAULT_SRC = r"E:\ung\build\src"
DEFAULT_STORE = os.path.join(CORE, ".pristine")


def store_for(src):
    """The pristine store belonging to one source tree.

    The default tree keeps the original path. Any other tree gets a
    store named after the Chromium version inside it, so two trees can
    never be mistaken for one another.
    """
    if os.path.abspath(src) == os.path.abspath(DEFAULT_SRC):
        return DEFAULT_STORE
    version_file = os.path.join(src, "chrome", "VERSION")
    version = "unknown"
    if os.path.exists(version_file):
        with open(version_file, encoding="utf-8") as f:
            parts = [line.strip().split("=")[1] for line in f if "=" in line]
        if parts:
            version = ".".join(parts)
    return DEFAULT_STORE + "-" + version


def text(src, rel, store=None):
    """The original file as text, saving a copy the first time.

    `rel` is a forward slash path relative to the source tree.
    """
    keep = os.path.join(store or store_for(src), rel.replace("/", os.sep))
    if not os.path.exists(keep):
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        import shutil

        shutil.copy2(os.path.join(src, rel.replace("/", os.sep)), keep)
    with open(keep, encoding="utf-8", newline="") as f:
        return f.read()
