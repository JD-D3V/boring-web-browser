#!/usr/bin/env python3
"""Download the filter lists the ad blocker uses, and prove they are real.

Writes them into the build output folder (next to chrome.exe) in a
folder called boring. Run again any time to refresh the lists.

  boring\\easylist.txt     EasyList and EasyPrivacy, as they are served
  boring\\ubo.txt          uBlock filters, Quick fixes, Privacy, Unbreak
  boring\\cookies.txt      Easylist Cookie List
  boring\\regional\\*.txt   optional regional lists, with index.json
  boring\\sources.json     what was fetched, when, and its SHA-256

and, beside chrome.exe, one NOTICES-*.txt per licence those lists are
under. Every list is only included after its header was checked for
the licence it was cleared under (see V1_PLAN.md, Release 2). A list
whose header changes licence stops the run rather than shipping.

ubo.txt, cookies.txt and the regional lists go through the two steps
uBlock Origin itself applies when it loads a list: each "!#include" is
replaced by the file it names (same site only, a few levels deep at
most), and "!#if" blocks are resolved for Chromium on a desktop. The
engine understands neither directive, so without this it would apply
filters meant for Firefox or phones and miss every included file. No
filter is otherwise changed. easylist.txt is left exactly as served.

This module also holds the plumbing the two list tools share: one HTTP
fetch, one per source status record, one build result, and the checks
that apply to any feed whatever its format. The tools directory is one
module per list with no separate library module, so the generic half
lives in this one and get_scamlist.py imports it.

Exits non-zero when any list that came back is not usable. A build
that bakes in a broken filter list ships a browser that blocks nothing,
which is worse than a build that stops. What did validate is still
written, so one flaky host does not cost the other lists.

Usage: python get_filterlists.py [--out DIR] [--no-regional]
"""

import argparse
import dataclasses
import datetime
import glob
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

LISTS = [
    ("easylist", "https://easylist.to/easylist/easylist.txt"),
    ("easyprivacy", "https://easylist.to/easylist/easyprivacy.txt"),
]

# The same environment variable drive.py reads. The workflows set it to
# the tree they build, so the lists land in that build and not in
# whichever tree happened to be the default.
DEFAULT_OUT = os.environ.get("BORING_OUT", r"E:\ung\build\src\out\Default")

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
    return count_rules(text, MIN_FILTER_RULES)


def count_rules(text: str, min_rules: int) -> int:
    """How many filter rules the text holds, whatever its header.

    FeedError when it looks truncated, too small or not like filters.
    """
    # Both real lists end with a newline, so every rule is terminated.
    # A download cut short arrives without one, and half a rule quietly
    # changes what is blocked rather than obviously breaking.
    if not text.endswith("\n"):
        raise FeedError("does not end with a newline, looks truncated")

    rules = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith(("!", "["))
    ]
    if len(rules) < min_rules:
        raise FeedError(f"only {len(rules)} rules")

    with_syntax = sum(1 for rule in rules if FILTER_SYNTAX_RE.search(rule))
    ratio = with_syntax / len(rules) if rules else 0.0
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


# ---------------------------------------------------------------------
# uBlock Origin's lists, the cookie list and the regional lists.
# ---------------------------------------------------------------------

# The browser's list updater refuses anything bigger (kMaxListBytes in
# components/boring/lists/list_updater.cc), so a list past this could
# ship in a build and then never be replaceable by an update.
MAX_LIST_BYTES = 32 * 1024 * 1024

# How far "!#include" is followed. uAssets and the cookie list go one
# level deep today; three leaves room without letting a list that
# includes itself by another name run away.
MAX_INCLUDE_DEPTH = 3

# Lines at the top of a list that count as its header. The licence line
# is on line 5 to 13 in every list we take.
HEADER_LINES = 40

