#!/usr/bin/env python3
"""Wire boring-core into the ungoogled-chromium build tree.

Copies components/boring and chromium_src into the tree, applies the
patches listed in patches/series, and builds the Rust static library.
Run with --restore to undo every change to Chromium files.

A Chromium upgrade moves the ground under some of those patches, so a
rebased copy of one lives in patches/<set>/<name>, and --patch-set picks
it. The series is the same either way: only the patches that actually
had to change are in the subdirectory, and everything else comes from
patches/ as before, so there is one list of what we do to Chromium
rather than one per engine version.
"""

import argparse
import filecmp
import os
import shutil
import subprocess
import sys

import pristine
from rebrand import rebrand

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = r"E:\ung\build\src"
# Originals of every Chromium file we replace, so --restore can put the
# tree back. One store per source tree: a copy saved from Chromium 151
# is not what a 153 tree wants back, and restoring the wrong one looks
# like a working restore until something fails to compile hours later.
PRISTINE = os.path.join(CORE, ".pristine")


def patch_path(name, patch_set):
    """Where to read one patch from, preferring the rebased copy."""
    if patch_set:
        rebased = os.path.join(CORE, "patches", patch_set, name)
        if os.path.exists(rebased):
            return rebased
    return os.path.join(CORE, "patches", name)


def series_names():
    """The patches to apply, in order."""
    series = os.path.join(CORE, "patches", "series")
    if not os.path.exists(series):
        return []
    with open(series) as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


# Files apply.py puts into components/boring itself, rather than
# copying from boring-core/components/boring, so sync_tree leaves them.
# The repository's LICENSE is the one copy of our licence; the package
# needs it inside the tree to ship it.
#
# WinSparkle is a downloaded binary, pinned by hash in
# tools/get_winsparkle.py, and kept out of git.
WINSPARKLE = os.path.join(CORE, "third_party", "winsparkle")
GENERATED = {
    os.path.join("notices", "LICENSE-BoringBrowser.txt"): os.path.join(
        os.path.dirname(CORE), "LICENSE"
    ),
    os.path.join("update", "lib", "WinSparkle.dll"): os.path.join(
        WINSPARKLE, "WinSparkle.dll"
    ),
    os.path.join("update", "lib", "NOTICES-WinSparkle.txt"): os.path.join(
        WINSPARKLE, "NOTICES-WinSparkle.txt"
    ),
}


# Said in the licence file that ships, because the MIT text above it
# does not cover this one file and the MPL-2.0 asks that people who get
# the program are told where its source is.
LICENCE_SUFFIX = {
    os.path.join("notices", "LICENSE-BoringBrowser.txt"): (
        b"\n"
        b"One file of our code is not under the licence above:\n"
        b"boring-core/components/boring/privacy/tracking_params.cc is adapted\n"
        b"from brave-core (Copyright (c) 2023 The Brave Authors) and is under\n"
        b"the Mozilla Public License 2.0, https://mozilla.org/MPL/2.0/.\n"
        b"Its source: https://github.com/JD-D3V/boring-web-browser/blob/main/\n"
        b"boring-core/components/boring/privacy/tracking_params.cc\n"
    ),
}


def sync_tree(src_dir, dst_dir, keep=()):
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
                # copy, not copy2: a fresh mtime, so ninja sees the change
                # even when the source file is older than the last build.
                shutil.copy(s, d)
                print("copy", os.path.join(rel, f) if rel != "." else f)
    # Remove files in dst that are gone from src.
    if os.path.isdir(dst_dir):
        for root, _dirs, files in os.walk(dst_dir):
            rel = os.path.relpath(root, dst_dir)
            for f in files:
                s = (
                    os.path.join(src_dir, rel, f)
                    if rel != "."
                    else os.path.join(src_dir, f)
                )
                if not os.path.exists(s):
                    if os.path.join(rel, f) in keep:
                        continue
                    os.remove(os.path.join(root, f))
                    print("remove stale", os.path.join(rel, f))


def pristine_for(src):
    """Where this tree's originals live. See pristine.py."""
    return pristine.store_for(src)


def snapshot(src, relpath, pristine=PRISTINE):
    """Save a pristine copy of a Chromium file before we change it."""
    orig = os.path.join(src, relpath)
    keep = os.path.join(pristine, relpath)
    if not os.path.exists(keep):
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        shutil.copy2(orig, keep)


def patched_files(patch):
    """The files a patch touches, as tree-relative paths."""
    files = []
    with open(patch, encoding="utf-8") as f:
        for line in f:
            if line.startswith("+++ b/"):
                files.append(line[6:].strip().replace("/", os.sep))
    return files


