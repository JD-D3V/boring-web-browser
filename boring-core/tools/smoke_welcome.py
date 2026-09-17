#!/usr/bin/env python3
"""Check the welcome page and the links into our pages from settings.

The test driver starts the browser with --no-first-run, so the welcome
page is opened directly. It must turn Senior Safe Mode on, and must not
offer a way to turn it off. The settings side menu must link to the
Protection and AI pages. Screenshots go to artifacts/ui-implemented.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

from drive import Browser

OUT = Path(__file__).resolve().parents[2] / "artifacts/ui-implemented"

# Settings is built from nested shadow roots.
FIND_DEEP = """
  function find(root, selector) {
    var hit = root.querySelector(selector);
    if (hit) return hit;
    for (var el of root.querySelectorAll('*')) {
      if (el.shadowRoot) {
        hit = find(el.shadowRoot, selector);
        if (hit) return hit;
      }
    }
    return null;
  }
  var link = find(document, arguments[0]);
  return link ? link.getAttribute('href') : null;
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    with (
        tempfile.TemporaryDirectory(prefix="welcome-", dir=OUT) as profile,
        Browser(user_data_dir=profile, args=["--window-size=1360,900"]) as b,
    ):
        b.get("chrome://boring-welcome")
        time.sleep(1)
        checks["welcome offers senior mode"] = b.run(
            "return !document.getElementById('senior-off').classList.contains('hidden')"
        )
        checks["welcome has no way to turn it off"] = b.run(
            "return !document.body.innerText.match(/turn (it|this) off/i)"
        )
        b.screenshot(str(OUT / "welcome.png"))
        b.run("document.getElementById('senior-on').click()")
        time.sleep(1)
        checks["welcome turns senior mode on"] = b.run(
            "return !document.getElementById('senior-done').classList"
            ".contains('hidden')"
        )
        b.get("chrome://boring-protection")
        time.sleep(1)
        checks["protection page agrees"] = b.run(
            "return document.getElementById('senior').checked"
        )

        b.get("chrome://settings")
        time.sleep(3)
        checks["settings links to protection"] = (
            b.run(FIND_DEEP, ["#boringProtectionLink"]) == "chrome://boring-protection"
        )
        checks["settings links to AI"] = (
            b.run(FIND_DEEP, ["#boringAiLink"]) == "chrome://boring-ai"
        )
        b.screenshot(str(OUT / "settings-menu.png"))

    (OUT / "welcome-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
