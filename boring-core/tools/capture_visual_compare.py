#!/usr/bin/env python3
r"""Headless pictures of the same pages on one build, for the 154 against 157
visual comparison (ledger 100). Run once per build, then combine.py (kept
beside the output) puts the two side by side.

  set BORING_OUT=E:\ung-154\build\src\out\Default   (or E:\ung-157\...)
  python capture_visual_compare.py --label b154 --out E:\tmp\r3-visual-compare

Everything is headless: WebDriver screenshots of the page, fresh profile
per colour scheme, the same window size on both builds. No window opens, no
desktop capture. The scam warning and look-alike pages come from the local
test hosts of smoke_scam.py and smoke_lookalike.py. Writes
OUT/LABEL/<light|dark>/<name>.png and OUT/LABEL/report.json (what each page
actually showed, so a page that did not load as meant is visible).
"""

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

import drive
from drive import Browser
from smoke_local import HTML, Pages, list_folder, wait_for
from smoke_lookalike import NO_TARGET, PLAIN, WARNED, Recorder, browser_args
from smoke_lookalike import open_url as open_lookalike
from smoke_scam import LISTED, SAFE_PAGE, SCAM_LIST, args_for, open_url

SIZE = "--window-size=1360,900"

SCHEMES = (("light", []), ("dark", ["--force-dark-mode"]))

# (name, url). Same list on both builds; a page one build does not have shows
# up as its error page, which the report records.
WEBUI = [
    ("settings-main", "chrome://settings"),
    ("settings-appearance", "chrome://settings/appearance"),
    ("settings-privacy", "chrome://settings/privacy"),
    ("settings-protection", "chrome://settings/protection"),
    ("settings-reading", "chrome://settings/reading"),
    ("settings-summaries", "chrome://settings/summaries"),
    ("protection", "chrome://boring-protection"),
    ("welcome", "chrome://boring-welcome"),
    ("new-tab", "chrome://newtab"),
    ("boring-new-tab", "chrome://boring-newtab"),
    ("takeover", "chrome://boring-takeover/?site=example.com"),
]


def probe(b):
    return b.run(
        "return {title: document.title, dark: matchMedia('(prefers-color-scheme: dark)').matches,"
        " url: location.href, w: innerWidth, h: innerHeight,"
        " text: (document.body ? document.body.innerText : '').slice(0, 160)}"
    )


def shoot(b, out_dir, name, report, scheme, settle=2.5):
    time.sleep(settle)
    path = out_dir / f"{name}.png"
    b.screenshot(str(path))
    try:
        info = probe(b)
    except Exception as e:  # a page that cannot run script
        info = {"error": repr(e)}
    report[f"{scheme}/{name}"] = info
    print(
        f"  {scheme}/{name}: {info.get('title')!r} dark={info.get('dark')}", flush=True
    )


def webui(out, scheme, extra, report):
    d = out / scheme
    d.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(
            prefix="vc-", dir=os.environ.get("TMP") or None
        ) as profile,
        Browser(user_data_dir=profile, args=[SIZE, *extra]) as b,
    ):
        for name, url in WEBUI:
            try:
                b.get(url)
            except Exception as e:
                print(f"  {name}: navigation error {e!r}")
            shoot(b, d, name, report, scheme)


def scam(out, scheme, extra, report):
    d = out / scheme
    pages = Pages({"/": (SAFE_PAGE, HTML)})
    try:
        with (
            list_folder({"scamlist.txt": SCAM_LIST}) as lists,
            tempfile.TemporaryDirectory(
                prefix="vc-scam-", dir=os.environ.get("TMP") or None
            ) as profile,
            Browser(user_data_dir=profile, args=args_for(lists, pages, extra)) as b,
        ):
            b.get("chrome://boring-protection")
            wait_for(
                b,
                "document.body.innerText.includes('blocked before they open')",
                20000,
            )
            open_url(b, f"http://{LISTED}:{pages.port}/")
            time.sleep(1)
            shoot(b, d, "scam-warning", report, scheme)
    finally:
        pages.close()


def lookalike(out, scheme, extra, report):
    d = out / scheme
    server = Recorder()
    try:
        with (
            tempfile.TemporaryDirectory(
                prefix="vc-look-", dir=os.environ.get("TMP") or None
            ) as profile,
            Browser(user_data_dir=profile, args=browser_args(extra)) as b,
        ):
            for word, host in (
                ("lookalike-site", PLAIN[0]),
                ("lookalike-no-site", NO_TARGET),
            ):
                open_lookalike(b, f"http://{host}:{server.port}/")
                wait_for(b, WARNED)
                shoot(b, d, word, report, scheme, settle=1.5)
    finally:
        server.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", nargs="*", choices=("webui", "scam", "lookalike"))
    args = ap.parse_args()
    out = Path(args.out) / args.label
    out.mkdir(parents=True, exist_ok=True)
    print("chrome:", drive.CHROME)
    report = {"chrome": drive.CHROME}
    for scheme, extra in SCHEMES:
        for fn in (webui, scam, lookalike):
            if args.only and fn.__name__ not in args.only:
                continue
            try:
                fn(out, scheme, extra, report)
            except Exception as e:
                report[f"{scheme}/{fn.__name__}"] = {"error": repr(e)}
                print(f"  {scheme}/{fn.__name__}: ERROR {e!r}", flush=True)
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("report:", out / "report.json")


if __name__ == "__main__":
    main()
