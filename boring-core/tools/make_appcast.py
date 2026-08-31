#!/usr/bin/env python3
"""Write the update feed the browser reads to find new versions.

We use WinSparkle on Windows, which reads a small appcast XML file. Put
the file and the installer on any static host, for example GitHub
Releases, and point the browser at the file's address.

Usage:
  python make_appcast.py --installer E:\\ung\\build\\...installer_x64.exe \\
      --version 151.0.7922.173 --base-url https://example.com/downloads \\
      --out C:\\path\\to\\dist\\appcast.xml
"""

import argparse
import datetime
import hashlib
import os
import sys
from xml.sax.saxutils import escape

TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>boring browser updates</title>
    <link>{base_url}/appcast.xml</link>
    <description>Updates for the boring browser</description>
    <language>en</language>
    <item>
      <title>Version {version}</title>
      <pubDate>{date}</pubDate>
      <description><![CDATA[{notes}]]></description>
      <enclosure url="{base_url}/{filename}"
                 sparkle:version="{version}"
                 sparkle:shortVersionString="{version}"
                 sparkle:os="windows"
                 length="{size}"
                 type="application/octet-stream" />
    </item>
  </channel>
</rss>
"""

DEFAULT_NOTES = """<h2>What changed</h2>
<p>Security fixes from the latest Chromium, plus our own changes. See
the release notes on the project page.</p>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--base-url", required=True,
                    help="where the files are hosted, with no trailing slash")
    ap.add_argument("--out", required=True)
    ap.add_argument("--notes", default=DEFAULT_NOTES)
    args = ap.parse_args()

    if not os.path.exists(args.installer):
        sys.exit("no installer at " + args.installer)

    size = os.path.getsize(args.installer)
    digest = hashlib.sha256()
    with open(args.installer, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)

    xml = TEMPLATE.format(
        base_url=escape(args.base_url.rstrip("/")),
        version=escape(args.version),
        filename=escape(os.path.basename(args.installer)),
        size=size,
        date=datetime.datetime.now(datetime.timezone.utc).strftime(
            "%a, %d %b %Y %H:%M:%S +0000"),
        notes=args.notes,
    )

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(xml)

    print("wrote", args.out)
    print("installer size:", size)
    print("sha256:", digest.hexdigest())
    print()
    print("Note: WinSparkle checks the installer's Authenticode signature.")
    print("Until we have a signing certificate, updates will warn on other")
    print("machines.")


if __name__ == "__main__":
    main()
