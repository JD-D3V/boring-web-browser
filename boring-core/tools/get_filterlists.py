#!/usr/bin/env python3
"""Download the filter lists the ad blocker uses, and prove they are real.

Writes them into the build output folder (next to chrome.exe) in a
folder called boring. Run again any time to refresh the lists.

This module also holds the plumbing the two list tools share: one HTTP
fetch, one per source status record, one build result, and the checks
that apply to any feed whatever its format. The tools directory is one
module per list with no separate library module, so the generic half
lives in this one and get_scamlist.py imports it.

Exits non-zero when the lists that came back are not usable. A build
that bakes in a broken filter list ships a browser that blocks nothing,
which is worse than a build that stops.

Usage: python get_filterlists.py [--out DIR]
"""

import argparse
import dataclasses
import os
import re
import sys
import urllib.error
import urllib.request

LISTS = [
    ("easylist", "https://easylist.to/easylist/easylist.txt"),
    ("easyprivacy", "https://easylist.to/easylist/easyprivacy.txt"),
]

DEFAULT_OUT = r"E:\ung\build\src\out\Default"

# A source that stops responding should fail the run, not hang it.
TIMEOUT_SECONDS = 60

# Measured 2026-09-19: easylist 2,166,195 bytes, easyprivacy 1,504,162,
# urlhaus 11,786, openphish 16,048. 64 MB is far above any of them and
# still small enough that a feed which has turned into something else
# cannot make this tool eat the machine.
MAX_FETCH_BYTES = 64 * 1024 * 1024

# Feeds are plain text. A release host answering an outage with an HTML
# error page is the failure this catches, and it answers with
# text/html, so the content type alone separates the two cases.
ALLOWED_CONTENT_TYPES = ("text/plain", "")

# Measured 2026-09-19: easylist starts "[Adblock Plus 2.0]" and
# easyprivacy "[Adblock Plus 1.1]". Every adblock list carries one of
# these; an error page or a truncated-from-the-front download does not.
FILTER_HEADER_RE = re.compile(r"^\[Adblock[^\]]*\]$")

# Measured 2026-09-19: easylist holds 82,279 rules, easyprivacy 56,132.
# 1,000 is under two per cent of the smaller one, so a healthy list
# clears it by fifty times over while a truncated fragment does not.
# This is a "has the file arrived at all" floor, not a coverage floor;
# coverage is publish_lists.py's job because only it knows what the
# previous bundle held.
MIN_FILTER_RULES = 1000

# Characters that appear in adblock syntax: anchors, separators,
# options, cosmetic selectors, exceptions, paths and wildcards.
FILTER_SYNTAX_RE = re.compile(r"[|^$#@/*]")

# Measured 2026-09-19: 99.80 per cent of easylist rules and 99.82 per
# cent of easyprivacy rules carry one of those characters, the rest
# being plain substring rules like ".cfm?ad=". A real list will not
# drop from 99.8 to below 90, so anything that does is prose or markup
# wearing a filter list's name.
MIN_FILTER_SYNTAX_RATIO = 0.90


class FeedError(Exception):
    """A feed could not be fetched or is not what it claims to be."""


@dataclasses.dataclass(frozen=True)
class Fetched:
    """One HTTP response, kept as bytes so nothing guesses at encoding."""

    url: str
    http_status: int
    content_type: str
    data: bytes


@dataclasses.dataclass
class SourceStatus:
    """What happened to one source, for the manifest and for a human.

    This is returned rather than printed. A status that is only printed
    is a status nobody downstream can act on, which is how a failed
    refresh ends up looking like a healthy one.
    """

    name: str
    url: str
    http_status: int | None = None
    bytes: int = 0
    entries: int = 0
    ok: bool = False
    reason: str | None = None

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class BuildResult:
    """The text of one list plus how every source that fed it fared."""

    text: str
    # Real entries only. Test entries are never counted here, so no
    # caller can mistake a list of test data for protection.
    entries: int
    sources: list[SourceStatus]

    @property
    def failed(self) -> list[SourceStatus]:
        return [s for s in self.sources if not s.ok]

    @property
    def healthy(self) -> list[SourceStatus]:
        return [s for s in self.sources if s.ok]

    @property
    def degraded(self) -> bool:
        """True when some but not all sources answered."""
        return bool(self.failed) and bool(self.healthy)

    def describe_failures(self) -> str:
        return "; ".join(f"{s.name}: {s.reason}" for s in self.failed)


