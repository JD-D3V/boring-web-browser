#!/usr/bin/env python3
"""Build the list bundle the browser downloads to keep its blocking fresh.

The filter list is baked in when the browser is built, so on an installed
copy it only gets older. This writes the same file plus a small signed
manifest into a folder, ready to be uploaded to the release host.

No scam blocklist is published. No feed we use grants permission to
redistribute its data this way, so v1 ships and publishes none; see
get_scamlist.py. The browser refuses a scam list offered by an update
feed for the same reason, so publishing one would not even take effect. The browser reads the manifest, checks the
signature, compares it with what it already has, and downloads only the
files that changed.

The manifest looks like this:

    {
      "version": 260,
      "updated": "2026-09-17",
      "degraded": false,
      "files": [{"name": "easylist.txt", "size": 123, "sha256": "...",
                 "entries": 138411}],
      "sources": [{"list": "easylist.txt", "name": "easylist", "ok": true,
                   "http_status": 200, "bytes": 2166195, "entries": 82279,
                   "reason": null}]
    }

The version only ever goes up, so an older bundle served from a cache
can never talk a browser into going backwards.

Beside it sits lists.json.sig, an ECDSA P-256 signature over the exact
bytes of lists.json. Hashes in the manifest catch a file that arrived
corrupted; they say nothing about who wrote the manifest. Anyone who can
replace the files on the release host can replace the manifest too, so
the browser only trusts a manifest signed by a key compiled into it.

Nothing is published unless every list validated. A refusal leaves the
previous bundle exactly as it was and exits non-zero.

Usage:
  python publish_lists.py --out DIR [--previous DIR] [--version N]
                          [--sign-key PEM | --unsigned]
  python publish_lists.py --gen-test-key [DIR]

The signing key is never in the repo. Give it as --sign-key PATH or in
the BORING_LIST_SIGNING_KEY environment variable as PEM text.
"""

import argparse
import base64
import dataclasses
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

from get_filterlists import (
    BuildResult,
    build_filter_list,
    fetch_url,
    parse_filter_list,
)
from get_scamlist import count_real_hosts

# The version is days since this date, which keeps it going up on its
# own without anything having to remember the last one.
VERSION_EPOCH = datetime.date(2026, 1, 1)

MANIFEST_NAME = "lists.json"
SIGNATURE_NAME = "lists.json.sig"

SIGNATURE_ALG = "ecdsa-p256-sha256"
SIGNING_KEY_ENV = "BORING_LIST_SIGNING_KEY"

# Where --gen-test-key puts its throwaway key. Off the repo on purpose.
DEFAULT_TEST_KEY_DIR = r"E:\tmp\boring-list-test-key"

# DER object identifiers inside a SubjectPublicKeyInfo: id-ecPublicKey
# and prime256v1. Checking for both is a cheap way to be sure the key
# handed to us is the curve the browser will try to verify with,
# instead of finding out when every installed browser rejects a bundle.
OID_EC_PUBLIC_KEY = bytes.fromhex("2a8648ce3d0201")
OID_PRIME256V1 = bytes.fromhex("2a8648ce3d030107")


@dataclasses.dataclass(frozen=True)
class Policy:
    """When a list is allowed out, and why those numbers.

    All three floors come from what the real feeds held on 2026-09-19,
    measured by fetching each one once:

      easylist      2,166,195 bytes    82,279 rules
      easyprivacy   1,504,162 bytes    56,132 rules
      urlhaus          11,786 bytes       390 hosts
      openphish        16,048 bytes       234 hosts

    Combined, that is 138,411 filter rules and 624 scam hosts.

    Nothing here is a large round number picked for comfort. A floor
    that is too high refuses a legitimate quiet week and leaves people
    on last month's list, which is its own failure.
    """

    name: str
    # Enough coverage to publish when there is no previous bundle to
    # compare against, so a first ever run cannot ship an empty list.
    first_run_floor: int
    # Smallest share of the previous bundle we accept when every
    # source answered. A drop past this is the data being wrong, not
    # the week being quiet.
    healthy_shrink_floor: float
    # The same when a source failed, which legitimately costs coverage.
    degraded_shrink_floor: float


# Not published, and kept only so a previous bundle that still holds a
# scamlist.txt can be read and counted correctly.
SCAM_POLICY = Policy(
    name="scamlist.txt",
    # The smaller of the two scam feeds held 234 hosts, so one healthy
    # source clears 100 twice over while a mostly broken run does not.
    first_run_floor=100,
    # URLhaus is a rolling window of malware hosts that are live right
    # now and is about 60 per cent of the union, so week to week churn
    # is real and large. Halving is the most an ordinary week should
    # manage; past that something is wrong with the data.
    healthy_shrink_floor=0.50,
    # The two feeds did not overlap at all on 2026-09-19: 390 plus 234
    # made a union of 624. Losing URLhaus leaves 234 of 624, so 37.5
    # per cent is the worst a single source outage explains. 35 sits
    # just under that, which keeps a real outage publishable.
    degraded_shrink_floor=0.35,
)

