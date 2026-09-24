#!/usr/bin/env python3
"""Fetch the WinSparkle release the browser updater is built against.

WinSparkle (https://winsparkle.org, MIT) is the Windows port of Sparkle.
The browser loads WinSparkle.dll from beside chrome.dll to check the
update feed, download a new installer, check its EdDSA signature against
our key, and run it. See components/boring/update.

The release zip is pinned by SHA-256, so a changed or replaced download
is refused rather than shipped. Moving to a newer WinSparkle means
changing VERSION and SHA256 here together, after reading its NEWS.

What lands in boring-core/third_party/winsparkle (not in git):
  WinSparkle.dll          x64 build, staged into the tree by apply.py
  winsparkle-tool.exe     signs installers and makes keys, release use only
  NOTICES-WinSparkle.txt  its licence and the ones it carries (expat,
                          OpenSSL), shipped beside chrome.exe

Usage:
  python get_winsparkle.py
"""

import hashlib
import io
import os
import sys
import urllib.request
import zipfile

VERSION = "0.9.4"
SHA256 = "6037df37fc263bd1650a1c4949681a9d40ffe991d01f35892a406cb5d103c976"
URL = (
    "https://github.com/vslavik/winsparkle/releases/download/"
    f"v{VERSION}/WinSparkle-{VERSION}.zip"
)

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(CORE, "third_party", "winsparkle")

# Inside the zip, under WinSparkle-<version>/.
DLL = "x64/Release/WinSparkle.dll"
TOOL = "bin/winsparkle-tool.exe"
LICENCES = ["COPYING", "COPYING.expat"]


def fetch():
    cached = os.path.join(OUT, f"WinSparkle-{VERSION}.zip")
    if os.path.exists(cached):
        with open(cached, "rb") as f:
            data = f.read()
    else:
        print("downloading", URL)
        with urllib.request.urlopen(URL, timeout=120) as response:
            data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        sys.exit(
            f"WinSparkle zip hash {digest} is not the pinned {SHA256}, refusing it"
        )
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(cached):
        with open(cached, "wb") as f:
            f.write(data)
    return data


def main():
    archive = zipfile.ZipFile(io.BytesIO(fetch()))
    root = f"WinSparkle-{VERSION}/"

    for inner, name in ((DLL, "WinSparkle.dll"), (TOOL, "winsparkle-tool.exe")):
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(archive.read(root + inner))
        print("wrote", name)

    parts = [
        f"WinSparkle {VERSION}, https://winsparkle.org/\n"
        "Used by Boring Browser to check for and install updates.\n"
    ]
    for licence in LICENCES:
        parts.append(f"\n==== {licence} ====\n\n")
        parts.append(archive.read(root + licence).decode("utf-8"))
    with open(
        os.path.join(OUT, "NOTICES-WinSparkle.txt"), "w", encoding="utf-8", newline="\n"
    ) as f:
        f.write("".join(parts))
    print("wrote NOTICES-WinSparkle.txt")


if __name__ == "__main__":
    main()
