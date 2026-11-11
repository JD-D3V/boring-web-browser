#!/usr/bin/env python3
r"""The Release 3 real-window pass: every step that needs a browser window,
one command, one log per step, one summary table.

Not part of smoke_all.py: it opens real (off screen) browser windows on the
machine it runs on, so it is run on purpose, with nobody working on that
machine. Read the README beside run_window_pass.bat first.

Steps, in order (a failed or stuck step does not stop the later ones):

  1  the seven real-window smokes: tab freezing and sleeping, per-site
     blocking off, shield panel and site settings, Web Store installs,
     forget this site, tabs survive restart, side tabs
  2  the screen takeover checks headless cannot do: pointer lock and
     keyboard lock (smoke_takeover.py in a real window; the scam page takes
     the window fullscreen for a few seconds)
  3  the add-on Remove question, Cancel and Remove (smoke_apps_rows.py)
  4  net_audit.py with every scenario including all-off, hosts printed
  5  pictures, light and dark: Settings pages, tab strip states, toolbar,
     app menu, side tabs, Protection, Welcome, new tab, the four warning
     pages
  6  measure_startup.py; test_update_local.py is NOT run here (it needs an
     installed copy and belongs to the Sandbox test)

Safe to stop: every step ends by closing the browsers it started, and after
each step anything left under the build folder is killed. Ctrl+C stops the
pass, cleans up and writes the summary. If the console window is closed
instead, run this with --cleanup.

    python run_window_pass.py --dry-run          print the plan, start nothing
    python run_window_pass.py --check-tools      compile, import and --help check
    python run_window_pass.py [--yes]            the pass
    python run_window_pass.py --only 2 3         some steps (ids or prefixes)
    python run_window_pass.py --cleanup          kill leftovers of the build
"""

import argparse
import ctypes
import datetime
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_BUILD = r"E:\ung-157\build\src\out\Default"
DEFAULT_OUT = r"E:\tmp\r3-window-pass"
DEFAULT_NET_SECONDS = 90
EXPECT_VERSION = "157.0.8103.38"

# Scripts that parse arguments, so `--help` is safe to run on them. A smoke
# without argparse would START the test on --help, so none of those are asked.
ARGPARSE_TOOLS = {
    "capture_r3_pass.py",
    "capture_app_menu.py",
    "capture_scam_warning.py",
    "capture_lookalike.py",
    "net_audit.py",
    "measure_startup.py",
    "smoke_site_panel.py",
    "smoke_forget.py",
    "smoke_tabs.py",
    "smoke_vtabs.py",
    "test_update_local.py",
    "probe_focus.py",
}


@dataclass
class Step:
    id: str
    title: str
    commands: list  # each a list of arguments after the python executable
    timeout: int  # seconds for the whole step
    window: str  # what the person may see: a short sentence for the README/plan
    detail: tuple = ()  # regexes of log lines worth copying into SUMMARY.txt
    takeover: bool = False  # puts a fullscreen window on a real monitor
    info_only: bool = False  # run for the log, result is NOT RUN not PASS
    note: str = ""


@dataclass
class Result:
    step: Step
    status: str = "NOT RUN"
    seconds: float = 0.0
    codes: list = field(default_factory=list)
    counts: str = ""
    focus: str = "n/a"
    details: list = field(default_factory=list)
    leftovers: int = 0
    log: str = ""


def tool(name, *args):
    return [str(HERE / name), *args]


