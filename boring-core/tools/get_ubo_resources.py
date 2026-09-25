#!/usr/bin/env python3
"""Build resources.json, the scriptlets and $redirect stubs from uBO.

Filters such as example.com##+js(set-constant, ...) and
||ads.example/x.js$redirect=noop.js name a resource. The engine
(adblock-rust 0.13.3) needs those resources handed to it as a JSON
array of its Resource type:

  {"name": "set-constant.js", "aliases": ["set.js"],
   "kind": {"mime": "application/javascript"},
   "content": "<base64>", "dependencies": ["safe-self.fn"],
   "permission": 1}

This takes them from one pinned, tagged uBlock Origin release, checked
against a SHA-256 of its source tarball and the commit it was cut
from, so the same build always ships the same code:

  - scriptlets from src/js/resources/scriptlets.js. The modules are ES
    modules, so node imports them (ubo_resources_dump.mjs) and each
    function's source is kept exactly as uBO keeps it, fn.toString().
    Names ending ".fn" are helpers other scriptlets depend on
    (fn/javascript); names ending ".js" are the scriptlets filters call.
    requiresTrust becomes permission bit TRUSTED_PERMISSION, so only a
    list loaded with that bit (ubo.txt) can call them.
  - redirect resources from src/web_accessible_resources, indexed by
    src/js/redirect-resources.js, the same mapping adblock-rust's own
    resource_assembler.rs reads. Entries with "params" are skipped, as
    resource_assembler.rs skips them.

Anything unexpected in uBO's format stops the run: an unknown field, a
scriptlet that is not a named function, a dependency that is not
there, a name used twice. adblock-rust drops a clashing resource
without a word, so a silent mistake here would ship a scriptlet that
never runs.

The output is GPL-3.0 code by Raymond Hill and the uBlock Origin
contributors. It ships unchanged in meaning, as a separate file, with
NOTICES-uBlock-resources.txt beside chrome.exe carrying the licence,
the tag, the commit and where the source is.

Needs node (v22 is what this was written against).

Usage: python get_ubo_resources.py [--out DIR] [--node PATH]
"""

import argparse
import base64
import dataclasses
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from get_filterlists import (
    DEFAULT_OUT,
    FeedError,
    check_gpl3,
    fetch_url,
    read_manifest,
    utc_stamp,
    write_text,
)

# The release. Bump all four together, after reading what changed in
# src/js/resources and src/web_accessible_resources since the last one.
# 1.75.0 is the latest release not marked pre-release on 2026-09-24.
UBO_TAG = "1.75.0"
UBO_COMMIT = "21f0e686506bb21b514b451c8c6cb9bf8c82d232"
TARBALL_URL = f"https://codeload.github.com/gorhill/uBlock/tar.gz/refs/tags/{UBO_TAG}"
TARBALL_SHA256 = "a518c7d6e6b3f81d1a738befeb617abba59f93bd6b1e626da079a1003e9db52b"
SOURCE_URL = f"https://github.com/gorhill/uBlock/tree/{UBO_COMMIT}"

# The folder every path in the tarball starts with.
TARBALL_ROOT = f"uBlock-{UBO_TAG}"

# The bit a trusted scriptlet needs. The engine has to load ubo.txt
# with this bit set (the plan calls it trusted) and easylist.txt,
# cookies.txt and the regional lists without it.
TRUSTED_PERMISSION = 0b00000001

# Measured at 1.75.0: 151 scriptlet entries (98 scriptlets, 53 helpers,
# 33 needing trust) and 47 redirect entries, one with params. Floors a
# little under that catch a release that moved them somewhere else.
MIN_SCRIPTLETS = 120
MIN_REDIRECTS = 35

# What smoke tests and common filters rely on. Missing any of these
# means the format moved, not that uBO dropped them.
REQUIRED_NAMES = (
    "set-constant.js",
    "json-prune.js",
    "abort-on-property-read.js",
    "abort-current-script.js",
    "safe-self.fn",
    "noop.js",
    "noop.txt",
    "noop.html",
    "1x1.gif",
    "noop-0.1s.mp3",
    "google-analytics_analytics.js",
    "googlesyndication_adsbygoogle.js",
)

# Fields a builtinScriptlets entry may have. "world" is uBO's choice of
# where to run a scriptlet; adblock-rust has no such field and injects
# everything into the page, which is where the others run anyway.
# "priority" orders injection in uBO; adblock-rust has no ordering.
SCRIPTLET_FIELDS = {
    "name",
    "aliases",
    "fn",
    "dependencies",
    "requiresTrust",
    "world",
    "priority",
}
REDIRECT_FIELDS = {"alias", "data", "params", "requiresTrust"}

