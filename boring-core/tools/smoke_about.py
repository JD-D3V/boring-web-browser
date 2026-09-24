#!/usr/bin/env python3
"""Check the browser still credits the people whose code it runs on.

Renaming the product used to rename the project with it, so the About
page read "made possible by the Boring Browser open source project",
which claims someone else's work and drops a credit we are not free to
drop. This reads the built binary's own pages rather than the source, so
it catches a bad string that got as far as a build.

Pages checked: chrome://version and chrome://settings/help.
"""

import json
import sys
import tempfile
import time
from pathlib import Path

from drive import Browser

OUT = Path(__file__).resolve().parents[2] / "artifacts/ui-implemented"

PRODUCT = "Boring Browser"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    with (
        tempfile.TemporaryDirectory(prefix="about-", dir=OUT) as profile,
        Browser(user_data_dir=profile, args=["--window-size=1100,900"]) as b,
    ):
        # ungoogled strips the licence line and every link from
        # chrome://version, so the copyright holder is all this page has
        # left to check. The credit itself lives on the About page.
        b.get("chrome://version")
        time.sleep(1)
        text = b.run("return document.body.innerText")
        checks["version page names our product"] = PRODUCT in text
        checks["copyright still says The Chromium Authors"] = (
            "The Chromium Authors" in text
        )
        checks["version page does not rename the project"] = (
            f"the {PRODUCT} open source project" not in text
        )
        b.screenshot(str(OUT / "about-version.png"))

        b.get("chrome://settings/help")
        time.sleep(3)
        about = b.run(
            "function text(root){let out=root.textContent||'';"
            "for(const el of root.querySelectorAll('*'))"
            "if(el.shadowRoot)out+=' '+text(el.shadowRoot);return out;}"
            "return text(document.body)"
        )
        links = b.run(
            "function walk(root,out){"
            "for(const a of root.querySelectorAll('a'))"
            "out.push((a.textContent||'').trim()+' -> '+a.getAttribute('href'));"
            "for(const el of root.querySelectorAll('*'))"
            "if(el.shadowRoot)walk(el.shadowRoot,out);return out;}"
            "return walk(document,[])"
        )
        checks["About page names our product"] = PRODUCT in about
        checks["About page credits the Chromium project"] = (
            "made possible by the Chromium open source project" in about
        )
        checks["About page does not rename the project"] = (
            f"the {PRODUCT} open source project" not in about
        )
        # A credit that points at a domain which does not exist is not a
        # credit. ungoogled's domain substitution rewrites this one; our
        # attribution-link patch puts it back.
        checks["the credit links to chromium.org"] = any(
            link.startswith("Chromium ->") and "www.chromium.org" in link
            for link in links
        )
        # chrome://credits carries the full third party notices.
        checks["About page links to the notices"] = any(
            "chrome://credits" in link for link in links
        )
        b.screenshot(str(OUT / "about-help.png"))

    (OUT / "about-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