FILTER_POLICY = Policy(
    name="easylist.txt",
    # The smaller filter source held 56,132 rules, so one healthy
    # source clears 10,000 five times over.
    first_run_floor=10_000,
    # EasyList and EasyPrivacy are curated by hand and move by small
    # percentages. With both sources healthy a quarter of the rules
    # disappearing is already not a normal week.
    healthy_shrink_floor=0.75,
    # Losing EasyList leaves EasyPrivacy's 56,132 of 138,411, so 41 per
    # cent is the worst a single source outage explains.
    degraded_shrink_floor=0.35,
)


class RefusedError(Exception):
    """The bundle is not safe to publish. The previous one stays put."""


def version_for(day: datetime.date) -> int:
    return (day - VERSION_EPOCH).days


def entries_in(name: str, text: str) -> int:
    """Real entries in a list's text, whichever list it is."""
    if name == SCAM_POLICY.name:
        return count_real_hosts(text)
    return parse_filter_list(text)


def read_previous(directory: str | None) -> dict | None:
    """The manifest of the bundle already published, or None.

    A bundle we cannot read is treated as no bundle rather than as a
    reason to stop: a first run and an unreadable leftover should both
    end with a good bundle on disk.
    """
    if not directory:
        return None
    path = os.path.join(directory, MANIFEST_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) else None


def previous_entries(manifest: dict | None, directory: str, name: str) -> int | None:
    """How many entries the previous bundle held for one list, if we can tell.

    Prefers the count the manifest wrote down, and falls back to
    counting the file itself, which is what a bundle published before
    this tool recorded counts looks like. None means unknown, and an
    unknown previous size cannot be shrunk from.
    """
    for entry in (manifest or {}).get("files", []):
        if isinstance(entry, dict) and entry.get("name") == name:
            count = entry.get("entries")
            if isinstance(count, int) and count >= 0:
                return count
    try:
        with open(os.path.join(directory, name), encoding="utf-8") as f:
            return entries_in(name, f.read())
    except Exception:
        # Any unreadable or unparseable leftover is simply not evidence.
        return None


def check_coverage(policy: Policy, built: BuildResult, previous: int | None) -> None:
    """Applies the publication policy to one list, or raises RefusedError."""
    if not built.healthy:
        raise RefusedError(
            f"{policy.name}: every source failed ({built.describe_failures()})"
        )

    if previous is None:
        if built.entries < policy.first_run_floor:
            raise RefusedError(
                f"{policy.name}: only {built.entries} entries and no previous "
                f"bundle to compare against, floor is {policy.first_run_floor}"
            )
        return

    floor_share = (
        policy.degraded_shrink_floor if built.degraded else policy.healthy_shrink_floor
    )
    floor = int(previous * floor_share)
    if built.entries < floor:
        raise RefusedError(
            f"{policy.name}: {built.entries} entries against {previous} last "
            f"time, below the {floor_share:.0%} floor of {floor}"
            + (f" ({built.describe_failures()})" if built.degraded else "")
        )


def source_rows(policy: Policy, built: BuildResult) -> list[dict]:
    """Per source status for the manifest, named by the list it feeds."""
    return [{"list": policy.name, **status.as_dict()} for status in built.sources]


def openssl(args: list[str], stdin: bytes | None = None) -> bytes:
    """Runs openssl and returns stdout. Raises RefusedError if it cannot."""
    try:
        done = subprocess.run(
            ["openssl", *args],
            input=stdin,
            capture_output=True,
            check=True,
        )
    except FileNotFoundError as e:
        raise RefusedError(
            "openssl is not on PATH, so the manifest cannot be signed. "
            "Install it, or pass --unsigned if you understand that the "
            "browser will reject the bundle."
        ) from e
    except subprocess.CalledProcessError as e:
        message = e.stderr.decode("utf-8", "replace").strip()
        raise RefusedError(f"openssl {args[0]} failed: {message}") from e
    return done.stdout


def key_id_for(spki_der: bytes) -> str:
    """The name a key goes by: the first 16 hex of the SHA-256 of its SPKI.

    Short enough to read in a manifest and long enough that nobody is
    going to collide with it. It exists so a key can be rotated and so
    a browser can say which key it trusted.
    """
    return hashlib.sha256(spki_der).hexdigest()[:16]