# uBlock Origin's names for "!#if" tokens and what each one tests, from
# src/js/static-filtering-parser.js (preparserTokens) at the release
# get_ubo_resources.py pins. A token that is not here is unknown: uBO
# keeps a block it cannot evaluate, unless the token starts with cap_.
PREPARSER_TOKENS = {
    "ext_ublock": "ublock",
    "ext_ubol": "ubol",
    "ext_devbuild": "devbuild",
    "env_brave": "brave",
    "env_chromium": "chromium",
    "env_edge": "edge",
    "env_firefox": "firefox",
    "env_legacy": "legacy",
    "env_mobile": "mobile",
    "env_mv3": "mv3",
    "env_safari": "safari",
    "cap_html_filtering": "html_filtering",
    "cap_ipaddress": "ipaddress",
    "false": "false",
    "ext_abp": "false",
    "adguard": "adguard",
    "adguard_app_android": "false",
    "adguard_app_cli": "false",
    "adguard_app_ios": "false",
    "adguard_app_mac": "false",
    "adguard_app_windows": "false",
    "adguard_ext_android_cb": "false",
    "adguard_ext_chromium": "chromium",
    "adguard_ext_chromium_mv3": "mv3",
    "adguard_ext_edge": "edge",
    "adguard_ext_firefox": "firefox",
    "adguard_ext_opera": "chromium",
    "adguard_ext_safari": "false",
}

# What this browser is, in those terms. uBO in desktop Chromium also
# says "ipaddress", because it can match on the address a host resolved
# to. The engine here (adblock-rust) cannot, and has no HTML filtering
# either, so both stay false and their fallbacks are the ones kept.
PREPARSER_ENV = frozenset({"ublock", "chromium"})

DIRECTIVE_RE = re.compile(r"^!#(if|else|endif)\b(.*)$")
INCLUDE_RE = re.compile(r"^!#include +(\S+)")
EXPR_PART_RE = re.compile(r"(?:(?:&&|\|\|)\s+)?\S+")


@dataclasses.dataclass(frozen=True)
class Licence:
    """A licence a list was cleared under, as it was seen at the source."""

    # Short name for index.json and the manifest.
    spdx: str
    # The name people read in the notice.
    title: str
    # Where the licence is. For a Creative Commons licence the notice
    # gives this link, which section 4(a) of the 3.0 licences accepts in
    # place of the text.
    url: str
    # The full text to copy into the notice, when the licence asks for
    # the text itself. The GPL does.
    text_url: str | None = None


GPL3_UASSETS = Licence(
    spdx="GPL-3.0",
    title="GNU General Public License, version 3",
    url="https://github.com/uBlockOrigin/uAssets/blob/master/LICENSE",
    text_url="https://raw.githubusercontent.com/uBlockOrigin/uAssets/master/LICENSE",
)
GPL3_ADGUARD = Licence(
    spdx="GPL-3.0",
    title="GNU General Public License, version 3",
    url="https://github.com/AdguardTeam/AdguardFilters/blob/master/LICENSE",
    text_url=(
        "https://raw.githubusercontent.com/AdguardTeam/AdguardFilters/master/LICENSE"
    ),
)
CC_BY_3 = Licence(
    spdx="CC-BY-3.0",
    title="Creative Commons Attribution 3.0 Unported",
    url="https://creativecommons.org/licenses/by/3.0/legalcode",
)
CC_BY_SA_3 = Licence(
    spdx="CC-BY-SA-3.0",
    title="Creative Commons Attribution-ShareAlike 3.0 Unported",
    url="https://creativecommons.org/licenses/by-sa/3.0/legalcode",
)
# easylist.to/pages/licence.html, seen 2026-09-24: "dual licensed under
# the GNU General Public License version 3 of the License, or (at your
# option) any later version, and Creative Commons Attribution-ShareAlike
# 3.0 Unported, or (at your option) any later version". It names
# EasyList, EasyPrivacy, EasyList Germany and EasyList Italy as covered.
# Used here under the CC BY-SA option, which accepts a link.
EASYLIST_DUAL = Licence(
    spdx="GPL-3.0-or-later OR CC-BY-SA-3.0",
    title=(
        "GNU General Public License version 3 or later, or Creative "
        "Commons Attribution-ShareAlike 3.0 Unported or later, used "
        "here under CC BY-SA 3.0 "
        "(https://creativecommons.org/licenses/by-sa/3.0/legalcode)"
    ),
    url="https://easylist.to/pages/licence.html",
)


