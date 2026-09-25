#!/usr/bin/env python3
"""Write the update feed the browser reads to find new versions.

The feed is a small appcast XML file in the shape WinSparkle reads. Put
the file and the installer on any static host, for example GitHub
Releases, and point the browser at the file's address. The address must
be a fixed one that never mentions a version, or a browser two releases
behind has nowhere to look.

WinSparkle trusts an installer only when the enclosure carries an EdDSA
signature made with the key whose public half is compiled into the
browser. Give that signature with --ed-signature, or let this script
make it with --private-key-file (or BORING_UPDATE_KEY_FILE), which runs
`winsparkle-tool sign`. The key file's path is never printed.

With --check-key-from, the signature is also checked against the public
key the browser was built with, so a release signed with the wrong key
file is caught here and not on everyone's machine.

Usage:
  python make_appcast.py --installer dist\\BoringBrowser_..._installer_x64.exe \\
      --version 153.0.8010.52 --release 1 \\
      --base-url https://github.com/JD-D3V/boring-web-browser/releases/download/v1 \\
      --feed-url https://jd-d3v.github.io/boring-web-browser/appcast.xml \\
      --require-signature --out dist\\appcast.xml
"""

import argparse
import base64
import binascii
import datetime
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

TOOLS = Path(__file__).resolve().parent
DEFAULT_TOOL = TOOLS.parent / "third_party" / "winsparkle" / "winsparkle-tool.exe"

# Read when --private-key-file is not given, so the path can come from a
# secret without ever being typed into a log.
KEY_FILE_ENV = "BORING_UPDATE_KEY_FILE"

# The one address the browser reads, compiled into browser_updater.cc.
FEED_URL = "https://jd-d3v.github.io/boring-web-browser/appcast.xml"

CONFIG_ERROR = 2

TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>Boring Browser updates</title>
    <link>{feed_url}</link>
    <description>Updates for Boring Browser</description>
    <language>en</language>
    <item>
      <title>Version {build_version}</title>
      <pubDate>{date}</pubDate>
      <description><![CDATA[{notes}]]></description>
      <enclosure url="{base_url}/{filename}"
                 sparkle:version="{build_version}"
                 sparkle:shortVersionString="{build_version}"
                 sparkle:os="windows"{extra}
                 length="{size}"
                 type="application/octet-stream" />
    </item>
  </channel>
