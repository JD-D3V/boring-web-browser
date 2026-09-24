#!/usr/bin/env python3
"""Fetch the chromium-web-store release the browser ships with.

chromium-web-store (https://github.com/NeverDecaf/chromium-web-store,
MIT) puts an "Add to Chrome" button back on the Chrome Web Store for
Chromium builds that have no store of their own, and checks the
extensions a person installed from it for updates. The browser installs
it once per profile, from the copy beside chrome.dll. See
components/boring/webstore.

The release .crx is pinned by SHA-256, so a changed or replaced download
is refused rather than shipped. Its licences are pinned the same way,
read from the repository at the release's own commit. Moving to a newer
release means changing VERSION, COMMIT and the hashes here together,
after reading what changed.

Before it ships, two things are changed, and nothing else:
  - update_url is taken out of manifest.json, so the extension is only
    ever updated by a browser release. Left in, NeverDecaf's GitHub
    account could push new code with the "management" permission
    straight into every copy.
  - The update check runs every 300 minutes rather than 60, the same
    5 hours Chromium waits between its own extension update checks.
    Each check sends Google the ID of every store extension installed,
    and once an hour is more often than anyone needs that done.

What lands where:
  boring-core/third_party/chromium-web-store/   download cache, not in git
  boring-core/components/boring/webstore/chromium-web-store/
                                                the changed extension, in
                                                git so a review sees it
  boring-core/components/boring/webstore/chromium_web_store.gni
  boring-core/components/boring/webstore/chromium_web_store_version.h
  boring-core/components/boring/notices/NOTICES-chromium-web-store.txt

Usage:
  python get_chromium_web_store.py           fetch (or reuse the cache)
                                             and write everything above
  python get_chromium_web_store.py --check   say whether what is in the
                                             repository matches what this
                                             script would write; exit 1
                                             if not
"""

import argparse
import base64
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import urllib.request
import zipfile

VERSION = "1.5.5.4"
# The commit the v1.5.5.4 tag points at.
COMMIT = "207fded21203b686896d8ab1b6d1ce818770a0fa"
SHA256 = "63c075b4a25b11af2c536dad191946e8d9547f92d5b6c257b2ce4138d2996f32"
URL = (
    "https://github.com/NeverDecaf/chromium-web-store/releases/download/"
    f"v{VERSION}/Chromium.Web.Store.crx"
)
# The extension ID, fixed by the "key" in its manifest. The browser
# looks for this ID, so a release signed with a different key is
# refused here rather than installed beside the old one.
EXTENSION_ID = "ocaahdebbfolfmndjeplogmgcagdmblk"

# The .crx carries no licence file. These are the repository's, at the
# release commit: the extension's own, and the one for the fromXML
# parser that scripts/util.js embeds.
LICENCES = {
    "LICENSE": "0d0e90c6c9823b67bbc433085a1ad901dc3b736b2c3498b0443b1ad5565c2de6",
    "LICENSE-fromXML": (
        "eb964aa0d87d76a7250d4c459da7072923b8edc8d35850ed2e85d96e517ac113"
    ),
}
RAW = f"https://raw.githubusercontent.com/NeverDecaf/chromium-web-store/{COMMIT}/"

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(CORE, "third_party", "chromium-web-store")
WEBSTORE = os.path.join(CORE, "components", "boring", "webstore")
EXTENSION_DIR_NAME = "chromium-web-store"
EXTENSION_OUT = os.path.join(WEBSTORE, EXTENSION_DIR_NAME)
GNI = os.path.join(WEBSTORE, "chromium_web_store.gni")
HEADER = os.path.join(WEBSTORE, "chromium_web_store_version.h")
NOTICE = os.path.join(
    CORE, "components", "boring", "notices", "NOTICES-chromium-web-store.txt"
)

UPDATE_PERIOD_MINUTES = 300

# Exact text edits, each of which must match exactly once. A release
# that moved any of these fails here instead of shipping half changed.
EDITS = {
    "scripts/util.js": [
        (
            b"update_period_in_minutes: 60,",
            b"update_period_in_minutes: %d," % UPDATE_PERIOD_MINUTES,
        ),
    ],
    "options.html": [
        (
            b"id='update_period_in_minutes' type='number' value='60'/>",
            b"id='update_period_in_minutes' type='number' value='%d'/>"
            % UPDATE_PERIOD_MINUTES,
        ),
    ],
    "scripts/options.js": [
        (
            b"parseInt(e.target.value) || 60;",
            b"parseInt(e.target.value) || %d;" % UPDATE_PERIOD_MINUTES,
        ),
        (
            b'node.value = "60";',
            b'node.value = "%d";' % UPDATE_PERIOD_MINUTES,
        ),
    ],
    "managed_storage.json": [
        (b'"Default is 60"', b'"Default is %d"' % UPDATE_PERIOD_MINUTES),
    ],
}


