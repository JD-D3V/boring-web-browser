#!/usr/bin/env python3
"""Does a test run take the foreground away from whoever is using the PC?

Runs a command and watches GetForegroundWindow around it: before, while
it runs, and after. Every change of the foreground window is listed,
and the ones that landed on a window of the browser under test (or of
anything the command started) are marked. If any did, the run took the
focus and the exit code is 1.

Read only. It never calls SetForegroundWindow, never sends input and
never touches a window. It does not hold the build lock, so wrap it the
same way as the command it measures:

  python joblock.py --job focus -- python probe_focus.py -- python drive.py
  python probe_focus.py -- python smoke_protection.py
  python probe_focus.py -- python capture_native.py --out E:\\tmp\\x.png
"""

import argparse
import ctypes
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

# How often the foreground window is read. A window that takes the focus
# and gives it back inside this long goes unseen; 5 ms is below anything
# a browser start does.
INTERVAL = 0.005


@dataclass
class Change:
    at: float
    title: str
    exe: str
    ours: bool


def stolen(changes):
    """The changes that put one of our windows in front."""
    return [c for c in changes if c.ours]


def describe(change):
    mark = "OURS " if change.ours else "other"
    title = change.title or "(untitled)"
    return f"+{change.at:6.2f}s  {mark}  {title!r}  [{change.exe or '?'}]"


def report(before, changes, after, code):
    """The text a person reads, and whether the run took the focus."""
    lines = [f"before: {before}"]
    if changes:
        lines += ["foreground changes while it ran:"]
        lines += ["  " + describe(c) for c in changes]
    else:
        lines += ["foreground changes while it ran: none"]
    lines += [f"after:  {after}"]
    took = stolen(changes)
    if took:
        lines += [f"RESULT: took the focus ({len(took)} change(s) onto our windows)"]
    else:
        lines += ["RESULT: foreground unchanged by the run"]
    lines += [f"command exit code: {code}"]
    return "\n".join(lines), bool(took)


# Windows ----------------------------------------------------------------

user32 = kernel32 = None
if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def image_of(pid):
    """Full path of a process's program, or '' if it is not ours to ask."""
    # PROCESS_QUERY_LIMITED_INFORMATION
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        name = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            return name.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def parent_map():
    """Every process id on the machine mapped to its parent."""

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    out = {}
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    if kernel32.Process32First(snap, ctypes.byref(entry)):
        while True:
            out[entry.th32ProcessID] = entry.th32ParentProcessID
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snap)
    return out


def descends_from(pid, root):
    """True if `root` is an ancestor of `pid`, however many launchers sit between."""
    parents = parent_map()
    seen = set()
    while pid in parents and pid not in seen:
        seen.add(pid)
        pid = parents[pid]
        if pid == root:
            return True
    return False


def foreground():
    """(handle, title, pid, program) of the window in front right now."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return (None, "", 0, "")
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return (hwnd, buf.value, pid.value, image_of(pid.value))


def label(fg):
    hwnd, title, _pid, exe = fg
    if hwnd is None:
        return "(no foreground window)"
    return f"{title or '(untitled)'!r} [{os.path.basename(exe) or '?'}]"


class Watcher(threading.Thread):
    """Reads the foreground window until stopped and keeps every change."""

    def __init__(self, root_pid_of, build_dir):
        super().__init__(daemon=True)
        self.root_pid_of = root_pid_of
        self.build_dir = (
            os.path.normcase(os.path.abspath(build_dir)) if build_dir else ""
        )
        self.changes = []
        self.last = foreground()
        self.t0 = None
        self._stop_event = threading.Event()

    def is_ours(self, fg):
        _hwnd, _title, pid, exe = fg
        if self.build_dir and os.path.normcase(exe).startswith(self.build_dir):
            return True
        root = self.root_pid_of()
        return bool(root and pid and descends_from(pid, root))

    def run(self):
        while not self._stop_event.is_set():
            now = foreground()
            if now[0] != self.last[0]:
                if self.t0 is not None:
                    self.changes.append(
                        Change(
                            time.perf_counter() - self.t0,
                            now[1],
                            os.path.basename(now[3]),
                            self.is_ours(now),
                        )
                    )
                self.last = now
            time.sleep(INTERVAL)

    def stop(self):
        self._stop_event.set()
        self.join()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--settle",
        type=float,
        default=1.5,
        help="seconds watched after the command ends",
    )
    ap.add_argument(
        "command", nargs=argparse.REMAINDER, help="-- then the command to run"
    )
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        ap.error("give the command to run after --")

    out_dir = os.environ.get("BORING_OUT", "")
    proc_holder = {}
    watcher = Watcher(
        lambda: proc_holder["p"].pid if "p" in proc_holder else 0, out_dir
    )
    watcher.start()
    time.sleep(0.5)
    before = label(watcher.last)
    watcher.t0 = time.perf_counter()
    try:
        proc_holder["p"] = subprocess.Popen(command)
        code = proc_holder["p"].wait()
        time.sleep(args.settle)
    finally:
        watcher.stop()
    text, took = report(before, watcher.changes, label(watcher.last), code)
    print("\n" + text)
    return 1 if took else code


if __name__ == "__main__":
    sys.exit(main())
