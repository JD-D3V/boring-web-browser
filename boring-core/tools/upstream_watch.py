#!/usr/bin/env python3
"""Notice a newer ungoogled-chromium-windows tag and keep one issue about it.

Run daily by .github/workflows/upstream-watch.yml. Compares the newest
tag upstream with boring-core/UPSTREAM_VERSION, reads Chrome's stable
channel and Google's release posts to say how far behind we are and
whether the newer release carries security fixes, then opens or updates
ONE issue (found by a marker in its body). When we have caught up, that
issue is closed.

Only public JSON endpoints; the GitHub token is sent to api.github.com
and nowhere else. --dry-run prints the issue instead of writing it.

  python upstream_watch.py --repo JD-D3V/boring-web-browser --dry-run
"""

import argparse
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime

UPSTREAM = "ungoogled-software/ungoogled-chromium-windows"
TAGS_URL = f"https://api.github.com/repos/{UPSTREAM}/tags?per_page=100"
STABLE_URL = (
    "https://versionhistory.googleapis.com/v1/chrome/platforms/win64/channels/"
    "stable/versions/all/releases?order_by=version%20desc&pageSize=40"
)
POSTS_URL = (
    "https://chromereleases.googleblog.com/feeds/posts/default?alt=json"
    "&max-results=50&q=%22Stable+Channel+Update+for+Desktop%22"
)
MARKER = "<!-- upstream-watch -->"
BOT = "github-actions[bot]"
CHECKED = "Last checked:"
TAG_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+)-(\d+)(?:\.(\d+))?$")
VERSION_RE = re.compile(r"\b(\d{2,4}\.\d+\.\d{3,5}\.\d+)\b")
POST_URL_RE = re.compile(r"^https://chromereleases\.googleblog\.com/[A-Za-z0-9._~/%?=&-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MD_SPECIAL_RE = re.compile(r"([\\`*_{}\[\]()#+!|<>@~&])")


def md_escape(text):
    """Backslash-escape what Markdown or an @mention would act on."""
    return MD_SPECIAL_RE.sub(r"\\\1", str(text))


def parse_tag(tag):
    """'157.0.8103.50-1.1' -> (157, 0, 8103, 50, 1, 1), or None."""
    m = TAG_RE.match(tag.strip())
    if not m:
        return None
    return tuple(int(g) if g is not None else 0 for g in m.groups())


def chromium_of(tag):
    """The Chromium version inside a tag: '157.0.8103.50-1.1' -> '157.0.8103.50'."""
    return tag.split("-", 1)[0]


def vtuple(version):
    return tuple(int(p) for p in version.split("."))


def pick_latest(names):
    """The highest release tag among names; None if there is none."""
    tags = [n for n in names if parse_tag(n)]
    return max(tags, key=parse_tag) if tags else None


def read_current(path):
    """The tag recorded in UPSTREAM_VERSION: first line that is not a comment."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if not parse_tag(line):
                    raise ValueError(f"{path}: {line!r} is not a tag")
                return line
    raise ValueError(f"{path}: no tag in it")


def get_json(url, token=None):
    req = urllib.request.Request(url, headers={"User-Agent": "boring-upstream-watch"})
    if token and urllib.parse.urlsplit(url).hostname == "api.github.com":
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def fetch_tags(token=None):
    return [t["name"] for t in get_json(TAGS_URL, token)]


def stable_summary(releases, ours):
    """Chrome stable for Windows against our Chromium version.

    releases: the "releases" list of the versionhistory API. A release
    serving to a small fraction (an early roll out) still counts as out.
    """
    ours_t = vtuple(ours)
    newest, everyone, first_newer = None, None, None
    for r in releases:
        v = r.get("version", "")
        if not VERSION_RE.fullmatch(v):
            continue
        if newest is None or vtuple(v) > vtuple(newest):
            newest = v
        if r.get("fraction", 1) >= 1 and (
            everyone is None or vtuple(v) > vtuple(everyone)
        ):
            everyone = v
        start = (r.get("serving") or {}).get("startTime", "")
        if (
            vtuple(v) > ours_t
            and start
            and (first_newer is None or start < first_newer)
        ):
            first_newer = start
    return {"newest": newest, "everyone": everyone, "first_newer_start": first_newer}


def _text(entry, key):
    return (entry.get(key) or {}).get("$t", "")


def security_posts(feed):
    """Desktop stable posts from the Chrome Releases feed, with their fixes."""
    out = []
    for e in (feed.get("feed") or {}).get("entry", []):
        title = _text(e, "title")
        if not title.startswith("Stable Channel Update for Desktop"):
            continue
        body = re.sub(
            r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", _text(e, "content")))
        )
        version = VERSION_RE.search(body)
        fixes = re.search(r"includes (\d+) security fix", body)
        link = next(
            (x.get("href") for x in e.get("link", []) if x.get("rel") == "alternate"),
            "",
        )
        # The feed is not ours: keep a link only if it is a plain page of
        # the Chrome Releases blog, and a date only if it is a date.
        date = _text(e, "published")[:10]
        link = link if POST_URL_RE.match(link or "") else ""
        out.append(
            {
                "date": date if DATE_RE.match(date) else "",
                "version": version.group(1) if version else None,
                "fixes": int(fixes.group(1)) if fixes else None,
                "cves": len(set(re.findall(r"CVE-\d{4}-\d+", body))),
                "in_the_wild": bool(
                    re.search(r"exploit for CVE-\d{4}-\d+ exists in the wild", body)
                ),
                "url": link,
            }
        )
    return out


def security_between(posts, ours, theirs):
    """Posts for versions after ours, up to and including the new tag's."""
    lo, hi = vtuple(ours), vtuple(theirs)
    picked = [p for p in posts if p["version"] and lo < vtuple(p["version"]) <= hi]
    picked.sort(key=lambda p: vtuple(p["version"]))
    return picked


def issue_text(current, latest, newer_tags, stable, posts, now):
    """Title and body of the one issue."""
    ours, theirs = chromium_of(current), chromium_of(latest)
    majors = parse_tag(latest)[0] - parse_tag(current)[0]
    span = f"{majors} major version(s) ahead" if majors else "same major, newer build"
    lines = [
        MARKER,
        f"We build on **{current}** (boring-core/UPSTREAM_VERSION).",
        f"Newest ungoogled-chromium-windows tag: **{latest}** ({span}; "
        f"{newer_tags} tag(s) newer than ours).",
    ]
    if stable.get("newest"):
        line = f"Chrome stable for Windows is at {stable.get('everyone') or stable['newest']}"
        if stable.get("everyone") and stable["newest"] != stable["everyone"]:
            line += f" ({stable['newest']} rolling out)"
        line += "."
        if stable.get("first_newer_start"):
            try:
                started = datetime.fromisoformat(
                    stable["first_newer_start"].replace("Z", "+00:00")
                )
                line += (
                    f" The first Chrome newer than ours went out {started:%Y-%m-%d}, "
                    f"{(now - started).days} day(s) ago."
                )
            except (ValueError, TypeError, AttributeError):
                pass  # a start time we cannot read is left out, not a crash
        lines.append(line)
    else:
        lines.append("Chrome stable for Windows: could not be read today.")
    lines += ["", "Security fixes between our version and the new tag:"]
    if posts is None:
        lines.append("- unknown: the Chrome Releases feed could not be read today.")
    elif not posts:
        lines.append(
            f"- no Stable Desktop post found for versions after {ours} up to {theirs}."
        )
    else:
        total = 0
        for p in posts:
            fixes = "an unstated number of" if p["fixes"] is None else str(p["fixes"])
            total += p["fixes"] or 0
            wild = " One is exploited in the wild." if p["in_the_wild"] else ""
            when = f" ({md_escape(p['date'])})" if p["date"] else ""
            url = f" <{p['url']}>" if p["url"] else ""  # checked in security_posts
            lines.append(
                f"- {md_escape(p['version'])}{when}: {fixes} security fixes, "
                f"{p['cves']} CVEs.{wild}{url}"
            )
        lines.append(f"Total stated: {total} security fixes.")
    lines += [
        "",
        "To move to it (see boring-core/tools/BUMP.txt):",
        "```",
        f"python boring-core/tools/bump.py --tag {latest} --dir E:\\ung-{theirs} "
        "--prev <current tree> --branch <bump branch>",
        "```",
        "",
        f"{CHECKED} {now:%Y-%m-%d %H:%M} UTC by the upstream-watch workflow.",
    ]
    title = f"Upstream: ungoogled-chromium {latest} is out (we are on {current})"
    return title, "\n".join(lines) + "\n"


def without_checked(body):
    return "\n".join(
        ln for ln in (body or "").splitlines() if not ln.startswith(CHECKED)
    )


def plan(existing, behind, title, body):
    """What to do with the issue: 'create', 'update', 'close' or 'none'."""
    if not behind:
        return "close" if existing else "none"
    if not existing:
        return "create"
    same = existing.get("title") == title and without_checked(
        existing.get("body")
    ) == without_checked(body)
    return "none" if same else "update"


def find_issue(issues):
    """The open issue this watcher owns: the marker in its body AND opened
    by the Actions bot. Anyone can paste the marker into an issue on a
    public repo; the watcher must not rewrite or close those."""
    for i in issues:
        if (
            "pull_request" not in i
            and MARKER in (i.get("body") or "")
            and (i.get("user") or {}).get("login") == BOT
        ):
            return i
    return None


def github(method, path, token, payload=None):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "boring-upstream-watch",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--current", default="boring-core/UPSTREAM_VERSION")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN")
    if not args.dry_run and not (token and args.repo):
        sys.exit("needs --repo and GITHUB_TOKEN, or --dry-run")

    current = read_current(args.current)
    names = fetch_tags(token)
    latest = pick_latest(names)
    if latest is None:
        sys.exit("upstream lists no release tags")
    newer = sorted(
        {n for n in names if parse_tag(n) and parse_tag(n) > parse_tag(current)}
    )
    behind = bool(newer)
    print(f"ours {current}, newest upstream {latest}, {len(newer)} newer")

    title = body = None
    if behind:
        now = datetime.now(UTC)
        try:
            stable = stable_summary(
                get_json(STABLE_URL).get("releases", []), chromium_of(current)
            )
        except (OSError, ValueError) as err:
            print("stable channel not read:", err)
            stable = {}
        try:
            posts = security_between(
                security_posts(get_json(POSTS_URL)),
                chromium_of(current),
                chromium_of(latest),
            )
        except (OSError, ValueError) as err:
            print("release posts not read:", err)
            posts = None
        title, body = issue_text(current, latest, len(newer), stable, posts, now)

    if args.dry_run:
        print(title or "up to date, no issue")
        print(body or "")
        return 0

    issues = github("GET", f"/repos/{args.repo}/issues?state=open&per_page=100", token)
    existing = find_issue(issues)
    action = plan(existing, behind, title, body)
    print("issue:", action)
    if action == "create":
        made = github(
            "POST", f"/repos/{args.repo}/issues", token, {"title": title, "body": body}
        )
        print("opened", made.get("html_url"))
    elif action == "update":
        github(
            "PATCH",
            f"/repos/{args.repo}/issues/{existing['number']}",
            token,
            {"title": title, "body": body},
        )
        print("updated", existing.get("html_url"))
    elif action == "close":
        github(
            "PATCH",
            f"/repos/{args.repo}/issues/{existing['number']}",
            token,
            {"state": "closed", "state_reason": "completed"},
        )
        print("closed", existing.get("html_url"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
