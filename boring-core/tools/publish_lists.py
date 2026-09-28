#!/usr/bin/env python3
"""Build the list bundle the browser downloads to keep its blocking fresh.

The filter lists are baked in when the browser is built, so on an
installed copy they only get older. This writes the same files, built
exactly as get_filterlists.py builds them, plus a small signed manifest
into a folder, ready to be uploaded to the release host:

    easylist.txt           EasyList and EasyPrivacy
    ubo.txt                uBlock filters, Quick fixes, Privacy, Unbreak
    cookies.txt            Easylist Cookie List
    aggressive-ubo.txt     uBlock filters - Annoyances
    aggressive-fanboy.txt  Fanboy's Social, Newsletter, Notifications
    regional-<id>.txt      each regional list (saved as regional/<id>.txt)
    regional-index.json    the regional index (saved as regional/index.json)
    NOTICES-*.txt          the licence notices, beside the lists; not in
                           the manifest and never read by the browser

Filter rules only. Scriptlets and $redirect resources are code that runs
in pages, so they ship only with signed browser updates, and the browser
ignores a resources file in a bundle. Names are flat because a release
keeps its files in one folder; the browser maps regional-* into its
regional folder.

No scam blocklist is published. No feed we use grants permission to
redistribute its data this way, so v1 ships and publishes none; see
get_scamlist.py. The browser refuses a scam list offered by an update
feed for the same reason. The browser reads the manifest, checks the
signature, compares it with what it already has, and downloads only the
files that changed.

The manifest looks like this:

    {
      "version": 260,
      "updated": "2026-09-17",
      "degraded": false,
      "files": [{"name": "easylist.txt", "size": 123, "sha256": "...",
                 "entries": 138411, "parse_errors": 2967},
                {"name": "ubo.txt", ...}, ...],
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

Nothing is published unless every list validated, and that means three
things for each list: the download checks in get_filterlists.py (header,
licence line, truncation, rule floors); the shrink limits below against
the bundle published last time; and a parse by the browser's own engine
code (the check_lists binary built from boring-core/rust), which refuses
a list the engine cannot read. A refusal leaves the previous bundle
exactly as it was and exits non-zero.

Usage:
  python publish_lists.py --out DIR [--previous DIR] [--version N]
                          [--sign-key PEM | --unsigned] [--checker EXE]
  python publish_lists.py --sign-bundle DIR [--sign-key PEM]
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
    AGGRESSIVE,
    COOKIES,
    REGIONAL,
    UBO,
    BuildResult,
    FeedError,
    ListBuild,
    OutputList,
    build_filter_list,
    build_output_list,
    count_rules,
    fetch_licence_text,
    fetch_url,
    notice_text,
    parse_filter_list,
    regional_index,
    utc_stamp,
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
    # percentages, well under 1 per cent a week. More than 20 per cent
    # gone with both sources healthy is not a normal week.
    healthy_shrink_floor=0.80,
    # Losing EasyList leaves EasyPrivacy's 56,132 of 138,411, so 41 per
    # cent is the worst a single source outage explains.
    degraded_shrink_floor=0.35,
)


class RefusedError(Exception):
    """The bundle is not safe to publish. The previous one stays put."""


def version_for(day: datetime.date) -> int:
    return (day - VERSION_EPOCH).days


# Every other list is published whole or not at all, like the build
# does: half of uBO's lists or half of the cookie list is a different
# list, not a thinner one. So their degraded floor is never used.
#
# Shrink limits, as a share of the rules the published bundle held:
#
#   ubo.txt, cookies.txt, aggressive-*.txt   80 per cent (refuse a drop
#       of more than 20). Curated by hand like EasyList; uAssets and the
#       Fanboy lists moved by under 2 per cent a week in September 2026.
#   regional-*.txt                            75 per cent (more than 25).
#       Smaller lists, where one cleanup of a few hundred dead rules is
#       a larger share, and still far from what a broken build loses.
#
# First run floors are the rule floors get_filterlists.py already
# holds each source to, added up, so a bundle with nothing to compare
# against still has to be a real list.
CURATED_SHRINK_FLOOR = 0.80
REGIONAL_SHRINK_FLOOR = 0.75

# The engine skips rules it cannot read, and every real list has some:
# uBO syntax it lacks, like HTML filtering and a few options. Measured
# with check_lists on 2026-09-25: easylist 2.1 per cent, ubo 4.2, cookies
# 0, uBO Annoyances 1.4, Fanboy 0, regional 0.5 to 5.3 (Liste FR). A
# list past 15 per cent has changed syntax or is not a filter list, and
# the browser would silently use little of it.
MAX_PARSE_ERROR_SHARE = 0.15

# The checker, built by `cargo build --release --bin check_lists` in
# boring-core/rust. --checker or BORING_LIST_CHECKER can point elsewhere.
RUST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rust"
)
DEFAULT_CHECKER = os.path.join(
    RUST_DIR,
    "target",
    "release",
    "check_lists" + (".exe" if os.name == "nt" else ""),
)
CHECKER_ENV = "BORING_LIST_CHECKER"

REGIONAL_INDEX_NAME = "regional-index.json"

# Lists used with every scriptlet permission. The check parses them the
# same way, so a trusted-only rule in them counts as fine.
TRUSTED_NAMES = frozenset({UBO.path, AGGRESSIVE[0].path})


def bundle_name(output: OutputList) -> str:
    """The flat name a list has in the bundle, see the module docstring."""
    return output.path.replace("/", "-")


def policy_for(output: OutputList) -> Policy:
    share = REGIONAL_SHRINK_FLOOR if output.regional_id else CURATED_SHRINK_FLOOR
    return Policy(
        name=bundle_name(output),
        first_run_floor=sum(source.min_rules for source in output.sources),
        healthy_shrink_floor=share,
        degraded_shrink_floor=share,
    )


# Every list in the bundle but easylist.txt, in the order they appear.
BUNDLED_OUTPUTS = (UBO, COOKIES, *AGGRESSIVE, *REGIONAL)


def entries_in(name: str, text: str) -> int:
    """Real entries in a list's text, whichever list it is."""
    if name == SCAM_POLICY.name:
        return count_real_hosts(text)
    if name == REGIONAL_INDEX_NAME:
        return len(json.loads(text))
    if name == FILTER_POLICY.name:
        return parse_filter_list(text)
    # uAssets lists carry no [Adblock] line, so only count.
    return count_rules(text, 1)