def rewind(src, patch, pristine=PRISTINE):
    """Put a patch's files back to pristine so it can go on cleanly.

    An edited patch leaves the tree holding the old version of the
    change: it will not reverse (the text moved) and it will not apply
    (the lines are taken). The pristine copy is the way out, and this is
    the only safe moment to use it, because every patch is applied again
    right after.
    """
    restored = []
    for rel in patched_files(patch):
        keep = os.path.join(pristine, rel)
        if os.path.exists(keep):
            shutil.copy2(keep, os.path.join(src, rel))
            restored.append(rel)
    return restored


def apply_patches(src, patch_set=None, pristine=PRISTINE):
    names = series_names()
    if not names:
        return
    # A rewind puts a whole file back, which can take another patch's
    # change with it, so anything already applied has to go on again.
    for attempt in range(2):
        rewound = False
        for name in names:
            patch = patch_path(name, patch_set)
            # Skip a patch that is already in.
            r = subprocess.run(
                ["git", "apply", "--reverse", "--check", patch],
                cwd=src,
                capture_output=True,
            )
            if r.returncode == 0:
                print("already applied", name)
                continue
            r = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", patch],
                cwd=src,
                capture_output=True,
                text=True,
            )
            if r.returncode == 0:
                print("applied", name)
                continue
            back = rewind(src, patch, pristine) if attempt == 0 else []
            if not back:
                print("FAILED to apply", name)
                print(r.stderr)
                sys.exit(1)
            print("rewound", name, "->", ", ".join(back))
            rewound = True
        if not rewound:
            return


def overlay_chromium_src(src, pristine=PRISTINE):
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
                snapshot(src, rel, pristine)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            if not os.path.exists(d) or not filecmp.cmp(s, d, shallow=False):
                shutil.copy(s, d)  # fresh mtime, see sync_tree
                print("overlay", rel)


def restore(src, patch_set=None, pristine=PRISTINE):
    """Put every changed Chromium file back."""
    # Reverse the patches, newest first.
    for name in reversed(series_names()):
        patch = patch_path(name, patch_set)
        subprocess.run(
            ["git", "apply", "--reverse", patch], cwd=src, capture_output=True
        )
    # Restore pristine copies.
    if os.path.isdir(pristine):
        for root, _dirs, files in os.walk(pristine):
            for f in files:
                keep = os.path.join(root, f)
                rel = os.path.relpath(keep, pristine)
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
    ap.add_argument(
        "--patch-set",
        help="subdirectory of patches/ holding rebased copies, e.g. 153",
    )
    ap.add_argument(
        "--no-patches",
        action="store_true",
        help="copy our files into the tree but apply no patches and do "
        "no rebranding. For rebase_patch.py, which needs the overlay in "
        "place before it can tell where a patch really lands.",
    )
    args = ap.parse_args()

    if args.patch_set and not os.path.isdir(
        os.path.join(CORE, "patches", args.patch_set)
    ):
        sys.exit(f"no such patch set: patches/{args.patch_set}")

    pristine = pristine_for(args.src)
    if pristine != PRISTINE:
        print("pristine store for this tree:", os.path.basename(pristine))

    if args.restore:
        restore(args.src, args.patch_set, pristine)
        return

    if not args.no_rust:
        build_rust(args.src)
    boring_dst = os.path.join(args.src, "components", "boring")
    sync_tree(
        os.path.join(CORE, "components", "boring"),
        boring_dst,
        keep=GENERATED,
    )
    for rel, source in GENERATED.items():
        if not os.path.exists(source):
            sys.exit(f"missing {source}; run tools/get_winsparkle.py first")
        d = os.path.join(boring_dst, rel)
        os.makedirs(os.path.dirname(d), exist_ok=True)
        with open(source, "rb") as f:
            data = f.read()
        data += LICENCE_SUFFIX.get(rel, b"")
        current = None
        if os.path.exists(d):
            with open(d, "rb") as f:
                current = f.read()
        if current != data:
            with open(d, "wb") as f:
                f.write(data)
            print("copy", rel)
    # Stage the cargo build products where GN expects them.
    rust_out = os.path.join(CORE, "rust", "target", "release")
    lib_dir = os.path.join(args.src, "components", "boring", "adblock", "lib")
    os.makedirs(lib_dir, exist_ok=True)
    for name in ("boring_adblock.dll", "boring_adblock.dll.lib"):
        built = os.path.join(rust_out, name)
        if os.path.exists(built):
            shutil.copy2(built, os.path.join(lib_dir, name))
            print("stage", name)
    overlay_chromium_src(args.src, pristine)
    if args.no_patches:
        print("stopped before the patches, as asked")
        return
    apply_patches(args.src, args.patch_set, pristine)
    rebrand(args.src)
    print("done")


if __name__ == "__main__":
    main()