def build_steps(out, net_seconds):
    shots = out / "shots"
    smoke_lines = (r"^(FAIL|SKIP)\b", r"^not taken", r"^FAILED ")
    return [
        Step(
            "1a-memory",
            "tab freezing and sleeping",
            [tool("smoke_memory.py")],
            1500,
            "one browser window off screen, several tabs opened and discarded",
            smoke_lines,
        ),
        Step(
            "1b-siteoff",
            "per-site blocking off",
            [tool("smoke_siteoff.py")],
            900,
            "browser windows off screen, one after another",
            smoke_lines,
        ),
        Step(
            "1c-site-panel",
            "shield panel and site settings",
            [
                tool(
                    "smoke_site_panel.py",
                    "--shots",
                    str(shots / "smoke" / "site-panel"),
                )
            ],
            1200,
            "browser window off screen; the shield panel is opened through "
            "UI Automation on our own window",
            smoke_lines,
        ),
        Step(
            "1d-webstore",
            "Web Store installs",
            [tool("smoke_webstore.py")],
            900,
            "browser window off screen; an install prompt appears and is only read",
            smoke_lines,
        ),
        Step(
            "1e-forget",
            "forget this site",
            [tool("smoke_forget.py", "--shots", str(shots / "smoke" / "forget"))],
            1200,
            "browser window off screen; panel pressed through UI Automation",
            smoke_lines,
        ),
        Step(
            "1f-tabs",
            "tabs survive restart",
            [tool("smoke_tabs.py", "--out", str(shots / "smoke" / "tabs-restart"))],
            1200,
            "three launches of one browser, off screen; one is killed on purpose",
            smoke_lines,
        ),
        Step(
            "1g-vtabs",
            "side tabs (smoke and pictures)",
            [tool("smoke_vtabs.py", "--out", str(shots / "side-tabs"))],
            1200,
            "four short browser launches, off screen",
            smoke_lines,
        ),
        Step(
            "2-takeover",
            "screen takeover: pointer lock and keyboard lock, real window",
            [tool("smoke_takeover.py")],
            900,
            "the scam stand-in page takes the browser window FULLSCREEN, muted, for a "
            "few seconds at a time; the script ends it with Esc through DevTools and "
            "the browser's takeover page",
            smoke_lines + (r"^INFO ",),
            takeover=True,
        ),
        Step(
            "3-apps-rows",
            "add-on Remove question: Cancel keeps, Remove removes",
            [tool("smoke_apps_rows.py")],
            900,
            "browser windows off screen; Chromium's own Remove question appears in "
            "one and is answered through UI Automation",
            smoke_lines + (r"^remove", r"^pressed", r"^after "),
        ),
        Step(
            "4-net-audit",
            "net_audit.py, all scenarios including all-off",
            [
                tool(
                    "net_audit.py",
                    "--all",
                    "--seconds",
                    str(net_seconds),
                    "--out",
                    str(out / "net"),
                )
            ],
            int((net_seconds + 90) * 6 + 300),
            f"six browser launches off screen, {net_seconds} seconds each, sitting "
            "on a page doing nothing",
            smoke_lines
            + (
                r"^=== ",
                r"hosts contacted",
                r"capture check",
                r"^Hosts reached",
                r"^  \S+\s+-- ",
                r"^  none",
                r"^FAIL",
                r"^CAPTURE",
                r"^This reads as",
                r"^capture proven",
            ),
        ),
        Step(
            "5a-webui",
            "pictures: Settings pages, Protection, Welcome, new tab, takeover page",
            [
                tool(
                    "capture_r3_pass.py",
                    "--out",
                    str(shots / "pages"),
                    "--group",
                    "webui",
                )
            ],
            1200,
            "browser windows off screen, navigating page to page, light then dark",
            smoke_lines,
        ),
        Step(
            "5b-tabs",
            "pictures: tab strip states and toolbar",
            [
                tool(
                    "capture_r3_pass.py",
                    "--out",
                    str(shots / "tabs"),
                    "--group",
                    "tabs",
                )
            ],
            1200,
            "browser windows off screen; a small test add-on opens pinned tabs",
            smoke_lines,
        ),
        Step(
            "5c-quad9",
            "picture: Quad9 warning page",
            [
                tool(
                    "capture_r3_pass.py",
                    "--out",
                    str(shots / "warnings"),
                    "--group",
                    "quad9",
                )
            ],
            600,
            "two browser launches off screen",
            smoke_lines,
        ),
        Step(
            "5d-app-menu",
            "pictures: app menu, light and dark",
            [
                tool(
                    "capture_app_menu.py",
                    "--out",
                    str(shots / "app-menu" / "app-menu-light.png"),
                ),
                tool(
                    "capture_app_menu.py",
                    "--dark",
                    "--out",
                    str(shots / "app-menu" / "app-menu-dark.png"),
                ),
            ],
            600,
            "two browser launches off screen",
            smoke_lines,
        ),
        Step(
            "5e-scam-warning",
            "pictures: scam warning page, four looks",
            [tool("capture_scam_warning.py", "--out", str(shots / "warnings"))],
            900,
            "four browser launches off screen",
            smoke_lines,
        ),
        Step(
            "5f-lookalike",
            "pictures: look-alike warning page",
            [tool("capture_lookalike.py", "--out", str(shots / "warnings"))],
            600,
            "two browser launches off screen",
            smoke_lines,
        ),
        Step(
            "5g-site-panel-dark",
            "pictures: shield panel and site settings, dark",
            [
                tool(
                    "smoke_site_panel.py",
                    "--dark",
                    "--shots",
                    str(shots / "smoke" / "site-panel"),
                )
            ],
            1200,
            "the shield panel smoke again in dark mode, off screen",
            smoke_lines,
        ),
        Step(
            "5h-forget-dark",
            "pictures: forget this site, dark",
            [
                tool(
                    "smoke_forget.py",
                    "--dark",
                    "--shots",
                    str(shots / "smoke" / "forget"),
                )
            ],
            1200,
            "the forget smoke again in dark mode, off screen",
            smoke_lines,
        ),
        Step(
            "6a-startup",
            "measure_startup.py (this build only)",
            [
                tool(
                    "measure_startup.py",
                    "--browser",
                    "r3=@CHROME@",
                    "--first-runs",
                    "3",
                    "--warm-runs",
                    "5",
                    "--json",
                    str(out / "startup.json"),
                )
            ],
            900,
            "eight short browser launches off screen",
            (r"^r3:", r"^  ", r"^FAIL"),
        ),
        Step(
            "6b-update-local",
            "test_update_local.py (not run on this machine)",
            [tool("test_update_local.py", "--list")],
            60,
            "nothing: it only lists its cases",
            (r"^\w+( \[click\])?:",),
            info_only=True,
            note="needs an installed copy with Installer\\setup.exe and a clicker; "
            "it belongs to the Sandbox update test, not to this pass",
        ),
    ]