def fetch_url(url: str) -> Fetched:
    """Fetches one feed. Raises FeedError for anything short of 200 OK."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            # Read one byte past the cap so an oversized body is a
            # refusal rather than a silent truncation we then validate.
            data = response.read(MAX_FETCH_BYTES + 1)
            status = response.status
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        raise FeedError(f"HTTP {e.code}") from e
    except Exception as e:
        # Any transport failure reads the same downstream: no payload.
        raise FeedError(f"{type(e).__name__}: {e}") from e
    if status != 200:
        raise FeedError(f"HTTP {status}")
    if len(data) > MAX_FETCH_BYTES:
        raise FeedError(f"over {MAX_FETCH_BYTES} bytes")
    return Fetched(url=url, http_status=status, content_type=content_type, data=data)


def decode_payload(fetched: Fetched) -> str:
    """The body as text, or a FeedError saying why it is not usable.

    Everything here applies to any feed, whatever its format: the
    checks that a download happened are not the same as the checks that
    what arrived is a list.
    """
    if not fetched.data.strip():
        raise FeedError("empty")

    main_type = fetched.content_type.split(";")[0].strip().lower()
    if main_type not in ALLOWED_CONTENT_TYPES:
        raise FeedError(f"content type {main_type or 'missing'}")

    # An outage, a captive portal or a moved feed answers with a page,
    # not a list. Without this check that page becomes the blocklist.
    head = fetched.data[:1024].lstrip().lower()
    if head.startswith(b"<") or b"<html" in head or b"<!doctype" in head:
        raise FeedError("HTML page, not a list")

    try:
        # Strict, not "replace". Replacement characters would let a
        # compressed or binary body through looking like text.
        return fetched.data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise FeedError("not valid UTF-8 text") from e


def parse_filter_list(text: str) -> int:
    """How many filter rules the text holds. FeedError if it is not one."""
    lines = text.splitlines()
    first = next((ln for ln in lines if ln.strip()), "")
    if not FILTER_HEADER_RE.match(first.strip()):
        raise FeedError("no [Adblock] header line")

    # Both real lists end with a newline, so every rule is terminated.
    # A download cut short arrives without one, and half a rule quietly
    # changes what is blocked rather than obviously breaking.
    if not text.endswith("\n"):
        raise FeedError("does not end with a newline, looks truncated")

    rules = [
        ln.strip()
        for ln in lines
        if ln.strip() and not ln.strip().startswith(("!", "["))
    ]
    if len(rules) < MIN_FILTER_RULES:
        raise FeedError(f"only {len(rules)} rules")

    with_syntax = sum(1 for rule in rules if FILTER_SYNTAX_RE.search(rule))
    ratio = with_syntax / len(rules)
    if ratio < MIN_FILTER_SYNTAX_RATIO:
        raise FeedError(f"only {ratio:.0%} of lines look like filter rules")
    return len(rules)


def build_filter_list(fetch=fetch_url) -> BuildResult:
    """Downloads every source list and returns them as one list's text.

    The fetch is a parameter so tests can hand in their own without
    reaching the network.
    """
    parts: list[str] = []
    sources: list[SourceStatus] = []
    entries = 0

    for name, url in LISTS:
        status = SourceStatus(name=name, url=url)
        sources.append(status)
        try:
            fetched = fetch(url)
            status.http_status = fetched.http_status
            status.bytes = len(fetched.data)
            text = decode_payload(fetched)
            status.entries = parse_filter_list(text)
        except FeedError as e:
            status.reason = str(e)
            continue
        status.ok = True
        entries += status.entries
        parts.append(text)

    # The engine takes one combined list, so join them.
    return BuildResult(text="\n".join(parts), entries=entries, sources=sources)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    built = build_filter_list()
    for source in built.sources:
        state = f"{source.entries} rules" if source.ok else f"FAILED, {source.reason}"
        print(f"  {source.name}: {state}")

    if not built.healthy:
        print("no filter source came back usable, not writing a list")
        return 1

    dest_dir = os.path.join(args.out, "boring")
    os.makedirs(dest_dir, exist_ok=True)
    out_path = os.path.join(dest_dir, "easylist.txt")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(built.text)
    print("wrote", out_path, "with", built.entries, "rules")
    if built.degraded:
        print("WARNING: written from some sources only,", built.describe_failures())
    return 0


if __name__ == "__main__":
    sys.exit(main())
