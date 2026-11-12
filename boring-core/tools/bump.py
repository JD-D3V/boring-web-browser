#!/usr/bin/env python3
r"""Move the browser to a newer ungoogled-chromium-windows tag, one command.

Runs every step the 154 to 157 port did by hand, in order, and stops at
the first one that needs a person, saying exactly what is left. Run the
same command again to resume: a state file in the new tree remembers
which stages are done. See BUMP.txt next to this file.

  python bump.py --tag latest --dir E:\ung-160 --prev E:\ung-157 --branch r4/chromium-160
  python bump.py --dir E:\ung-160 --branch r4/chromium-160          (resume)
  python bump.py --dir E:\ung-160 --status
  python bump.py --dir E:\ung-160 --branch ... --redo sort
  python bump.py --dir E:\ung-160 --branch ... --accept-scan
  python bump.py --dir E:\ung-160 --branch ... --accept-args
  python bump.py --dir E:\ung-160 --branch ... --write-port tab-shape.patch

It writes only into the new tree (--dir) and into this checkout, which
must be on --branch: patches/<major>/, the tree's pristine store and, at
the end, UPSTREAM_VERSION. It never deletes a tree, never commits, and
refuses a tree whose build lock (boring-build.lock, see joblock.py) is
held by someone else.
"""

import argparse
import ast
import ctypes
import functools
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
from datetime import UTC, datetime
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
CORE = TOOLS.parent
REPO = CORE.parent
PATCHES = CORE / "patches"
sys.path.insert(0, str(TOOLS))

from upstream_watch import fetch_tags, parse_tag, pick_latest  # noqa: E402

VCVARS = Path(
    r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
)
STATE_DIR = "boring-bump"
LOCK_NAME = "boring-build.lock"
BELOW_NORMAL = 0x00004000
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

# Stage name, free space it needs in GB (rough: the 154 and 157 trees were
# about 46 GB each, source plus out\Default), and what it replaces.
STAGES = [
    ("stage", 45, "stage_upstream.py by hand"),
    ("patchset", 0, "copying patches/<prev> to patches/<major>"),
    ("pristine", 1, "snapshot.py and apply.py --no-patches"),
    ("sort", 0, "rebase_patch.py and the patch table"),
    ("scan", 1, "offset_scan, ambig_scan, place_scan and file_check"),
    ("flips", 0, "the feature flip extractor"),
    ("args", 0, "write_args.py and add_metagen.py"),
    ("layer", 1, "apply.py --patch-set <major>"),
    ("toolchain", 3, "pre_ninja.bat, copy_rustc_dev.py, MINIBRANCH, gnbin"),
    ("gn", 0, "gn_gen.bat and gn_check.bat"),
    ("compile", 30, "run_ninja.bat at below normal"),
    ("record", 0, "writing down the tag we are on"),
]
NAMES = [s[0] for s in STAGES]

# The _run_build_process calls build.py makes, by their plain string
# arguments. A call that matches none of these is a step build.py gained
# that this script does not know, and the bump stops rather than skip it.
KNOWN_STEPS = {
    "bootstrap": (
        r"tools\gn\bootstrap\bootstrap.py",
        "-o",
        r"out\Default\gn.exe",
        "--skip-generate-buildfiles",
    ),
    "gen": (r"out\Default\gn.exe", "gen", r"out\Default", "--fail-on-unused-args"),
    "bindgen": (r"tools\rust\build_bindgen.py", "--skip-test"),
    "crubit": (
        "build",
        "--release",
        "--locked",
        "-p",
        "cc_bindings_from_rs",
        "--bin",
        "cc_bindings_from_rs",
        "--manifest-path",
        "--target-dir",
    ),
    "ninja": (),
}

# Where a changed feature default is likely to show in what users see.
UI_PREFIXES = (
    "chrome/browser/ui/",
    "chrome/browser/resources/",
    "ui/",
    "components/omnibox/",
)


class NeedsHuman(Exception):
    """A stage reached something a person has to decide or fix."""


# ---------------------------------------------------------------- state


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_state(path):
    if not Path(path).exists():
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_state(path, state):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def new_state(tag, root, prev, branch, source):
    return {
        "tag": tag,
        "major": parse_tag(tag)[0],
        "dir": str(root),
        "prev": str(prev),
        "branch": branch,
        "source": source,
        "stages": {name: {"status": "pending"} for name in NAMES},
    }


def next_stage(state):
    """The first stage that is not done, or None when all are."""
    for name in NAMES:
        if state["stages"][name]["status"] != "done":
            return name
    return None


def mark(state, name, status, note=""):
    state["stages"][name] = {"status": status, "at": now(), "note": note}


def redo(state, name):
    """Make name and every stage after it run again."""
    for later in NAMES[NAMES.index(name) :]:
        state["stages"][later] = {"status": "pending"}


# ----------------------------------------------------------------- disk


def disk_need_gb(state):
    """Space the stages still to run need, roughly."""
    if state is None:
        return sum(gb for _, gb, _ in STAGES)
    return sum(
        gb for name, gb, _ in STAGES if state["stages"][name]["status"] != "done"
    )


def check_disk(path, need_gb, usage=shutil.disk_usage):
    """(ok, message) for the drive holding path."""
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    free_gb = usage(str(probe)).free / 2**30
    msg = f"{free_gb:.0f} GB free on {probe.anchor or probe}, about {need_gb} GB needed"
    return free_gb >= need_gb, msg


# ------------------------------------------------------------ sorting


BUCKETS = {
    "applies as is": "applies",
    "already in the tree": "applies",
    "rebased": "refreshed",
}


def changed_lines(text):
    """The added and removed lines of a patch, without the file headers."""
    out = []
    for line in text.splitlines():
        if line.startswith(("+++", "---")):
            continue
        if line.startswith(("+", "-")):
            out.append(line)
    return sorted(out)


def sort_series(names, rebase_one, read_patch):
    """Put every patch in a bucket: applies, refreshed (context only) or conflict.

    rebase_one(name) -> (state, detail) is rebase_patch.rebase_one bound
    to the tree; read_patch(name) -> text reads the set's copy. A refresh
    only counts as context only when the added and removed lines are the
    same before and after; anything else is a conflict for a person.
    """
    rows = []
    for name in names:
        before = read_patch(name)
        try:
            state, detail = rebase_one(name)
        except Exception as err:  # a patch that breaks the tool is a conflict too
            state, detail = "ERROR", f"{type(err).__name__}: {err}"
        bucket = BUCKETS.get(state, "conflict")
        if bucket == "refreshed" and changed_lines(read_patch(name)) != changed_lines(
            before
        ):
            bucket, detail = "conflict", "refreshed, but its changed lines differ"
        rows.append({"patch": name, "bucket": bucket, "state": state, "detail": detail})
    return rows