# adblock-rust calls a scriptlet by the name of its function
# (resource_storage.rs, extract_function_name), so a ".js" scriptlet
# that is not a plain named function would be pasted in as a template.
FUNCTION_RE = re.compile(r"^function\s+([^\(\)\{\}\s]+)\s*\(")

# MIME types by file ending, as adblock-rust's MimeType::from_extension.
MIME_BY_EXTENSION = {
    "css": "text/css",
    "gif": "image/gif",
    "html": "text/html",
    "js": "application/javascript",
    "json": "application/json",
    "mp3": "audio/mp3",
    "mp4": "video/mp4",
    "png": "image/png",
    "txt": "text/plain",
    "xml": "text/xml",
}

MAX_TARBALL_BYTES = 64 * 1024 * 1024
NODE_TIMEOUT_SECONDS = 120

DEFAULT_NODE = r"C:\Program Files\nodejs\node.exe"
HELPER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "ubo_resources_dump.mjs"
)

NOTICE_NAME = "NOTICES-uBlock-resources.txt"


class FormatError(Exception):
    """uBO's resources are not in the shape this tool was written for."""


def verify_tarball(data: bytes) -> None:
    """FeedError unless this is the pinned tarball, byte for byte."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != TARBALL_SHA256:
        raise FeedError(f"tarball SHA-256 is {digest}, pinned {TARBALL_SHA256}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        # git archive writes the commit into the tarball's pax header.
        commit = tar.pax_headers.get("comment")
    if commit != UBO_COMMIT:
        raise FeedError(f"tarball says commit {commit}, pinned {UBO_COMMIT}")


def extract(data: bytes, dest: str) -> str:
    """Unpacks the parts we read into dest and returns the source root.

    Only regular files under src/js, src/web_accessible_resources and
    the licence, and only paths that stay inside dest.
    """
    wanted = (
        f"{TARBALL_ROOT}/src/js/",
        f"{TARBALL_ROOT}/src/web_accessible_resources/",
    )
    licence = f"{TARBALL_ROOT}/LICENSE.txt"
    root = os.path.realpath(dest)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if not (member.name.startswith(wanted) or member.name == licence):
                continue
            target = os.path.realpath(os.path.join(root, member.name))
            if not target.startswith(root + os.sep):
                raise FeedError(f"tarball path escapes: {member.name}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with tar.extractfile(member) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return os.path.join(root, TARBALL_ROOT)


def dump_with_node(source_root: str, node: str) -> dict:
    """What uBO's modules declare, read by node. FormatError if not usable."""
    try:
        done = subprocess.run(
            [node, HELPER, source_root],
            capture_output=True,
            timeout=NODE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as e:
        raise FormatError(f"node not found at {node}") from e
    if done.returncode != 0:
        message = done.stderr.decode("utf-8", "replace").strip()
        raise FormatError(f"node could not load uBO's modules: {message}")
    try:
        dumped = json.loads(done.stdout.decode("utf-8"))
    except ValueError as e:
        raise FormatError("node did not print JSON") from e
    if not isinstance(dumped, dict) or not isinstance(dumped.get("scriptlets"), list):
        raise FormatError("node printed something other than the dump")
    return dumped


def string_list(value, what: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    raise FormatError(f"{what} is not a string or a list of strings")


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def resource(name, aliases, mime, data: bytes, dependencies=(), permission=0):
    """One adblock-rust Resource, fields as serde writes them."""
    entry = {
        "name": name,
        "aliases": list(aliases),
        "kind": {"mime": mime},
        "content": b64(data),
    }
    # serde skips these when empty or zero, so do the same.
    if dependencies:
        entry["dependencies"] = list(dependencies)
    if permission:
        entry["permission"] = permission
    return entry


def scriptlet_resources(entries: list) -> list[dict]:
    """Resources for uBO's builtinScriptlets entries."""
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise FormatError("a scriptlet entry is not an object")
        name = entry.get("name")
        if not isinstance(name, str) or not isinstance(entry.get("fn"), str):
            raise FormatError(f"scriptlet {name!r} has no name or no function")
        unknown = set(entry) - SCRIPTLET_FIELDS
        if unknown:
            raise FormatError(f"scriptlet {name} has new fields {sorted(unknown)}")
        if name.endswith(".fn"):
            mime = "fn/javascript"
        elif name.endswith(".js"):
            mime = "application/javascript"
            if not FUNCTION_RE.match(entry["fn"]):
                raise FormatError(f"scriptlet {name} is not a named function")
        else:
            raise FormatError(f"scriptlet {name} ends in neither .js nor .fn")
        trust = entry.get("requiresTrust", False)
        if not isinstance(trust, bool):
            raise FormatError(f"scriptlet {name}: requiresTrust is not true or false")
        out.append(
            resource(
                name,
                string_list(entry.get("aliases"), f"{name} aliases"),
                mime,
                entry["fn"].encode("utf-8"),
                string_list(entry.get("dependencies"), f"{name} dependencies"),
                TRUSTED_PERMISSION if trust else 0,
            )
        )
    return out


def redirect_resources(entries: list, war_dir: str) -> tuple[list[dict], list[str]]:
    """Resources for redirect-resources.js, and the names skipped."""
    out = []
    skipped = []
    for item in entries:
        if not (isinstance(item, list) and len(item) == 2 and isinstance(item[0], str)):
            raise FormatError("a redirect entry is not [name, details]")
        name, details = item
        if not isinstance(details, dict):
            raise FormatError(f"redirect {name}: details are not an object")
        unknown = set(details) - REDIRECT_FIELDS
        if unknown:
            raise FormatError(f"redirect {name} has new fields {sorted(unknown)}")
        if "params" in details:
            # A resource that takes parameters (click2load.html) is
            # skipped, as adblock-rust's resource_assembler.rs does.
            skipped.append(name)
            continue
        if os.path.basename(name) != name:
            raise FormatError(f"redirect {name} is not a plain file name")
        path = os.path.join(war_dir, name)
        if not os.path.isfile(path):
            raise FormatError(f"redirect {name} has no file")
        with open(path, "rb") as f:
            data = f.read()
        extension = name.rsplit(".", 1)[-1] if "." in name else ""
        mime = MIME_BY_EXTENSION.get(extension, "application/octet-stream")
        if mime in ("application/javascript", "text/html", "text/plain"):
            # resource_assembler.rs drops carriage returns from text.
            data = data.decode("utf-8").replace("\r", "").encode("utf-8")
        trust = details.get("requiresTrust", False)
        out.append(
            resource(
                name,
                string_list(details.get("alias"), f"{name} alias"),
                mime,
                data,
                permission=TRUSTED_PERMISSION if trust is True else 0,
            )
        )
    return out, skipped


def check_resources(resources: list[dict]) -> None:
    """FormatError unless the set is whole and every name is unique."""
    seen: set[str] = set()
    for entry in resources:
        for ident in [entry["name"], *entry["aliases"]]:
            if ident in seen:
                raise FormatError(f"{ident} is used twice")
            seen.add(ident)
    names = {entry["name"] for entry in resources}
    for entry in resources:
        for dependency in entry.get("dependencies", []):
            if dependency not in names:
                raise FormatError(f"{entry['name']} needs missing {dependency}")
    for name in REQUIRED_NAMES:
        if name not in names:
            raise FormatError(f"{name} is missing")


def build_resources(dumped: dict, war_dir: str) -> tuple[list[dict], int, list[str]]:
    """Every resource, how many are scriptlets, and redirects skipped."""
    scriptlets = scriptlet_resources(dumped.get("scriptlets", []))
    redirects, skipped = redirect_resources(dumped.get("redirects", []), war_dir)
    if len(scriptlets) < MIN_SCRIPTLETS:
        raise FormatError(f"only {len(scriptlets)} scriptlets")
    if len(redirects) < MIN_REDIRECTS:
        raise FormatError(f"only {len(redirects)} redirect resources")
    resources = scriptlets + redirects
    check_resources(resources)
    return resources, len(scriptlets), skipped


def notice_text(licence_text: str, fetched_at: str, sha256: str, counts) -> str:
    scriptlets, redirects = counts
    lines = [
        "uBlock Origin scriptlets and redirect resources",
        "===============================================",
        "",
        "boring\\resources.json, in the version folder beside chrome.dll,",
        f"holds {scriptlets} scriptlets and helpers and {redirects} redirect",
        "resources from uBlock Origin, by Raymond Hill and the uBlock",
        "Origin contributors.",
        "",
        f"Release: {UBO_TAG}",
        f"Commit:  {UBO_COMMIT}",
        f"Source:  {SOURCE_URL}",
        f"Tarball: {TARBALL_URL}",
        f"         SHA-256 {TARBALL_SHA256}",
        f"Built:   {fetched_at}, resources.json SHA-256 {sha256}",
        "",
        "Taken from src/js/resources (each scriptlet's function source, as",
        "uBlock Origin itself reads it) and src/web_accessible_resources",
        "(files unchanged, carriage returns removed from text ones), and",
        "stored base64 encoded in the JSON form the adblock-rust engine",
        "reads. The code itself is not changed.",
        "",
        "Licence: GNU General Public License, version 3 or (at your",
        "option) any later version, as the source files say. The full",
        "text follows, from LICENSE.txt in the same release.",
        "",
        "-" * 72,
        "",
        licence_text.rstrip(),
    ]
    return "\n".join(lines) + "\n"


@dataclasses.dataclass
class Built:
    """resources.json's content and what went into it."""

    resources: list[dict]
    scriptlets: int
    skipped: list[str]
    licence_text: str
    tarball_bytes: int

    @property
    def redirects(self) -> int:
        return len(self.resources) - self.scriptlets

    def json_text(self) -> str:
        return json.dumps(self.resources, separators=(",", ":")) + "\n"


def build(fetch=fetch_url, node: str = DEFAULT_NODE) -> Built:
    """Fetches the pinned release and builds the resources from it.

    Raises FeedError or FormatError, so nothing half made is returned.
    """
    fetched = fetch(TARBALL_URL)
    if len(fetched.data) > MAX_TARBALL_BYTES:
        raise FeedError("tarball is too big")
    verify_tarball(fetched.data)
    try:
        with tempfile.TemporaryDirectory(prefix="ubo-src-") as work:
            root = extract(fetched.data, work)
            with open(os.path.join(root, "LICENSE.txt"), encoding="utf-8") as f:
                licence_text = f.read()
            check_gpl3(licence_text)
            dumped = dump_with_node(root, node)
            resources, scriptlets, skipped = build_resources(
                dumped, os.path.join(root, "src", "web_accessible_resources")
            )
    except (OSError, tarfile.TarError) as e:
        raise FeedError(f"{type(e).__name__}: {e}") from e
    return Built(resources, scriptlets, skipped, licence_text, len(fetched.data))


def default_node() -> str:
    return shutil.which("node") or DEFAULT_NODE


def main(argv: list[str] | None = None, fetch=fetch_url, now=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--node", default=default_node())
    args = ap.parse_args(argv)

    fetched_at = utc_stamp(now or datetime.datetime.now(datetime.UTC))
    try:
        built = build(fetch, args.node)
    except (FeedError, FormatError) as e:
        print("not writing resources.json:", e)
        return 1

    resources, scriptlets, redirects = (
        built.resources,
        built.scriptlets,
        built.redirects,
    )
    dest_dir = os.path.join(args.out, "boring")
    out_path = os.path.join(dest_dir, "resources.json")
    sha256 = write_text(out_path, built.json_text())
    write_text(
        os.path.join(args.out, NOTICE_NAME),
        notice_text(built.licence_text, fetched_at, sha256, (scriptlets, redirects)),
    )

    manifest_path = os.path.join(dest_dir, "sources.json")
    manifest = read_manifest(manifest_path)
    lists = manifest.get("lists") if isinstance(manifest.get("lists"), dict) else {}
    lists["resources.json"] = {
        "sha256": sha256,
        "bytes": os.path.getsize(out_path),
        "resources": len(resources),
        "fetched": fetched_at,
        "licence": "GPL-3.0-or-later",
        "licence_url": f"https://github.com/gorhill/uBlock/blob/{UBO_COMMIT}/LICENSE.txt",
        "notice": NOTICE_NAME,
        "sources": [
            {
                "url": TARBALL_URL,
                "bytes": built.tarball_bytes,
                "sha256": TARBALL_SHA256,
                "tag": UBO_TAG,
                "commit": UBO_COMMIT,
            }
        ],
    }
    manifest["lists"] = dict(sorted(lists.items()))
    write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")

    print(f"uBlock Origin {UBO_TAG} ({UBO_COMMIT[:12]})")
    print(f"  {scriptlets} scriptlets and helpers, {redirects} redirect resources")
    for name in built.skipped:
        print(f"  skipped {name}: takes parameters")
    print("wrote", out_path, "SHA-256", sha256)
    return 0


if __name__ == "__main__":
    sys.exit(main())