# ---------------------------------------------------------------- Windows

user32 = kernel32 = None
if os.name == "nt":
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)


def under(path, folder):
    return os.path.normcase(os.path.abspath(path)).startswith(
        os.path.normcase(os.path.abspath(folder)) + os.sep
    )


def processes_under(build):
    """(pid, program) of every running program that lives under the build
    folder: its chrome.exe and chromedriver.exe. Never any other browser."""
    import probe_focus  # same folder; reads process lists only

    mine = os.getpid()
    found = []
    for pid in probe_focus.parent_map():
        if pid == mine or pid == 0:
            continue
        image = probe_focus.image_of(pid)
        if image and under(image, build):
            found.append((pid, image))
    return found


def sweep(build):
    """Kill whatever of the build is still running. Returns how many."""
    left = processes_under(build)
    for pid, _ in left:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    time.sleep(1.0)
    return len(left)


def file_version(path):
    """The product version in the exe's version resource, or 'unknown'."""
    try:
        v = ctypes.WinDLL("version")
        size = v.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return "unknown"
        buf = ctypes.create_string_buffer(size)
        v.GetFileVersionInfoW(str(path), 0, size, buf)
        p = ctypes.c_void_p()
        n = ctypes.c_uint()
        v.VerQueryValueW(buf, "\\", ctypes.byref(p), ctypes.byref(n))

        class FixedInfo(ctypes.Structure):
            _fields_ = [
                ("sig", ctypes.c_uint32),
                ("struc", ctypes.c_uint32),
                ("ms", ctypes.c_uint32),
                ("ls", ctypes.c_uint32),
            ]

        info = ctypes.cast(p, ctypes.POINTER(FixedInfo)).contents
        return f"{info.ms >> 16}.{info.ms & 0xFFFF}.{info.ls >> 16}.{info.ls & 0xFFFF}"
    except Exception:
        return "unknown"


# ------------------------------------------------------------------- run