@dataclasses.dataclass(frozen=True)
class ListSource:
    """One list as published, and what its header has to say."""

    name: str
    title: str
    url: str
    # A line that must be in the list's header, exactly. It is the
    # licence the list was cleared under. A list that starts naming
    # another one is refused until somebody has looked again.
    licence_line: str
    # Rules the list has to hold once its includes are in.
    min_rules: int
    # Whether the list is served ending in a newline, which is then the
    # truncation check. Measured 2026-09-25: Liste FR, EasyList Italy,
    # the AdGuard lists and RU AdList are served without one. Their
    # hosts send a Content-Length, and a body shorter than that is an
    # error in the fetch, so they are not left unchecked.
    newline_terminated: bool = True


@dataclasses.dataclass(frozen=True)
class OutputList:
    """One file in boring\\, built from one or more published lists."""

    # Path under boring\, with forward slashes.
    path: str
    # What the notice calls the whole file.
    title: str
    sources: tuple[ListSource, ...]
    licence: Licence
    # Who the notice credits.
    attribution: str
    # The notice's file name, beside chrome.exe.
    notice: str
    # For a regional list: its id and the languages it is for.
    regional_id: str | None = None
    locales: tuple[str, ...] = ()


UASSETS = "https://ublockorigin.github.io/uAssets/filters/"
UASSETS_LICENCE_LINE = (
    "! License: https://github.com/uBlockOrigin/uAssets/blob/master/LICENSE"
)
ADGUARD_LICENCE_LINE = (
    "! License: https://github.com/AdguardTeam/AdguardFilters/blob/master/LICENSE"
)
ADGUARD_CREDIT = (
    "AdGuard and the AdguardFilters contributors "
    "(https://github.com/AdguardTeam/AdguardFilters)"
)
EASYLIST_CREDIT = "The EasyList authors (https://easylist.to/)"

# Rule floors. Measured 2026-09-25 with the includes in and "!#if"
# resolved:
#
#   uBlock filters 23,035   Quick fixes 348    Privacy 1,801
#   Unbreak 2,539           Cookie List 28,053
#   EasyList Germany 5,983  Liste FR 13,818    EasyList Italy 4,206
#   AdGuard es/pt 5,646     AdGuard ja 12,059  AdGuard zh 22,060
#   RU AdList 27,015
#
# Each floor is about a third of that, so a normal month clears it and
# a fragment or an error page does not.
UBO = OutputList(
    path="ubo.txt",
    title="uBlock Origin filter lists (uAssets)",
    sources=(
        ListSource(
            "ublock-filters",
            "uBlock filters",
            UASSETS + "filters.txt",
            UASSETS_LICENCE_LINE,
            min_rules=8000,
        ),
        ListSource(
            "ublock-quick-fixes",
            "uBlock filters - Quick fixes",
            UASSETS + "quick-fixes.txt",
            UASSETS_LICENCE_LINE,
            min_rules=100,
        ),
        ListSource(
            "ublock-privacy",
            "uBlock filters - Privacy",
            UASSETS + "privacy.txt",
            UASSETS_LICENCE_LINE,
            min_rules=500,
        ),
        ListSource(
            "ublock-unbreak",
            "uBlock filters - Unbreak",
            UASSETS + "unbreak.txt",
            UASSETS_LICENCE_LINE,
            min_rules=800,
        ),
    ),
    licence=GPL3_UASSETS,
    attribution=(
        "The uBlock Origin uAssets contributors "
        "(https://github.com/uBlockOrigin/uAssets)"
    ),
    notice="NOTICES-uAssets.txt",
)

COOKIES = OutputList(
    path="cookies.txt",
    title="Easylist Cookie List",
    sources=(
        ListSource(
            "easylist-cookie",
            "Easylist Cookie List",
            "https://secure.fanboy.co.nz/fanboy-cookiemonster.txt",
            "! License: http://creativecommons.org/licenses/by/3.0/",
            min_rules=9000,
        ),
    ),
    licence=CC_BY_3,
    attribution=EASYLIST_CREDIT,
    notice="NOTICES-easylist-cookie.txt",
)

