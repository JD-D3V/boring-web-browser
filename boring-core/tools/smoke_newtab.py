#!/usr/bin/env python3
"""Check the new tab page.

A fresh profile's new tab should be our page, say "Just a Browser." with
the B mark above it and as its tab icon, report real protection
state, start with the Reading and Wikipedia shortcuts, and let a person
add and remove shortcuts, with removed defaults staying removed. Only web addresses may become
shortcuts, never script or local files. Screenshots go to
artifacts/ui-implemented.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

from drive import Browser

OUT = Path(__file__).resolve().parents[2] / "artifacts/ui-implemented"


def wait_for(b, condition, timeout_ms=5000):
    """True once the JavaScript expression holds, false at the timeout.

    Polled from here rather than with eval in the page: the page's
    content security policy rightly refuses eval.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        if b.run("return !!(" + condition + ")"):
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)


# The tab icon must be served by the page itself and be a real SVG. Tried
# with fetch first; if a chrome:// page ever refuses to fetch itself, the
# icon must still decode as an image, otherwise the check fails.
ICON_LOADS = r"""
  const done = arguments[arguments.length - 1];
  const link = document.querySelector('link[rel~="icon"]');
  if (!link || link.getAttribute('href') !== 'brand.svg') {
    done('no icon link to brand.svg');
    return;
  }
  function asImage(why) {
    const img = new Image();
    img.src = link.href;
    img.decode().then(() => done('ok'), () => done(why + ', and not an image'));
  }
  fetch(link.href).then(r => r.text().then(t => {
    const type = r.headers.get('content-type') || '';
    if (r.status === 200 && type.includes('image/svg+xml') && t.includes('<svg')) {
      done('ok');
    } else {
      done('status ' + r.status + ', type ' + type + ', ' + t.length + ' bytes');
    }
  })).catch(e => asImage('fetch failed: ' + e));
"""

# The mark above the heading must actually decode, not just be in the markup.
MARK_DECODES = r"""
  const done = arguments[arguments.length - 1];
  const img = document.querySelector('img.home-brand');
  if (!img || img.getAttribute('src') !== 'brand.svg') { done(false); return; }
  img.decode().then(() => done(true), () => done(false));
"""


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
        checks["heading is exactly 'Just a Browser.'"] = b.run(
            "var h=document.querySelectorAll('h1');"
            "return h.length===1 && h[0].textContent==='Just a Browser.'"
        )
        checks["old copy is gone"] = b.run(
            "var html=document.documentElement.outerHTML;"
            "return !html.includes('A little less noise') && "
            "!html.includes('Your web') && !html.includes('Room to breathe') && "
            "!document.querySelector('.eyebrow')"
        )
        checks["'Find what you came for.' is kept"] = b.run(
            "var p=document.querySelector('.intro');"
            "return !!p && p.textContent==='Find what you came for.'"
        )
        checks["tab title is still New Tab"] = b.run(
            "return document.title==='New Tab'"
        )
        icon = b.run_async(ICON_LOADS)
        checks["tab icon brand.svg loads"] = icon == "ok"
        if icon != "ok":
            print("  icon:", icon)
        checks["B mark above the heading loads and is decorative"] = b.run_async(
            MARK_DECODES
        ) and b.run(
            "var img=document.querySelector('img.home-brand');"
            "return img.getAttribute('alt')==='' && "
            "img.getAttribute('aria-hidden')==='true' && "
            "!!(img.compareDocumentPosition(document.querySelector('h1')) & "
            "Node.DOCUMENT_POSITION_FOLLOWING) && "
            "!/provisional/i.test(document.body.innerText)"
        )
        checks["protection line reports real state"] = wait_for(
            b,
            "!document.getElementById('protection').hidden && "
            "/Protection is on|needs attention/.test("
            "document.getElementById('protection').textContent)",
            15000,
        )
        checks["starts with Reading and Wikipedia"] = wait_for(
            b,
            "[...document.querySelectorAll('#shortcuts a')].map(a=>a.href)"
            ".join(' ')==='chrome://settings/reading https://www.wikipedia.org/'",
        )
        checks["editor is closed on load"] = b.run(
            "return getComputedStyle(document.getElementById('add-form'))"
            ".display==='none'"
        )
        b.screenshot(str(OUT / "newtab-default.png"))

        add(b, "Script", "javascript:alert(1)")
        checks["script address is refused"] = wait_for(
            b,
            "!document.getElementById('add-bad').hidden"
            " && document.querySelectorAll('#shortcuts a').length===2",
        )
        b.run("document.getElementById('add-cancel').click()")
        checks["cancel closes the editor"] = wait_for(
            b,
            "getComputedStyle(document.getElementById('add-form'))"
            ".display==='none'",
        )

        add(b, "Example", "example.com")
        checks["web address becomes a shortcut"] = wait_for(
            b,
            "[...document.querySelectorAll('#shortcuts a')].some("
            "a=>a.href==='https://example.com/') && "
            "getComputedStyle(document.getElementById('add-form'))"
            ".display==='none'",
        )
        b.screenshot(str(OUT / "newtab-shortcut.png"))

        b.get("chrome://newtab")
        checks["shortcut survives a reload"] = wait_for(
            b, "document.querySelectorAll('#shortcuts a').length===3"
        )
        for _ in range(3):
            b.run("document.querySelector('#shortcuts .remove').click()")
            wait_for(b, "false", 400)
        checks["shortcuts can be removed"] = wait_for(
            b, "document.querySelectorAll('#shortcuts a').length===0"
        )
        b.get("chrome://newtab")
        checks["removed defaults stay removed"] = wait_for(
            b,
            "document.getElementById('shortcuts') && "
            "document.querySelectorAll('#shortcuts a').length===0",
        ) and not wait_for(
            b, "document.querySelectorAll('#shortcuts a').length>0", 1500
        )

    (OUT / "newtab-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