def public_key_der(key_pem_path: str) -> bytes:
    """The signer's SubjectPublicKeyInfo, checked to be the curve we use."""
    spki = openssl(["pkey", "-in", key_pem_path, "-pubout", "-outform", "DER"])
    if OID_EC_PUBLIC_KEY not in spki or OID_PRIME256V1 not in spki:
        raise RefusedError("the signing key is not an ECDSA P-256 key")
    return spki


def sign_manifest(manifest_path: str, key_pem_path: str, work: str) -> dict:
    """Signs the manifest's bytes on disk and returns the signature file.

    The signature covers the file exactly as written, not a re-encoded
    copy of the same values, so there is no way for a reader and this
    tool to disagree about what was signed.
    """
    spki = public_key_der(key_pem_path)
    signature = openssl(["dgst", "-sha256", "-sign", key_pem_path, manifest_path])

    # Verify what we just produced before anyone relies on it. A wrong
    # key file or an openssl that signed with a different digest fails
    # here rather than on every installed browser.
    pub_pem = os.path.join(work, "signer-pub.pem")
    sig_der = os.path.join(work, "manifest.sig.der")
    with open(pub_pem, "wb") as f:
        f.write(openssl(["pkey", "-in", key_pem_path, "-pubout"]))
    with open(sig_der, "wb") as f:
        f.write(signature)
    openssl(
        [
            "dgst",
            "-sha256",
            "-verify",
            pub_pem,
            "-signature",
            sig_der,
            manifest_path,
        ]
    )

    return {
        "alg": SIGNATURE_ALG,
        "key": key_id_for(spki),
        "sig": base64.b64encode(signature).decode("ascii"),
    }


def resolve_key(args, work: str) -> str:
    """The path to the signing key, writing the one from the environment out.

    The key is never in the repo. When it arrives as PEM in an
    environment variable it is written into the working folder, which
    is removed whatever happens.
    """
    if args.sign_key:
        if not os.path.isfile(args.sign_key):
            raise RefusedError(f"no signing key at {args.sign_key}")
        return args.sign_key

    pem = os.environ.get(SIGNING_KEY_ENV)
    if not pem:
        raise RefusedError(
            f"no signing key: pass --sign-key PATH or set {SIGNING_KEY_ENV} "
            "to the key's PEM text. Pass --unsigned to publish without one."
        )
    path = os.path.join(work, "signing-key.pem")
    # Readable only by this user. The folder goes away at the end, but
    # the key should not be readable by anyone else while it is there.
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(pem if pem.endswith("\n") else pem + "\n")
    return path


