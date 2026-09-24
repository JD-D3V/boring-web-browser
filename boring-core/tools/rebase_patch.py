#!/usr/bin/env python3
r"""Re-cut our patches against a newer Chromium tree.

`rebase_check.py` says which patches no longer apply. Most of them have
not stopped making sense; their context has moved by a few lines, or a
neighbouring hunk upstream rewrote. `git apply -C1` can usually still
place them, and what is wanted afterwards is a patch that applies to the
new tree with no slack at all, because `apply.py` uses a plain
`git apply` and a build should not depend on fuzz.

So: for each patch, keep a copy of the files it touches, let git place
it with less context, and write out the difference between the copy and
the result. That difference is the same change expressed against the new
tree.

It works through the series in order and **leaves every patch applied**,
because that is the only way the answers are right. Half the series
touches files the other half also touches, so a patch rebased against a
tree where the ones before it are missing is rebased against a tree that
will never exist. Run `apply.py` first with `--no-patches` so the
chromium_src overlay is in place for the same reason.

What this does not do is think. If a hunk lands somewhere that looks
right to git and is wrong for us, only reading it catches that, so what
it writes is a draft to read, not an answer to trust. Anything it cannot
place at all it leaves alone and says so.

Usage:
  python rebase_patch.py --src E:\ung-153-47\build\src --set 153
  python rebase_patch.py --src ... --set 153 --dry-run
  python rebase_patch.py --src ... --set 153 tab-shape.patch
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCHES = os.path.join(CORE, "patches")


def series():
    with open(os.path.join(PATCHES, "series")) as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


def patch_path(name, patch_set):
    """The copy to rebase from: the set's, if it has one."""
    if patch_set:
        rebased = os.path.join(PATCHES, patch_set, name)
        if os.path.exists(rebased):
            return rebased
    return os.path.join(PATCHES, name)


def targets(patch):
    """Every file the patch writes to, and which of them it creates."""
    changed, created = [], []
    with open(patch, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("+++ b/"):
            continue
        name = line[6:].strip()
        before = lines[i - 1] if i else ""
        (created if before.strip() == "--- /dev/null" else changed).append(name)
    return changed, created


def git_apply(src, patch, extra):
    return subprocess.run(
        ["git", "apply", "--whitespace=nowarn", *extra, patch],
        cwd=src,
        capture_output=True,
        text=True,
    )


def unified(old_path, new_path, rel, created):
    """A diff in the shape git apply expects, or "" when nothing changed."""
    result = subprocess.run(
        ["git", "diff", "--no-index", "--src-prefix=a/", "--dst-prefix=b/",
         old_path, new_path],
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        return ""
    out = []
    for line in result.stdout.splitlines():
        if line.startswith("diff --git "):
            out.append(f"diff --git a/{rel} b/{rel}")
        elif line.startswith("--- "):
            out.append("--- /dev/null" if created else f"--- a/{rel}")
        elif line.startswith("+++ "):
            out.append(f"+++ b/{rel}")
        elif line.startswith(("index ", "new file mode ", "deleted file mode ")):
            continue
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def rebase_one(src, name, patch_set, dry_run):
    """Place one patch and, if it needed slack, write the rebased copy.

    Leaves the patch applied either way, so the next one in the series
    sees the tree it will really meet.
    """
    patch = patch_path(name, patch_set)
    changed, created = targets(patch)

    missing = [f for f in changed if not os.path.exists(os.path.join(src, f))]
    if missing:
        return "file gone", "no longer in the tree: " + ", ".join(missing)

    if git_apply(src, patch, ["--reverse", "--check"]).returncode == 0:
        return "already in the tree", ""

    if git_apply(src, patch, []).returncode == 0:
        return "applies as is", ""

    keep = tempfile.mkdtemp(prefix="boring-rebase-")
    try:
        for rel in changed + created:
            dest = os.path.join(keep, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            source = os.path.join(src, rel)
            if os.path.exists(source):
                shutil.copy2(source, dest)
            else:
                open(dest, "w").close()

        placed = git_apply(src, patch, ["-C1"])
        if placed.returncode != 0:
            detail = (placed.stderr or "").strip().splitlines()
            return "CANNOT PLACE", detail[0] if detail else "git apply failed"

        pieces = []
        for rel in changed + created:
            piece = unified(
                os.path.join(keep, rel.replace("/", os.sep)),
                os.path.join(src, rel),
                rel,
                rel in created,
            )
            if piece:
                pieces.append(piece)
        if not pieces:
            return "no change", "the patch is a no-op against this tree"

        text = "".join(pieces)
        if dry_run:
            return "would write", f"{len(text.splitlines())} lines"

        out_dir = os.path.join(PATCHES, patch_set)
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, name)
        with open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

        # The whole point is a patch that needs no slack. Prove it: undo
        # what git placed, then apply the rebased copy strictly.
        subprocess.run(["git", "apply", "--reverse", "-C1", patch],
                       cwd=src, capture_output=True, text=True)
        strict = git_apply(src, out, [])
        if strict.returncode != 0:
            detail = (strict.stderr or "").strip().splitlines()
            return "REBASED BUT STILL FUZZY", detail[0] if detail else ""
        return "rebased", os.path.relpath(out, CORE).replace(os.sep, "/")
    finally:
        shutil.rmtree(keep, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="the prepared source tree")
    ap.add_argument("--set", required=True, help="patch set to write into, e.g. 153")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("names", nargs="*", help="default: the whole series, in order")
    args = ap.parse_args()

    if not os.path.exists(os.path.join(args.src, "BUILD.gn")):
        sys.exit(f"{args.src} does not look like a Chromium source tree")
    names = args.names or series()

    width = max(len(n) for n in names)
    counts = {}
    for name in names:
        state, detail = rebase_one(args.src, name, args.set, args.dry_run)
        counts[state] = counts.get(state, 0) + 1
        print(f"  {name.ljust(width)}  {state}" + (f"  {detail}" if detail else ""),
              flush=True)
    print()
    print(", ".join(f"{n} {state}" for state, n in sorted(counts.items())))
    bad = ("CANNOT PLACE", "file gone", "REBASED BUT STILL FUZZY")
    return 1 if any(counts.get(state) for state in bad) else 0


if __name__ == "__main__":
    sys.exit(main())
