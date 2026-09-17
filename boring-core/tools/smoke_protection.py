#!/usr/bin/env python3
"""Check the Protection page tells the truth and its switches work.

Opens chrome://boring-protection in a throwaway profile. Checks that
both protections report a real state, that Senior Safe Mode turns on,
asks before it turns off, and survives a reload, and that turning it on
forces sponsored results hidden. Screenshots go to artifacts/ui-implemented.
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


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="protection-", dir=OUT) as profile:
        with Browser(user_data_dir=profile, args=["--window-size=1360,900"]) as b:
            b.get("chrome://boring-protection")
            checks["scam protection reports on"] = wait_for(
                b, "document.getElementById('scam-state').textContent==='On'"
            )
            checks["ad blocking reports on"] = wait_for(
                b, "document.getElementById('ads-state').textContent==='On'"
            )
            checks["senior mode starts off"] = b.run(
                "return !document.getElementById('senior').checked"
            )
            b.screenshot(str(OUT / "protection-light.png"))

            b.run("document.getElementById('senior').click()")
            checks["senior mode turns on"] = wait_for(
                b,
                "document.getElementById('senior').checked && "
                "document.getElementById('hide-ads').checked && "
                "document.getElementById('hide-ads').disabled",
            )

            b.run("document.getElementById('senior').click()")
            checks["turning off asks first"] = b.run(
                "return document.getElementById('senior').checked && "
                "!document.getElementById('confirm-off').classList"
                ".contains('hidden') && "
                "document.activeElement.id==='keep-on'"
            )
            b.screenshot(str(OUT / "protection-confirm-off.png"))
            b.run("document.getElementById('keep-on').click()")
            checks["keep it on keeps it on"] = b.run(
                "return document.getElementById('senior').checked && "
                "document.getElementById('confirm-off').classList"
                ".contains('hidden')"
            )

            b.get("chrome://boring-protection")
            checks["senior mode survives a reload"] = wait_for(
                b, "document.getElementById('senior').checked"
            )

            b.run("document.getElementById('senior').click()")
            b.run("document.getElementById('turn-off').click()")
            checks["turn it off turns it off"] = wait_for(
                b,
                "!document.getElementById('senior').checked && "
                "!document.getElementById('hide-ads').disabled",
            )

        with Browser(
            user_data_dir=profile,
            args=["--senior-safe-mode", "--window-size=1360,900"],
        ) as b:
            b.get("chrome://boring-protection")
            checks["switch locks senior mode on"] = wait_for(
                b,
                "document.getElementById('senior').checked && "
                "document.getElementById('senior').disabled",
            )

    (OUT / "protection-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
