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
CHECK_URL = "https://update.googleapis.com/service/update2/json"

DEFAULT_USER_DATA = os.path.join(os.environ.get("LOCALAPPDATA", ""),
                                 "Chromium", "User Data")


def find_package():
    """Ask the update service where the current CDM package lives."""
    body = json.dumps({"request": {
        "protocol": "3.1",
        "acceptformat": "crx3",
        "updater": "chromiumcrx",
        "updaterversion": "138.0.0.0",
        "prodversion": "138.0.0.0",
        "os": {"platform": "Windows", "arch": "x86_64"},
        "arch": "x64",
        "app": [{"appid": WIDEVINE_ID, "version": "0.0.0.0",
                 "updatecheck": {}}],
    }}).encode()
    req = urllib.request.Request(CHECK_URL, data=body, headers={
        "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    text = urllib.request.urlopen(req).read().decode()
    # The reply starts with a junk line that protects against script tags.
    text = text.split("\n", 1)[1] if text.startswith(")]}'") else text
    reply = json.loads(text)
    app = reply["response"]["app"][0]
    check = app["updatecheck"]
    if check.get("status") != "ok":
        sys.exit("update check failed: " + json.dumps(check))
    urls = [u["codebase"] for u in check["urls"]["url"]
            if u["codebase"].startswith("https")]
    package = check["manifest"]["packages"]["package"][0]
    return urls[0] + package["name"], package["hash_sha256"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-data-dir", default=DEFAULT_USER_DATA)
    args = ap.parse_args()

    print("asking for the CDM package location ...")
    url, sha256 = find_package()
    print("downloading", url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = urllib.request.urlopen(req).read()
    print("got", len(data), "bytes")
    import hashlib
    if hashlib.sha256(data).hexdigest() != sha256:
        sys.exit("download hash does not match, stopping")

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