# Regional lists. Each one is here only because its own header names a
# licence that allows passing it on, checked at the source on
# 2026-09-24, and for the AdGuard lists because the repository's LICENSE
# is the GPL the header points to. Left out on purpose: EasyList
# Spanish, Portuguese and China (their headers point at easylist.to's
# licence page, which vouches only for EasyList, EasyPrivacy, EasyList
# Germany and EasyList Italy), AdGuard French (it merges Liste FR, which
# is CC BY-SA 3.0 only, into a list it calls GPL-3.0) and RU AdList's
# uBO build (no licence line in its header; the build below has one).
REGIONAL = (
    OutputList(
        path="regional/de.txt",
        title="EasyList Germany",
        sources=(
            ListSource(
                "easylist-germany",
                "EasyList Germany",
                "https://easylist.to/easylistgermany/easylistgermany.txt",
                "! Licence: https://easylist.to/pages/licence.html",
                min_rules=2000,
            ),
        ),
        licence=EASYLIST_DUAL,
        attribution=EASYLIST_CREDIT,
        notice="NOTICES-regional-de.txt",
        regional_id="de",
        locales=("de",),
    ),
    OutputList(
        path="regional/fr.txt",
        title="Liste FR",
        sources=(
            ListSource(
                "liste-fr",
                "Liste FR",
                "https://easylist-downloads.adblockplus.org/liste_fr.txt",
                "! Licence : https://creativecommons.org/licenses/by-sa/3.0/",
                min_rules=4500,
                newline_terminated=False,
            ),
        ),
        licence=CC_BY_SA_3,
        attribution="The Liste FR authors (https://github.com/easylist/listefr)",
        notice="NOTICES-regional-fr.txt",
        regional_id="fr",
        locales=("fr",),
    ),
    OutputList(
        path="regional/it.txt",
        title="EasyList Italy",
        sources=(
            ListSource(
                "easylist-italy",
                "EasyList Italy",
                "https://easylist-downloads.adblockplus.org/easylistitaly.txt",
                "! Licenza: https://easylist.to/pages/licence.html",
                min_rules=1400,
                newline_terminated=False,
            ),
        ),
        licence=EASYLIST_DUAL,
        attribution=EASYLIST_CREDIT,
        notice="NOTICES-regional-it.txt",
        regional_id="it",
        locales=("it",),
    ),
    OutputList(
        path="regional/es-pt.txt",
        title="AdGuard Spanish/Portuguese filter",
        sources=(
            ListSource(
                "adguard-spanish-portuguese",
                "AdGuard Spanish/Portuguese filter",
                "https://filters.adtidy.org/extension/ublock/filters/9.txt",
                ADGUARD_LICENCE_LINE,
                min_rules=1800,
                newline_terminated=False,
            ),
        ),
        licence=GPL3_ADGUARD,
        attribution=ADGUARD_CREDIT,
        notice="NOTICES-regional-es-pt.txt",
        regional_id="es-pt",
        locales=("es", "pt"),
    ),
    OutputList(
        path="regional/ja.txt",
        title="AdGuard Japanese filter",
        sources=(
            ListSource(
                "adguard-japanese",
                "AdGuard Japanese filter",
                "https://filters.adtidy.org/extension/ublock/filters/7.txt",
                ADGUARD_LICENCE_LINE,
                min_rules=4000,
                newline_terminated=False,
            ),
        ),
        licence=GPL3_ADGUARD,
        attribution=ADGUARD_CREDIT,
        notice="NOTICES-regional-ja.txt",
        regional_id="ja",
        locales=("ja",),
    ),
    OutputList(
        path="regional/zh.txt",
        title="AdGuard Chinese filter",
        sources=(
            ListSource(
                "adguard-chinese",
                "AdGuard Chinese filter",
                "https://filters.adtidy.org/extension/ublock/filters/224.txt",
                ADGUARD_LICENCE_LINE,
                min_rules=7000,
                newline_terminated=False,
            ),
        ),
        licence=GPL3_ADGUARD,
        attribution=(
            ADGUARD_CREDIT + ", including EasyList China by " + EASYLIST_CREDIT
        ),
        notice="NOTICES-regional-zh.txt",
        regional_id="zh",
        locales=("zh",),
    ),
    OutputList(
        path="regional/ru.txt",
        title="RU AdList",
        sources=(
            ListSource(
                "ru-adlist",
                "RU AdList",
                "https://easylist-downloads.adblockplus.org/ruadlist.txt",
                # "Лицензия CC-BY", the list's own words, in Russian.
                "! Лицензия CC-BY: http://creativecommons.org/licenses/by/3.0/",
                min_rules=9000,
                newline_terminated=False,
            ),
        ),
        licence=CC_BY_3,
        attribution="The RU AdList authors (https://github.com/easylist/ruadlist)",
        notice="NOTICES-regional-ru.txt",
        regional_id="ru",
        locales=("ru", "uk", "be", "kk", "uz"),
    ),
)


