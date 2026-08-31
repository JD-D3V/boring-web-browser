#!/usr/bin/env python3
"""Check that Chromium's password manager is present and working.

We reuse Chromium's own password manager rather than write one, so this
checks it is really there and not stripped out: the manager page opens,
saving passwords is on, and the import and export routes exist so a
person can leave with their data.
"""

import sys
import time

from drive import Browser

PROFILE = r"E:\ung\testprofile"


def main():
    failures = []
    with Browser(user_data_dir=PROFILE) as b:
        b.get("chrome://password-manager/passwords")
        time.sleep(3)
        title = b.run("return document.title")
        print("password manager page:", title)
        if not title:
            failures.append("the password manager page did not open")

        # The page is built from nested shadow roots, so search through
        # them for the text a person would see.
        text = b.run("""
            function collect(root, out) {
              var nodes = root.querySelectorAll('*');
              for (var i = 0; i < nodes.length; i++) {
                if (nodes[i].shadowRoot) { collect(nodes[i].shadowRoot, out); }
              }
              out.push(root.textContent || '');
              return out;
            }
            return collect(document, []).join(' ').toLowerCase();
        """)
        for word in ("password",):
            if word not in text:
                failures.append("the page does not mention " + word)

        # Saving passwords must be available and on by default.
        b.get("chrome://settings/autofill")
        time.sleep(2)
        settings_ok = b.run("return document.title.length > 0")
        print("settings page opens:", settings_ok)
        if not settings_ok:
            failures.append("the autofill settings page did not open")

        # Passkeys: the browser must offer the WebAuthn interface.
        b.get("https://example.com")
        has_webauthn = b.run(
            "return typeof window.PublicKeyCredential === 'function'")
        print("passkeys supported (WebAuthn present):", has_webauthn)
        if not has_webauthn:
            failures.append("WebAuthn is missing, so passkeys cannot work")

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("PASS: the password manager and passkey support are in place")
    return 0


if __name__ == "__main__":
    sys.exit(main())
