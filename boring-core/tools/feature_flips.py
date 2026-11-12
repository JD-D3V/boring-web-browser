#!/usr/bin/env python3
r"""Which Chromium features changed their default between two source trees.

Extracts every BASE_FEATURE / BASE_RUNTIME_MUTABLE_FEATURE definition from
both trees, evaluates #if conditions for the Windows x64 official
ungoogled build as far as it can, joins by feature name and sorts the
changes: off to on, on to off, new on, new off, removed.

Why it exists: on the 154 to 157 port, UseActionsForBrowserCommands went
from off to on and silently disabled two of our menu commands, and
ContextualTasks, ExtensionsPinnedByDefault and others changed what users
see. None of that showed up as a patch conflict.

Read only on both trees. bump.py calls run() and compare(); by hand:
  python feature_flips.py --old E:\ung-157\build\src --new E:\ung-160\build\src --out E:\tmp\flips
"""

import argparse
import bisect
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

SKIP_TOP = {
    "out",
    "third_party",
    "build",
    "buildtools",
    "tools",
    "testing",
    "docs",
    "ios",
    "android_webview",
    "fuchsia_web",
    "chromecast",
    "chromeos",
    "ash",
    "v8",
    "infra",
    "styleguide",
    "agents",
    "codelabs",
    "uc_staging",
    "remoting",
}
SKIP_DIRNAMES = {
    ".git",
    "node_modules",
    "test",
    "tests",
    "testing",
    "testdata",
    "test_data",
    "android",
    "ios",
    "mac",
    "linux",
    "fuchsia",
    "chromeos",
    "lacros",
    "jni",
    "perf_tests",
    "manual_tests",
    "web_tests",
    "fuzzers",
}
# dirs we keep even though the name appears in SKIP_DIRNAMES at depth (none now)
TEST_FILE_RE = re.compile(
    r"(_unittest|_browsertest|_test|_perftest|_fuzzer|_apitest|_uitest|_interactive_uitest|_test_util|_test_support|_mock)\.(cc|mm)$"
)
FEATURE_CALL_RE = re.compile(rb"\bBASE_(?:RUNTIME_MUTABLE_)?FEATURE\s*\(")
FEATURE_CALL_TXT = re.compile(r"\bBASE_(RUNTIME_MUTABLE_)?FEATURE\s*\(")


# ---------------------------------------------------------------- buildflags
def load_buildflags(root, outdir):
    flags = {}
    gen = os.path.join(root, outdir, "gen")
    pat = re.compile(r"#define\s+BUILDFLAG_INTERNAL_(\w+)\(\)\s*\((\d+)\)")
    n = 0
    for dp, _dn, fn in os.walk(gen):
        for f in fn:
            if f.endswith("buildflags.h") or f.endswith("buildflag.h"):
                try:
                    with open(
                        os.path.join(dp, f), encoding="utf-8", errors="ignore"
                    ) as fh:
                        t = fh.read()
                except OSError:
                    continue
                for m in pat.finditer(t):
                    flags[m.group(1)] = int(m.group(2))
                n += 1
    return flags, n