def eval_token(token: str) -> bool | None:
    """One "!#if" token, None when it is not one uBO knows."""
    negate = token.startswith("!")
    if negate:
        token = token[1:]
    state = PREPARSER_TOKENS.get(token)
    if state is None:
        if not token.startswith("cap_"):
            return None
        state = "false"
    return (state == "false" and negate) or ((state in PREPARSER_ENV) != negate)


def eval_expr(expr: str) -> bool | None:
    """An "!#if" expression, evaluated left to right the way uBO does.

    uBO gives && and || no precedence, so neither does this. None means
    uBO could not evaluate it, and then it keeps the block.
    """
    if expr.startswith("(") and expr.endswith(")"):
        expr = expr[1:-1]
    parts = [m.group(0) for m in EXPR_PART_RE.finditer(expr)]
    if not parts or parts[0].startswith(("|", "&")):
        return None
    result = eval_token(parts[0])
    for part in parts[1:]:
        pieces = re.split(r" +", part)
        if len(pieces) != 2:
            return None
        state = eval_token(pieces[1])
        if state is None:
            return None
        if pieces[0] == "||":
            result = result or state
        elif pieces[0] == "&&":
            result = result and state
        else:
            return None
    return result


def prune_directives(lines: list[str]) -> list[str]:
    """Drops what "!#if" blocks exclude here, line for line as uBO does.

    Mirrors preparser.splitter in uBO's static-filtering-parser.js: a
    block uBO cannot evaluate is kept, "!#else" flips its block, and a
    stray "!#endif" is ignored. Directive lines around kept blocks stay
    in, as the comments they are.
    """
    out: list[str] = []
    stack: list[dict] = []
    discarding = False

    def should_discard() -> bool:
        return any(block["known"] and block["discard"] for block in stack)

    for line in lines:
        drop = discarding
        match = DIRECTIVE_RE.match(line)
        if match:
            kind = match.group(1)
            if kind == "if":
                result = eval_expr(match.group(2).strip())
                block = {"known": result is not None, "discard": result is False}
                if not discarding and block["known"] and block["discard"]:
                    discarding = drop = True
                stack.append(block)
            elif kind == "else" and stack:
                block = stack.pop()
                if discarding and not should_discard():
                    discarding = False
                    drop = True
                block["discard"] = not block["discard"]
                if not discarding and block["known"] and block["discard"]:
                    discarding = drop = True
                stack.append(block)
            elif kind == "endif":
                if stack:
                    stack.pop()
                if discarding and not should_discard():
                    discarding = False
                    drop = True
        if not drop:
            out.append(line)
    return out


def include_url(parent_url: str, target: str) -> str | None:
    """Where an "!#include" points, or None when it is not followed.

    uBO follows a relative path only, never a full address and never
    one with "..", resolved against the folder the parent came from.
    The same-site check is ours, on top.
    """
    if urllib.parse.urlsplit(target).scheme or ".." in target:
        return None
    pos = parent_url.rfind("/")
    if pos == -1:
        return None
    url = parent_url[: pos + 1] + target.strip()
    parent = urllib.parse.urlsplit(parent_url)
    child = urllib.parse.urlsplit(url)
    if (child.scheme, child.netloc) != (parent.scheme, parent.netloc):
        return None
    return url


