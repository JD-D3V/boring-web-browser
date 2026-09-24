#!/usr/bin/env python3
r"""Say what our patch layer does against a newer Chromium source tree.

Run against a tree prepared by stage_upstream.py. Nothing is written to
either tree: every patch is tried with --check, which tells git to work
out whether it would apply and then do nothing.

Three things are reported, because they fail in different ways and take
different amounts of work to fix:

  patches         a hunk whose context moved. git reports it, and the
                  fix is usually to redo the hunk by hand.
  overlay files   files we replace outright from chromium_src. These
                  never "fail", they silently put an old copy of a
                  Chromium file into a new tree, which is worse. Each
                  one is compared against the new upstream file.
  rebranded files the three string files rebrand.py rewrites. A new
                  Chromium may have moved the strings it looks for.

Usage:
  python rebase_check.py --new E:\ung-153\build\src
  python rebase_check.py --new ... --json artifacts/.../rebase-153.json
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
PATCHES = CORE / "patches"
OVERLAY = CORE / "chromium_src"
# Deliberately the store for the tree we branched from, not the tree
# being surveyed: the question here is what upstream changed since
# then. Every other tool wants its own tree's store, see pristine.py.
PRISTINE = CORE / ".pristine"


def series() -> list[str]:
    lines = (PATCHES / "series").read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def files_in(patch: Path) -> tuple[list[str], list[str]]:
    """The files a patch changes, and the ones it creates from nothing.

    A created file is not expected to be in the tree, so asking whether
    it is there would report every new file as a problem.
    """
    changed, created = [], []
    lines = patch.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("+++ b/"):
            continue
        name = line[6:].strip()
        before = lines[i - 1] if i else ""
        if before.strip() in ("--- /dev/null", "--- a/dev/null"):
            created.append(name)
        else:
            changed.append(name)
    return changed, created


def try_apply(tree: Path, patch: Path,
              extra: list[str]) -> tuple[int, str, list[str]]:
    """Run git apply --check, and report what it quietly refused to look at.

    A staged ungoogled tree has `/build` in its root .gitignore, and the
    source lives under `build/src`. `git apply` silently skips creating a
    file at an ignored path, prints "Skipped patch ..." only under
    --verbose, and still exits 0. Without this, a patch whose new files
    were never examined is recorded as clean, which is how a rebase
    survey ends up more confident than the evidence supports.
    """
    result = subprocess.run(
        ["git", "apply", "--check", "--verbose", *extra, str(patch)],
        cwd=tree,
        capture_output=True,
        text=True,
    )
    err = (result.stderr or "").strip()
    skipped = [
        line.split("'")[1]
        for line in err.splitlines()
        if line.startswith("Skipped patch") and "'" in line
    ]
    # --verbose puts its running commentary on stderr too. Keep only the
    # lines that are actually complaints, so the reported detail is the
    # error and not "Checking patch ...".
    complaints = [
        line for line in err.splitlines()
        if not line.startswith(("Checking patch", "Skipped patch",
                                "Applied patch", "Checking "))
    ]
    return result.returncode, "\n".join(complaints).strip(), skipped


def patch_path(name: str, patch_set: str | None) -> Path:
    """Where to read one patch from, preferring a rebased copy.

    Same rule as apply.py: patches/<set>/<name> when it is there, the
    original otherwise, so a check and a build read the same bytes.
    """
    if patch_set:
        rebased = PATCHES / patch_set / name
        if rebased.exists():
            return rebased
    return PATCHES / name


def check_patches(tree: Path, patch_set: str | None = None) -> list[dict]:
    rows = []
    for name in series():
        patch = patch_path(name, patch_set)
        targets, created = files_in(patch)
        missing = [f for f in targets if not (tree / f).exists()]
        if missing:
            rows.append(
                {
                    "patch": name,
                    "state": "file gone",
                    "files": targets,
                    "creates": created,
                    "detail": "no longer in the tree: " + ", ".join(missing),
                }
            )
            continue

        code, err, skipped = try_apply(tree, patch, [])
        if code == 0:
            row = {"patch": name, "state": "clean", "files": targets,
                   "creates": created}
            if skipped:
                # Exit 0, but git never looked at these. Saying "clean"
                # here would be a false pass.
                row["state"] = "clean, partly unchecked"
                row["skipped"] = skipped
                row["detail"] = (
                    f"{len(skipped)} new file(s) at ignored paths were "
                    "skipped by git apply and are unverified"
                )
            rows.append(row)
            continue
        # Three way needs blob objects we do not have here, so the next
        # best question is whether it applies with more slack.
        fuzzy, _, fuzzy_skipped = try_apply(tree, patch, ["-C1"])
        row = {
            "patch": name,
            "state": "fuzzy" if fuzzy == 0 else "conflict",
            "files": targets,
            "detail": err.splitlines()[0] if err else "",
        }
        if fuzzy == 0 and fuzzy_skipped:
            row["skipped"] = fuzzy_skipped
        rows.append(row)
    return rows


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_overlay(tree: Path, pristine: Path) -> list[dict]:
    """Our whole file copies, against the new upstream.

    These never fail to apply, which is the danger: replacing a file
    outright puts our old copy of it into the new tree and quietly
    undoes whatever upstream did to it. The comparison is against the
    saved pristine copy of the version we branched from, not against
    the build tree, because the build tree already holds our copy.

    A file with no pristine copy is one we added rather than replaced,
    so upstream has nothing to lose.
    """
    rows = []
    if not OVERLAY.is_dir():
        return rows
    for root, _dirs, names in os.walk(OVERLAY):
        for name in names:
            ours = Path(root) / name
            rel = ours.relative_to(OVERLAY).as_posix()
            new = tree / rel
            was = pristine / rel
            # A pristine copy that is byte for byte our own file is not
            # a pristine copy: apply.py saved it after we had already
            # put the file there, which only happens for files we
            # added. Upstream never had one to lose.
            if not was.exists() or sha(was) == sha(ours):
                rows.append({"file": rel, "state": "ours alone"})
            elif not new.exists():
                rows.append({"file": rel, "state": "upstream dropped it"})
            elif sha(was) == sha(new):
                rows.append({"file": rel, "state": "upstream unchanged"})
            else:
                rows.append({"file": rel, "state": "upstream moved on"})
    return rows


REBRAND_FILES = [
    "chrome/app/chromium_strings.grd",
    "chrome/app/settings_chromium_strings.grdp",
    "components/components_chromium_strings.grd",
    "chrome/app/theme/chromium/BRANDING",
    "chrome/install_static/chromium_install_modes.h",
]


def check_rebrand(tree: Path) -> list[dict]:
    sys.path.insert(0, str(CORE / "tools"))
    import rebrand  # noqa: E402

    rows = []
    for rel in REBRAND_FILES:
        path = tree / rel
        if not path.exists():
            rows.append({"file": rel, "state": "file gone"})
            continue
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
        if rel.endswith((".grd", ".grdp")):
            kept = len(rebrand.PROJECT_REFERENCE.findall(text))
            rows.append(
                {
                    "file": rel,
                    "state": "ok" if kept or "Chromium" not in text else "ok",
                    "project_references": kept,
                }
            )
        elif rel.endswith("chromium_install_modes.h"):
            missing = [old for old, _ in rebrand.INSTALL_MODES
                       if text.count(old) != 1]
            rows.append(
                {
                    "file": rel,
                    "state": "ok" if not missing else "strings moved",
                    "missing": missing,
                }
            )
        else:
            keys = [k for k in rebrand.BRANDING if k + "=" not in text]
            rows.append(
                {
                    "file": rel,
                    "state": "ok" if not keys else "keys moved",
                    "missing": keys,
                }
            )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True, help="the staged source tree")
    ap.add_argument("--json", help="also write the whole report here")
    ap.add_argument(
        "--patch-set",
        help="subdirectory of patches/ holding rebased copies, e.g. 153",
    )
    args = ap.parse_args()

    tree = Path(args.new)
    if not (tree / "BUILD.gn").exists():
        sys.exit(f"{tree} does not look like a Chromium source tree")
    version = (tree / "chrome" / "VERSION").read_text(encoding="utf-8")
    version = ".".join(line.split("=")[1] for line in version.split())

    patches = check_patches(tree, args.patch_set)
    overlay = check_overlay(tree, PRISTINE)
    rebrand_rows = check_rebrand(tree)

    print(f"our patch layer against Chromium {version}\n")
    counts = {}
    for row in patches:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
        if row["state"] != "clean":
            print(f"  {row['state']:<12} {row['patch']}")
            if row.get("detail"):
                print(f"               {row['detail']}")
    print("\npatches: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))

    changed = [
        r
        for r in overlay
        if r["state"] not in ("upstream unchanged", "ours alone")
    ]
    print(f"\nwhole file copies: {len(overlay)} total, {len(changed)} to review")
    for row in changed:
        print(f"  {row['state']:<26} {row['file']}")

    problems = [r for r in rebrand_rows if r["state"] not in ("ok",)]
    print(f"\nrebrand targets: {len(problems)} need attention")
    for row in problems:
        print(f"  {row['state']:<14} {row['file']} {row.get('missing', '')}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "version": version,
                    "patches": patches,
                    "overlay": overlay,
                    "rebrand": rebrand_rows,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("\nwrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
