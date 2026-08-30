#!/usr/bin/env python3
"""Wire boring-core into the ungoogled-chromium build tree.

Copies components/boring and chromium_src into the tree, applies the
patches listed in patches/series, and builds the Rust static library.
Run with --restore to undo every change to Chromium files.
"""

import argparse
import filecmp
import os
import shutil
import subprocess
import sys

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = r"E:\ung\build\src"
PRISTINE = os.path.join(CORE, ".pristine")


def sync_tree(src_dir, dst_dir):
    """Copy src_dir over dst_dir, removing files that no longer exist."""
    if not os.path.isdir(src_dir):
        return
    for root, _dirs, files in os.walk(src_dir):
        rel = os.path.relpath(root, src_dir)
        out_root = os.path.join(dst_dir, rel) if rel != "." else dst_dir
        os.makedirs(out_root, exist_ok=True)
        for f in files:
            s = os.path.join(root, f)
            d = os.path.join(out_root, f)
            if not os.path.exists(d) or not filecmp.cmp(s, d, shallow=False):
                shutil.copy2(s, d)
                print("copy", os.path.join(rel, f) if rel != "." else f)
    # Remove files in dst that are gone from src.
    if os.path.isdir(dst_dir):
        for root, _dirs, files in os.walk(dst_dir):
            rel = os.path.relpath(root, dst_dir)
            for f in files:
                s = os.path.join(src_dir, rel, f) if rel != "." else os.path.join(src_dir, f)
                if not os.path.exists(s):
                    os.remove(os.path.join(root, f))
                    print("remove stale", os.path.join(rel, f))


def snapshot(src, relpath):
    """Save a pristine copy of a Chromium file before we change it."""
    orig = os.path.join(src, relpath)
    keep = os.path.join(PRISTINE, relpath)
    if not os.path.exists(keep):
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        shutil.copy2(orig, keep)


def apply_patches(src):
    series = os.path.join(CORE, "patches", "series")
    if not os.path.exists(series):
        return
    with open(series) as f:
        names = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    for name in names:
        patch = os.path.join(CORE, "patches", name)
        # Skip a patch that is already in.
        r = subprocess.run(["git", "apply", "--reverse", "--check", patch],
                           cwd=src, capture_output=True)
        if r.returncode == 0:
            print("already applied", name)
            continue
        r = subprocess.run(["git", "apply", "--whitespace=nowarn", patch],
                           cwd=src, capture_output=True, text=True)
        if r.returncode != 0:
            print("FAILED to apply", name)
            print(r.stderr)
            sys.exit(1)
        print("applied", name)


def overlay_chromium_src(src):
    """Replace Chromium files with our chromium_src copies, keeping pristine backups."""
    overlay = os.path.join(CORE, "chromium_src")
    if not os.path.isdir(overlay):
        return
    for root, _dirs, files in os.walk(overlay):
        for f in files:
            s = os.path.join(root, f)
            rel = os.path.relpath(s, overlay)
            d = os.path.join(src, rel)
            if os.path.exists(d):
                snapshot(src, rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if not os.path.exists(d) or not filecmp.cmp(s, d, shallow=False):
                shutil.copy2(s, d)
                print("overlay", rel)


def restore(src):
    """Put every changed Chromium file back."""
    # Reverse the patches, newest first.
    series = os.path.join(CORE, "patches", "series")
    if os.path.exists(series):
        with open(series) as f:
            names = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        for name in reversed(names):
            patch = os.path.join(CORE, "patches", name)
            subprocess.run(["git", "apply", "--reverse", patch], cwd=src,
                           capture_output=True)
    # Restore pristine copies.
    if os.path.isdir(PRISTINE):
        for root, _dirs, files in os.walk(PRISTINE):
            for f in files:
                keep = os.path.join(root, f)
                rel = os.path.relpath(keep, PRISTINE)
                shutil.copy2(keep, os.path.join(src, rel))
                print("restored", rel)
    # Remove our component tree.
    boring = os.path.join(src, "components", "boring")
    if os.path.isdir(boring):
        shutil.rmtree(boring)
        print("removed components/boring")


def build_rust(src):
    rust = os.path.join(CORE, "rust")
    if not os.path.exists(os.path.join(rust, "Cargo.toml")):
        return
    r = subprocess.run(["cargo", "build", "--release"], cwd=rust)
    if r.returncode != 0:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--no-rust", action="store_true")
    args = ap.parse_args()

    if args.restore:
        restore(args.src)
        return

    sync_tree(os.path.join(CORE, "components", "boring"),
              os.path.join(args.src, "components", "boring"))
    overlay_chromium_src(args.src)
    apply_patches(args.src)
    if not args.no_rust:
        build_rust(args.src)
    print("done")


if __name__ == "__main__":
    main()
