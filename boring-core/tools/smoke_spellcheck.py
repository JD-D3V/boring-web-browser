#!/usr/bin/env python3
r"""Check that spelling mistakes are marked with no download (feature 14).

What it checks:

1. The en-US Hunspell dictionary is in Dictionaries beside chrome.dll,
   which is DIR_APP_DICTIONARIES once the spellcheck-dictionary-dir
   patch is in, and it passes the same checks Chromium runs before it
   uses one (check_package.bdic_problem).

2. A misspelled word typed into a textarea is marked, and a correctly
   spelled one is not. The page styles ::spelling-error with a pure
   green background, so the mark is visible in a CDP screenshot of the
   textarea (Page.captureScreenshot of the page, not the desktop). No
   network: every host but 127.0.0.1 resolves to nothing.

What it cannot tell apart, and says so: on Windows, Chromium asks the
Windows spellchecker first and only uses Hunspell for a language Windows
has no spelling data for. There is no switch to make it use Hunspell.
So the test asks Windows (ISpellCheckerFactory::IsSupported, read only)
whether it has en-US:
  - If it does not, Chromium must be using Hunspell for en-US, the
    download is blocked and the profile is new, so a marked mistake
    proves the bundled file loaded.
  - If it does (most English Windows), a marked mistake proves spelling
    works, but not that the bundled file loaded. Check 1 is then the
    only evidence for the file, and the result says so.

Exit 0 pass, 1 fail.
"""

import base64
import ctypes
import json
import os
import struct
import sys
import tempfile
import time
import zlib
from ctypes import wintypes

import check_package
from drive import CHROME, OUT, Browser

NO_NETWORK = "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"
WRONG = "I recieved the pakage yesturday"
RIGHT = "I received the package yesterday"

PAGE = """<!doctype html><meta charset="utf-8"><title>spelling</title>
<style>
  textarea { font: 28px Arial; width: 700px; height: 60px; color: black;
             background: white; border: 1px solid #888; caret-color: transparent; }
  ::spelling-error { background-color: rgb(0, 255, 0); color: black;
                     text-decoration: none; }
</style>
<textarea id="t" spellcheck="true" lang="en-US"></textarea>"""


# --- does Windows have en-US spelling data? --------------------------------

ole32 = ctypes.WinDLL("ole32")


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __init__(self, text):
        super().__init__()
        ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(self))


CLSID_SpellCheckerFactory = "{7AB36653-1796-484B-BDFA-E74F1DB7C1DC}"
IID_ISpellCheckerFactory = "{8E018A9D-2415-4677-BF08-794EA61F94BB}"


def windows_supports(language):
    """ISpellCheckerFactory::IsSupported, or None if it cannot be asked."""
    ole32.CoInitializeEx(None, 0x2)
    factory = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(GUID(CLSID_SpellCheckerFactory)),
        None,
        0x1 | 0x4,  # in process or local server
        ctypes.byref(GUID(IID_ISpellCheckerFactory)),
        ctypes.byref(factory),
    )
    if hr != 0 or not factory:
        return None
    vtable = ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
    try:
        # Slot 4 is IsSupported(LPCWSTR, BOOL*), after IUnknown's three
        # and get_SupportedLanguages.
        is_supported = ctypes.WINFUNCTYPE(
            ctypes.HRESULT,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.POINTER(wintypes.BOOL),
        )(vtable[0][4])
        result = wintypes.BOOL()
        is_supported(factory, language, ctypes.byref(result))
        return bool(result.value)
    except OSError:
        return None
    finally:
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[0][2])(factory)


# --- reading a screenshot ----------------------------------------------------