def run_checker(checker: str, files: list[tuple[str, bool]]) -> dict:
    """Runs check_lists on (path, trusted) pairs and returns its report."""
    if not os.path.isfile(checker):
        raise RefusedError(
            f"the list checker is not at {checker}. Build it with "
            "`cargo build --release --bin check_lists` in boring-core/rust, "
            f"or point --checker or {CHECKER_ENV} at it. Nothing is published "
            "without the engine having read every list."
        )
    argv = [checker]
    for path, trusted in files:
        argv += ["--trusted", path] if trusted else [path]
    try:
        done = subprocess.run(argv, capture_output=True, check=True)
        return json.loads(done.stdout.decode("utf-8"))
    except (OSError, subprocess.CalledProcessError, ValueError) as e:
        raise RefusedError(f"the list checker failed: {e}") from e


def check_parse(report: dict, names: list[str]) -> dict[str, dict]:
    """Applies the parse policy to a checker report, or raises RefusedError.

    Returns each list's numbers by its name in the bundle.
    """
    files = report.get("files")
    if not isinstance(files, list) or len(files) != len(names):
        raise RefusedError("the list checker did not report on every list")
    by_name = {}
    for name, entry in zip(names, files, strict=True):
        rules = entry.get("rules", 0)
        errors = entry.get("errors", 0)
        accepted = entry.get("network", 0) + entry.get("cosmetic", 0)
        if rules <= 0 or accepted <= 0:
            raise RefusedError(f"{name}: the engine read no rules from it")
        share = errors / rules
        if share > MAX_PARSE_ERROR_SHARE:
            examples = "; ".join(
                f"line {e['line']}: {e['error']}" for e in entry.get("examples", [])[:3]
            )
            raise RefusedError(
                f"{name}: the engine could not read {errors} of {rules} rules "
                f"({share:.1%}, limit {MAX_PARSE_ERROR_SHARE:.0%}): {examples}"
            )
        by_name[name] = entry
    engine = report.get("engine") or {}
    if not engine.get("built") or not engine.get("reloaded"):
        raise RefusedError(
            "the engine did not build from these lists, or its cache did not "
            f"load back ({engine})"
        )
    return by_name


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