DEFINED_TRUE = {
    "OFFICIAL_BUILD",
    "NDEBUG",
    "ARCH_CPU_X86_64",
    "ARCH_CPU_64_BITS",
    "ARCH_CPU_X86_FAMILY",
    "ARCH_CPU_LITTLE_ENDIAN",
    "__clang__",
    "_WIN32",
    "WIN32",
    "_WIN64",
    "COMPILER_MSVC",
    "NOMINMAX",
    "UNICODE",
    "_UNICODE",
    "USE_AURA",
}
DEFINED_FALSE = {
    "COMPONENT_BUILD",
    "ADDRESS_SANITIZER",
    "MEMORY_SANITIZER",
    "UNDEFINED_SANITIZER",
    "THREAD_SANITIZER",
    "DCHECK_ALWAYS_ON",
    "UNIT_TEST",
    "ARCH_CPU_ARM64",
    "ARCH_CPU_ARM_FAMILY",
    "ARCH_CPU_32_BITS",
    "ARCH_CPU_X86",
    "OS_WIN_DISABLED_NEVER",
    "__GNUC__",
    "__ARM_NEON__",
    "GOOGLE_CHROME_BRANDING_X",
    "ANDROID",
    "__linux__",
    "__APPLE__",
    "__ELF__",
    "OS_ANDROID",
    "OS_CHROMEOS",
    "OS_LINUX",
    "OS_MAC",
    "OS_IOS",
    "OS_POSIX",
    "FUCHSIA_WEB",
    "USE_GLIB",
    "USE_UDEV",
    "__GLIBC__",
    "OZONE_PLATFORM_IS_X11",
    "WEBRTC_USE_PIPEWIRE",
    "ENABLE_IPC_FUZZER",
    "NET_BUILD_STRESS_CACHE",
    "LEAK_SANITIZER",
    "ARCH_CPU_ARMEL",
    "__arm__",
}


class Ctx:
    def __init__(self, flags):
        self.flags = flags
        self.unknown = {}  # name -> count

    def flag(self, name):
        if name.startswith("IS_"):
            return 1 if name in ("IS_WIN", "IS_DESKTOP") else 0
        if name in self.flags:
            return self.flags[name]
        self.unknown[name] = self.unknown.get(name, 0) + 1
        return None

    def defined(self, name):
        if name in DEFINED_TRUE:
            return True
        if name in DEFINED_FALSE:
            return False
        if name in self.flags:
            return True
        self.unknown["defined:" + name] = self.unknown.get("defined:" + name, 0) + 1
        return None


TOKEN_RE = re.compile(
    r"\s*(?:(BUILDFLAG)\s*\(\s*(\w+)\s*\)|(defined)\s*\(?\s*(\w+)\s*\)?|(\d+)[uUlL]*|(&&|\|\||==|!=|<=|>=|<|>)|(!)|(\()|(\))|([A-Za-z_]\w*))"
)


def eval_expr(expr, ctx):
    """Return True/False/None (None = unknown) for a preprocessor expression."""
    expr = re.sub(r"/\*.*?\*/", " ", expr, flags=re.S)
    expr = re.sub(r"//.*", " ", expr)
    toks = []
    pos = 0
    expr = expr.strip()
    while pos < len(expr):
        m = TOKEN_RE.match(expr, pos)
        if not m or m.end() == pos:
            return None
        pos = m.end()
        if m.group(1):
            v = ctx.flag(m.group(2))
            toks.append(("val", None if v is None else bool(v) if v in (0, 1) else v))
        elif m.group(3):
            toks.append(("val", ctx.defined(m.group(4))))
        elif m.group(5):
            toks.append(("val", int(m.group(5))))
        elif m.group(6):
            toks.append(("op", m.group(6)))
        elif m.group(7):
            toks.append(("op", "!"))
        elif m.group(8):
            toks.append(("op", "("))
        elif m.group(9):
            toks.append(("op", ")"))
        else:
            ident = m.group(10)
            if ident.startswith("IS_"):
                toks.append(("val", bool(ctx.flag(ident))))
            elif ident in ("true", "TRUE"):
                toks.append(("val", True))
            elif ident in ("false", "FALSE"):
                toks.append(("val", False))
            else:
                toks.append(("val", None))  # unknown identifier
    i = [0]

    def peek():
        return toks[i[0]] if i[0] < len(toks) else None

    def p_or():
        a = p_and()
        while peek() == ("op", "||"):
            i[0] += 1
            b = p_and()
            if a is True or b is True:
                a = True
            elif a is None or b is None:
                a = None
            else:
                a = False
        return a

    def p_and():
        a = p_cmp()
        while peek() == ("op", "&&"):
            i[0] += 1
            b = p_cmp()
            if a is False or b is False:
                a = False
            elif a is None or b is None:
                a = None
            else:
                a = True
        return a

    def p_cmp():
        a = p_not()
        t = peek()
        if t and t[0] == "op" and t[1] in ("==", "!=", "<=", ">=", "<", ">"):
            i[0] += 1
            b = p_not()
            if a is None or b is None:
                return None
            a_, b_ = int(a), int(b)
            return {
                "==": a_ == b_,
                "!=": a_ != b_,
                "<=": a_ <= b_,
                ">=": a_ >= b_,
                "<": a_ < b_,
                ">": a_ > b_,
            }[t[1]]
        return a

    def p_not():
        t = peek()
        if t == ("op", "!"):
            i[0] += 1
            v = p_not()
            return None if v is None else (not v)
        return p_atom()

    def p_atom():
        t = peek()
        if t is None:
            raise ValueError
        i[0] += 1
        if t == ("op", "("):
            v = p_or()
            if peek() == ("op", ")"):
                i[0] += 1
            return v
        if t[0] == "val":
            return t[1]
        raise ValueError

    try:
        r = p_or()
    except (ValueError, IndexError):
        return None
    if r is None:
        return None
    return bool(r)