def resolve_list(
    url: str,
    text: str,
    fetch,
    seen: set[str],
    skipped: list[str],
    depth: int = 0,
) -> list[str]:
    """The list's lines with "!#if" resolved and every include put in.

    Each included file is marked the way uBO marks it, so a reader of
    the shipped file can see where every part came from.
    """
    out: list[str] = []
    for line in prune_directives(text.splitlines()):
        out.append(line)
        match = INCLUDE_RE.match(line)
        if not match:
            continue
        sub_url = include_url(url, match.group(1))
        if sub_url is None:
            skipped.append(f"{url}: {match.group(1)}")
            continue
        if sub_url in seen:
            continue
        if depth + 1 > MAX_INCLUDE_DEPTH:
            raise FeedError(f"includes nested deeper than {MAX_INCLUDE_DEPTH}")
        seen.add(sub_url)
        try:
            sub_text = decode_payload(fetch(sub_url))
        except FeedError as e:
            raise FeedError(f"include {sub_url}: {e}") from e
        out.append(f"! >>>>>>>> {sub_url}")
        # uBO trims the end of an included file and gives it one newline.
        out += resolve_list(
            sub_url, sub_text.rstrip() + "\n", fetch, seen, skipped, depth + 1
        )
        out.append(f"! <<<<<<<< {sub_url}")
    return out


def check_header(text: str, source: ListSource) -> None:
    """FeedError unless the header has a title and the licence we cleared."""
    header = [line.rstrip() for line in text.splitlines()[:HEADER_LINES]]
    if not any(line.startswith("! Title:") for line in header):
        raise FeedError("no ! Title: line in the header")
    if source.licence_line not in header:
        raise FeedError(
            f"header no longer says {source.licence_line!r}; "
            "check the licence again before shipping it"
        )


@dataclasses.dataclass
class ListBuild:
    """One output file, how its sources fared and every file fetched."""

    output: OutputList
    result: BuildResult
    # url, bytes and sha256 of each file fetched for it, includes too.
    files: list[dict]
    # "!#include" lines that uBO itself would not follow either.
    skipped: list[str]

    @property
    def complete(self) -> bool:
        # All or nothing. Unbreak without the filters it unbreaks, or
        # half of the cookie list, is a different list, not a thinner one.
        return bool(self.result.sources) and not self.result.failed


def recording(fetch, files: list[dict]):
    """The same fetch, noting what came back for the manifest."""

    def fetch_and_record(url: str) -> Fetched:
        fetched = fetch(url)
        files.append(
            {
                "url": url,
                "bytes": len(fetched.data),
                "sha256": hashlib.sha256(fetched.data).hexdigest(),
            }
        )
        return fetched

    return fetch_and_record


def build_output_list(output: OutputList, fetch=fetch_url) -> ListBuild:
    """Fetches, checks and joins every source of one output file."""
    files: list[dict] = []
    skipped: list[str] = []
    record = recording(fetch, files)
    parts: list[str] = []
    sources: list[SourceStatus] = []
    entries = 0

    for source in output.sources:
        status = SourceStatus(name=source.name, url=source.url)
        sources.append(status)
        try:
            fetched = record(source.url)
            status.http_status = fetched.http_status
            status.bytes = len(fetched.data)
            raw = decode_payload(fetched)
            check_header(raw, source)
            if source.newline_terminated and not raw.endswith("\n"):
                raise FeedError("does not end with a newline, looks truncated")
            lines = resolve_list(source.url, raw, record, {source.url}, skipped)
            text = "\n".join(lines) + "\n"
            status.entries = count_rules(text, source.min_rules)
        except FeedError as e:
            status.reason = str(e)
            continue
        status.ok = True
        entries += status.entries
        parts.append(text)

    text = "\n".join(parts)
    if len(text.encode("utf-8")) > MAX_LIST_BYTES:
        for status in sources:
            status.ok = False
            status.reason = f"joined list is over {MAX_LIST_BYTES} bytes"
    result = BuildResult(text=text, entries=entries, sources=sources)
    return ListBuild(output=output, result=result, files=files, skipped=skipped)


GPL3_MARKERS = (
    "GNU GENERAL PUBLIC LICENSE",
    "Version 3, 29 June 2007",
    "END OF TERMS AND CONDITIONS",
)


def check_gpl3(text: str) -> None:
    """FeedError unless this is the text of the GPL, version 3."""
    for marker in GPL3_MARKERS:
        if marker not in text:
            raise FeedError(f"licence text lacks {marker!r}, not the GPL-3.0")