</rss>
"""

DEFAULT_NOTES = """<h2>What changed</h2>
<p>Security fixes from the latest Chromium, plus our own changes. See
the release notes on the project page.</p>"""

_UPDATE_KEY_LINE = re.compile(r'constexpr\s+char\s+kUpdateKey\[\]\s*=\s*"([^"]*)"\s*;')


class SigningError(RuntimeError):
    """The installer could not be signed or its signature did not check out."""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Write the browser's update feed.")
    ap.add_argument("--installer", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument(
        "--base-url",
        required=True,
        help="where this version's installer is hosted, no trailing slash",
    )
    ap.add_argument(
        "--feed-url",
        required=True,
        help=(
            "the fixed address of this file, which must never mention a "
            "version: a browser two releases behind looks here"
        ),
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--notes", default=DEFAULT_NOTES)
    ap.add_argument(
        "--release",
        type=int,
        default=None,
        help=(
            "our release number on top of the Chromium version, the "
            "kBoringRelease the browser was built with. The browser "
            "compares <version>.<release> against the feed, so a fix to "
            "our own code on the same Chromium still counts as newer"
        ),
    )
    ap.add_argument(
        "--require-signature",
        action="store_true",
        help="refuse to write a feed without a signature (release use)",
    )
    signature = ap.add_mutually_exclusive_group()
    signature.add_argument(
        "--ed-signature",
        default=None,
        help="base64 EdDSA signature of the installer, from winsparkle-tool sign",
    )
    signature.add_argument(
        "--private-key-file",
        default=None,
        help=(
            "sign the installer with this EdDSA private key file. Defaults "
            f"to ${KEY_FILE_ENV} when that is set. Never printed"
        ),
    )
    ap.add_argument(
        "--winsparkle-tool",
        default=str(DEFAULT_TOOL),
        help="winsparkle-tool.exe, from get_winsparkle.py",
    )
    ap.add_argument(
        "--public-key",
        default=None,
        help="check the signature against this base64 public key",
    )
    ap.add_argument(
        "--check-key-from",
        default=None,
        metavar="BROWSER_UPDATER_CC",
        help=(
            "check the signature against kUpdateKey in this browser_updater.cc, "
            "the key the browser was built to trust"
        ),
    )
    ap.add_argument(
        "--installer-arguments",
        default=None,
        help="sparkle:installerArguments, for the local update test only",
    )
    return ap


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def decoded_length(value: str) -> int | None:
    """How many bytes a base64 string holds, or None if it is not base64."""
    try:
        return len(base64.b64decode(value.strip(), validate=True))
    except (binascii.Error, ValueError):
        return None


def is_ed25519_public_key(value: str) -> bool:
    return decoded_length(value) == 32


def is_ed25519_signature(value: str) -> bool:
    return decoded_length(value) == 64


def read_update_key(path: str) -> str:
    """kUpdateKey from browser_updater.cc, or raise if it is not a real key."""
    text = Path(path).read_text(encoding="utf-8")
    found = _UPDATE_KEY_LINE.findall(text)
    if len(found) != 1:
        raise SigningError(f"expected one kUpdateKey in {path}, found {len(found)}")
    if not is_ed25519_public_key(found[0]):
        raise SigningError(
            "the browser was built without a real update key (kUpdateKey is "
            "still a placeholder), so no copy of it would ever read this feed"
        )
    return found[0]


def _hide(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


def sign_installer(tool: str, key_file: str, installer: str) -> str:
    """Run winsparkle-tool sign and return the base64 signature.

    The key file's path is kept out of everything this raises or prints.
    """
    if not os.path.isfile(tool):
        raise SigningError(f"no winsparkle-tool at {tool}, run get_winsparkle.py")
    if not os.path.isfile(key_file):
        raise SigningError("the update key file is not there")
    done = subprocess.run(
        [tool, "sign", "--private-key-file", key_file, installer],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        said = _hide((done.stdout + done.stderr).strip(), key_file)
        raise SigningError(f"winsparkle-tool sign failed: {said}")
    signature = done.stdout.strip()
    if not is_ed25519_signature(signature):
        raise SigningError("winsparkle-tool sign did not print an EdDSA signature")
    return signature


def verify_signature(tool: str, public_key: str, signature: str, path: str) -> None:
    """Raise unless the signature is good for this file and this key."""
    if not os.path.isfile(tool):
        raise SigningError(f"no winsparkle-tool at {tool}, run get_winsparkle.py")
    done = subprocess.run(
        [tool, "verify", "--public-key", public_key, "--signature", signature, path],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        said = (done.stdout + done.stderr).strip()
        raise SigningError(
            "the signature does not check out against the key the browser "
            f"trusts, so every copy would refuse this update: {said}"
        )


def render_feed(
    *,
    installer: str,
    version: str,
    base_url: str,
    feed_url: str,
    release: int | None = None,
    ed_signature: str | None = None,
    notes: str = DEFAULT_NOTES,
    installer_arguments: str | None = None,
    now: datetime.datetime | None = None,
) -> str:
    """The appcast XML for one installer."""
    build_version = version if release is None else f"{version}.{release}"
    extra = ""
    if ed_signature:
        extra += "\n                 sparkle:edSignature=" + quoteattr(ed_signature)
    if installer_arguments:
        extra += "\n                 sparkle:installerArguments=" + quoteattr(
            installer_arguments
        )
    now = now or datetime.datetime.now(datetime.UTC)
    return TEMPLATE.format(
        base_url=escape(base_url.rstrip("/")),
        feed_url=escape(feed_url),
        version=escape(version),
        build_version=escape(build_version),
        filename=escape(os.path.basename(installer)),
        size=os.path.getsize(installer),
        extra=extra,
        date=now.strftime("%a, %d %b %Y %H:%M:%S +0000"),
        notes=notes,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    if not os.path.isfile(args.installer):
        print("no installer at " + args.installer, file=sys.stderr)
        return CONFIG_ERROR

    if any(part in args.feed_url for part in args.version.split("-")):
        print(
            "the feed address contains the version, so a browser on an "
            "older version would have nowhere to look: " + args.feed_url,
            file=sys.stderr,
        )
        return CONFIG_ERROR

    key_file = args.private_key_file
    if key_file is None and args.ed_signature is None:
        key_file = os.environ.get(KEY_FILE_ENV) or None

    try:
        public_key = args.public_key
        if args.check_key_from:
            built_in = read_update_key(args.check_key_from)
            if public_key and public_key != built_in:
                raise SigningError(
                    "--public-key is not the key the browser was built with"
                )
            public_key = built_in
        if public_key and not is_ed25519_public_key(public_key):
            raise SigningError("--public-key is not a base64 Ed25519 public key")

        signature = args.ed_signature
        if key_file:
            signature = sign_installer(args.winsparkle_tool, key_file, args.installer)
            print("signed the installer with the update key")
        elif signature and not is_ed25519_signature(signature):
            raise SigningError("--ed-signature is not a base64 EdDSA signature")

        if args.require_signature and not signature:
            raise SigningError(
                "refusing to write an unsigned feed: every browser that reads "
                "it would run an installer nobody vouched for"
            )
        if public_key and not signature:
            raise SigningError("a key to check against, but no signature to check")
        if public_key:
            verify_signature(
                args.winsparkle_tool, public_key, signature, args.installer
            )
            print("the signature checks out against the browser's key")
    except (SigningError, OSError) as error:
        print(str(error), file=sys.stderr)
        return CONFIG_ERROR

    xml = render_feed(
        installer=args.installer,
        version=args.version,
        base_url=args.base_url,
        feed_url=args.feed_url,
        release=args.release,
        ed_signature=signature,
        notes=args.notes,
        installer_arguments=args.installer_arguments,
    )

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(xml)

    print("wrote", args.out)
    print("installer size:", os.path.getsize(args.installer))
    print("sha256:", sha256_of(args.installer))
    if not signature:
        # WinSparkle authenticates an update by the EdDSA signature on
        # the enclosure, not by the installer's Authenticode signature.
        # Without one, anything that can answer for the feed's host can
        # hand the browser a different installer.
        print()
        print("WARNING: no signature, so this feed is unauthenticated.")
        print("See docs/release/UPDATER.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
