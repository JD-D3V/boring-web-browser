#!/usr/bin/env python3
"""Capture page UI and test search filtering without visiting a scam site.

Usage: python boring-core/tools/capture_ui_baseline.py
Screenshots capture web content, not the native browser toolbar.
AI states are rendering fixtures; no provider is contacted.
"""

import json
import re
import tempfile
import time
import urllib.error
from pathlib import Path

from drive import Browser

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "ui-baseline"


def color_scheme(b, theme):
    """Emulate the system light or dark setting. None puts it back."""
    features = [{"name": "prefers-color-scheme", "value": theme}] if theme else []
    b._req(
        "POST",
        f"/session/{b.sid}/goog/cdp/execute",
        {"cmd": "Emulation.setEmulatedMedia", "params": {"features": features}},
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"capture_scope": "page content only", "checks": {}}
    checks = report["checks"]
    script_source = (
        ROOT / "boring-core/components/boring/serp/serp_tab_helper.cc"
    ).read_text()
    script = re.search(r'kScript\[\] = R"\((.*?)\)";', script_source, re.S).group(1)
    with tempfile.TemporaryDirectory(prefix="baseline-", dir=OUT) as profile:
        with Browser(user_data_dir=profile, args=["--window-size=1360,900"]) as b:
            report["browser"] = b.run("return navigator.userAgent")
            for name, url in [
                ("new-tab", "chrome://newtab"),
                ("settings", "chrome://settings"),
                ("ai-settings", "chrome://boring-ai"),
            ]:
                b.get(url)
                time.sleep(1)
                b.screenshot(str(OUT / f"{name}.png"))
            checks["ai_off_by_default"] = b.run(
                "return document.getElementById('p-off').checked"
            )
            for state in ["waiting", "working", "done", "failed"]:
                try:
                    b.run(
                        "window.loadSummaryState(arguments[0])",
                        [
                            {
                                "state": state,
                                "title": "A quieter web",
                                "provider": "ollama",
                                "destination": "Ollama on your own computer",
                                "local": True,
                                "textLength": 4200,
                                "summary": "Local rendering fixture. Nothing was sent.",
                                "error": "The selected service could not be reached.",
                            }
                        ],
                    )
                    checks[f"ai_{state}_render"] = True
                except urllib.error.HTTPError as error:
                    checks[f"ai_{state}_render"] = json.loads(error.read())["value"][
                        "message"
                    ]
                b.screenshot(str(OUT / f"ai-{state}-fixture.png"))
            b.get("http://boring-scam-test.invalid/")
            text = b.run("return document.body.innerText")
            checks["listed_site_blocked"] = "This site looks dangerous" in text
            checks["normal_mode_continue_visible"] = "continue anyway" in text
            checks["warning_button_uses_page_font"] = b.run(
                "return getComputedStyle(document.querySelector('.safe')).fontFamily"
                "===getComputedStyle(document.body).fontFamily"
            )
            b.screenshot(str(OUT / "scam-warning.png"))
            color_scheme(b, "dark")
            checks["warning_follows_dark_mode"] = (
                b.run("return getComputedStyle(document.body).backgroundColor")
                == "rgb(28, 36, 34)"
            )
            b.screenshot(str(OUT / "scam-warning-dark.png"))
            color_scheme(b, None)
            # Execute the exact production script against controlled markup.
            # This tests DOM behavior, not Google/Bing selector coverage.
            for hide in [False, True]:
                b.get(
                    "data:text/html,<title>Controlled search fixture</title>"
                    "<main><div id='tads'>Sponsored offer</div>"
                    "<div id='organic'>Ordinary result</div></main>"
                )
                b.run(script.replace("%HIDE%", str(hide).lower()))
                result = b.run(
                    "var ad=document.getElementById('tads');"
                    "var organic=document.getElementById('organic');"
                    "return {hidden:getComputedStyle(ad).display==='none',"
                    "label:ad.innerText.includes('Sponsored result'),"
                    "organic:getComputedStyle(organic).display!=='none'}"
                )
                checks[f"search_{'hide' if hide else 'label'}_fixture"] = result
                b.run(
                    "var ad=document.createElement('div');ad.className='b_ad';"
                    "ad.textContent='Later sponsored offer';document.body.append(ad)"
                )
                time.sleep(0.2)
                checks[f"search_dynamic_{hide}"] = b.run(
                    "var ad=document.querySelector('.b_ad');"
                    "return getComputedStyle(ad).display==='none'"
                    if hide
                    else "return !!document.querySelector('.b_ad')"
                    ".dataset.boringLabeled"
                )
                b.screenshot(str(OUT / f"search-{'hidden' if hide else 'labeled'}.png"))
        with Browser(
            user_data_dir=profile, args=["--senior-safe-mode", "--window-size=1360,900"]
        ) as b:
            b.get("http://boring-scam-test.invalid/")
            text = b.run("return document.body.innerText")
            checks["senior_blocks_without_bypass"] = (
                "This site looks dangerous" in text and "continue anyway" not in text
            )
            b.screenshot(str(OUT / "scam-warning-senior.png"))
    (OUT / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