def fetch_licence_text(licence: Licence, fetch=fetch_url) -> str:
    """The licence's full text as served at the source, checked."""
    text = decode_payload(fetch(licence.text_url))
    if licence.spdx.startswith("GPL-3.0"):
        check_gpl3(text)
    return text


def utc_stamp(now: datetime.datetime) -> str:
    return now.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def windows_path(path: str) -> str:
    return "boring\\" + path.replace("/", "\\")


def notice_text(build: ListBuild, fetched_at: str, licence_text: str | None) -> str:
    """The notice that ships beside chrome.exe for one output file."""
    output = build.output
    lines = [
        output.title,
        "=" * len(output.title),
        "",
        f"{windows_path(output.path)}, in the version folder beside",
        "chrome.dll, is built from:",
        "",
    ]
    for source in output.sources:
        lines += [f"  {source.title}", f"    {source.url}"]
    top = {source.url for source in output.sources}
    included = [f["url"] for f in build.files if f["url"] not in top]
    if included:
        lines += ["", "and the files those include:", ""]
        lines += [f"    {url}" for url in included]
    lines += [
        "",
        f"By: {output.attribution}",
        f"Fetched: {fetched_at}. Every file fetched, with its size and",
        "SHA-256, is listed in boring\\sources.json.",
        "",
        'Changes: none to any filter. Each "!#include" line is followed by',
        'the file it names, and "!#if" blocks are resolved for desktop',
        "Chromium, the way uBlock Origin does both when it loads a list.",
        "",
        f"Licence: {output.licence.title}.",
        "The list's own header says:",
    ]
    lines += sorted({f"  {source.licence_line}" for source in output.sources})
    lines.append(f"Licence: {output.licence.url}")
    if output is COOKIES:
        lines += [
            "",
            "EasyList and EasyPrivacy themselves (boring\\easylist.txt) are",
            "dual licensed by easylist.to under the GNU GPL version 3 or",
            "later and Creative Commons Attribution-ShareAlike 3.0 or later,",
            "see https://easylist.to/pages/licence.html.",
        ]
    if licence_text:
        lines += [
            "",
            f"The full licence text follows, as served on {fetched_at} from",
            output.licence.text_url,
            "",
            "-" * 72,
            "",
            licence_text.rstrip(),
        ]
    return "\n".join(lines) + "\n"


def regional_index(builds: list[ListBuild]) -> list[dict]:
    """index.json: the regional lists that were written, in a fixed order."""
    return [
        {
            "id": build.output.regional_id,
            "title": build.output.title,
            "locales": list(build.output.locales),
            "licence": build.output.licence.spdx,
            "source": build.output.sources[0].url,
        }
        for build in builds
    ]