# --------------------------------------------------------------- file parse
def line_activity(lines, ctx):
    """Return list act[i] in {True, False, None} for each line (0-based)."""
    act = []
    stack = []  # frames: [branch_state, any_taken_true, parent_state]
    cur = True

    def and3(a, b):
        if a is False or b is False:
            return False
        if a is None or b is None:
            return None
        return True

    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        s = raw.lstrip()
        if s.startswith("#"):
            d = s[1:].lstrip()
            # join continuation lines
            full = d
            j = i
            while full.rstrip().endswith("\\") and j + 1 < n:
                full = full.rstrip()[:-1] + " " + lines[j + 1]
                j += 1
            m = re.match(r"(ifdef|ifndef|if|elif|else|endif)\b(.*)", full, flags=re.S)
            if m:
                kw, rest = m.group(1), m.group(2)
                parent = cur
                if kw in ("if", "ifdef", "ifndef"):
                    if kw == "if":
                        c = eval_expr(rest, ctx)
                    else:
                        name = rest.strip().split()[0] if rest.strip() else ""
                        dv = ctx.defined(name)
                        c = dv if kw == "ifdef" else (None if dv is None else (not dv))
                    stack.append([c, c is True, parent, c is None])
                    cur = and3(parent, c)
                elif kw == "elif" and stack:
                    fr = stack[-1]
                    c = eval_expr(rest, ctx)
                    if fr[1]:
                        c2 = False
                    elif c is None or fr[3]:
                        c2 = None
                        fr[3] = True
                    else:
                        c2 = c
                    if c is True and not fr[3]:
                        fr[1] = True
                    fr[0] = c2
                    cur = and3(fr[2], c2)
                elif kw == "else" and stack:
                    fr = stack[-1]
                    if fr[1]:
                        c2 = False
                    elif fr[3]:
                        c2 = None
                    else:
                        c2 = True
                    fr[0] = c2
                    cur = and3(fr[2], c2)
                elif kw == "endif" and stack:
                    fr = stack.pop()
                    cur = fr[2]
                act.extend([cur] * (j + 1 - i))
                i = j + 1
                continue
        act.append(cur)
        i += 1
    return act


def strip_comments(t):
    t = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), t, flags=re.S)
    t = re.sub(r"//[^\n]*", "", t)
    return t


