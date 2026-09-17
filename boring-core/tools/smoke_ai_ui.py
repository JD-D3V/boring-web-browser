#!/usr/bin/env python3
"""Check summary rendering under the real WebUI Trusted Types policy.

Only local rendering fixtures are used. No provider receives page text.
Screenshots and results are saved under artifacts/ui-implemented.
"""

import json
import sys
import tempfile
from pathlib import Path

from drive import Browser

OUT = Path(__file__).resolve().parents[2] / "artifacts/ui-implemented"

# Contrast of a control's edge against the panel behind it. WCAG asks for
# at least 3:1 so a text box can be found without guessing.
CONTRAST = r"""
  function lum(c) {
    return c.match(/[\d.]+/g).slice(0, 3).map(Number).map(function(v) {
      v /= 255;
      return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    }).reduce(function(sum, v, i) {
      return sum + v * [0.2126, 0.7152, 0.0722][i];
    }, 0);
  }
  var box = document.getElementById('api-key');
  var a = lum(getComputedStyle(box).borderTopColor);
  var b = lum(getComputedStyle(box.closest('fieldset')).backgroundColor);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
"""


def wait_for(b, condition, timeout_ms=3000):
    """True once the JavaScript expression holds, false at the timeout."""
    return b.run_async(
        """
      const [condition, limit, done] = arguments;
      const deadline = performance.now() + limit;
      function check() {
        const ok = !!eval(condition);
        if (ok || performance.now() > deadline) done(ok);
        else setTimeout(check, 25);
      }
      check();
    """,
        [condition, timeout_ms],
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    with (
        tempfile.TemporaryDirectory(prefix="ai-ui-", dir=OUT) as profile,
        Browser(user_data_dir=profile, args=["--window-size=1360,900"]) as b,
    ):
        b.get("chrome://boring-ai")
        checks["AI defaults off"] = b.run(
            "return document.getElementById('p-off').checked"
        )
        checks["settings visible when idle"] = b.run(
            "return !document.getElementById('settings-panel')"
            ".classList.contains('hidden')"
        )
        b.screenshot(str(OUT / "ai-settings-light.png"))

        # A rejected key must not be reported as saved.
        b.run(
            "document.getElementById('p-gemini').click();"
            "document.getElementById('api-key').value='not a key';"
            "document.getElementById('save').click()"
        )
        checks["rejected key is not called saved"] = wait_for(
            b,
            "document.getElementById('saved').textContent==="
            "'Other settings saved. The key was not.'",
        )
        checks["rejected key is explained"] = b.run(
            "return !document.getElementById('key-bad').classList"
            ".contains('hidden') && document.getElementById('api-key')"
            ".getAttribute('aria-invalid')==='true'"
        )
        b.run(
            "document.getElementById('p-off').click();"
            "document.getElementById('save').click()"
        )
        checks["plain save says saved"] = wait_for(
            b,
            "document.getElementById('saved').textContent==='Saved' && "
            "document.getElementById('key-bad').classList.contains('hidden')",
        )
        for theme in ["light", "dark"]:
            b._req(
                "POST",
                f"/session/{b.sid}/goog/cdp/execute",
                {
                    "cmd": "Emulation.setEmulatedMedia",
                    "params": {
                        "features": [{"name": "prefers-color-scheme", "value": theme}]
                    },
                },
            )
            for state in ["waiting", "working", "done", "failed"]:
                fixture = {
                    "state": state,
                    "title": "<img src=x onerror=alert(1)>",
                    "provider": "gemini",
                    "destination": "Google Gemini",
                    "local": False,
                    "textLength": 4200,
                    "summary": "<script>unsafe()</script> is literal text.",
                    "error": "A <b>sample</b> error.",
                }
                b.run("window.loadSummaryState(arguments[0])", [fixture])
                checks[f"{theme}/{state} renders"] = b.run(
                    "return !!document.querySelector('#ask h2') && "
                    "!document.getElementById('ask').classList.contains('hidden')"
                )
                checks[f"{theme}/{state} treats content as text"] = b.run(
                    "return !document.querySelector('#ask img, #ask script, #ask b')"
                    " && document.querySelector('#ask .page-name')"
                    ".textContent===arguments[0]",
                    [fixture["title"]],
                )
                checks[f"{theme}/{state} settings secondary"] = b.run(
                    "return document.getElementById('settings-panel')"
                    ".classList.contains('hidden')"
                )
                b.screenshot(str(OUT / f"ai-{state}-{theme}.png"))
                if state == "working":
                    b.run("keepUpToDate('nothing')")
            b.run("window.loadSummaryState({state:'nothing'})")
            checks[f"{theme}/idle clears previous content"] = b.run(
                "return document.getElementById('ask').childElementCount===0 && "
                "!document.getElementById('settings-panel')"
                ".classList.contains('hidden')"
            )
            b.run("document.getElementById('p-gemini').click()")
            checks[f"{theme}/text box edge is easy to see"] = b.run(CONTRAST) >= 3
            b.run("document.getElementById('p-off').click()")
        b.run(
            "window.loadSummaryState({state:'waiting',title:'Sample',"
            "provider:'gemini',destination:'Google Gemini',"
            "local:false,textLength:4200})"
        )
        checks["consent names external destination"] = b.run(
            "return document.querySelector('.going').textContent"
            ".includes('Google Gemini, over the internet')"
        )
        checks["consent gives the character count"] = b.run(
            "return document.querySelector('.going').textContent"
            ".includes('About 4,200 characters')"
        )
        checks["new state takes focus and is announced"] = b.run(
            "return document.activeElement.id==='summary-heading' && "
            "document.getElementById('summary-status').textContent"
            ".startsWith('Summarise this page?')"
        )
        working = (
            "{state:'working',title:'Sample',provider:'gemini',"
            "destination:'Google Gemini',local:false,textLength:4200}"
        )
        b.run(f"window.loadSummaryState({working})")
        b.run(
            "window.heading=document.getElementById('summary-heading');"
            f"window.loadSummaryState({working})"
        )
        checks["polling the same state keeps focus"] = b.run(
            "return document.getElementById('summary-heading')===window.heading"
            " && document.activeElement===window.heading"
        )
        b.run("keepUpToDate('nothing')")
        b.run(
            "window.loadSummaryState({state:'waiting',title:'Sample',"
            "provider:'gemini',destination:'Google Gemini',"
            "local:false,textLength:4200})"
        )
        b.run("document.getElementById('summary-settings').click()")
        checks["settings disclosure works"] = b.run(
            "return !document.getElementById('settings-panel')"
            ".classList.contains('hidden') && "
            "document.getElementById('summary-settings')"
            ".getAttribute('aria-expanded')==='true'"
        )
        b.run("document.getElementById('do-cancel').click()")
        checks["cancel returns to idle"] = b.run_async("""
          const done = arguments[0];
          const deadline = performance.now() + 2000;
          function check() {
            const hidden = document.getElementById('ask')
                .classList.contains('hidden');
            if (hidden || performance.now() > deadline) done(hidden);
            else setTimeout(check, 25);
          }
          check();
        """)
        checks["closing hands focus back to the settings"] = b.run(
            "return document.activeElement.id==='settings-heading' && "
            "document.getElementById('summary-status').textContent"
            "==='Summary closed.'"
        )
    (OUT / "ai-checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