def print_statuses(name: str, result: BuildResult) -> None:
    for status in result.sources:
        state = f"{status.entries} entries" if status.ok else f"FAILED, {status.reason}"
        print(f"  {name} {status.name}: {state}")


def build_outputs(fetch, previous: dict | None, previous_dir: str) -> list[ListBuild]:
    """Builds every list after easylist.txt, all or nothing."""
    builds = []
    for output in BUNDLED_OUTPUTS:
        policy = policy_for(output)
        build = build_output_list(output, fetch)
        print_statuses(policy.name, build.result)
        if not build.complete:
            raise RefusedError(f"{policy.name}: {build.result.describe_failures()}")
        check_coverage(
            policy,
            build.result,
            previous_entries(previous, previous_dir, policy.name),
        )
        builds.append(build)
    return builds


def licence_texts(builds: list[ListBuild], fetch) -> dict[str, str]:
    """The full licence texts the notices quote, fetched once each."""
    texts = {}
    for build in builds:
        url = build.output.licence.text_url
        if url and url not in texts:
            try:
                texts[url] = fetch_licence_text(build.output.licence, fetch)
            except FeedError as e:
                raise RefusedError(f"licence text {url}: {e}") from e
    return texts


def bundle_notice(build: ListBuild, fetched_at: str, texts: dict[str, str]) -> str:
    """The list's notice, as the build writes it, said to be for the bundle."""
    name = bundle_name(build.output)
    head = (
        f"This notice travels with {name} in the Boring Browser list bundle.\n"
        "The browser saves that file under the name given below.\n\n"
    )
    return head + notice_text(
        build, fetched_at, texts.get(build.output.licence.text_url or "")
    )