def write_text(path: str, text: str) -> str:
    """Writes UTF-8 with LF line ends and returns the SHA-256 written."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = text.encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest()


def read_manifest(path: str) -> dict:
    """The sources.json already there, or an empty one."""
    try:
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        return {}
    return manifest if isinstance(manifest, dict) else {}


def manifest_entry(build: ListBuild, sha256: str, fetched_at: str) -> dict:
    return {
        "sha256": sha256,
        "bytes": len(build.result.text.encode("utf-8")),
        "rules": build.result.entries,
        "fetched": fetched_at,
        "licence": build.output.licence.spdx,
        "licence_url": build.output.licence.url,
        "notice": build.output.notice,
        "sources": build.files,
    }


def build_all(fetch=fetch_url, regional: bool = True) -> list[ListBuild]:
    """Every list but easylist.txt, in the order they are written."""
    outputs = [UBO, COOKIES, *(REGIONAL if regional else ())]
    return [build_output_list(output, fetch) for output in outputs]


def main(argv: list[str] | None = None, fetch=fetch_url, now=None) -> int:
    """Fetches everything and writes what validated.

    The fetch and the clock are parameters so tests can run all of this
    without the network.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument(
        "--no-regional",
        action="store_true",
        help="leave the optional regional lists as they are",
    )
    args = ap.parse_args(argv)
    fetched_at = utc_stamp(now or datetime.datetime.now(datetime.UTC))
    failed = False

    dest_dir = os.path.join(args.out, "boring")
    manifest_path = os.path.join(dest_dir, "sources.json")
    manifest = read_manifest(manifest_path)
    lists = manifest.get("lists")
    if not isinstance(lists, dict):
        lists = {}

    # EasyList and EasyPrivacy, built and written exactly as before.
    easylist_files: list[dict] = []
    built = build_filter_list(fetch=recording(fetch, easylist_files))
    for source in built.sources:
        state = f"{source.entries} rules" if source.ok else f"FAILED, {source.reason}"
        print(f"  {source.name}: {state}")

    if not built.healthy:
        print("no filter source came back usable, not writing a list")
        failed = True
    else:
        os.makedirs(dest_dir, exist_ok=True)
        out_path = os.path.join(dest_dir, "easylist.txt")
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(built.text)
        print("wrote", out_path, "with", built.entries, "rules")
        if built.degraded:
            print("WARNING: written from some sources only,", built.describe_failures())
        with open(out_path, "rb") as f:
            data = f.read()
        lists["easylist.txt"] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "rules": built.entries,
            "fetched": fetched_at,
            "licence": EASYLIST_DUAL.spdx,
            "licence_url": EASYLIST_DUAL.url,
            "sources": easylist_files,
        }

    builds = build_all(fetch, regional=not args.no_regional)

    # The licence texts go into the notices. A list whose licence text
    # cannot be fetched and recognised is not shipped.
    licence_texts: dict[str, str | None] = {}
    for build in builds:
        url = build.output.licence.text_url
        if url and url not in licence_texts:
            try:
                licence_texts[url] = fetch_licence_text(build.output.licence, fetch)
            except FeedError as e:
                print(f"  licence {url}: FAILED, {e}")
                licence_texts[url] = None

    written_regional: list[ListBuild] = []
    for build in builds:
        output = build.output
        for source in build.result.sources:
            state = (
                f"{source.entries} rules" if source.ok else f"FAILED, {source.reason}"
            )
            print(f"  {output.path} {source.name}: {state}")
        for line in build.skipped:
            print(f"  {output.path}: include not followed, {line}")

        licence_text = licence_texts.get(output.licence.text_url or "")
        if output.licence.text_url and licence_text is None:
            print(f"not writing {output.path}: its licence text is missing")
            failed = True
            continue
        if not build.complete:
            print(f"not writing {output.path}:", build.result.describe_failures())
            failed = True
            continue

        out_path = os.path.join(dest_dir, *output.path.split("/"))
        sha256 = write_text(out_path, build.result.text)
        write_text(
            os.path.join(args.out, output.notice),
            notice_text(build, fetched_at, licence_text),
        )
        lists[output.path] = manifest_entry(build, sha256, fetched_at)
        print("wrote", out_path, "with", build.result.entries, "rules")
        if output.regional_id:
            written_regional.append(build)

    if not args.no_regional:
        regional_dir = os.path.join(dest_dir, "regional")
        os.makedirs(regional_dir, exist_ok=True)
        # A list that is no longer written must not linger and be
        # packaged: the installer takes every file the pattern matches.
        keep = {build.output.path for build in written_regional}
        for stale in glob.glob(os.path.join(regional_dir, "*.txt")):
            path = "regional/" + os.path.basename(stale)
            if path not in keep:
                os.remove(stale)
                lists.pop(path, None)
                print("removed", stale)
        notices = {build.output.notice for build in written_regional}
        for stale in glob.glob(os.path.join(args.out, "NOTICES-regional-*.txt")):
            if os.path.basename(stale) not in notices:
                os.remove(stale)
                print("removed", stale)
        index = regional_index(written_regional)
        index_path = os.path.join(regional_dir, "index.json")
        write_text(index_path, json.dumps(index, indent=2, ensure_ascii=False) + "\n")
        print("wrote", index_path, "with", len(index), "lists")

    manifest["generated"] = fetched_at
    manifest["lists"] = dict(sorted(lists.items()))
    write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
    print("wrote", manifest_path)

    if failed:
        print("FAILED: a list above is missing or unusable")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