class CrxError(Exception):
    pass


def _varint(data, pos):
    value = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise CrxError("truncated varint in the CRX header")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 63:
            raise CrxError("varint too long in the CRX header")


def proto_fields(data):
    """The (field number, bytes) pairs of the length-delimited fields.

    Enough protobuf to read a CRX3 header, which holds nothing else.
    Other wire types are skipped.
    """
    pos = 0
    fields = []
    while pos < len(data):
        key, pos = _varint(data, pos)
        number, wire = key >> 3, key & 7
        if wire == 2:
            length, pos = _varint(data, pos)
            if pos + length > len(data):
                raise CrxError("field runs past the end of the CRX header")
            fields.append((number, data[pos : pos + length]))
            pos += length
        elif wire == 0:
            _, pos = _varint(data, pos)
        elif wire == 1:
            pos += 8
        elif wire == 5:
            pos += 4
        else:
            raise CrxError(f"unexpected wire type {wire} in the CRX header")
    return fields


def id_from_key(der):
    """Chromium's extension ID for a public key (SubjectPublicKeyInfo)."""
    digest = hashlib.sha256(der).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in digest)


def read_crx3(data):
    """Returns (zip bytes, crx id, [RSA public keys]) from a CRX3 file.

    The signatures themselves are not checked: the SHA-256 pin on the
    whole file is what says these are the bytes NeverDecaf published.
    This reads the header so a file whose ID does not match its own
    manifest key is caught.
    """
    if len(data) < 12 or data[:4] != b"Cr24":
        raise CrxError("not a CRX file")
    version, header_size = struct.unpack("<II", data[4:12])
    if version != 3:
        raise CrxError(f"CRX version {version}, expected 3")
    header = data[12 : 12 + header_size]
    if len(header) != header_size:
        raise CrxError("CRX header runs past the end of the file")
    rsa_keys = []
    crx_id = None
    for number, value in proto_fields(header):
        if number == 2:  # sha256_with_rsa: AsymmetricKeyProof
            for inner_number, inner in proto_fields(value):
                if inner_number == 1:
                    rsa_keys.append(inner)
        elif number == 10000:  # signed_header_data: SignedData
            for inner_number, inner in proto_fields(value):
                if inner_number == 1:
                    crx_id = inner
    if crx_id is None:
        raise CrxError("CRX header has no crx_id")
    return data[12 + header_size :], crx_id, rsa_keys


def fetch(url, cached, sha256):
    if os.path.exists(cached):
        with open(cached, "rb") as f:
            data = f.read()
    else:
        print("downloading", url)
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        sys.exit(
            f"{os.path.basename(cached)} hash {digest} is not the pinned "
            f"{sha256}, refusing it"
        )
    if not os.path.exists(cached):
        os.makedirs(os.path.dirname(cached), exist_ok=True)
        with open(cached, "wb") as f:
            f.write(data)
    return data


def remove_update_url(manifest_bytes):
    """manifest.json without its update_url line, and nothing else moved."""
    lines = manifest_bytes.splitlines(keepends=True)
    kept = [line for line in lines if not line.lstrip().startswith(b'"update_url"')]
    if len(lines) - len(kept) != 1:
        raise CrxError("expected exactly one update_url line in manifest.json")
    out = b"".join(kept)
    parsed = json.loads(out.decode("utf-8"))
    if "update_url" in parsed:
        raise CrxError("update_url is still in manifest.json")
    return out


def prepare(zip_bytes, crx_id, rsa_keys):
    """The extension's files as shipped: {relative path: bytes}."""
    archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    files = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if name.startswith("/") or ".." in name.split("/"):
            raise CrxError(f"unsafe path in the CRX: {name}")
        files[name] = archive.read(info)

    manifest = json.loads(files["manifest.json"].decode("utf-8"))
    if manifest.get("version") != VERSION:
        raise CrxError(
            f"manifest says version {manifest.get('version')}, expected {VERSION}"
        )
    key = base64.b64decode(manifest["key"])
    if id_from_key(key) != EXTENSION_ID:
        raise CrxError(
            f"manifest key gives ID {id_from_key(key)}, expected {EXTENSION_ID}"
        )
    if crx_id != hashlib.sha256(key).digest()[:16]:
        raise CrxError("the CRX header's crx_id is not the manifest key's")
    if key not in rsa_keys:
        raise CrxError("the manifest key is not one of the CRX signing keys")

    files["manifest.json"] = remove_update_url(files["manifest.json"])
    for name, edits in EDITS.items():
        body = files[name]
        for old, new in edits:
            count = body.count(old)
            if count != 1:
                raise CrxError(f"{name}: expected {old!r} once, found it {count} times")
            body = body.replace(old, new)
        files[name] = body
    return files, manifest["key"]


