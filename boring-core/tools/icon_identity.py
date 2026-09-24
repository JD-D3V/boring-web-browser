#!/usr/bin/env python3
"""Show which icon Windows gets from the built browser.

Reads the icon two ways, without touching the screen or the desktop:
the icon resource inside chrome.exe (what the taskbar, Alt-Tab and
shortcuts load), and the icons the running browser window hands to
Windows (WM_GETICON / class icon). Each one is drawn into a PNG so it
can be compared with the brand master.

    python icon_identity.py --exe E:\\ung\\build\\src\\out\\Default\\chrome.exe --out DIR
    python icon_identity.py --pid 1234 --out DIR

Only the windows of the given process are read.
"""

import argparse
import ctypes
import hashlib
import os
import struct
import zlib
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

WM_GETICON = 0x007F
ICON_SMALL, ICON_BIG, ICON_SMALL2 = 0, 1, 2
GCLP_HICON, GCLP_HICONSM = -14, -34
DI_NORMAL = 0x0003
SMTO_ABORTIFHUNG = 0x0002

user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.GetClassLongPtrW.restype = ctypes.c_size_t
user32.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.DrawIconEx.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HANDLE, ctypes.c_int,
    ctypes.c_int, wintypes.UINT, wintypes.HANDLE, wintypes.UINT]
gdi32.CreateDIBSection.restype = wintypes.HANDLE
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.SelectObject.restype = wintypes.HANDLE
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
shell32.SHDefExtractIconW.argtypes = [
    wintypes.LPCWSTR, ctypes.c_int, wintypes.UINT,
    ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.HICON),
    wintypes.UINT]

ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def png_bytes(w, h, rgba):
    def chunk(kind, data):
        c = struct.pack(">I", len(data)) + kind + data
        return c + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def draw_icon(hicon, size):
    """Render an HICON into straight-alpha RGBA bytes."""
    class BMI(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD),
                    ("rest", wintypes.DWORD * 6)]
    bmi = BMI()
    bmi.biSize = 40
    bmi.biWidth = size
    bmi.biHeight = -size
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    bits = ctypes.c_void_p()
    dc = gdi32.CreateCompatibleDC(None)
    dib = gdi32.CreateDIBSection(dc, ctypes.byref(bmi), 0,
                                 ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(dc, dib)
    user32.DrawIconEx(dc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
    raw = ctypes.string_at(bits, size * size * 4)
    gdi32.SelectObject(dc, old)
    gdi32.DeleteObject(dib)
    gdi32.DeleteDC(dc)
    out = bytearray(len(raw))
    for i in range(0, len(raw), 4):
        b, g, r, a = raw[i:i + 4]
        if a:
            r, g, b = (min(255, r * 255 // a), min(255, g * 255 // a),
                       min(255, b * 255 // a))
        out[i:i + 4] = bytes((r, g, b, a))
    return bytes(out)


def save(hicon, size, path):
    data = png_bytes(size, size, draw_icon(hicon, size))
    with open(path, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()[:16]


def from_exe(exe, out):
    for size in (16, 24, 32, 48, 256):
        large = wintypes.HICON()
        small = wintypes.HICON()
        hr = shell32.SHDefExtractIconW(exe, 0, 0, ctypes.byref(large),
                                       ctypes.byref(small), size)
        if hr != 0 or not large.value:
            print("exe", size, "no icon, hr", hr)
            continue
        path = os.path.join(out, "exe-%d.png" % size)
        print("exe", size, path, save(large.value, size, path))
        user32.DestroyIcon(large.value)


def from_process(pid, out):
    found = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and user32.IsWindowVisible(hwnd) and \
                user32.GetWindowTextLengthW(hwnd):
            found.append(hwnd)
        return True
    user32.EnumWindows(ENUMPROC(cb), 0)
    for n, hwnd in enumerate(found):
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        print("window", n, hex(hwnd), repr(title.value))
        for name, kind in (("big", ICON_BIG), ("small2", ICON_SMALL2)):
            res = ctypes.c_size_t()
            user32.SendMessageTimeoutW(hwnd, WM_GETICON, kind, 0,
                                       SMTO_ABORTIFHUNG, 2000,
                                       ctypes.byref(res))
            if res.value:
                path = os.path.join(out, "win%d-%s.png" % (n, name))
                print(" ", name, path, save(res.value, 32, path))
        for name, idx in (("class", GCLP_HICON), ("classsm", GCLP_HICONSM)):
            h = user32.GetClassLongPtrW(hwnd, idx)
            if h:
                path = os.path.join(out, "win%d-%s.png" % (n, name))
                print(" ", name, path, save(h, 32, path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    if args.exe:
        from_exe(args.exe, args.out)
    if args.pid:
        from_process(args.pid, args.out)


if __name__ == "__main__":
    main()