def environment(build, out):
    tmp = out / "tmp"
    env = dict(os.environ)
    env.update(
        BORING_OUT=str(build),
        BORING_CHROME=str(Path(build) / "chrome.exe"),
        # Only the children get this, and only for this pass: it is what lets
        # the real-window checks run at all (drive.py).
        BORING_ALLOW_HEADFUL="1",
        TMP=str(tmp),
        TEMP=str(tmp),
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env, tmp


def command_line(step, argv, build, use_probe):
    args = [a.replace("@CHROME@", str(Path(build) / "chrome.exe")) for a in argv]
    cmd = [sys.executable, *args]
    if use_probe and not step.info_only:
        # Reads the foreground window around the command and says whether a
        # window of ours was put in front. Sends nothing, touches nothing.
        cmd = [sys.executable, str(HERE / "probe_focus.py"), "--", *cmd]
    return cmd


def kill_tree(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def run_step(step, ctx):
    result = Result(step)
    log = ctx["logs"] / f"{step.id}.log"
    result.log = str(log)
    started = time.monotonic()
    deadline = started + step.timeout
    codes = []
    status = "PASS"
    with open(log, "w", encoding="utf-8", errors="replace") as f:
        f.write(
            f"# {step.id}: {step.title}\n# started {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n"
        )
        for argv in step.commands:
            cmd = command_line(step, argv, ctx["build"], ctx["probe"])
            f.write("\n$ " + " ".join(cmd) + "\n")
            f.flush()
            proc = subprocess.Popen(
                cmd,
                stdout=f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=ctx["env"],
                cwd=str(HERE),
            )
            ctx["current"] = proc
            try:
                code = proc.wait(timeout=max(1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                kill_tree(proc.pid)
                f.write(f"\n# TIMEOUT after {step.timeout}s, killed\n")
                status = "TIMEOUT"
                code = "timeout"
            finally:
                ctx["current"] = None
            codes.append(code)
            if status == "TIMEOUT":
                break
        f.write(f"\n# ended {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
    result.seconds = time.monotonic() - started
    text = log.read_text(encoding="utf-8", errors="replace")

    # With the focus probe the real exit code is the line it prints; its own
    # exit code is 1 whenever the focus moved.
    real = re.findall(r"^command exit code: (\d+)", text, re.M)
    if real and ctx["probe"] and not step.info_only:
        codes = [int(c) for c in real] + ([c for c in codes if c == "timeout"])
    result.codes = codes
    took = len(re.findall(r"^RESULT: took the focus", text, re.M))
    kept = len(re.findall(r"^RESULT: foreground unchanged", text, re.M))
    if took:
        result.focus = f"TOOK FOCUS x{took}"
    elif kept:
        result.focus = "no"

    p = len(re.findall(r"^PASS\b", text, re.M))
    fl = len(re.findall(r"^FAIL(?:ED)?\b", text, re.M))
    sk = len(re.findall(r"^SKIP\b", text, re.M))
    result.counts = f"{p} pass, {fl} fail, {sk} skip"

    if status != "TIMEOUT":
        bad = [c for c in codes if c != 0]
        if step.info_only:
            status = "NOT RUN" if not bad else "ERROR"
        elif bad:
            status = "FAIL"
        else:
            status = "PASS"
    result.status = status

    wanted = [re.compile(p_) for p_ in step.detail]
    seen = set()
    for line in text.splitlines():
        if any(r.search(line) for r in wanted) and line not in seen:
            seen.add(line)
            result.details.append(line.rstrip())
    result.details = result.details[:60]
    return result


def write_summary(path, ctx, results, state):
    lines = []
    lines.append("Release 3 real-window pass")
    lines.append(f"state:    {state}")
    lines.append(f"build:    {ctx['build']}  (chrome.exe {ctx['version']})")
    lines.append(f"started:  {ctx['started']:%Y-%m-%d %H:%M:%S}")
    lines.append(f"updated:  {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    lines.append(f"tools:    {ctx['tools']}")
    lines.append("")
    head = f"{'step':<20} {'result':<8} {'time':>6}  {'focus':<14} {'counts':<26} what"
    lines.append(head)
    lines.append("-" * len(head))
    for r in results:
        t = f"{int(r.seconds) // 60}:{int(r.seconds) % 60:02d}"
        note = (
            f"  [left {r.leftovers} process(es) behind, killed]" if r.leftovers else ""
        )
        lines.append(
            f"{r.step.id:<20} {r.status:<8} {t:>6}  {r.focus:<14} {r.counts:<26} "
            f"{r.step.title}{note}"
        )
    pending = [s for s in ctx["all_steps"] if s.id not in {r.step.id for r in results}]
    for s in pending:
        lines.append(f"{s.id:<20} {'pending':<8} {'':>6}  {'':<14} {'':<26} {s.title}")
    lines.append("")
    lines.append(
        "Result words: PASS = exit 0. FAIL = a check failed or the tool exited non-zero."
    )
    lines.append(
        "TIMEOUT = killed at its time limit. NOT RUN = deliberately not run here."
    )
    lines.append(
        "A SKIP inside a step is a check that could not be exercised; it is not a pass."
    )
    lines.append("")
    for r in results:
        lines.append(f"== {r.step.id}: {r.step.title}")
        lines.append(f"   exit codes: {r.codes}   log: {r.log}")
        if r.step.note:
            lines.append(f"   note: {r.step.note}")
        for d in r.details:
            lines.append("   " + d)
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------- checks


def check_tools(steps, tmp):
    """Compile every script, import the ones that are safe to import, and
    ask `--help` of the ones that parse arguments. Starts no window."""
    import ast

    bad = 0
    names = sorted({Path(a[0]).name for s in steps for a in s.commands})
    names += ["probe_focus.py"]
    for name in dict.fromkeys(names):
        path = HERE / name
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, str(path))
            compile(source, str(path), "exec")
        except (OSError, SyntaxError) as e:
            print(f"BAD   {name}: does not compile: {e}")
            bad += 1
            continue
        guarded = '__name__ == "__main__"' in source
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        env["TMP"] = env["TEMP"] = str(tmp)
        problems = []
        if guarded:
            r = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    f"import sys; sys.path.insert(0, r'{HERE}'); import {path.stem}",
                ],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(HERE),
                timeout=60,
            )
            if r.returncode:
                problems.append(
                    "import: " + (r.stderr.strip().splitlines() or ["failed"])[-1]
                )
        else:
            problems.append("no __main__ guard, so not imported")
        if name in ARGPARSE_TOOLS:
            r = subprocess.run(
                [sys.executable, str(path), "--help"],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(HERE),
                timeout=60,
            )
            if r.returncode:
                problems.append(
                    "--help: " + (r.stderr.strip().splitlines() or ["failed"])[-1]
                )
        hard = [p for p in problems if not p.startswith("no __main__")]
        print(
            ("BAD   " if hard else "ok    ")
            + name
            + (" (" + "; ".join(problems) + ")" if problems else "")
        )
        bad += bool(hard)
        del tree
    return bad


def print_plan(steps, ctx, only_ids):
    print("Release 3 real-window pass: PLAN (nothing is started)")
    print(f"  build        {ctx['build']}  chrome.exe {ctx['version']}")
    print(f"  output       {ctx['out']}")
    print(f"  logs         {ctx['logs']}")
    print(f"  summary      {ctx['out'] / 'SUMMARY.txt'}")
    print(f"  temp         {ctx['tmp']}  (profiles and scratch; nothing goes to C:)")
    print(
        "  environment  BORING_OUT, BORING_CHROME, BORING_ALLOW_HEADFUL=1 (children only), TMP/TEMP"
    )
    print(f"  focus probe  {'on' if ctx['probe'] else 'off'}")
    total = 0
    for s in steps:
        mark = "" if s.id in only_ids else "  (skipped by --only/--skip)"
        print(f"\n[{s.id}] {s.title}{mark}")
        print(f"   limit {s.timeout // 60} min; log {ctx['logs'] / (s.id + '.log')}")
        print(f"   on screen: {s.window}")
        if s.takeover:
            print(
                "   NOTE: a window goes FULLSCREEN on the monitor nearest to (-32000,-32000)"
            )
        for argv in s.commands:
            print("   $", " ".join(command_line(s, argv, ctx["build"], ctx["probe"])))
        if s.id in only_ids:
            total += s.timeout
    print(
        f"\nSum of the step limits: {total // 60} min (a ceiling, not the expected time)."
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--build", default=DEFAULT_BUILD, help="folder holding chrome.exe")
    ap.add_argument("--out", default=DEFAULT_OUT, help="results folder")
    ap.add_argument("--net-seconds", type=int, default=DEFAULT_NET_SECONDS)
    ap.add_argument(
        "--only", nargs="+", metavar="ID", help="step ids or prefixes, e.g. 2 3 5a"
    )
    ap.add_argument("--skip", nargs="+", metavar="ID", default=[])
    ap.add_argument(
        "--no-takeover",
        action="store_true",
        help="leave out step 2, which takes a window fullscreen on a monitor",
    )
    ap.add_argument("--no-focus-probe", action="store_true")
    ap.add_argument(
        "--max-minutes", type=int, default=240, help="start no new step after this long"
    )
    ap.add_argument("--dry-run", action="store_true", help="print the plan and stop")
    ap.add_argument(
        "--check-tools",
        action="store_true",
        help="compile, import and --help every tool, then stop",
    )
    ap.add_argument(
        "--cleanup",
        action="store_true",
        help="kill leftover browsers of the build, then stop",
    )
    ap.add_argument("--yes", action="store_true", help="do not wait for Enter")
    args = ap.parse_args()

    build = Path(args.build)
    out = Path(args.out)
    steps = build_steps(out, args.net_seconds)

    def chosen(s):
        if args.no_takeover and s.takeover:
            return False
        if args.only and not any(s.id == o or s.id.startswith(o) for o in args.only):
            return False
        return not any(s.id == o or s.id.startswith(o) for o in args.skip)

    selected = [s for s in steps if chosen(s)]
    env, tmp = environment(build, out)
    ctx = {
        "build": build,
        "out": out,
        "logs": out / "logs",
        "tmp": tmp,
        "env": env,
        "probe": not args.no_focus_probe,
        "all_steps": selected,
        "current": None,
        "version": file_version(build / "chrome.exe") if build.exists() else "missing",
        "started": datetime.datetime.now(),
        "tools": (HERE.parent / "TOOLS_COMMIT.txt").read_text().strip()
        if (HERE.parent / "TOOLS_COMMIT.txt").exists()
        else str(HERE),
    }

    if args.check_tools:
        tmp.mkdir(parents=True, exist_ok=True)
        return 1 if check_tools(steps, tmp) else 0
    if args.dry_run:
        print_plan(steps, ctx, {s.id for s in selected})
        problems = [s.id for s in steps for a in s.commands if not Path(a[0]).exists()]
        print("\nmissing scripts:", problems or "none")
        print(
            "chrome.exe:",
            "present" if (build / "chrome.exe").exists() else "MISSING",
            "| chromedriver.exe:",
            "present" if (build / "chromedriver.exe").exists() else "MISSING",
        )
        return 1 if problems else 0
    if args.cleanup:
        print(f"killed {sweep(build)} process(es) under {build}")
        return 0

    # ---- preflight: refuse to start on a wrong footing
    for need in ("chrome.exe", "chromedriver.exe"):
        if not (build / need).exists():
            print(f"stop: no {need} in {build}")
            return 2
    if ctx["version"] != "unknown" and not ctx["version"].startswith(EXPECT_VERSION):
        print(
            f"stop: chrome.exe is {ctx['version']}, this pass is for {EXPECT_VERSION}. "
            "Pass --build for another folder if that is meant."
        )
        return 2
    free = shutil.disk_usage(out.anchor or ".").free
    if free < 2 * 1024**3:
        print(f"stop: only {free // 1024**2} MB free on {out.anchor}")
        return 2
    running = processes_under(build)
    if running:
        print(
            "stop: this build is already running (pid "
            + ", ".join(str(p) for p, _ in running)
            + "). Close it or run with --cleanup."
        )
        return 2
    out.mkdir(parents=True, exist_ok=True)
    ctx["logs"].mkdir(exist_ok=True)
    tmp.mkdir(exist_ok=True)
    (out / "shots").mkdir(exist_ok=True)

    print(f"Release 3 real-window pass on {build} (chrome.exe {ctx['version']})")
    print(f"{len(selected)} steps; results in {out}")
    print("Browser windows will open OFF SCREEN. Step 2 takes a window fullscreen on a")
    print(
        "monitor for a few seconds at a time. Do not type or click on this machine while"
    )
    print("it runs: a new window can take the keyboard focus. Ctrl+C stops it cleanly.")
    if not args.yes:
        input("Press Enter to start... ")

    results = []
    summary = out / "SUMMARY.txt"
    state = "running"
    write_summary(summary, ctx, results, state)
    began = time.monotonic()
    try:
        for step in selected:
            if (time.monotonic() - began) / 60 > args.max_minutes:
                print(
                    f"time limit of {args.max_minutes} min reached, stopping before {step.id}"
                )
                state = "stopped at the time limit"
                break
            print(f"\n[{step.id}] {step.title} ...", flush=True)
            try:
                r = run_step(step, ctx)
            except Exception as e:  # a harness fault in one step must not stop the rest
                r = Result(step, status="ERROR", details=[f"harness error: {e!r}"])
            r.leftovers = sweep(build)
            results.append(r)
            print(
                f"[{step.id}] {r.status} in {int(r.seconds)}s ({r.counts}; focus: {r.focus})",
                flush=True,
            )
            write_summary(summary, ctx, results, state)
        else:
            state = "finished"
    except KeyboardInterrupt:
        print("\nstopped from the keyboard; cleaning up")
        if ctx["current"] is not None:
            kill_tree(ctx["current"].pid)
        state = "STOPPED from the keyboard"
    finally:
        left = sweep(build)
        if left:
            print(f"cleanup killed {left} leftover process(es)")
        write_summary(summary, ctx, results, state)
    print(f"\n{state}. Summary: {summary}")
    print(summary.read_text(encoding="utf-8").split("\n\n")[1])
    return 1 if any(r.status in ("FAIL", "TIMEOUT", "ERROR") for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