def build_bundle(args, fetch_filters, fetch_scam=None) -> int:
    """Builds, validates and publishes. Raises RefusedError to stop.

    fetch_scam is accepted and ignored: no scam list is published, and
    keeping the parameter means a caller that still passes one gets the
    same refusal rather than a TypeError.
    """
    previous_dir = args.previous or args.out
    previous = read_previous(previous_dir)

    filters = build_filter_list(fetch=fetch_filters)
    print_statuses(FILTER_POLICY.name, filters)
    check_coverage(
        FILTER_POLICY,
        filters,
        previous_entries(previous, previous_dir, FILTER_POLICY.name),
    )

    builds = build_outputs(fetch_filters, previous, previous_dir)
    texts = licence_texts(builds, fetch_filters)
    regional_builds = [b for b in builds if b.output.regional_id]
    index_text = (
        json.dumps(regional_index(regional_builds), indent=2, ensure_ascii=False)
        + "\n"
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
    fetched_at = utc_stamp(datetime.datetime.now(datetime.UTC))

    work = tempfile.mkdtemp(prefix="boring-lists-")
    try:
        staging = os.path.join(work, "bundle")
        os.makedirs(staging)

        files = [
            write_file(staging, FILTER_POLICY.name, filters.text, filters.entries),
            *(
                write_file(
                    staging,
                    bundle_name(build.output),
                    build.result.text,
                    build.result.entries,
                )
                for build in builds
            ),
        ]
        confirm_on_disk(staging, files)

        # The engine reads every list before anything goes out.
        lists = [entry["name"] for entry in files]
        report = args.check_parse(
            [
                (os.path.join(staging, name), name in TRUSTED_NAMES)
                for name in lists
            ]
        )
        parsed = check_parse(report, lists)
        for entry in files:
            entry["parse_errors"] = parsed[entry["name"]].get("errors", 0)
            print(
                f"  {entry['name']}: the engine read "
                f"{entry['entries'] - entry['parse_errors']} of "
                f"{entry['entries']} rules"
            )

        files.append(
            write_file(
                staging,
                REGIONAL_INDEX_NAME,
                index_text,
                len(regional_builds),
            )
        )
        confirm_on_disk(staging, files)

        notices = []
        for build in builds:
            if build.output.notice in notices:
                continue
            with open(
                os.path.join(staging, build.output.notice),
                "w",
                encoding="utf-8",
                newline="\n",
            ) as f:
                f.write(bundle_notice(build, fetched_at, texts))
            notices.append(build.output.notice)

        manifest = {
            "version": version,
            "updated": today.isoformat(),
            "degraded": degraded,
            "files": files,
            "notices": notices,
            "sources": [
                *source_rows(FILTER_POLICY, filters),
                *(
                    row
                    for build in builds
                    for row in source_rows(policy_for(build.output), build.result)
                ),
            ],
        }
        manifest_path = os.path.join(staging, MANIFEST_NAME)
        with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")

        names = [entry["name"] for entry in files] + notices
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


def sign_bundle(args) -> int:
    """Signs the manifest of a bundle already built and checked.

    For the publish job in lists.yml: the build job checks the bundle
    without ever seeing the key, and the job that holds the key only
    signs those exact bytes. Refuses a bundle with a resources file in
    it, which no bundle may carry.
    """
    directory = args.sign_bundle
    manifest_path = os.path.join(directory, MANIFEST_NAME)
    manifest = read_previous(directory)
    if manifest is None:
        raise RefusedError(f"no readable {MANIFEST_NAME} in {directory}")
    names = [entry.get("name") for entry in manifest.get("files", [])]
    if "resources.json" in names or os.path.exists(
        os.path.join(directory, "resources.json")
    ):
        raise RefusedError("a list bundle must never carry resources.json")
    for entry in manifest.get("files", []):
        confirm_on_disk(directory, [entry])
    work = tempfile.mkdtemp(prefix="boring-sign-")
    try:
        signature = sign_manifest(manifest_path, resolve_key(args, work), work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with open(
        os.path.join(directory, SIGNATURE_NAME), "w", encoding="utf-8", newline="\n"
    ) as f:
        json.dump(signature, f, indent=2)
        f.write("\n")
    print("signed", manifest_path, "with key", signature["key"])
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
        "--checker",
        default=os.environ.get(CHECKER_ENV, DEFAULT_CHECKER),
        help="the check_lists binary from boring-core/rust",
    )
    ap.add_argument(
        "--unsigned",
        action="store_true",
        help="publish without a signature; the browser will reject it",
    )
    ap.add_argument(
        "--sign-bundle",
        default=None,
        metavar="DIR",
        help="only sign the manifest of the bundle already built in DIR",
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


def main(
    argv: list[str] | None = None,
    fetch_filters=None,
    fetch_scam=None,
    check_parse=None,
) -> int:
    """Runs a publication.

    The fetches and the engine check are parameters so tests can stub
    them. check_parse takes [(path, trusted)] and returns what the
    check_lists binary prints.
    """
    args = parse_args(argv)
    try:
        if args.gen_test_key:
            return gen_test_key(args.gen_test_key)
        if args.sign_bundle:
            return sign_bundle(args)
        if not args.out:
            raise RefusedError("--out is required")
        args.check_parse = check_parse or (
            lambda files: run_checker(args.checker, files)
        )
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