def decode_png(data):
    """(width, height, bytes per pixel, rows) for an 8-bit PNG."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos = 8
    idat = b""
    width = height = channels = None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(
                ">IIBBBBB", body
            )
            if depth != 8 or interlace:
                raise ValueError("only 8-bit, non-interlaced PNGs")
            channels = {2: 3, 6: 4}.get(colour)
            if not channels:
                raise ValueError(f"PNG colour type {colour}")
        elif kind == b"IDAT":
            idat += body
    raw = zlib.decompress(idat)
    stride = width * channels
    rows = []
    previous = bytearray(stride)
    i = 0
    for _ in range(height):
        kind = raw[i]
        line = bytearray(raw[i + 1 : i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            left = line[x - channels] if x >= channels else 0
            up = previous[x]
            corner = previous[x - channels] if x >= channels else 0
            if kind == 1:
                line[x] = (line[x] + left) & 0xFF
            elif kind == 2:
                line[x] = (line[x] + up) & 0xFF
            elif kind == 3:
                line[x] = (line[x] + (left + up) // 2) & 0xFF
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                pred = left if pa <= pb and pa <= pc else up if pb <= pc else corner
                line[x] = (line[x] + pred) & 0xFF
        rows.append(bytes(line))
        previous = line
    return width, height, channels, rows


def green_pixels(png):
    width, _height, channels, rows = decode_png(png)
    count = 0
    for row in rows:
        for x in range(width):
            r, g, b = row[x * channels : x * channels + 3]
            # The highlight is blended a little, so near green counts.
            if g > 200 and g - max(r, b) > 120:
                count += 1
    return count


def cdp(b, cmd, params=None):
    return b._req(
        "POST",
        f"/session/{b.sid}/goog/cdp/execute",
        {"cmd": cmd, "params": params or {}},
    )["value"]


def marked_pixels(b, text):
    """Type `text` into the textarea and count the marked pixels."""
    b.run("const t = document.getElementById('t');t.value = ''; t.blur(); t.focus();")
    # The space ends the last word, which is when it gets checked.
    cdp(b, "Input.insertText", {"text": text + " "})
    rect = None
    count = 0
    # Spelling is checked when the page is idle, a moment after typing.
    for _ in range(20):
        time.sleep(0.5)
        rect = b.run(
            "const r = document.getElementById('t').getBoundingClientRect();"
            "return {x: r.x, y: r.y, width: r.width, height: r.height};"
        )
        shot = cdp(
            b,
            "Page.captureScreenshot",
            {"format": "png", "clip": {**rect, "scale": 1}},
        )
        count = green_pixels(base64.b64decode(shot["data"]))
        if count:
            break
    return count


def main():
    if not os.path.exists(CHROME):
        print("no browser at", CHROME, "(set BORING_OUT)")
        return 1
    print("browser:", OUT)
    failures = []

    def check(name, ok, detail=""):
        print(
            f"{'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail else "")
        )
        if not ok:
            failures.append(name)

    # 1. The file, where Chromium looks for it.
    dictionary = os.path.join(OUT, *check_package.DICTIONARY.split("/"))
    if os.path.exists(dictionary):
        with open(dictionary, "rb") as f:
            problem = check_package.bdic_problem(f.read())
        check("en-US dictionary beside chrome.dll loads", problem is None, problem)
    else:
        check("en-US dictionary beside chrome.dll", False, f"no {dictionary}")

    windows = windows_supports("en-US")
    if windows is None:
        engine = "unknown (could not ask Windows)"
    elif windows:
        engine = "the Windows spellchecker (Windows has en-US)"
    else:
        engine = "Hunspell (Windows has no en-US spelling data)"
    print("en-US is checked by", engine)

    # 2. Marks in a real page.
    base = r"E:\tmp" if os.path.isdir(r"E:\tmp") else None
    with tempfile.TemporaryDirectory(prefix="boring-spell-", dir=base) as work:
        page = os.path.join(work, "page.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write(PAGE)
        profile = os.path.join(work, "profile")
        os.makedirs(os.path.join(profile, "Default"))
        # A new profile's spelling language follows the browser's; set
        # it so the test does not depend on the Windows display language.
        with open(
            os.path.join(profile, "Default", "Preferences"), "w", encoding="utf-8"
        ) as f:
            json.dump(
                {
                    "browser": {"enable_spellchecking": True},
                    "spellcheck": {"dictionaries": ["en-US"]},
                    "intl": {"accept_languages": "en-US,en"},
                },
                f,
            )
        with Browser(user_data_dir=profile, args=[NO_NETWORK, "--lang=en-US"]) as b:
            b.get("file:///" + page.replace("\\", "/"))
            right = marked_pixels(b, RIGHT)
            wrong = marked_pixels(b, WRONG)
        print(f"marked pixels: correct text {right}, misspelled text {wrong}")
        check("a misspelled word is marked", wrong > 0)
        check("correct words are not marked", right == 0)

    if windows is False:
        print(
            "Windows has no en-US spelling data here, so the marks above came "
            "from Hunspell and the bundled dictionary."
        )
    else:
        print(
            "Windows handled en-US here, so the marks do not show the bundled "
            "dictionary loading. Only check 1 speaks for the file. To see "
            "Hunspell use it, run this on a Windows without English spelling "
            "data."
        )
    print()
    print("FAIL" if failures else "PASS", f"{len(failures)} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
