#!/usr/bin/env python3
"""Download the Widevine CDM and install it for the browser to find.

The browser build already has Widevine support compiled in. What is
missing is the CDM library itself, because we do not talk to Google's
update service at run time. This script does that one download up front,
then places the files where the browser's component registration finds
them on startup: <user data dir>\\WidevineCdm\\<version>\\.

Usage: python get_widevine.py [--user-data-dir PATH]

Note: this contacts Google's update server once, on purpose, when you
run it. The browser itself never phones home.
"""

import argparse
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile

WIDEVINE_ID = "oimompecagnajdejgnnjijobebaeigek"
URL = ("https://update.googleapis.com/service/update2/crx"
       "?response=redirect&os=win&arch=x64&os_arch=x86_64&nacl_arch=x86-64"
       "&prod=chromiumcrx&prodchannel=unknown&prodversion=138.0.0.0"
       "&acceptformat=crx3"
       "&x=id%3D" + WIDEVINE_ID + "%26v%3D0%26installedby%3Dondemand%26uc")

DEFAULT_USER_DATA = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                 "Chromium", "User Data")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-data-dir", default=DEFAULT_USER_DATA)
    args = ap.parse_args()

    print("downloading Widevine CDM ...")
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req).read()
    print("got", len(data), "bytes")

    # A crx file is a zip with a small header in front. zipfile copes with
    # the leading bytes on its own.
    zf = zipfile.ZipFile(io.BytesIO(data))
    manifest = json.loads(zf.read("manifest.json"))
    version = manifest["version"]
    print("CDM version", version)

    dest = os.path.join(args.user_data_dir, "WidevineCdm", version)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest, exist_ok=True)
    for name in zf.namelist():
        if name.endswith("/"):
            continue
        out = os.path.join(dest, name.replace("/", os.sep))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(zf.read(name))
    print("installed to", dest)
    dll = os.path.join(dest, "_platform_specific", "win_x64", "widevinecdm.dll")
    print("dll present:", os.path.exists(dll))


if __name__ == "__main__":
    main()