def match_paren(text, start):
    """text[start] == '(' ; return index of matching ')' or -1. Skips strings."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    i += 1
                i += 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


STATE_RE = re.compile(
    r"(?:base::)?FEATURE_(ENABLED|DISABLED)_BY_DEFAULT|\b(ENABLED|DISABLED)\b|\b(enable|disable)_if\s*\("
)


def seg_tokens(seg, a, ctx):
    seg2 = re.sub(r'"(?:[^"\\]|\\.)*"', '""', seg)
    out = []
    pos = 0
    while True:
        m = STATE_RE.search(seg2, pos)
        if not m:
            break
        if m.group(3):
            op = m.end() - 1
            cl = match_paren(seg2, op)
            if cl < 0:
                out.append(("UNCLEAR", a))
                break
            cv = eval_expr(seg2[op + 1 : cl], ctx)
            if cv is None:
                out.append(("UNCLEAR", a))
            else:
                en = m.group(3) == "enable"
                out.append(("ENABLED" if (cv == en) else "DISABLED", a))
            pos = cl + 1
        else:
            out.append((m.group(1) or m.group(2), a))
            pos = m.end()
    return out


def parse_file(path, rel, ctx):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return []
    if not FEATURE_CALL_RE.search(raw):
        return []
    text = raw.decode("utf-8", errors="ignore")
    text_nc = strip_comments(text)
    lines = text_nc.split("\n")
    act = line_activity(lines, ctx)
    offs = []
    o = 0
    for line in lines:
        offs.append(o)
        o += len(line) + 1
    # same offsets as text_nc, but lines that are inactive on Windows (and all
    # preprocessor lines) are blanked, so parentheses balance across #if/#else
    lines_pp = [
        (" " * len(line))
        if (act[i] is False or line.lstrip().startswith("#"))
        else line
        for i, line in enumerate(lines)
    ]
    text_pp = "\n".join(lines_pp)
    res = []
    for m in FEATURE_CALL_TXT.finditer(text_nc):
        ln = bisect.bisect_right(offs, m.start()) - 1
        if lines[ln].lstrip().startswith("#define"):
            continue  # the macro definition itself
        start_act = act[ln] if ln < len(act) else True
        src_text = text_nc if start_act is False else text_pp
        use_lines = lines if start_act is False else lines_pp
        op = src_text.index("(", m.start())
        cl = match_paren(src_text, op)
        if cl < 0:
            continue
        mutable = bool(m.group(1))
        # lines in the body
        body_start_ln = bisect.bisect_right(offs, op) - 1
        body_end_ln = bisect.bisect_right(offs, cl) - 1
        kept = []
        toks = []
        for k in range(body_start_ln, body_end_ln + 1):
            a = act[k] if k < len(act) else True
            if a is False and start_act is not False:
                continue
            full_line = use_lines[k]
            lo = max(op + 1, offs[k]) - offs[k]
            hi = min(cl, offs[k] + len(full_line)) - offs[k]
            seg = full_line[lo:hi]
            if full_line.lstrip().startswith("#"):
                continue
            kept.append(seg)
            toks.extend(seg_tokens(seg, a, ctx))
        kbody = " ".join(x.strip() for x in kept)
        # identifier and name
        args = []
        depth = 0
        cur = ""
        instr = False
        for ch in kbody:
            if ch == '"':
                instr = not instr
            if not instr:
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth -= 1
                elif ch == "," and depth == 0:
                    args.append(cur.strip())
                    cur = ""
                    continue
            cur += ch
        if cur.strip():
            args.append(cur.strip())
        ident = args[0] if args else ""
        fname = None
        if len(args) >= 2 and args[1].startswith('"'):
            sm = re.match(r'"([^"]*)"', args[1])
            fname = sm.group(1) if sm else None
        elif ident:
            fname = ident[1:] if ident.startswith("k") else ident
        flags = []
        if start_act is False:
            state = "NOT_WIN"
        else:
            if len(toks) == 0 and len(args) >= 2:
                sarg = (
                    args[2] if (len(args) >= 3 and args[1].startswith('"')) else args[1]
                )
                ALIAS = {
                    "enabled_by_default_desktop_only": "ENABLED",
                    "enabled_by_default_non_ios": "ENABLED",
                    "enabled_by_default_ios_only": "DISABLED",
                    "enabled_by_default_android_only": "DISABLED",
                    "kDefaultEnabled": "ENABLED",
                }
                if sarg in ALIAS:
                    toks.append((ALIAS[sarg], True))
                    flags.append("alias")
                elif re.fullmatch(r"[A-Za-z_]\w*", sarg or ""):
                    dm = re.search(
                        r"\b" + re.escape(sarg) + r"\b\s*=\s*([^;]*);", text_nc
                    )
                    if dm:
                        d_s = bisect.bisect_right(offs, dm.start(1)) - 1
                        d_e = bisect.bisect_right(offs, dm.end(1)) - 1
                        for k in range(d_s, d_e + 1):
                            a2 = act[k] if k < len(act) else True
                            if a2 is False or lines[k].lstrip().startswith("#"):
                                continue
                            lo = max(dm.start(1), offs[k]) - offs[k]
                            hi = min(dm.end(1), offs[k] + len(lines[k])) - offs[k]
                            toks.extend(seg_tokens(lines[k][lo:hi], a2, ctx))
                        if toks:
                            flags.append("via_const")
            vals = {v for v, _ in toks}
            if len(toks) == 0:
                state = "OTHER"
            elif len(toks) == 1:
                state = toks[0][0]
                if toks[0][1] is None:
                    flags.append("cond")
            elif len(vals) == 1:
                state = list(vals)[0]
                flags.append("multi_same")
            else:
                tm = re.search(
                    r"(.*?)\?\s*(?:base::)?(?:FEATURE_)?(ENABLED|DISABLED)(?:_BY_DEFAULT)?\s*:\s*(?:base::)?(?:FEATURE_)?(ENABLED|DISABLED)(?:_BY_DEFAULT)?",
                    kbody,
                    flags=re.S,
                )
                state = "UNCLEAR"
                if tm and len(toks) == 2:
                    cond = tm.group(1).rsplit(",", 1)[-1]
                    cv = eval_expr(cond, ctx)
                    if cv is True:
                        state = tm.group(2)
                    elif cv is False:
                        state = tm.group(3)
                    else:
                        flags.append("ternary_unknown")
                if state == "UNCLEAR":
                    flags.append(
                        "branches="
                        + "/".join(
                            f"{v[0]}:{'?' if a is None else 'T'}" for v, a in toks
                        )
                    )
            if start_act is None:
                flags.append("encl_cond")
        res.append(
            {
                "name": fname or "?",
                "ident": ident,
                "file": rel.replace("\\", "/"),
                "line": ln + 1,
                "state": state,
                "flags": ",".join(flags),
                "mutable": "1" if mutable else "",
                "body": kbody[:200] if state in ("UNCLEAR", "OTHER") else "",
            }
        )
    return res


# ----------------------------------------------------------------- walking
def collect(root):
    paths = []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            it = list(os.scandir(d))
        except OSError:
            continue
        for e in it:
            name = e.name
            if e.is_dir(follow_symlinks=False):
                if d == root and name in SKIP_TOP:
                    continue
                if name in SKIP_DIRNAMES:
                    continue
                if name.startswith("."):
                    continue
                stack.append(e.path)
            else:
                if name.endswith(".cc") and not TEST_FILE_RE.search(name):
                    paths.append(e.path)
    # third_party/blink extras (common features, renderer features)
    for sub in ("third_party/blink",):
        stack = [os.path.join(root, sub)]
        while stack:
            d = stack.pop()
            try:
                it = list(os.scandir(d))
            except OSError:
                continue
            for e in it:
                if e.is_dir(follow_symlinks=False):
                    if e.name in SKIP_DIRNAMES or e.name in (
                        "web_tests",
                        "tools",
                        "perf_tests",
                    ):
                        continue
                    stack.append(e.path)
                elif e.name.endswith(".cc") and not TEST_FILE_RE.search(e.name):
                    paths.append(e.path)
    # other third_party dirs: only *features*.cc
    tp = os.path.join(root, "third_party")
    stack = [tp]
    while stack:
        d = stack.pop()
        try:
            it = list(os.scandir(d))
        except OSError:
            continue
        for e in it:
            if e.is_dir(follow_symlinks=False):
                if e.name in (
                    ".git",
                    "node_modules",
                    "blink",
                    "rust-toolchain",
                    "llvm-build",
                    "depot_tools",
                    "catapult",
                    "angle",
                    "dawn",
                    "webgpu-cts",
                    "test_fonts",
                    "android_sdk",
                    "android_deps",
                ):
                    continue
                stack.append(e.path)
            elif "feature" in e.name and e.name.endswith(".cc"):
                paths.append(e.path)
    return paths


def run(root, flags_root=None):
    """Every feature definition in one tree.

    The buildflag headers only exist once a tree has been compiled. A
    freshly staged tree has none, so flags_root names a tree whose
    headers stand in (buildflags rarely change between majors). The
    third value says when that happened, so a report can say so.
    """
    flags, nflag = load_buildflags(root, "out/Default")
    note = ""
    if not nflag and flags_root:
        flags, nflag = load_buildflags(flags_root, "out/Default")
        note = f"buildflags borrowed from {flags_root}"
    ctx = Ctx(flags)
    paths = collect(root)
    sys.stderr.write(f"[{root}] {len(flags)} buildflags; {len(paths)} files\n")
    results = []

    def work(p):
        return parse_file(p, os.path.relpath(p, root), ctx)

    with ThreadPoolExecutor(max_workers=24) as ex:
        for r in ex.map(work, paths, chunksize=64):
            results.extend(r)
    return results, ctx, note


def _index(res):
    d = {}
    for r in res:
        d.setdefault(r["name"], []).append(r)
    return d


def _pick(lst):
    """Prefer a definition that applies on Windows."""
    for r in lst:
        if r["state"] != "NOT_WIN":
            return r
    return lst[0]


def compare(old_res, new_res):
    """Join two runs by feature name and sort the changes on Windows."""
    old, new = _index(old_res), _index(new_res)
    out = {k: [] for k in ("off_to_on", "on_to_off", "new_on", "new_off", "removed")}
    for name in sorted(set(old) | set(new)):
        a = _pick(old[name]) if name in old else None
        b = _pick(new[name]) if name in new else None
        sa = a["state"] if a else "-"
        sb = b["state"] if b else "-"
        row = {
            "name": name,
            "ident": (b or a)["ident"],
            "old": sa,
            "new": sb,
            "file": (b or a)["file"],
            "line": (b or a)["line"],
        }
        pa = sa not in ("-", "NOT_WIN")
        pb = sb not in ("-", "NOT_WIN")
        if pa and pb:
            if sa == "DISABLED" and sb == "ENABLED":
                out["off_to_on"].append(row)
            elif sa == "ENABLED" and sb == "DISABLED":
                out["on_to_off"].append(row)
        elif pb and not pa:
            if sb == "ENABLED":
                out["new_on"].append(row)
            elif sb == "DISABLED":
                out["new_off"].append(row)
        elif pa and not pb:
            out["removed"].append(row)
    return out


def write_tsv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write(
                "\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in r)
                + "\n"
            )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--old", required=True, help="previous source tree")
    ap.add_argument("--new", required=True, help="new source tree")
    ap.add_argument("--out", required=True, help="folder for the TSV files")
    args = ap.parse_args()
    old_res, _, _ = run(args.old)
    new_res, _, note = run(args.new, flags_root=args.old)
    changes = compare(old_res, new_res)
    os.makedirs(args.out, exist_ok=True)
    cols = ["name", "ident", "old", "new", "file", "line"]
    for kind, rows in changes.items():
        write_tsv(
            os.path.join(args.out, kind + ".tsv"),
            cols,
            [[r[c] for c in cols] for r in rows],
        )
    summary = {k: len(v) for k, v in changes.items()}
    if note:
        summary["note"] = note
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