def gen_test_key(directory: str) -> int:
    """Writes a throwaway P-256 keypair for local tests."""
    os.makedirs(directory, exist_ok=True)
    key_path = os.path.join(directory, "key.pem")
    fd = os.open(key_path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(openssl(["ecparam", "-name", "prime256v1", "-genkey", "-noout"]))

    spki = public_key_der(key_path)
    spki_path = os.path.join(directory, "pub.der")
    with open(spki_path, "wb") as f:
        f.write(spki)

    print("wrote a test signing key:")
    print("  private key ", key_path)
    print("  public key  ", spki_path)
    print("  key id      ", key_id_for(spki))
    print("  base64 SPKI ", base64.b64encode(spki).decode("ascii"))
    print()
    print("THIS KEY IS FOR LOCAL TESTING ONLY.")
    print("It is generated on this machine with no protection of any kind.")
    print("Never present it as a publisher key, never sign a real bundle")
    print("with it, and never install it into any trust store.")
    return 0


def write_file(directory: str, name: str, text: str, entries: int) -> dict:
    """Writes one list and returns its entry for the manifest."""
    data = text.encode("utf-8")
    with open(os.path.join(directory, name), "wb") as f:
        f.write(data)
    return {
        "name": name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "entries": entries,
    }


def confirm_on_disk(directory: str, files: list[dict]) -> None:
    """Re-reads what was written and checks it against the manifest.

    The manifest is what the browser trusts, so the hashes in it have
    to describe the bytes that actually landed, not the string we meant
    to write.
    """
    for entry in files:
        with open(os.path.join(directory, entry["name"]), "rb") as f:
            data = f.read()
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != entry["size"] or digest != entry["sha256"]:
            raise RefusedError(f"{entry['name']} on disk is not what we wrote")


def move_into_place(staging: str, out: str, names: list[str]) -> None:
    """Puts a validated bundle in place, one whole file at a time.

    The manifest goes last. A browser that reads the folder halfway
    through gets the old manifest, whose hashes will not match the new
    lists, and a list whose hash does not match is refused. Every order
    has a losing case; this is the one that fails closed.
    """
    os.makedirs(out, exist_ok=True)
    for name in names:
        source = os.path.join(staging, name)
        if not os.path.exists(source):
            continue
        target = os.path.join(out, name)
        pending = target + ".new"
        shutil.copyfile(source, pending)
        os.replace(pending, target)


def build_bundle(args, fetch_filters, fetch_scam=None) -> int:
    """Builds, validates and publishes. Raises RefusedError to stop.

    fetch_scam is accepted and ignored: no scam list is published, and
    keeping the parameter means a caller that still passes one gets the
    same refusal rather than a TypeError.
    """
    previous_dir = args.previous or args.out
    previous = read_previous(previous_dir)

    filters = build_filter_list(fetch=fetch_filters)

    for status in filters.sources:
        state = (
            f"{status.entries} entries" if status.ok else f"FAILED, {status.reason}"
        )
        print(f"  {FILTER_POLICY.name} {status.name}: {state}")

    check_coverage(
        FILTER_POLICY,
        filters,
        previous_entries(previous, previous_dir, FILTER_POLICY.name),
    )

    today = datetime.date.today()
    version = args.version if args.version is not None else version_for(today)
    previous_version = (previous or {}).get("version")
    if isinstance(previous_version, int) and version < previous_version:
        raise RefusedError(
            f"version {version} is below the published {previous_version}; "
            "the browser would ignore it. Check the clock, or pass --version."
        )

    degraded = filters.degraded

    work = tempfile.mkdtemp(prefix="boring-lists-")
    try:
        staging = os.path.join(work, "bundle")
        os.makedirs(staging)

        files = [
            write_file(staging, FILTER_POLICY.name, filters.text, filters.entries),
        ]
        confirm_on_disk(staging, files)

        manifest = {
            "version": version,
            "updated": today.isoformat(),
            "degraded": degraded,
            "files": files,
            "sources": source_rows(FILTER_POLICY, filters),
        }
        manifest_path = os.path.join(staging, MANIFEST_NAME)
        with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")

        names = [entry["name"] for entry in files]
        if args.unsigned:
            print()
            print("WARNING: publishing without a signature.")
            print("The browser only trusts a manifest signed by a key it was")
            print("built with, so it will reject this bundle and keep the")
            print("lists it already has. Use this for local testing only.")
        else:
            signature = sign_manifest(manifest_path, resolve_key(args, work), work)
            with open(
                os.path.join(staging, SIGNATURE_NAME),
                "w",
                encoding="utf-8",
                newline="\n",
            ) as f:
                json.dump(signature, f, indent=2)
                f.write("\n")
            names.append(SIGNATURE_NAME)
            print("signed with key", signature["key"])

        # Manifest last, so it never names a file that is not there yet.
        move_into_place(staging, args.out, [*names, MANIFEST_NAME])
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print()
    print("bundle version", version, "degraded" if degraded else "complete")
    for entry in files:
        print(
            " ",
            entry["name"],
            entry["size"],
            "bytes",
            entry["entries"],
            "entries",
            entry["sha256"][:12],
        )
    print("wrote", os.path.join(args.out, MANIFEST_NAME))
    return 0


def parse_args(argv: list[str] | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="folder to write the bundle into")
    ap.add_argument(
        "--previous",
        default=None,
        help="folder holding the bundle already published; defaults to --out",
    )
    ap.add_argument(
        "--version",
        type=int,
        default=None,
        help="manifest version; defaults to days since 2026-01-01",
    )
    ap.add_argument("--sign-key", default=None, help="path to the signing key PEM")
    ap.add_argument(
        "--unsigned",
        action="store_true",
        help="publish without a signature; the browser will reject it",
    )
    ap.add_argument(
        "--gen-test-key",
        nargs="?",
        const=DEFAULT_TEST_KEY_DIR,
        default=None,
        metavar="DIR",
        help="write a throwaway P-256 key for local tests and stop",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None, fetch_filters=None, fetch_scam=None) -> int:
    """Runs a publication. The fetches are parameters so tests can stub them."""
    args = parse_args(argv)
    try:
        if args.gen_test_key:
            return gen_test_key(args.gen_test_key)
        if not args.out:
            raise RefusedError("--out is required")
        return build_bundle(
            args,
            fetch_filters or fetch_url,
            fetch_scam or fetch_url,
        )
    except RefusedError as e:
        print("not publishing:", e, file=sys.stderr)
        print("the bundle already on disk is untouched", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
