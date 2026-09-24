#!/usr/bin/env python3
"""Check the welcome page and the links into our pages from settings.

The test driver starts the browser with --no-first-run, so the welcome
page is opened directly. It must turn Senior Safe Mode on, and must not
offer a way to turn it off, and it shows the B mark and uses it as its
tab icon. The settings side menu must link to the Protection and AI
pages. Screenshots go to artifacts/ui-implemented.

"Import from Chrome or Edge" shows only when a Chrome or Edge profile is
found, and opens the import dialog. The browser is pointed at a made up
Chrome profile (see smoke_import.py) for that, and at an empty folder to
check the button stays hidden, so the test never reads the real ones.
"""

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from drive import Browser
from smoke_import import import_switches, make_fake_user_data, scratch_root
from smoke_newtab import ICON_LOADS

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

# How the Chrome or Edge button and the general import link look.
IMPORT_STATE = r"""
  // null when the element is not on the page at all, so a page without
  // it cannot pass a check that it is hidden.
  function shown(el) {
    return el ? getComputedStyle(el).display !== 'none' : null;
  }
  var button = document.getElementById('import-chromium');
  var other = document.getElementById('import-other');
  return {
    button: shown(button),
    other: shown(other),
    tag: button ? button.tagName : null,
    label: button ? button.textContent.replace(/\s+/g, ' ').trim() : null,
  };
"""


def import_state(b, want_button, timeout=10):
    """The page asks for the answer after it loads, so wait for it."""
    end = time.time() + timeout
    state = {}
    while time.time() < end:
        state = b.run(IMPORT_STATE)
        if state.get("button") == want_button:
            break
        time.sleep(0.5)
    return state


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    root = scratch_root()
    try:
        chrome_dir = make_fake_user_data(root)
        run_with_chrome(checks, import_switches(chrome_dir, root))
        run_without_chrome(checks, import_switches(f"{root}/no-chrome", root))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    (OUT / "welcome-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


def run_without_chrome(checks, switches):
    with (
        tempfile.TemporaryDirectory(prefix="welcome-", dir=OUT) as profile,
        Browser(user_data_dir=profile, args=switches) as b,
    ):
        b.get("chrome://boring-welcome")
        # Nothing to wait for when there is nothing to find, so give the
        # page the time it would take to say otherwise.
        time.sleep(3)
        state = import_state(b, want_button=False, timeout=1)
        checks["no Chrome or Edge: no import button"] = state.get("button") is False
        checks["no Chrome or Edge: general import link"] = state.get("other") is True


def run_with_chrome(checks, switches):
    with (
        tempfile.TemporaryDirectory(prefix="welcome-", dir=OUT) as profile,
        Browser(user_data_dir=profile, args=["--window-size=1360,900", *switches]) as b,
    ):
        b.get("chrome://boring-welcome")
        time.sleep(1)
        checks["welcome offers senior mode"] = b.run(
            "return !document.getElementById('senior-off').classList.contains('hidden')"
        )
        checks["welcome has no way to turn it off"] = b.run(
            "return !document.body.innerText.match(/turn (it|this) off/i)"
        )
        icon = b.run_async(ICON_LOADS)
        checks["welcome tab icon brand.svg loads"] = icon == "ok"
        if icon != "ok":
            print("  icon:", icon)
        checks["welcome B mark loads and is decorative"] = b.run_async(
            "const done=arguments[arguments.length-1];"
            "const img=document.querySelector('img.brand');"
            "if(!img||img.getAttribute('src')!=='brand.svg'||"
            "img.getAttribute('alt')!==''){done(false);return;}"
            "img.decode().then(()=>done(true),()=>done(false));"
        )
        state = import_state(b, want_button=True)
        print("  import:", state)
        checks["Chrome found: import button shown"] = state.get("button") is True
        checks["import button is a button"] = state.get("tag") == "BUTTON"
        checks["import button label"] = (
            state.get("label") == "Import from Chrome or Edge"
        )
        checks["Chrome found: general link gives way"] = state.get("other") is False
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

        b.get("chrome://boring-welcome")
        import_state(b, want_button=True)
        # A missing button is a failed check, not a crash that hides the
        # rest of the results.
        clicked = b.run(
            "var el = document.getElementById('import-chromium');"
            "if (!el) return false; el.click(); return true;"
        )
        time.sleep(2)
        checks["import button opens the import dialog"] = (
            clicked is True
            and b.current_url().startswith("chrome://settings/importData")
        )

        b.get("chrome://settings")
        time.sleep(3)
        # Protection and Page summaries are settings pages of their own,
        # in the settings menu like every other category.
        checks["settings links to protection"] = (
            b.run(FIND_DEEP, ["a.cr-nav-menu-item[href='/protection']"])
            == "/protection"
        )
        checks["settings links to AI"] = (
            b.run(FIND_DEEP, ["a.cr-nav-menu-item[href='/summaries']"]) == "/summaries"
        )
        b.screenshot(str(OUT / "settings-menu.png"))


if __name__ == "__main__":
    sys.exit(main())