# --------------------------------------------------------- args.gn

# What the args.gn interpreter lets build.py do to a value. Reading only:
# a Path gets pure path operations and a read under the tree, a str gets
# replace (which on a str only returns a new str). Anything that writes,
# moves or deletes (Path.replace, rename, unlink, write_text, open, mkdir
# in an expression, ...) is not in these sets and stops the bump.
PATH_READS = {"resolve", "as_posix", "parent"}
STR_METHODS = {"replace"}
WRITING_CALLS = {
    "replace", "rename", "unlink", "write_text", "write_bytes", "open", "mkdir",
    "rmdir", "touch", "chmod", "symlink_to", "hardlink_to", "link_to",
}  # fmt: skip
WRITING_NAMES = {"open", "exec", "eval", "compile", "__import__"}
# The only modules build.py may ask importlib to find: plain top-level
# names, never dotted (find_spec("a.b") imports package a).
SPEC_NAMES = {"clang"}


class _Logger:
    def __init__(self):
        self.messages = []

    def error(self, msg, *args):
        self.messages.append(msg % args if args else msg)

    info = warning = error


def _args_block(tree):
    """The statements around build.py's write of out/Default/args.gn."""
    for node in ast.walk(tree):
        for field in ("body", "orelse"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            for stmt in stmts:
                if (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Call)
                    and isinstance(stmt.value.func, ast.Attribute)
                    and stmt.value.func.attr == "write_text"
                    and "args.gn" in ast.unparse(stmt.value.func.value)
                ):
                    return stmts
    raise NeedsHuman("build.py no longer writes out/Default/args.gn; write it by hand")


