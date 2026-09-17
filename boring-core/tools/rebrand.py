#!/usr/bin/env python3
"""Give the browser its own name and Windows identity.

Rewrites Chromium's product name in the English strings, the BRANDING
file and the Windows install constants. Every run starts from the
pristine copy of each file, so running it twice changes nothing, and
apply.py --restore puts the originals back.

Credit to the Chromium authors is left as it is.

Usage: python rebrand.py [--src E:\\ung\\build\\src]
"""

import argparse
import os
import re
import shutil

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = r"E:\ung\build\src"
PRISTINE = os.path.join(CORE, ".pristine")

NAME = "Boring Browser"
# Used where Windows wants no spaces: the install folder, registry ids,
# ProgIDs and the URL scheme.
ID = "BoringBrowser"

STRING_FILES = [
    "chrome/app/chromium_strings.grd",
    "chrome/app/settings_chromium_strings.grdp",
    "components/components_chromium_strings.grd",
]

# "The Chromium Authors" stays: they wrote the code.
PRODUCT_WORD = re.compile(r"\bChromium\b(?! Authors)")

BRANDING = {
    "PRODUCT_FULLNAME": NAME,
    "PRODUCT_SHORTNAME": NAME,
    "PRODUCT_INSTALLER_FULLNAME": NAME + " Installer",
    "PRODUCT_INSTALLER_SHORTNAME": NAME + " Installer",
}

INSTALL_MODES = [
    # The install and profile folder. No space: Windows cannot load the
    # browser's side-by-side assembly from a folder name with one.
    ('kProductPathName[] = L"Chromium";', f'kProductPathName[] = L"{ID}";'),
    ('.base_app_name = L"Chromium",', f'.base_app_name = L"{NAME}",'),
    ('.base_app_id = L"Chromium",', f'.base_app_id = L"{ID}",'),
    (
        '.browser_prog_id_prefix = L"ChromiumHTM",',
        '.browser_prog_id_prefix = L"BoringHTM",',
    ),
    ('L"Chromium HTML Document",', f'L"{NAME} HTML Document",'),
    (
        '.direct_launch_url_scheme = "chromium",',
        '.direct_launch_url_scheme = "boringbrowser",',
    ),
    ('.pdf_prog_id_prefix = L"ChromiumPDF",', '.pdf_prog_id_prefix = L"BoringPDF",'),
    ('L"Chromium PDF Document",', f'L"{NAME} PDF Document",'),
    # Our own ids, so an installed Chromium and this browser never
    # overwrite each other's registration.
    (
        'L"{7D2B3E1D-D096-4594-9D8F-A6667F12E0AC}"',
        'L"{5B0E9C2A-6F3D-4A71-9C88-2E4B7D1A6C35}"',
    ),
]


def pristine_text(src, rel):
    """The original file, saved the first time we touch it."""
    keep = os.path.join(PRISTINE, rel)
    if not os.path.exists(keep):
        os.makedirs(os.path.dirname(keep), exist_ok=True)
        shutil.copy2(os.path.join(src, rel), keep)
    with open(keep, encoding="utf-8", newline="") as f:
        return f.read()


def write_if_changed(src, rel, text):
    path = os.path.join(src, rel)
    with open(path, encoding="utf-8", newline="") as f:
        if f.read() == text:
            return
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print("rebrand", rel)


def rebrand(src):
    for rel in STRING_FILES:
        write_if_changed(src, rel, PRODUCT_WORD.sub(NAME, pristine_text(src, rel)))

    rel = "chrome/app/theme/chromium/BRANDING"
    lines = []
    for line in pristine_text(src, rel).splitlines(keepends=True):
        key = line.split("=", 1)[0]
        if key in BRANDING:
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            line = f"{key}={BRANDING[key]}{ending}"
        lines.append(line)
    write_if_changed(src, rel, "".join(lines))

    rel = "chrome/install_static/chromium_install_modes.h"
    text = pristine_text(src, rel)
    for old, new in INSTALL_MODES:
        if text.count(old) != 1:
            raise SystemExit(f"rebrand: expected one {old!r} in {rel}")
        text = text.replace(old, new)
    write_if_changed(src, rel, text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    rebrand(ap.parse_args().src)


if __name__ == "__main__":
    main()
