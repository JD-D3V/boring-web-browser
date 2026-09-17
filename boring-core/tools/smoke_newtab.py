#!/usr/bin/env python3
"""Check the new tab page.

A fresh profile's new tab should be our page, say protection is on, and
let a person add and remove shortcuts. Only web addresses may become
shortcuts, never script or local files. Screenshots go to
artifacts/ui-implemented.
"""

import json
import sys
import tempfile
from pathlib import Path

from drive import Browser

OUT = Path(__file__).resolve().parents[2] / "artifacts/ui-implemented"


def wait_for(b, condition, timeout_ms=5000):
    """True once the JavaScript expression holds, false at the timeout."""
    return b.run_async(
        """
      const [condition, limit, done] = arguments;
      const deadline = performance.now() + limit;
      function check() {
        const ok = !!eval(condition);
        if (ok || performance.now() > deadline) done(ok);
        else setTimeout(check, 50);
      }
      check();
    """,
        [condition, timeout_ms],
    )


def add(b, title, url):
    b.run(
        "document.getElementById('add-open').click();"
        "document.getElementById('add-title').value=arguments[0];"
        "document.getElementById('add-url').value=arguments[1];"
        "document.getElementById('add-form').requestSubmit()",
        [title, url],
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    with (
        tempfile.TemporaryDirectory(prefix="newtab-", dir=OUT) as profile,
        Browser(user_data_dir=profile, args=["--window-size=1360,900"]) as b,
    ):
        b.get("chrome://newtab")
        checks["new tab is our page"] = wait_for(b, "location.host==='boring-newtab'")
        checks["protection line says on"] = wait_for(
            b,
            "document.getElementById('protection-text').textContent"
            ".startsWith('Scam and ad protection is on')",
        )
        checks["starts with no shortcuts"] = b.run(
            "return document.querySelectorAll('#shortcuts a').length===0"
        )
        b.screenshot(str(OUT / "newtab-empty.png"))

        add(b, "Script", "javascript:alert(1)")
        checks["script address is refused"] = wait_for(
            b,
            "!document.getElementById('add-bad').classList.contains('hidden')"
            " && document.querySelectorAll('#shortcuts a').length===0",
        )
        b.run("document.getElementById('add-cancel').click()")

        add(b, "Example", "example.com")
        checks["web address becomes a shortcut"] = wait_for(
            b,
            "document.querySelector('#shortcuts a') && "
            "document.querySelector('#shortcuts a').href==="
            "'https://example.com/' && "
            "document.getElementById('add-form').classList.contains('hidden')",
        )
        b.screenshot(str(OUT / "newtab-shortcut.png"))

        b.get("chrome://newtab")
        checks["shortcut survives a reload"] = wait_for(
            b, "document.querySelectorAll('#shortcuts a').length===1"
        )
        b.run("document.querySelector('#shortcuts .remove').click()")
        checks["shortcut can be removed"] = wait_for(
            b, "document.querySelectorAll('#shortcuts a').length===0"
        )

    (OUT / "newtab-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