def args_gn_from_build_py(text, root, tarball, find_spec=importlib.util.find_spec):
    """args.gn exactly as the tag's build.py would write it (x64).

    Interprets the few statements of build.py that build the file, with
    a whitelist: anything it does not understand stops the bump instead
    of being guessed at. Files are only read, and only under root.
    """
    root = Path(root).resolve()
    log = _Logger()
    real_find_spec = find_spec

    def find_spec(name, *_a):
        # A dotted name imports its parent package, which runs its code.
        if not isinstance(name, str) or name not in SPEC_NAMES:
            raise NeedsHuman(
                f"build.py looks up module {name!r}; bump.py only looks up "
                f"{sorted(SPEC_NAMES)} (a dotted or unknown name could run code)"
            )
        return real_find_spec(name)

    def exit_(*_a):
        raise NeedsHuman(
            "build.py stops here: " + (log.messages[-1] if log.messages else "sys.exit")
        )

    def read_text(path, **_kw):
        path = Path(path).resolve()
        if root not in path.parents:
            raise NeedsHuman(f"build.py reads {path}, outside {root}")
        return path.read_text(encoding="utf-8")

    env = {
        "_ROOT_DIR": root,
        "source_tree": root / "build" / "src",
        "ENCODING": "utf-8",
        "args": types.SimpleNamespace(x86=False, arm=False, tarball=tarball, ci=False),
        "importlib": types.SimpleNamespace(
            util=types.SimpleNamespace(find_spec=find_spec)
        ),
        "sys": types.SimpleNamespace(exit=exit_),
        "get_logger": lambda: log,
        "Path": Path,
        "list": list,
    }

    def unsupported(node):
        writes = sorted(
            {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            & WRITING_CALLS
            | {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} & WRITING_NAMES
        )
        if writes:
            return NeedsHuman(
                f"build.py line {node.lineno} writes, moves or runs something "
                f"({', '.join(writes)}): {ast.unparse(node)[:120]}; bump.py only reads "
                "files, so it stops here. Read that line, then write args.gn by hand "
                "and run again with --redo layer"
            )
        return NeedsHuman(
            f"build.py line {node.lineno} is new to bump.py: {ast.unparse(node)[:120]}; "
            "write args.gn by hand and run again with --redo layer"
        )

    def ev(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in env:
            return env[node.id]
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append(v.value)
                elif isinstance(v, ast.FormattedValue) and v.format_spec is None:
                    val = ev(v.value)
                    parts.append(repr(val) if v.conversion == ord("r") else str(val))
                else:
                    raise unsupported(node)
            return "".join(parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Add) and isinstance(left, str):
                return left + right
            if isinstance(node.op, ast.Div) and isinstance(left, Path):
                return left / right
            raise unsupported(node)
        if isinstance(node, ast.Attribute):
            base = ev(node.value)
            if isinstance(base, Path):
                if node.attr == "read_text":
                    return functools.partial(read_text, base)
                if node.attr in PATH_READS:
                    return getattr(base, node.attr)
                raise unsupported(node)
            if isinstance(base, str):
                if node.attr in STR_METHODS:
                    return getattr(base, node.attr)
                raise unsupported(node)
            if node.attr.startswith("_"):
                raise unsupported(node)
            if isinstance(base, types.SimpleNamespace | _Logger) or node.attr in (
                "submodule_search_locations",
            ):
                try:
                    return getattr(base, node.attr)
                except AttributeError:
                    raise unsupported(node) from None
            raise unsupported(node)
        if isinstance(node, ast.Call):
            fn = ev(node.func)
            return fn(
                *[ev(a) for a in node.args],
                **{k.arg: ev(k.value) for k in node.keywords},
            )
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            return ev(node.value)[node.slice.value]
        if isinstance(node, ast.BoolOp):
            vals = (ev(v) for v in node.values)
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not ev(node.operand)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            a, b, op = ev(node.left), ev(node.comparators[0]), node.ops[0]
            if isinstance(op, ast.Is):
                return a is b
            if isinstance(op, ast.IsNot):
                return a is not b
            if isinstance(op, ast.Eq):
                return a == b
        raise unsupported(node)

    def run(stmts):
        for s in stmts:
            if (
                isinstance(s, ast.Assign)
                and len(s.targets) == 1
                and isinstance(s.targets[0], ast.Name)
            ):
                env[s.targets[0].id] = ev(s.value)
            elif (
                isinstance(s, ast.AugAssign)
                and isinstance(s.target, ast.Name)
                and isinstance(s.op, ast.Add)
            ):
                env[s.target.id] = env[s.target.id] + ev(s.value)
            elif isinstance(s, ast.If):
                result = run(s.body if ev(s.test) else s.orelse)
                if result is not None:
                    return result
            elif isinstance(s, ast.Expr) and isinstance(s.value, ast.Call):
                func = s.value.func
                # Never executed: the folder and the file are bump.py's to write.
                if isinstance(func, ast.Attribute) and func.attr == "mkdir":
                    continue
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "write_text"
                    and "args.gn" in ast.unparse(func.value)
                ):
                    return ev(s.value.args[0])
                ev(s.value)
            else:
                raise unsupported(s)
        return None

    out = run(_args_block(ast.parse(text)))
    if not isinstance(out, str):
        raise NeedsHuman("could not work out what build.py writes to args.gn")
    return out


# Keys whose value follows the tree or the machine, not a decision upstream
# made: where libclang and the Python clang bindings are.
VERSION_KEYS = {"v8_metagen_libclang_so", "v8_metagen_libclang_bindings_dir"}


def args_gn_values(text):
    """{key: value} of an args.gn; a key set twice keeps its last value, as gn does."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def args_gn_diff(old_text, new_text):
    """Lines saying which args.gn keys differ, leaving out VERSION_KEYS."""
    old, new = args_gn_values(old_text), args_gn_values(new_text)
    out = []
    for key in sorted(set(old) | set(new)):
        if key in VERSION_KEYS or old.get(key) == new.get(key):
            continue
        if key not in old:
            out.append(f"ADDED   {key}={new[key]}")
        elif key not in new:
            out.append(f"REMOVED {key}={old[key]}")
        else:
            out.append(f"CHANGED {key}: {old[key]} -> {new[key]}")
    return out


def build_steps(text):
    """[(kind, line)] for every _run_build_process call; kind None = unknown."""
    steps = []
    for node in ast.walk(ast.parse(text)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if not node.func.id.startswith("_run_build_process") or not node.args:
            continue
        consts = tuple(
            a.value
            for a in node.args
            if isinstance(a, ast.Constant) and isinstance(a.value, str)
        )
        kind = next((k for k, v in KNOWN_STEPS.items() if v == consts), None)
        if kind == "ninja" and not any(isinstance(a, ast.Starred) for a in node.args):
            kind = None
        steps.append((kind, node.lineno))
    return sorted(steps, key=lambda s: s[1])


# ------------------------------------------------------ the tag's commit

# The line under the tag in UPSTREAM_VERSION. A comment, so the watcher
# still reads the tag as the first line that is not one.
COMMIT_PREFIX = "# commit "
# And the tree it was built in, so the next bump never writes there.
TREE_PREFIX = "# tree "


def recorded_trees(path):
    """The tree folders named on '# tree' lines of UPSTREAM_VERSION."""
    path = Path(path)
    if not path.exists():
        return []
    return [
        Path(ln[len(TREE_PREFIX) :].strip()).resolve()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.startswith(TREE_PREFIX) and ln[len(TREE_PREFIX) :].strip()
    ]


def check_tag_pin(tag, pinned, local, remote):
    """Stop unless the clone and GitHub's tag are still on the pinned commit.

    pinned is the commit the tag named when staging began; local is the
    clone's HEAD now; remote is what GitHub says the tag points at now
    (None if it could not be asked).
    """
    if local != pinned:
        raise NeedsHuman(
            f"the clone is on {local}, but tag {tag} was pinned at {pinned} when the "
            "bump began; the source changed under us. Start again in a new folder."
        )
    if remote is None:
        raise NeedsHuman(
            f"could not ask GitHub where tag {tag} points now; run again when online"
        )
    if remote != pinned:
        raise NeedsHuman(
            f"upstream moved tag {tag} from {pinned} to {remote} since staging; "
            "read what changed before trusting it, and start again in a new folder."
        )


# ----------------------------------------------------- patch helpers


def series():
    text = (PATCHES / "series").read_text(encoding="utf-8")
    return [
        ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")
    ]


def patch_path(name, patch_set):
    rebased = PATCHES / patch_set / name
    return rebased if rebased.exists() else PATCHES / name


def patch_files(text):
    """(changed, created) tree paths of one patch."""
    changed, created = [], []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("+++ b/"):
            prev = lines[i - 1].strip() if i else ""
            (
                created if prev in ("--- /dev/null", "--- a/dev/null") else changed
            ).append(line[6:].strip())
    return changed, created


def hunks(text):
    """[(file, header, preimage lines, first run of added lines)] of one patch."""
    out, rel, cur = [], None, None
    for line in text.splitlines():
        if line.startswith("+++ b/"):
            rel = line[6:].strip()
        elif line.startswith("@@") and rel:
            cur = (rel, line, [], [])
            out.append(cur)
        elif cur and not line.startswith(("---", "+++")):
            if line.startswith((" ", "-")) or line == "":
                cur[2].append(line[1:])
                if cur[3]:
                    cur[3].append(None)
            elif line.startswith("+"):
                cur[3].append(line[1:])
    result = []
    for rel, head, pre, added in out:
        run = []
        for a in added:
            if a is None:
                break
            if a.strip():
                run.append(a)
        result.append((rel, head, pre, run[:4]))
    return result


def read_lines(path):
    return (
        Path(path)
        .read_bytes()
        .decode("utf-8", "replace")
        .replace("\r\n", "\n")
        .split("\n")
    )


FN = re.compile(r"^[A-Za-z_~#]")
NOT_FN = re.compile(
    r"^(public|private|protected|default)\s*:|^#(include|endif|else|if|define|undef)"
)


def enclosing(lines, at):
    """git's idea of the function line above `at`."""
    for i in range(at - 1, -1, -1):
        if FN.match(lines[i]) and not NOT_FN.match(lines[i]):
            return lines[i].strip()[:80]
    return ""


def find_run(lines, run):
    for s, line in enumerate(lines):
        if line == run[0]:
            j, ok = s, True
            for r in run[1:]:
                try:
                    j = lines.index(r, j + 1, j + 9)
                except ValueError:
                    ok = False
                    break
            if ok:
                return s
    return -1


def git_env(*no_repo_dirs):
    """Environment that keeps git from finding a repository above these dirs.

    A tarball tree sits inside the ungoogled checkout, whose .gitignore
    has /build; git apply then silently skips new files there.
    """
    env = dict(os.environ)
    ceilings = [str(Path(d).parent) for d in no_repo_dirs]
    if env.get("GIT_CEILING_DIRECTORIES"):
        ceilings.append(env["GIT_CEILING_DIRECTORIES"])
    env["GIT_CEILING_DIRECTORIES"] = os.pathsep.join(ceilings)
    return env


def fresh_dir(path):
    """An empty scratch folder. Only ever under the new tree's state dir."""
    path = Path(path)
    if STATE_DIR not in path.parts:
        raise RuntimeError(f"refusing to clear {path}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


# ------------------------------------------------------- the driver


class Bump:
    def __init__(self, root, state, args):
        self.root = Path(root)
        self.src = self.root / "build" / "src"
        self.dir = self.root / STATE_DIR
        self.state = state
        self.args = args
        self.set = str(state["major"])
        self.prev_src = Path(state["prev"]) / "build" / "src"
        # Every git apply here, ours and apply.py's, must not see the
        # ungoogled checkout around a tarball tree.
        os.environ["GIT_CEILING_DIRECTORIES"] = git_env(self.src)[
            "GIT_CEILING_DIRECTORIES"
        ]

    # helpers
    def log(self, name):
        return self.dir / f"{name}.log"

    def call(self, cmd, log, **kw):
        """Run cmd at below normal priority, output to log; return the exit code."""
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n=== {now()} {' '.join(str(c) for c in cmd)}\n")
            f.flush()
            flags = BELOW_NORMAL if os.name == "nt" else 0
            return subprocess.call(
                [str(c) for c in cmd],
                stdout=f,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                **kw,
            )

    def store(self):
        import pristine

        return Path(pristine.store_for(str(self.src)))

    def patches(self):
        return [(n, patch_path(n, self.set)) for n in series()]

    def our_files(self):
        files = set()
        for _n, p in self.patches():
            changed, created = patch_files(
                p.read_text(encoding="utf-8", errors="replace")
            )
            files.update(changed + created)
        overlay = CORE / "chromium_src"
        files.update(
            p.relative_to(overlay).as_posix() for p in overlay.rglob("*") if p.is_file()
        )
        return files

    def bat(self, name, body):
        """A batch file with build.py's environment around body."""
        path = self.dir / f"{name}.bat"
        tmp = os.environ.get("TMP", r"E:\tmp")
        path.write_text(
            "@echo off\r\n"
            f'call "{self.args.vcvars}" >nul || exit /b 1\r\n'
            f"set TMP={tmp}\r\nset TEMP={tmp}\r\nset DEPOT_TOOLS_WIN_TOOLCHAIN=0\r\n"
            f'cd /d "{self.src}" || exit /b 1\r\n' + body.replace("\n", "\r\n"),
            encoding="utf-8",
        )
        return path

    # stages
    def do_stage(self):
        cmd = [sys.executable, TOOLS / "stage_upstream.py", "--tag", self.state["tag"]]
        cmd += ["--dir", self.root, "--source", self.state["source"]]
        if self.state.get("tag_sha"):
            cmd += ["--expect-sha", self.state["tag_sha"]]
        if self.call(cmd, self.log("stage")):
            raise NeedsHuman(
                f"staging failed, see {self.log('stage')}. If Google never published the "
                "tarball for this tag, run again with --source clone."
            )
        import stage_upstream

        stage_upstream.add_rustc_dev(self.src)
        stage_upstream.write_minibranch(self.src)
        version = ".".join(
            ln.split("=")[1]
            for ln in (self.src / "chrome" / "VERSION")
            .read_text(encoding="utf-8")
            .split()
        )
        self.state["version"] = version
        return f"Chromium {version}"

    def do_patchset(self):
        older = sorted(
            int(p.name) for p in PATCHES.iterdir() if p.is_dir() and p.name.isdigit()
        )
        older = [m for m in older if m <= self.state["major"]]
        source = self.args.from_set or (str(older[-1]) if older else None)
        dest = PATCHES / self.set
        if dest.exists() or source is None or source == self.set:
            dest.mkdir(exist_ok=True)
            return f"patches/{self.set} kept as it is"
        dest.mkdir()
        for p in (PATCHES / source).iterdir():
            shutil.copy2(p, dest / p.name)
        return f"patches/{self.set} seeded from patches/{source}"

    def do_pristine(self):
        import apply
        from rebrand import STRING_FILES

        store = self.store()
        paths = [str(p) for _n, p in self.patches()]
        apply.seed_pristine(str(self.src), paths, str(store))
        # The patches' new files, whether or not sort already put them in
        # (a --redo pristine). One with a store copy is Chromium's own.
        ours_new = []
        for _n, p in self.patches():
            _changed, created = patch_files(
                p.read_text(encoding="utf-8", errors="replace")
            )
            ours_new += [c for c in created if not (store / c).exists()]
        self.state["ours_new"] = sorted(set(ours_new))
        for rel in STRING_FILES:
            if (self.src / rel).exists():
                apply.snapshot(str(self.src), rel.replace("/", os.sep), str(store))
        cmd = [
            sys.executable,
            TOOLS / "apply.py",
            "--src",
            self.src,
            "--patch-set",
            self.set,
        ]
        if self.call(cmd + ["--no-patches", "--no-rust"], self.log("pristine")):
            raise NeedsHuman(
                f"apply.py --no-patches failed, see {self.log('pristine')}"
            )
        return f"store {store.name}"

    def rewind(self):
        """Put every patched file back to the store copy, so sort can rerun."""
        store, overlay = self.store(), CORE / "chromium_src"
        for _n, p in self.patches():
            changed, _created = patch_files(
                p.read_text(encoding="utf-8", errors="replace")
            )
            for rel in changed:
                keep = store / rel
                if keep.exists() and not (overlay / rel).exists():
                    shutil.copy(keep, self.src / rel)
        for rel in self.state.get("ours_new", []):
            (self.src / rel).unlink(missing_ok=True)

    def do_sort(self):
        import rebase_patch

        self.rewind()
        rows = sort_series(
            series(),
            lambda n: rebase_patch.rebase_one(str(self.src), n, self.set, False),
            lambda n: patch_path(n, self.set).read_text(
                encoding="utf-8", errors="replace"
            ),
        )
        (self.dir / "sort.json").write_text(
            json.dumps(rows, indent=2), encoding="utf-8"
        )
        counts = {
            b: sum(r["bucket"] == b for r in rows)
            for b in ("applies", "refreshed", "conflict")
        }
        lines = [
            f"{r['bucket']:<10} {r['patch']}  {r['state']}  {r['detail']}" for r in rows
        ]
        (self.dir / "sort.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        summary = ", ".join(f"{v} {k}" for k, v in counts.items())
        print(summary)
        for r in rows:
            if r["bucket"] != "applies":
                print(f"  {r['bucket']:<10} {r['patch']}  {r['detail']}")
        conflicts = [r["patch"] for r in rows if r["bucket"] == "conflict"]
        if conflicts:
            raise NeedsHuman(
                f"{len(conflicts)} patch(es) need a hand port: {', '.join(conflicts)}.\n"
                f"  For each: edit the files under {self.src} (the patches before it are in),\n"
                f"  then: python bump.py --dir {self.root} --branch {self.state['branch']} "
                "--write-port <name>\n"
                "  When every conflict has a port, run bump.py again; sort reruns from the store."
            )
        return summary

    def series_scratch(self, work, upto=None):
        """Store copies of the patched files with the series applied in a scratch dir.

        Stops before patch `upto` when given. Returns findings.
        """
        work = fresh_dir(work)
        store = self.store()
        found = {"FAIL": [], "OFFSET": [], "AMBIG": []}
        texts = [
            (n, p, p.read_text(encoding="utf-8", errors="replace"))
            for n, p in self.patches()
        ]
        for _n, _p, text in texts:
            changed, _created = patch_files(text)
            for rel in changed:
                if (store / rel).exists() and not (work / rel).exists():
                    (work / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(store / rel, work / rel)
        env = git_env(work)
        offset = re.compile(r"Hunk #(\d+) succeeded at (\d+) \(offset (-?\d+) lines?\)")
        for name, p, text in texts:
            if name == upto:
                break
            for rel, head, pre, _run in hunks(text):
                if pre and (work / rel).exists():
                    lines = read_lines(work / rel)
                    hits = [
                        s + 1
                        for s in range(len(lines) - len(pre) + 1)
                        if lines[s] == pre[0] and lines[s : s + len(pre)] == pre
                    ]
                    if len(hits) > 1:
                        found["AMBIG"].append(
                            f"{name} {rel} {head[:60]} matches at {hits}"
                        )
            r = subprocess.run(
                ["git", "apply", "--verbose", "--whitespace=nowarn", str(p)],
                cwd=work,
                capture_output=True,
                text=True,
                env=env,
            )
            if r.returncode:
                found["FAIL"].append(f"{name}: {r.stderr.strip()[:300]}")
                continue
            for m in offset.finditer(r.stdout + r.stderr):
                if abs(int(m.group(3))) >= 40:
                    found["OFFSET"].append(
                        f"{name} hunk {m.group(1)} offset {m.group(3)}"
                    )
        return found

    def do_scan(self):
        work = self.dir / "scan"
        found = self.series_scratch(work)
        found["DIFF"], found["PLACE"] = [], []
        for _n, p in self.patches():
            changed, created = patch_files(
                p.read_text(encoding="utf-8", errors="replace")
            )
            for rel in changed + created:
                mine, tree = work / rel, self.src / rel
                if (
                    mine.exists()
                    and tree.exists()
                    and read_lines(mine) != read_lines(tree)
                ):
                    found["DIFF"].append(f"{rel}: store + series differs from the tree")
        found["DIFF"] = sorted(set(found["DIFF"]))
        cache = {}
        for name, p in self.patches():
            for k, (rel, _head, _pre, run) in enumerate(
                hunks(p.read_text(encoding="utf-8")), 1
            ):
                a, b = self.src / rel, self.prev_src / rel
                if not run or not a.exists() or not b.exists():
                    continue
                ta = cache.setdefault(a, read_lines(a))
                tb = cache.setdefault(b, read_lines(b))
                ia, ib = find_run(ta, run), find_run(tb, run)
                if ia >= 0 and ib >= 0 and enclosing(ta, ia) != enclosing(tb, ib):
                    found["PLACE"].append(
                        f"{name} {rel} hunk {k}: now under '{enclosing(ta, ia)}', "
                        f"was under '{enclosing(tb, ib)}'"
                    )
        report = [f"{kind} {item}" for kind, items in found.items() for item in items]
        (self.dir / "scan.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
        counts = ", ".join(f"{len(v)} {k}" for k, v in found.items())
        print(counts)
        stop = [r for r in report if not r.startswith("OFFSET")]
        for line in stop[:40]:
            print(" ", line)
        if stop and not self.args.accept_scan:
            raise NeedsHuman(
                f"{len(stop)} placement finding(s), see {self.dir / 'scan.txt'}. FAIL and DIFF mean "
                "the tree is not the store plus the series; PLACE means a hunk now sits in a "
                "different function than on the previous tree (the 157 adblock throttle bug); "
                "AMBIG means git had more than one place to put a hunk. Read each, fix what is "
                "wrong (--write-port, then --redo sort), then run again with --accept-scan."
            )
        return counts

    def do_flips(self):
        import feature_flips

        old, _ctx, _note = feature_flips.run(str(self.prev_src))
        new, _ctx, note = feature_flips.run(
            str(self.src), flags_root=str(self.prev_src)
        )
        changes = feature_flips.compare(old, new)
        ours = self.our_files()
        our_dirs = {str(Path(f).parent.as_posix()) for f in ours}
        texts = {}
        for f in ours:
            if (self.src / f).is_file():
                texts[f] = (self.src / f).read_text(encoding="utf-8", errors="replace")
        lines = [note] if note else []
        hits = 0
        for kind in ("off_to_on", "on_to_off", "new_on"):
            for row in changes[kind]:
                ident = row["ident"].split("::")[-1]
                why = []
                if row["file"].startswith(UI_PREFIXES):
                    why.append("defined in UI code")
                if str(Path(row["file"]).parent.as_posix()) in our_dirs:
                    why.append("defined next to a file we patch")
                used = [
                    f
                    for f, t in texts.items()
                    if re.search(rf"\b{re.escape(ident)}\b", t)
                ]
                if used:
                    why.append("used in " + ", ".join(sorted(used)[:3]))
                if why:
                    hits += 1
                    lines.append(
                        f"{kind:<10} {row['name']}  ({row['file']}:{row['line']}) {'; '.join(why)}"
                    )
        defaults = patch_path("feature-defaults.patch", self.set)
        names_now = {r["name"] for r in new}
        if defaults.exists():
            text = defaults.read_text(encoding="utf-8")
            for name in re.findall(r'^\+\s+"([A-Za-z0-9_]+)",\s*$', text, re.M):
                if name not in names_now:
                    lines.append(
                        f"GONE       {name}: feature-defaults.patch no longer forces anything"
                    )
        (self.dir / "flips.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        for line in lines:
            print(" ", line)
        return f"{hits} flips touch our patches or the UI; {self.dir / 'flips.txt'}"

    def do_args(self):
        text = (self.root / "build.py").read_text(encoding="utf-8")
        unknown = [line for kind, line in build_steps(text) if kind is None]
        if unknown:
            raise NeedsHuman(
                f"build.py runs step(s) bump.py does not know, at line(s) {unknown}; "
                "read them and teach KNOWN_STEPS or run them by hand"
            )
        kinds = {kind for kind, _ in build_steps(text)}
        self.state["bindgen"], self.state["crubit"] = (
            "bindgen" in kinds,
            "crubit" in kinds,
        )
        content = args_gn_from_build_py(
            text, self.root, self.state["source"] == "tarball"
        )
        # A flag upstream added or flipped (official build, dcheck, symbols,
        # sandbox, API keys) must not slip into our build unseen.
        prev_args = self.prev_src / "out" / "Default" / "args.gn"
        if prev_args.is_file():
            diff = args_gn_diff(prev_args.read_text(encoding="utf-8"), content)
        else:
            diff = [f"no args.gn in the previous tree at {prev_args} to compare with"]
        (self.dir / "args-diff.txt").write_text(
            "\n".join(diff) + "\n" if diff else "", encoding="utf-8"
        )
        if diff and not self.args.accept_args:
            for line in diff:
                print(" ", line)
            raise NeedsHuman(
                f"args.gn differs from the previous tree ({diff[0]}; {len(diff)} line(s), "
                f"listed above and in {self.dir / 'args-diff.txt'}). Read each (a changed default can "
                "undo a privacy or safety setting), then run again with --accept-args."
            )
        out = self.src / "out" / "Default"
        out.mkdir(parents=True, exist_ok=True)
        (out / "args.gn").write_text(content, encoding="utf-8")
        return f"args.gn {len(content.splitlines())} lines"

    def do_layer(self):
        cmd = [
            sys.executable,
            TOOLS / "apply.py",
            "--src",
            self.src,
            "--patch-set",
            self.set,
        ]
        if self.args.no_rust:
            cmd.append("--no-rust")
        if self.call(cmd, self.log("layer")):
            raise NeedsHuman(f"apply.py failed, see {self.log('layer')}")
        return "components, overlay, patches and rebrand in the tree"

    def do_toolchain(self):
        import stage_upstream

        stage_upstream.add_rustc_dev(self.src)
        stage_upstream.write_minibranch(self.src)
        py = sys.executable
        body = (
            "if not exist out\\Default\\gn.exe (\n"
            f'  "{py}" tools\\gn\\bootstrap\\bootstrap.py -o out\\Default\\gn.exe '
            "--skip-generate-buildfiles || exit /b 1\n)\n"
        )
        if self.state.get("bindgen", True):
            body += (
                "if not exist third_party\\rust-toolchain\\bin\\bindgen.exe (\n"
                f'  "{py}" tools\\rust\\build_bindgen.py --skip-test || exit /b 1\n)\n'
            )
        if self.state.get("crubit", True):
            rt, crubit = (
                self.src / "third_party" / "rust-toolchain",
                self.src / "out" / "crubit",
            )
            body += (
                "if not exist third_party\\rust-toolchain\\crubit\\bin\\cc_bindings_from_rs.exe (\n"
                f'  set "RUSTC={rt}\\bin\\rustc.exe"\n'
                f'  set "CARGO_HOME={crubit}\\cargo_home"\n'
                '  set "RUSTFLAGS=-Ctarget-feature=+crt-static"\n'
                "  third_party\\rust-toolchain\\bin\\cargo.exe build --release --locked "
                "-p cc_bindings_from_rs --bin cc_bindings_from_rs "
                f'--manifest-path "{rt}\\crubit\\lib\\third_party\\crubit\\Cargo.toml" '
                f'--target-dir "{crubit}" || exit /b 1\n'
                "  if not exist third_party\\rust-toolchain\\crubit\\bin "
                "mkdir third_party\\rust-toolchain\\crubit\\bin\n"
                "  copy /y out\\crubit\\release\\cc_bindings_from_rs.exe "
                "third_party\\rust-toolchain\\crubit\\bin\\ || exit /b 1\n"
                "  copy /y third_party\\rust-toolchain\\bin\\*.dll "
                "third_party\\rust-toolchain\\crubit\\bin\\ || exit /b 1\n"
                "  third_party\\rust-toolchain\\crubit\\bin\\cc_bindings_from_rs.exe --help "
                ">nul || exit /b 1\n)\n"
            )
        body += "echo TOOLCHAIN OK\n"
        if self.call(["cmd", "/c", self.bat("toolchain", body)], self.log("toolchain")):
            raise NeedsHuman(
                f"gn bootstrap, bindgen or Crubit failed, see {self.log('toolchain')}"
            )
        # V8's metagen looks for gn on PATH; ungoogled has no buildtools\win\gn.exe.
        gnbin = self.dir / "gnbin"
        gnbin.mkdir(exist_ok=True)
        shutil.copy2(self.src / "out" / "Default" / "gn.exe", gnbin / "gn.exe")
        return "gn.exe, bindgen, Crubit, gn on PATH for metagen"

    def do_gn(self):
        body = (
            "out\\Default\\gn.exe gen out\\Default --fail-on-unused-args || exit /b 1\n"
            "echo GN GEN OK\n"
            "out\\Default\\gn.exe check out\\Default //components/boring/* || exit /b 2\n"
            "echo GN CHECK OK\n"
        )
        rc = self.call(["cmd", "/c", self.bat("gn", body)], self.log("gn"))
        if rc == 1:
            raise NeedsHuman(f"gn gen failed, see {self.log('gn')}")
        if rc:
            raise NeedsHuman(
                f"gn check of //components/boring/* failed (our BUILD.gn deps), see {self.log('gn')}"
            )
        return "gn gen and gn check OK"

    def do_compile(self):
        log = self.log("compile")
        body = (
            f'set "PATH={self.dir / "gnbin"};%PATH%"\n'
            f'echo START %DATE% %TIME% >> "{log}"\n'
            f'third_party\\ninja\\ninja.exe -C out\\Default chrome chromedriver >> "{log}" 2>&1\n'
            "set RC=%ERRORLEVEL%\n"
            f'echo DONE RC=%RC% >> "{log}"\n'
        )
        bat = self.bat("compile", body)
        cmd = [
            sys.executable,
            TOOLS / "joblock.py",
            "--lock-file",
            self.root / LOCK_NAME,
        ]
        compile_owner = f"bump-{self.set}-compile"
        cmd += [
            "--owner",
            compile_owner,
            "--job",
            f"bump compile {self.state['tag']}",
        ]
        cmd += ["--", "cmd", "/c", bat]
        # No gap: name the compile job as the holder (short lease), THEN let
        # go of the operating system lock. Another job that grabs the tree in
        # between sees a lease that is not its own and is refused.
        lock = getattr(self, "lock", None)
        if lock is None:
            raise NeedsHuman("bump.py does not hold the build lock to hand to ninja")
        lock.hand_over(compile_owner, f"bump compile {self.state['tag']}", HANDOVER_LEASE)
        self.lock = None
        with open(self.dir / "compile-launch.log", "a", encoding="utf-8") as out:
            proc = subprocess.Popen(
                [str(c) for c in cmd],
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=BELOW_NORMAL | DETACHED if os.name == "nt" else 0,
                close_fds=True,
            )
        confirm_handover(self.root / LOCK_NAME, compile_owner, proc)
        self.state["compile"] = {"pid": proc.pid, "log": str(log), "started": now()}
        return "started"

    def do_record(self):
        import stage_upstream

        sha = self.state.get("tag_sha")
        if sha:
            check_tag_pin(
                self.state["tag"],
                sha,
                stage_upstream.head_sha(self.root),
                stage_upstream.remote_tag_sha(self.state["tag"]),
            )
        path = CORE / "UPSTREAM_VERSION"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        head = [
            ln
            for ln in text.splitlines()
            if ln.startswith("#") and not ln.startswith((COMMIT_PREFIX, TREE_PREFIX))
        ]
        tail = ([f"{COMMIT_PREFIX}{sha}"] if sha else []) + [
            f"{TREE_PREFIX}{self.root}"
        ]
        path.write_text(
            "\n".join(head + [self.state["tag"]] + tail) + "\n", encoding="utf-8"
        )
        old = str(Path(self.state["prev"]))
        r = subprocess.run(
            ["git", "-C", str(REPO), "grep", "-l", "-F", old],
            capture_output=True,
            text=True,
        )
        stale = r.stdout.split()
        print(f"UPSTREAM_VERSION now {self.state['tag']}.")
        if stale:
            print(
                f"These files still name {old} (workflows, defaults); move them when it ships:"
            )
            for f in stale:
                print("   ", f)
        return "recorded"

    # locking
    def take_lock(self):
        import joblock

        self.lock = joblock.JobLock(
            f"bump {self.state['tag']}",
            path=self.root / LOCK_NAME,
            owner=f"bump-{self.set}",
        )
        try:
            self.lock.acquire()
        except joblock.TreeBusy as busy:
            sys.exit(f"refusing: {busy}")

    def release_lock(self):
        lock = getattr(self, "lock", None)
        if lock:
            lock.release()
            self.lock = None


# ---------------------------------------------------------- compile

# How long the compile job's claim on the tree stands before joblock.py has
# started and taken the lock itself.
HANDOVER_LEASE = 120.0


def confirm_handover(lock_path, owner, proc, wait=60.0, poll=0.5, clock=None):
    """Stop unless joblock.py (proc) really took the tree as owner.

    Its holder note shows the owner and the pid of proc once it has the
    operating system lock. If it exits first (75 means the tree was busy)
    the compile did not start.
    """
    import joblock

    clock = clock or time.monotonic
    deadline = clock() + wait
    while True:
        holder = joblock.read_holder(Path(lock_path)) or {}
        if holder.get("owner") == owner and holder.get("pid") == proc.pid:
            return
        code = proc.poll()
        if code is not None:
            why = (
                "someone else has the tree"
                if code == joblock.BUSY_EXIT
                else f"it exited with {code}"
            )
            raise NeedsHuman(
                f"the compile job did not start: {why}. See compile-launch.log; "
                "run again when the tree is free."
            )
        if clock() >= deadline:
            raise NeedsHuman(
                f"the compile job has not taken the build lock after {wait:.0f} s; "
                "check compile-launch.log and boring-build.lock.holder.json"
            )
        time.sleep(poll)


def compile_status(log_text):
    """(status, progress, failures) from the compile log.

    status: running (no DONE yet), ok, failed. failures: FAILED and error
    lines after the last START.
    """
    start = log_text.rfind("START ")
    text = log_text[start:] if start >= 0 else log_text
    done = re.search(r"^DONE RC=(\d+)", text, re.M)
    progress = re.findall(r"\[(\d+)/(\d+)\]", text)
    failures = [
        ln
        for ln in text.splitlines()
        if ln.startswith("FAILED:")
        or re.search(r"(\(\d+(,\d+)?\)|:\d+:\d+):? (fatal )?error", ln)
    ]
    status = "running" if not done else ("ok" if done.group(1) == "0" else "failed")
    return status, ("/".join(progress[-1]) if progress else ""), failures


def ours(failures, our_files):
    """The failure lines that name our code."""
    names = {f.replace("\\", "/") for f in our_files}
    out = []
    for line in failures:
        flat = line.replace("\\", "/")
        if "components/boring" in flat or any(n in flat for n in names):
            out.append(line)
    return out


def pid_alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259


def check_compile(bump):
    """Stage compile on a rerun: still going, done, or stopped for a person."""
    info = bump.state.get("compile") or {}
    log = Path(info.get("log", bump.log("compile")))
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    status, progress, failures = compile_status(text)
    if status == "ok":
        return "done", f"DONE RC=0 [{progress}]"
    if status == "running":
        if info.get("pid") and pid_alive(info["pid"]):
            return "running", f"compiling [{progress}], log {log}"
        raise NeedsHuman(
            f"the compile stopped without a DONE line at [{progress}] (killed or rebooted?). "
            "ninja is incremental: run again with --redo compile."
        )
    mine = ours(failures, bump.our_files())
    where = (
        "in our code"
        if mine
        else "outside our code (upstream, toolchain or environment)"
    )
    shown = "\n  ".join((mine or failures)[:12])
    raise NeedsHuman(
        f"the compile failed {where}, log {log}:\n  {shown}\n"
        "Fix the source (and its patch with --write-port), then run again with --redo compile."
    )


# ------------------------------------------------------- write-port


def write_port(bump, name):
    """Write patches/<major>/<name> from the tree, against the files as the
    series leaves them just before this patch. Proves it applies strictly."""
    import rebase_patch

    if name not in series():
        sys.exit(f"{name} is not in patches/series")
    work = bump.dir / "port"
    bump.series_scratch(work, upto=name)
    text = patch_path(name, bump.set).read_text(encoding="utf-8", errors="replace")
    changed, created = patch_files(text)
    pieces = []
    for rel in changed + created:
        before = work / rel
        if rel in changed and not before.exists():
            sys.exit(f"no store copy of {rel}; cannot tell the port from the original")
        if not before.exists():
            before.parent.mkdir(parents=True, exist_ok=True)
            before.write_text("", encoding="utf-8")
        piece = rebase_patch.unified(
            str(before), str(bump.src / rel), rel, rel in created
        )
        if piece:
            pieces.append(piece)
    if not pieces:
        sys.exit(f"the tree holds no change for {name}'s files")
    out = PATCHES / bump.set / name
    out.write_text("".join(pieces), encoding="utf-8", newline="\n")
    for rel in created:
        (work / rel).unlink(missing_ok=True)
    r = subprocess.run(
        ["git", "apply", "--check", str(out)],
        cwd=work,
        capture_output=True,
        text=True,
        env=git_env(work),
    )
    if r.returncode:
        sys.exit(
            f"wrote {out}, but it does not apply strictly: {r.stderr.strip()[:300]}"
        )
    print(
        f"wrote {out.relative_to(REPO)}; it applies strictly after the patches before it"
    )


# ------------------------------------------------------------- main


def preflight(args, root, state):
    """Refusals that come before anything is written."""
    import stage_upstream

    prev = Path(state["prev"] if state else args.prev).resolve()
    if root == prev:
        sys.exit("refusing: --dir is the previous tree; give a new folder")
    # The trees that build today: the one we move on from, the one the last
    # bump recorded in UPSTREAM_VERSION, and any given with --live-tree.
    live = [prev, *recorded_trees(CORE / "UPSTREAM_VERSION")]
    live += [Path(p).resolve() for p in getattr(args, "live_tree", None) or []]
    for tree in live:
        if root == tree or tree in root.parents:
            sys.exit(f"refusing: {root} is inside {tree}, a tree that builds today")
    built = stage_upstream.built_tree_at(root) if state is None else None
    if built:
        sys.exit(f"refusing: {built} holds a built browser; give a new folder")
    if not (prev / "build" / "src" / "BUILD.gn").exists():
        sys.exit(f"--prev {prev} is not a built ungoogled tree")
    branch = subprocess.run(
        ["git", "-C", str(REPO), "branch", "--show-current"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    want = state["branch"] if state else args.branch
    if args.branch and state and args.branch != state["branch"]:
        sys.exit(
            f"refusing: this bump runs on branch {state['branch']}, not {args.branch}"
        )
    if branch != want:
        sys.exit(
            f"refusing: check out {want} in {REPO} first (it is on {branch or 'no branch'})"
        )
    if not (CORE / "third_party" / "winsparkle" / "WinSparkle.dll").exists():
        sys.exit(
            "missing boring-core/third_party/winsparkle; run tools/get_winsparkle.py first"
        )
    if os.name == "nt" and not Path(args.vcvars).exists():
        sys.exit(f"no Visual Studio environment at {args.vcvars}; pass --vcvars")
    need = args.min_free_gb if args.min_free_gb is not None else disk_need_gb(state)
    ok, msg = check_disk(root, need)
    print("disk:", msg)
    if not ok:
        sys.exit("refusing: not enough disk space. " + msg)


def print_status(state, root):
    print(f"{state['tag']} -> {root} (from {state['prev']}, branch {state['branch']})")
    for name, _gb, what in STAGES:
        s = state["stages"][name]
        print(f"  {name:<10} {s['status']:<12} {s.get('note', '')}  [replaces {what}]")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", required=True, help="the new tree, e.g. E:\\ung-160")
    ap.add_argument("--tag", help="ungoogled-chromium-windows tag, or latest")
    ap.add_argument("--prev", help="the tree we are on now, e.g. E:\\ung-157")
    ap.add_argument("--branch", help="the branch of this checkout the bump writes to")
    ap.add_argument("--source", choices=("tarball", "clone"), default=None)
    ap.add_argument("--from-set", help="patch set to seed patches/<major> from")
    ap.add_argument("--vcvars", default=str(VCVARS))
    ap.add_argument("--min-free-gb", type=float, default=None)
    ap.add_argument(
        "--no-rust", action="store_true", help="do not cargo build the adblock DLL"
    )
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--redo", choices=NAMES)
    ap.add_argument("--accept-scan", action="store_true")
    ap.add_argument("--accept-args", action="store_true")
    ap.add_argument(
        "--live-tree",
        action="append",
        metavar="DIR",
        help="another tree that builds today, never to be written (repeatable)",
    )
    ap.add_argument("--write-port", metavar="PATCH")
    args = ap.parse_args(argv)

    root = Path(args.dir).resolve()
    state_path = root / STATE_DIR / "state.json"
    state = load_state(state_path)
    if args.status:
        if not state:
            sys.exit(f"no bump state in {root}")
        print_status(state, root)
        log = Path((state.get("compile") or {}).get("log", ""))
        if log.is_file():
            text = log.read_text(encoding="utf-8", errors="replace")
            print("  compile:", " ".join(compile_status(text)[:2]))
        return 0

    if state is None:
        if not (args.tag and args.prev and args.branch):
            sys.exit("a new bump needs --tag, --prev and --branch")
        tag = pick_latest(fetch_tags()) if args.tag == "latest" else args.tag
        if not parse_tag(tag or ""):
            sys.exit(f"not an ungoogled-chromium-windows release tag: {tag}")
        print("target tag:", tag)
    elif args.tag and args.tag not in ("latest", state["tag"]):
        sys.exit(f"refusing: {root} is a bump to {state['tag']}, not {args.tag}")

    preflight(args, root, state)
    if state is None:
        # A new bump only ever starts in a new folder, so it can never
        # write into a tree someone is building (git clone wants it empty
        # anyway, which is why the state file comes after the clone).
        if root.exists() and any(root.iterdir()):
            sys.exit(
                f"refusing: {root} is not empty and holds no bump; give a new folder"
            )
        state = new_state(
            tag, root, Path(args.prev).resolve(), args.branch, args.source or "tarball"
        )
        cmd = [sys.executable, TOOLS / "stage_upstream.py", "--tag", tag, "--dir", root]
        if subprocess.call([str(c) for c in cmd + ["--clone-only"]]):
            sys.exit("cloning the tag failed")
        # Tags can be moved. From here on this commit is the tag.
        import stage_upstream

        state["tag_sha"] = stage_upstream.head_sha(root)
        if not state["tag_sha"]:
            sys.exit("cannot read the commit of the cloned tag")
        (root / STATE_DIR).mkdir(exist_ok=True)
        save_state(state_path, state)

    bump = Bump(root, state, args)
    compile_running = (
        state["stages"]["compile"]["status"] == "running" and args.redo is None
    )
    if compile_running:
        # Our own ninja holds the tree lock, so only read until it is done.
        try:
            status, note = check_compile(bump)
        except NeedsHuman as stop:
            mark(state, "compile", "needs-human", str(stop).splitlines()[0])
            save_state(state_path, state)
            print(f"STOPPED at compile: {stop}")
            return 3
        if status == "running":
            print(note)
            return 0
        mark(state, "compile", "done", note)
        save_state(state_path, state)

    bump.take_lock()
    try:
        if args.source and state["stages"]["stage"]["status"] != "done":
            state["source"] = args.source
        if args.redo:
            redo(state, args.redo)
            save_state(state_path, state)
        if args.write_port:
            write_port(bump, args.write_port)
            return 0
        while (name := next_stage(state)) is not None:
            print(f"\n== {name}", flush=True)
            mark(state, name, "running")
            save_state(state_path, state)
            try:
                note = getattr(bump, f"do_{name}")()
            except NeedsHuman as stop:
                mark(state, name, "needs-human", str(stop).splitlines()[0])
                save_state(state_path, state)
                left = NAMES[NAMES.index(name) :]
                print(f"\nSTOPPED at {name}: {stop}\nStill to run: {', '.join(left)}")
                return 3
            if note == "started":
                mark(state, name, "running", "ninja started at below normal priority")
                save_state(state_path, state)
                print(
                    f"compile started in the background, log {bump.log('compile')}.\n"
                    "Run the same command again to check on it; it carries on when ninja is done."
                )
                return 0
            mark(state, name, "done", note)
            save_state(state_path, state)
            print(f"   {note}")
    finally:
        bump.release_lock()
    print(
        "\nThe new tree compiles. Left for people: smoke_all.py, package and check_package.py, "
        "the sandbox update test, the real-window pass, and moving the workflows to the new tree."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
