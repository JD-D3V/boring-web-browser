"""upstream_watch.py: tag ordering, reading the stable channel and the
release posts, and deciding what to do with the one issue. Offline."""

import os
import sys
from datetime import UTC, datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import upstream_watch as uw  # noqa: E402


def test_latest_tag_is_by_version_not_by_text():
    names = [
        "157.0.8103.38-1.1",
        "157.0.8103.50-1.1",
        "157.0.8103.9-1.1",
        "156.0.8078.79-1.1",
        "157.0.8103.50-1.2",
        "nightly",
    ]
    assert uw.pick_latest(names) == "157.0.8103.50-1.2"
    assert uw.parse_tag("157.0.8103.50-1") == (157, 0, 8103, 50, 1, 0)
    assert uw.parse_tag("v157") is None
    assert uw.pick_latest(["x"]) is None
    assert uw.chromium_of("157.0.8103.50-1.1") == "157.0.8103.50"


def test_current_tag_skips_comments(tmp_path):
    f = tmp_path / "UPSTREAM_VERSION"
    f.write_text("# comment\n\n157.0.8103.38-1.1\n", encoding="utf-8")
    assert uw.read_current(f) == "157.0.8103.38-1.1"
    f.write_text("# only a comment\n", encoding="utf-8")
    with pytest.raises(ValueError):
        uw.read_current(f)


def test_the_repo_records_a_tag():
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert uw.parse_tag(uw.read_current(os.path.join(here, "UPSTREAM_VERSION")))


RELEASES = [
    {
        "version": "158.0.8127.18",
        "fraction": 0.005,
        "serving": {"startTime": "2026-11-04T18:02:22Z"},
    },
    {"version": "157.0.8103.79", "serving": {"startTime": "2026-11-11T19:50:36Z"}},
    {"version": "157.0.8103.50", "serving": {"startTime": "2026-11-09T21:00:00Z"}},
    {"version": "157.0.8103.38", "serving": {"startTime": "2026-11-03T21:00:00Z"}},
]


def test_stable_summary_finds_newest_and_first_newer():
    s = uw.stable_summary(RELEASES, "157.0.8103.38")
    assert s["newest"] == "158.0.8127.18"
    assert s["everyone"] == "157.0.8103.79"
    assert s["first_newer_start"] == "2026-11-04T18:02:22Z"
    assert uw.stable_summary(RELEASES, "159.0.1.1")["first_newer_start"] is None


def post(title, body, date="2026-11-09"):
    return {
        "title": {"$t": title},
        "published": {"$t": date + "T12:00:00.000-08:00"},
        "content": {"$t": body},
        "link": [{"rel": "alternate", "href": f"https://example.invalid/{date}"}],
    }


FEED = {
    "feed": {
        "entry": [
            post(
                "Stable Channel Update for Desktop",
                "<p>The Stable channel has been updated to 157.0.8103.78/.79 for Windows."
                "</p> This update includes 83 security fixes. CVE-2026-1 CVE-2026-2 "
                "Google is aware that an exploit for CVE-2026-1 exists in the wild.",
                "2026-11-11",
            ),
            post(
                "Stable Channel Update for Desktop",
                "updated to 157.0.8103.50/.51 for Windows. This update includes 9 security "
                "fixes. CVE-2026-3 CVE-2026-3 CVE-2026-4",
            ),
            post(
                "Extended Stable Update for Desktop",
                "updated to 156.0.8078.96. includes 11 security fixes.",
            ),
            post(
                "Stable Channel Update for Desktop",
                "updated to 157.0.8103.38. includes 4 security fixes.",
            ),
        ]
    }
}


def test_security_posts_between_our_version_and_the_tag():
    posts = uw.security_posts(FEED)
    assert len(posts) == 3  # the Extended Stable post is not ours
    picked = uw.security_between(posts, "157.0.8103.38", "157.0.8103.50")
    assert [p["version"] for p in picked] == ["157.0.8103.50"]
    assert picked[0]["fixes"] == 9 and picked[0]["cves"] == 2
    assert not picked[0]["in_the_wild"]
    newer = uw.security_between(posts, "157.0.8103.38", "157.0.8103.79")
    assert [p["version"] for p in newer] == ["157.0.8103.50", "157.0.8103.78"]
    assert newer[1]["in_the_wild"]


def test_issue_says_how_far_behind_and_what_security_fixes():
    now = datetime(2026, 11, 12, 6, 0, tzinfo=UTC)
    stable = uw.stable_summary(RELEASES, "157.0.8103.38")
    posts = uw.security_between(
        uw.security_posts(FEED), "157.0.8103.38", "157.0.8103.79"
    )
    title, body = uw.issue_text(
        "157.0.8103.38-1.1", "157.0.8103.79-1.1", 2, stable, posts, now
    )
    assert (
        title
        == "Upstream: ungoogled-chromium 157.0.8103.79-1.1 is out (we are on 157.0.8103.38-1.1)"
    )
    assert uw.MARKER in body
    assert "same major, newer build; 2 tag(s) newer" in body
    assert "7 day(s) ago" in body
    assert "at 157.0.8103.79 (158.0.8127.18 rolling out)" in body
    assert "Total stated: 92 security fixes." in body
    assert "exploited in the wild" in body
    _, unknown = uw.issue_text(
        "157.0.8103.38-1.1", "158.0.8127.20-1.1", 3, {}, None, now
    )
    assert "1 major version(s) ahead" in unknown
    assert "could not be read today" in unknown


def test_plan_keeps_one_issue():
    now = datetime(2026, 11, 12, tzinfo=UTC)
    title, body = uw.issue_text(
        "157.0.8103.38-1.1", "157.0.8103.50-1.1", 1, {}, [], now
    )
    later = body.replace("2026-11-12 00:00", "2026-11-13 00:00")
    assert uw.plan(None, True, title, body) == "create"
    existing = {"title": title, "body": later, "number": 7}
    assert uw.plan(existing, True, title, body) == "none"  # only the timestamp moved
    assert uw.plan(existing, True, title.replace("50", "51"), body) == "update"
    assert uw.plan(existing, False, None, None) == "close"
    assert uw.plan(None, False, None, None) == "none"


BOT_USER = {"login": "github-actions[bot]"}


def test_find_issue_skips_pull_requests_and_strangers():
    issues = [
        {"number": 1, "body": uw.MARKER, "pull_request": {}, "user": BOT_USER},
        {"number": 2, "body": "something else", "user": BOT_USER},
        {"number": 3, "body": "x\n" + uw.MARKER, "user": BOT_USER},
    ]
    assert uw.find_issue(issues)["number"] == 3
    assert uw.find_issue(issues[:2]) is None


def test_find_issue_ignores_a_marker_pasted_by_someone_else():
    forged = [
        {"number": 4, "body": uw.MARKER, "user": {"login": "someone"}},
        {"number": 5, "body": uw.MARKER, "user": {"login": "github-actions"}},
        {"number": 6, "body": uw.MARKER},
        {"number": 7, "body": uw.MARKER, "user": None},
    ]
    assert uw.find_issue(forged) is None
    assert uw.find_issue(forged + [{"number": 8, "body": uw.MARKER, "user": BOT_USER}])[
        "number"
    ] == 8
