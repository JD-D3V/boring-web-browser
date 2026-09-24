#!/usr/bin/env python3
"""Photograph the real browser window, frame and all.

WebDriver screenshots only ever show the page. This drives the built
browser the same way the smoke tests do, then copies the window off the
screen, so tabs, toolbar and window buttons are in the picture.

    python capture_native.py --out shot.png --url chrome://boring-newtab
    python capture_native.py --out dark.png --dark --size 1404x631

Nothing here contacts the network unless the url given does.
"""

import argparse
import ctypes
import os
import sys
import time
from ctypes import wintypes

from drive import OFFSCREEN, Browser

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY = 0x00CC0020
SW_RESTORE = 9


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def windows_of(pids):
    """Every visible titled window belonging to one of these processes."""
    found = []

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            found.append(hwnd)
        return True

    user32.EnumWindows(ENUMPROC(cb), 0)
    return found


def chrome_pids(binary):
    """Process ids of the build we launched, never another Chrome."""
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    count = 4096
    buf = (wintypes.DWORD * count)()
    got = wintypes.DWORD()
    psapi.EnumProcesses(ctypes.byref(buf), ctypes.sizeof(buf), ctypes.byref(got))
    want = os.path.normcase(os.path.abspath(binary))
    pids = set()
    for i in range(got.value // ctypes.sizeof(wintypes.DWORD)):
        pid = buf[i]
        # Query information, plus read, is enough for the image name.
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            size = wintypes.DWORD(32768)
            name = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(
                    handle, 0, name, ctypes.byref(size)):
                if os.path.normcase(name.value) == want:
                    pids.add(pid)
        finally:
            kernel32.CloseHandle(handle)
    return pids


def parents_of(pids):
    """Map each process id to its parent, for the ids we care about."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    snap = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    out = {}
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    if kernel32.Process32First(snap, ctypes.byref(entry)):
        while True:
            if entry.th32ProcessID in pids:
                out[entry.th32ProcessID] = entry.th32ParentProcessID
            if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snap)
    return out


def frame_window(binary, timeout=20, under=None):
    """The browser frame: the biggest window the build owns.

    With `under`, only windows of a browser started by that process (the
    chromedriver we spawned) count. Without it, any window of the build
    does, which will photograph a browser someone else already had open.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        pids = chrome_pids(binary)
        if under is not None:
            parents = parents_of(pids)
            ours = {pid for pid, parent in parents.items() if parent == under}
            if ours:
                pids = ours
        best, best_area = None, 0
        for hwnd in windows_of(pids):
            r = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            if w > 400 and w * h > best_area:
                best, best_area = hwnd, w * h
        if best:
            return best
        time.sleep(0.5)
    raise SystemExit("no browser window found")


def grab(hwnd, path):
    """Copy the window into a PNG.

    PrintWindow asks the window to draw itself, so this works while the
    person is using something else on the same screen. It needs the
    browser to keep painting an occluded window, which is what the
    occlusion flags in main are for.
    """
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top

    screen = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    gdi32.SelectObject(mem, bmp)
    # 2 is PW_RENDERFULLCONTENT, which brings the page with it.
    user32.PrintWindow(hwnd, mem, 2)

    info = BITMAPINFOHEADER()
    info.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.biWidth = w
    info.biHeight = -h  # top down
    info.biPlanes = 1
    info.biBitCount = 32
    info.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(info), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, screen)

    write_png(path, w, h, bytes(buf))
    return w, h


def write_png(path, w, h, bgra):
    """A plain PNG, so this needs nothing installed."""
    import struct
    import zlib

    rows = bytearray()
    for y in range(h):
        rows.append(0)
        line = bgra[y * w * 4:(y + 1) * w * 4]
        # BGRA to RGB
        rows += bytes(
            b for i in range(0, len(line), 4)
            for b in (line[i + 2], line[i + 1], line[i])
        )

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="chrome://boring-newtab")
    ap.add_argument("--size", default="1404x631", help="window size, WxH")
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--tabs", type=int, default=1, help="how many tabs to open")
    ap.add_argument("--settle", type=float, default=2.0)
    ap.add_argument("--profile", default=None)
    ap.add_argument("--extra", action="append", default=[])
    ap.add_argument(
        "--automation-banner",
        action="store_true",
        help="keep chromedriver's 'controlled by automated test software' bar",
    )
    args = ap.parse_args()

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    w, h = (int(v) for v in args.size.lower().split("x"))

    # An occluded window stops painting, and then it photographs blank.
    # These keep it drawing while it sits behind whatever else is open.
    chrome_args = [
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
    ]
    chrome_args += list(args.extra)
    if args.dark:
        chrome_args.append("--force-dark-mode")
    chrome_args.append(f"--window-size={w},{h}")
    # Keep the window off the desktop while it is photographed, so a
    # capture run never covers what somebody is doing. PrintWindow
    # copies from the window, not from the screen, so offscreen is
    # fine. BORING_WINDOW_POSITION overrides it.
    place = os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN)
    chrome_args.append("--window-position=" + place)

    binary = os.environ.get(
        "BORING_CHROME", r"E:\ung\build\src\out\Default\chrome.exe")

    # chromedriver adds an infobar reading "Chrome is being controlled by
    # automated test software". It is the test harness talking, not the
    # browser, and it names the wrong product. A picture of the browser
    # should not contain it unless somebody asks for it.
    keep = None if args.automation_banner else ["enable-automation"]

    with Browser(user_data_dir=args.profile, args=chrome_args,
                 keep_switches=keep) as b:
        for _ in range(max(0, args.tabs - 1)):
            b.run("window.open('about:blank')")
        b.get(args.url)
        time.sleep(args.settle)
        # Only the browser this driver started, so an already open window
        # (JD's preview) is never the one photographed.
        hwnd = frame_window(binary, under=b.proc.pid)
        px, py = (int(v) for v in place.split(","))
        user32.MoveWindow(hwnd, px, py, w, h, True)
        time.sleep(0.6)
        got = grab(hwnd, args.out)
    print(f"saved {args.out} {got[0]}x{got[1]}")


if __name__ == "__main__":
    main()