def gni_text(names):
    lines = [
        "# Generated by boring-core/tools/get_chromium_web_store.py. Do not edit.",
        "",
        f'chromium_web_store_version = "{VERSION}"',
        "",
        "chromium_web_store_files = [",
    ]
    for name in sorted(names):
        lines.append(f'  "{EXTENSION_DIR_NAME}/{name}",')
    lines.append("]")
    return "\n".join(lines) + "\n"


def header_text(public_key):
    return (
        "// Copyright 2026 boring. BSD style license.\n"
        "\n"
        "// Generated by boring-core/tools/get_chromium_web_store.py. Do not\n"
        "// edit: change VERSION there and run it again.\n"
        "\n"
        "#ifndef COMPONENTS_BORING_WEBSTORE_CHROMIUM_WEB_STORE_VERSION_H_\n"
        "#define COMPONENTS_BORING_WEBSTORE_CHROMIUM_WEB_STORE_VERSION_H_\n"
        "\n"
        "namespace boring::webstore {\n"
        "\n"
        f'inline constexpr char kBundledId[] = "{EXTENSION_ID}";\n'
        f'inline constexpr char kBundledVersion[] = "{VERSION}";\n'
        "\n"
        '// The manifest\'s "key", base64 DER. It fixes the ID above.\n'
        "inline constexpr char kBundledPublicKey[] =\n"
        + "".join(
            f'    "{public_key[i : i + 64]}"\n' for i in range(0, len(public_key), 64)
        ).rstrip("\n")
        + ";\n"
        "\n"
        "}  // namespace boring::webstore\n"
        "\n"
        "#endif  // COMPONENTS_BORING_WEBSTORE_CHROMIUM_WEB_STORE_VERSION_H_\n"
    )


def notice_text(licences):
    parts = [
        f"Chromium Web Store {VERSION}, by NeverDecaf\n"
        "https://github.com/NeverDecaf/chromium-web-store\n"
        "Installed by Boring Browser so extensions can be added from the\n"
        "Chrome Web Store. Changed from the release: no update_url, and\n"
        f"store update checks every {UPDATE_PERIOD_MINUTES} minutes instead of 60.\n"
    ]
    for name in LICENCES:
        parts.append(f"\n==== {name} ====\n\n")
        parts.append(licences[name].decode("utf-8").replace("\r\n", "\n"))
        if not parts[-1].endswith("\n"):
            parts.append("\n")
    return "".join(parts)


def outputs(crx_data, licences):
    """Everything this script writes: {absolute path: bytes}."""
    zip_bytes, crx_id, rsa_keys = read_crx3(crx_data)
    files, public_key = prepare(zip_bytes, crx_id, rsa_keys)
    # The licences travel with the extension too, so the copy inside a
    # profile's Extensions folder still says whose it is.
    for name, body in licences.items():
        files[name] = body
    result = {}
    for name, body in files.items():
        result[os.path.join(EXTENSION_OUT, *name.split("/"))] = body
    result[GNI] = gni_text(files).encode("utf-8")
    result[HEADER] = header_text(public_key).encode("utf-8")
    result[NOTICE] = notice_text(licences).encode("utf-8")
    return result


def same_content(path, current, wanted):
    """Byte for byte, except that text may have gained or lost a CR.

    git with core.autocrlf rewrites line endings on checkout, which
    changes nothing Chromium cares about. Images must match exactly.
    """
    if current is None:
        return False
    if path.endswith(".png"):
        return current == wanted
    return current.replace(b"\r\n", b"\n") == wanted.replace(b"\r\n", b"\n")


def existing_extension_files():
    found = set()
    for root, _dirs, names in os.walk(EXTENSION_OUT):
        for name in names:
            found.add(os.path.join(root, name))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    crx = fetch(URL, os.path.join(CACHE, f"Chromium.Web.Store-{VERSION}.crx"), SHA256)
    licences = {
        name: fetch(RAW + name, os.path.join(CACHE, name), digest)
        for name, digest in LICENCES.items()
    }
    try:
        wanted = outputs(crx, licences)
    except CrxError as e:
        sys.exit(f"chromium-web-store {VERSION}: {e}")

    stale = existing_extension_files() - set(wanted)
    if args.check:
        wrong = []
        for path, body in wanted.items():
            current = None
            if os.path.exists(path):
                with open(path, "rb") as f:
                    current = f.read()
            if not same_content(path, current, body):
                wrong.append(path)
        wrong.extend(sorted(stale))
        for path in wrong:
            print("out of date:", os.path.relpath(path, CORE))
        if wrong:
            return 1
        print(f"chromium-web-store {VERSION} is up to date")
        return 0

    if os.path.isdir(EXTENSION_OUT):
        shutil.rmtree(EXTENSION_OUT)
    for path, body in sorted(wanted.items()):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)
    print(f"wrote chromium-web-store {VERSION}: {len(wanted)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
