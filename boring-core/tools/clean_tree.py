#!/usr/bin/env python3
r"""Put back Chromium files another branch left changed, before apply.py.

Several branches take turns building in one tree (E:\ung-154). apply.py
only rewinds files that the current branch's own patches touch, so a
file patched by an earlier branch and not by this one stays changed, and
the build quietly mixes the two branches.

For every file in the tree's pristine store this works out what the
current branch expects it to hold (its chromium_src copy, or pristine
with the branch's patches applied to that one file) and, if the tree
holds anything else, copies the pristine file back so apply.py puts the
branch's version on. Files that already match are left alone, so their
mtime does not change and ninja does not rebuild them.

Usage, from a worktree, holding the build lock:
  python E:\WEBBrowser\boring-core\tools\clean_tree.py ^
      --src E:\ung-154\build\src --core <worktree>\boring-core --patch-set 154
then run the worktree's own apply.py.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pristine  # noqa: E402  (the main checkout's stores)
from rebrand import STRING_FILES  # noqa: E402  (rebrand rewrites these itself)


def series(core, patch_set):
    path = os.path.join(core, "patches", "series")
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            name = line.strip()
            if not name or name.startswith("#"):
                continue
            rebased = os.path.join(core, "patches", patch_set or "", name)
            out.append(
                rebased
                if patch_set and os.path.exists(rebased)
                else os.path.join(core, "patches", name)
            )
    return out


def touched(patch):
    with open(patch, encoding="utf-8") as f:
        return {
            ln[6:].strip().replace("/", os.sep) for ln in f if ln.startswith("+++ b/")
        }


def created(patch):
    """Files the patch creates (--- /dev/null), which have no pristine copy."""
    out, prev = set(), ""
    with open(patch, encoding="utf-8") as f:
        for ln in f:
            if ln.startswith("+++ b/") and prev.startswith("--- /dev/null"):
                out.add(ln[6:].strip().replace("/", os.sep))
            prev = ln
    return out


def read(path):
    with open(path, "rb") as f:
        return f.read()


def expected(rel, base, patches, tmp):
    """What the branch wants in rel, or None if it cannot be worked out."""
    work = os.path.join(tmp, rel)
    os.makedirs(os.path.dirname(work), exist_ok=True)

    def run(data):
        with open(work, "wb") as f:
            f.write(data)
        for patch in patches:
            r = subprocess.run(
                # autocrlf off: the temp copy must keep the tree's line endings.
                [
                    "git",
                    "-c",
                    "core.autocrlf=false",
                    "apply",
                    "--whitespace=nowarn",
                    "--include=" + rel.replace(os.sep, "/"),
                    patch,
                ],
                cwd=tmp,
                capture_output=True,
            )
            if r.returncode != 0:
                return None
        return read(work)

    want = run(base)
    if want is None and b"\r\n" in base:
        # Some originals carry CRLF line endings and our patches are LF.
        # In the tree git reads such a file as LF and writes it back as LF,
        # so the patched file is LF all through.
        want = run(base.replace(b"\r\n", b"\n"))
    return want


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--core", required=True, help="the worktree's boring-core")
    ap.add_argument("--patch-set")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    store = pristine.store_for(args.src)
    if not os.path.isdir(store):
        sys.exit(f"no pristine store at {store}")
    skip = {p.replace("/", os.sep) for p in STRING_FILES}
    patches = series(args.core, args.patch_set)
    by_file = {}
    for patch in patches:
        for rel in touched(patch):
            by_file.setdefault(rel, []).append(patch)
    overlay = os.path.join(args.core, "chromium_src")

    restored = unknown = 0
    todo = {}  # tree-relative path -> (pristine copy, tree file) to put back
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMP")) as tmp:
        for root, _dirs, files in os.walk(store):
            for name in files:
                keep = os.path.join(root, name)
                rel = os.path.relpath(keep, store)
                if rel in skip:
                    continue
                tree_file = os.path.join(args.src, rel)
                if not os.path.exists(tree_file):
                    continue
                over = os.path.join(overlay, rel)
                base = read(over) if os.path.exists(over) else read(keep)
                want = base
                if rel in by_file:
                    want = expected(rel, base, by_file[rel], tmp)
                    if want is None:
                        unknown += 1
                        print("cannot predict", rel)
                if want is not None and read(tree_file) == want:
                    continue
                todo[rel] = (keep, tree_file)

        # apply.py works one patch at a time and cannot tell that a patch
        # sitting under later patches on the same lines is already in, and
        # it takes a patch whose files are only partly patched for a
        # failure; either sends it round a second pass that breaks the
        # stack. So put back whatever it would trip on: a stacked file
        # whose patches do not all reverse cleanly, then (repeating) every
        # other file of a patch that has a file being put back.
        def differs(rel):
            keep = os.path.join(store, rel)
            tree_file = os.path.join(args.src, rel)
            return (
                rel not in skip
                and os.path.exists(keep)
                and os.path.exists(tree_file)
                and read(keep) != read(tree_file)
            )

        for rel, ps in by_file.items():
            if rel in todo or len(ps) < 2 or not differs(rel):
                continue
            work = os.path.join(tmp, "stack", rel)
            os.makedirs(os.path.dirname(work), exist_ok=True)
            with open(work, "wb") as f:
                f.write(read(os.path.join(args.src, rel)))
            for patch in ps:
                r = subprocess.run(
                    [
                        "git",
                        "apply",
                        "--reverse",
                        "--check",
                        "--include=stack/" + rel.replace(os.sep, "/"),
                        "--directory=stack",
                        patch,
                    ],
                    cwd=tmp,
                    capture_output=True,
                )
                if r.returncode != 0:
                    print("stacked, cannot tell if applied", rel)
                    todo[rel] = (os.path.join(store, rel), os.path.join(args.src, rel))
                    break
        grew = True
        while grew:
            grew = False
            for patch in patches:
                files = touched(patch)
                if any(rel in todo for rel in files):
                    for rel in files:
                        if rel not in todo and differs(rel):
                            print("rest of a patch being redone", rel)
                            todo[rel] = (
                                os.path.join(store, rel),
                                os.path.join(args.src, rel),
                            )
                            grew = True
        for rel, (keep, tree_file) in sorted(todo.items()):
            print("restore", rel)
            restored += 1
            if not args.dry_run:
                shutil.copy2(keep, tree_file)
        # Files some branch patches that have no pristine copy: if
        # ungoogled's patches and domain substitution never touch them,
        # HEAD is the original. Save it to the store (so next time it is a
        # normal pristine file), and put it back if another branch left it
        # changed, unless this branch patches or overlays it. The ones
        # ungoogled does change cannot be seeded; they are listed.
        dsub = set()
        root = os.path.dirname(os.path.dirname(os.path.abspath(args.src)))
        for lst in (
            os.path.join(root, "domain_substitution.list"),
            os.path.join(root, "ungoogled-chromium", "domain_substitution.list"),
        ):
            if os.path.exists(lst):
                with open(lst, encoding="utf-8") as f:
                    dsub.update(ln.strip().replace("/", os.sep) for ln in f)
        # Only files some boring-core branch patches, and never a file
        # ungoogled's own patches change (HEAD is not its original).
        repo = os.path.dirname(os.path.abspath(args.core))
        refs = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname)", "refs/heads"],
            cwd=repo,
            capture_output=True,
            text=True,
        ).stdout.split()
        ours = set()
        if refs:
            g = subprocess.run(
                ["git", "grep", "-h", "^+++ b/"] + refs + ["--", "boring-core/patches"],
                cwd=repo,
                capture_output=True,
                text=True,
            )
            ours = {
                ln.split("+++ b/", 1)[1].strip().replace("/", os.sep)
                for ln in g.stdout.splitlines()
                if "+++ b/" in ln
            }
        # Uncommitted patches in other worktrees count too.
        # The worktrees live under the main checkout, which is not `repo`
        # when --core is a worktree's own boring-core.
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=repo,
            capture_output=True,
            text=True,
        ).stdout.strip()
        main_repo = os.path.dirname(common) if common else repo
        wt = os.path.join(main_repo, ".claude", "worktrees")
        if os.path.isdir(wt):
            for name in os.listdir(wt):
                pdir = os.path.join(wt, name, "boring-core", "patches")
                for proot, _d, pfiles in os.walk(pdir):
                    for pf in pfiles:
                        if pf.endswith(".patch"):
                            ours |= touched(os.path.join(proot, pf))
        theirs = set()
        for pdir in (
            os.path.join(root, "patches"),
            os.path.join(root, "ungoogled-chromium", "patches"),
        ):
            for proot, _d, pfiles in os.walk(pdir):
                for pf in pfiles:
                    if pf.endswith(".patch"):
                        theirs |= touched(os.path.join(proot, pf))
        r = subprocess.run(
            ["git", "status", "--porcelain", "-uno"],
            cwd=args.src,
            capture_output=True,
            text=True,
        )
        modified = {
            line[3:].strip().replace("/", os.sep)
            for line in r.stdout.splitlines()
            if line.startswith(" M")
        }
        unresolved = []
        for rel in sorted(ours):
            keep = os.path.join(store, rel)
            tree_file = os.path.join(args.src, rel)
            if rel in skip or os.path.exists(keep) or not os.path.exists(tree_file):
                continue
            # A change ungoogled itself makes: HEAD is not the original.
            if rel in theirs or rel in dsub:
                unresolved.append(rel)
                continue
            head = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.autocrlf=false",
                    "show",
                    "HEAD:" + rel.replace(os.sep, "/"),
                ],
                cwd=args.src,
                capture_output=True,
            )
            if head.returncode != 0:
                continue
            # Every patched file ends up with a store copy, so next time it
            # is a normal pristine file; put it back too if another branch
            # left it changed (and this one neither patches nor overlays it).
            print("seed store from HEAD", rel)
            if not args.dry_run:
                os.makedirs(os.path.dirname(keep), exist_ok=True)
                with open(keep, "wb") as f:
                    f.write(head.stdout)
            if (
                rel in modified
                and rel not in by_file
                and not os.path.exists(os.path.join(overlay, rel))
            ):
                print("restore from HEAD", rel)
                restored += 1
                if not args.dry_run:
                    with open(tree_file, "wb") as f:
                        f.write(head.stdout)
        for rel in unresolved:
            print("no pristine copy, ungoogled changes it (unresolved)", rel)
        # A file on ungoogled's domain_substitution.list has no store copy
        # (plain patches never snapshot it) and HEAD is not its original,
        # so a file another branch patched in place is neither restored
        # above nor predictable. Reverse the other worktrees' patches on
        # those files, only where git says the reverse applies exactly.
        foreign = []
        if os.path.isdir(wt):
            mine_root = os.path.abspath(args.core).lower()
            for name in sorted(os.listdir(wt)):
                other = os.path.join(wt, name, "boring-core")
                if os.path.abspath(other).lower() == mine_root:
                    continue
                for proot, _d, pfiles in os.walk(os.path.join(other, "patches")):
                    foreign += [
                        os.path.join(proot, pf)
                        for pf in sorted(pfiles)
                        if pf.endswith(".patch")
                    ]
        undone = set()
        for _pass in range(3):
            again = False
            for patch in foreign:
                for rel in sorted(touched(patch)):
                    if (
                        rel not in dsub
                        or rel in by_file
                        or os.path.exists(os.path.join(overlay, rel))
                        or (patch, rel) in undone
                    ):
                        continue
                    inc = "--include=" + rel.replace(os.sep, "/")
                    chk = subprocess.run(
                        ["git", "apply", "--reverse", "--check", inc, patch],
                        cwd=args.src,
                        capture_output=True,
                    )
                    if chk.returncode != 0:
                        continue
                    print("reverse foreign patch", os.path.basename(patch), rel)
                    undone.add((patch, rel))
                    restored += 1
                    again = True
                    if not args.dry_run:
                        r = subprocess.run(
                            [
                                "git",
                                "apply",
                                "--reverse",
                                "--whitespace=nowarn",
                                inc,
                                patch,
                            ],
                            cwd=args.src,
                            capture_output=True,
                            text=True,
                        )
                        if r.returncode != 0:
                            sys.exit(
                                "cannot reverse "
                                + patch
                                + " on "
                                + rel
                                + ": "
                                + r.stderr
                            )
            if not again:
                break
        # A file this branch's patch creates: if the tree holds another
        # version, remove it so the patch can create it again.
        for patch in patches:
            made = [
                rel
                for rel in created(patch)
                if os.path.exists(os.path.join(args.src, rel))
            ]
            # Some of a patch's new files there and some not is a half
            # applied patch, stale as a whole.
            stale = ["partial"] if made and len(made) < len(created(patch)) else []
            for rel in made:
                tree_file = os.path.join(args.src, rel)
                work = os.path.join(tmp, "new", rel)
                if os.path.exists(work):
                    os.remove(work)
                r = subprocess.run(
                    [
                        "git",
                        "-c",
                        "core.autocrlf=false",
                        "apply",
                        "--whitespace=nowarn",
                        "--directory=new",
                        "--include=new/" + rel.replace(os.sep, "/"),
                        patch,
                    ],
                    cwd=tmp,
                    capture_output=True,
                )
                if (
                    r.returncode == 0
                    and os.path.exists(work)
                    and read(work) == read(tree_file)
                ):
                    continue
                stale.append(rel)
            # One stale file takes the rest of that patch's new files with
            # it: apply.py can neither create files that exist nor see a
            # patch as applied when part of it is gone.
            if stale:
                for rel in made:
                    print("remove created", rel)
                    restored += 1
                    if not args.dry_run:
                        os.remove(os.path.join(args.src, rel))
    print(
        f"done: {restored} restored ({unknown} could not be predicted, "
        f"restored to pristine for apply.py to redo)"
    )


if __name__ == "__main__":
    main()
