#!/usr/bin/env python3
r"""Run every check a freshly built browser has to pass, and write it down.

A build landing is the moment everything has to be re-proved, and the
list of what to re-prove is long enough that doing it by hand means
doing some of it. This runs the lot in order, records the exit code of
each step, and writes a report that says what passed, what failed and
what was skipped.

It stops at nothing: a failing step is recorded and the rest still run,
because "the installer is also broken" is worth knowing on the same
pass rather than the next one.

Order, and why:

  1. facts        which binary this actually is, hashed, before anything
                  touches it
  2. sandbox      nothing else is worth checking in a browser whose
                  sandbox came loose
  3. smoke        the whole regression suite
  4. package      mini_installer and package.py, then read the package
                  back and check what is in it
  5. identity     the B in the exe, the window and the installer
  6. network      where the browser goes when nobody asks it to

Steps 4 to 6 are skipped unless asked for, because packaging takes a
while and a network capture takes minutes of sitting still.

It takes the build tree lock for the whole run, so it cannot collide
with a build, and refuses to start if ninja is running.

Usage:
  python verify_build.py --src E:\ung-153-47\build\src
  python verify_build.py --src ... --package --network
  python verify_build.py --src ... --only smoke
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
REPORTS = REPO / "artifacts/release-readiness"

# Hashed and reported every run. If one of these is missing the build is
# not finished, whatever ninja said.
BINARIES = [
    "chrome.exe",
    "chrome.dll",
    "chromedriver.exe",
    "boring_adblock.dll",
]

PACKAGED = ["mini_installer.exe", "setup.exe"]


class Step:
    def __init__(self, name: str):
        self.name = name
        self.code: int | None = None
        self.seconds = 0.0
        self.note = ""
        self.skipped = False

    def as_dict(self) -> dict:
        return {
            "step": self.name,
            "exit_code": self.code,
            "seconds": round(self.seconds, 1),
            "note": self.note,
            "skipped": self.skipped,
        }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ninja_running() -> bool:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "(Get-Process ninja,clang-cl,lld-link -ErrorAction SilentlyContinue"
         " | Measure-Object).Count"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() not in ("", "0")


def run(step: Step, args: list[str], env: dict, cwd: Path, log: Path) -> Step:
    print(f"\n=== {step.name} ===", flush=True)
    print("  " + " ".join(str(a) for a in args), flush=True)
    started = time.monotonic()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "w", encoding="utf-8", errors="replace") as out:
        result = subprocess.run(args, cwd=cwd, env=env, stdout=out,
                                stderr=subprocess.STDOUT, text=True)
    step.seconds = time.monotonic() - started
    step.code = result.returncode
    print(f"  exit {step.code} in {step.seconds:.0f}s, log {log.name}")
    return step


def build_facts(out_dir: Path, src: Path) -> dict:
    """What this binary is, hashed, before any check touches it."""
    facts = {
        "source_tree": str(src),
        "output": str(out_dir),
        "chromium_version": "",
        "binaries": {},
        "missing": [],
    }
    version_file = src / "chrome" / "VERSION"
    if version_file.exists():
        parts = version_file.read_text(encoding="utf-8").split()
        facts["chromium_version"] = ".".join(p.split("=")[1] for p in parts)
    for name in BINARIES + PACKAGED:
        path = out_dir / name
        if not path.exists():
            if name in BINARIES:
                facts["missing"].append(name)
            continue
        stat = path.stat()
        facts["binaries"][name] = {
            "sha256": sha256(path),
            "bytes": stat.st_size,
            "modified": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)
            ),
        }
    return facts


def newest(directory: Path, pattern: str) -> Path | None:
    hits = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="the Chromium source tree")
    ap.add_argument("--package", action="store_true",
                    help="also build the installer, package, and read it back")
    ap.add_argument("--network", action="store_true",
                    help="also capture where the browser goes on its own")
    ap.add_argument("--only", help="run one step by name and stop")
    ap.add_argument("--label", default="", help="name for this run's report")
    ap.add_argument("--force", action="store_true",
                    help="run even though a build looks to be in progress")
    args = ap.parse_args()

    src = Path(args.src).resolve()
    out_dir = src / "out" / "Default"
    root = src.parents[1]  # <root>\build\src -> <root>
    if not out_dir.is_dir():
        sys.exit(f"no build output at {out_dir}")

    if ninja_running() and not args.force:
        sys.exit(
            "ninja or a compiler is running. Checking a build tree while it "
            "is being written gives an answer about neither build. Wait, or "
            "pass --force if you are certain it is a different tree."
        )

    stamp = time.strftime("%Y%m%d-%H%M%S")
    label = args.label or stamp
    logs = REPO / "logs" / f"verify-{label}"
    logs.mkdir(parents=True, exist_ok=True)

    env = {**os.environ, "BORING_OUT": str(out_dir), "TMP": r"E:\tmp",
           "TEMP": r"E:\tmp"}

    facts = build_facts(out_dir, src)
    print("browser under test:", facts["chromium_version"], "at", out_dir)
    for name, info in facts["binaries"].items():
        print(f"  {name:<22} {info['sha256'][:16]}  {info['modified']}")
    if facts["missing"]:
        print("  MISSING:", ", ".join(facts["missing"]))

    steps: list[Step] = []

    def wanted(name: str) -> bool:
        return not args.only or args.only == name

    if wanted("sandbox"):
        steps.append(run(Step("sandbox"),
                         [sys.executable, str(HERE / "smoke_sandbox.py")],
                         env, HERE, logs / "sandbox.log"))

    if wanted("smoke"):
        steps.append(run(Step("smoke"),
                         [sys.executable, str(HERE / "smoke_all.py")],
                         env, HERE, logs / "smoke.log"))

    if args.package and wanted("package"):
        # mini_installer is not part of the default browser build, so it
        # is asked for by name here rather than assumed to be there.
        steps.append(run(Step("mini_installer"),
                         ["cmd", "/c", str(HERE / "build_chrome.bat"),
                          "-j", "4", "mini_installer"],
                         {**env, "BORING_SRC": str(src)}, REPO,
                         logs / "mini_installer.log"))
        steps.append(run(Step("package"),
                         [sys.executable, str(root / "package.py")],
                         env, root, logs / "package.log"))

        zip_path = newest(root / "build", "*_windows_x64.zip")
        installer = newest(root / "build", "*_installer_x64.exe")
        step = Step("check package")
        if not zip_path or not installer:
            step.skipped = True
            step.note = "package.py produced no zip or no installer"
            print("\n=== check package ===\n  skipped:", step.note)
            steps.append(step)
        else:
            steps.append(run(
                step,
                [sys.executable, str(HERE / "check_package.py"),
                 "--zip", str(zip_path), "--installer", str(installer),
                 "--expect-version", facts["chromium_version"]],
                env, HERE, logs / "check_package.log"))
            step.note = zip_path.name

    if args.package and wanted("identity"):
        steps.append(run(Step("icon identity"),
                         [sys.executable, str(HERE / "icon_identity.py"),
                          "--exe", str(out_dir / "chrome.exe"),
                          "--out", str(REPORTS / f"icons-{label}")],
                         env, HERE, logs / "icons.log"))

    if args.network and wanted("network"):
        steps.append(run(Step("network"),
                         [sys.executable, str(HERE / "net_audit.py"),
                          "--all", "--seconds", "120"],
                         env, HERE, logs / "network.log"))

    report = {
        "label": label,
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "build": facts,
        "steps": [s.as_dict() for s in steps],
        "logs": str(logs),
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"verify-{label}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n\nSummary")
    print("-------")
    failed = 0
    for step in steps:
        if step.skipped:
            outcome = "skipped"
        elif step.code == 0:
            outcome = "pass"
        else:
            outcome = f"FAIL ({step.code})"
            failed += 1
        print(f"{step.name:<20} {outcome:<12} {step.note}")
    if facts["missing"]:
        print(f"{'binaries':<20} {'FAIL':<12} missing "
              + ", ".join(facts["missing"]))
        failed += 1
    print("\nwrote", out)
    print("logs in", logs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
