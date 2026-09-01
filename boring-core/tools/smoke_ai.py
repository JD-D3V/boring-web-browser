#!/usr/bin/env python3
"""Check the AI settings page.

Opens chrome://boring-ai, saves a setting, reloads, and checks the
setting came back. Also checks the page starts with AI turned off.
"""

import sys
import time

from drive import Browser

PROFILE = r"E:\ung\testprofile"


def main():
    failures = []
    with Browser(user_data_dir=PROFILE) as b:
        b.get("chrome://boring-ai")
        time.sleep(2)
        title = b.run("return document.title")
        print("page title:", title)
        if title != "AI settings":
            print("FAIL: page did not open")
            return 1

        off = b.run("return document.getElementById('p-off').checked")
        print("starts turned off:", off)
        if not off:
            failures.append("AI was not off by default")

        note = b.run("return document.getElementById('dest-note').textContent")
        print("note when off:", note.strip()[:60])

        # With no page waiting, the summary panel must stay out of the
        # way. It only appears after the user asks for a summary.
        hidden = b.run(
            "return document.getElementById('ask')"
            ".classList.contains('hidden')")
        print("summary panel hidden when nothing waiting:", hidden)
        if not hidden:
            failures.append("the summary panel showed with nothing waiting")

        # Pick the local option and save.
        b.run("document.getElementById('p-ollama').click();"
              "document.getElementById('model').value = 'llama3.2';"
              "document.getElementById('save').click();")
        time.sleep(1)

        # The note must name where the text would go.
        note = b.run("return document.getElementById('dest-note').textContent")
        print("note for local:", note.strip()[:70])
        if "your own computer" not in note:
            failures.append("the page does not say where the text goes")

        # Reload and check the setting stuck.
        b.get("chrome://boring-ai")
        time.sleep(2)
        saved = b.run("return document.getElementById('p-ollama').checked")
        model = b.run("return document.getElementById('model').value")
        print("setting kept after reload:", saved, "model:", model)
        if not saved or model != "llama3.2":
            failures.append("the setting was not kept")

        # Put it back to off so the profile is left alone.
        b.run("document.getElementById('p-off').click();"
              "document.getElementById('save').click();")
        time.sleep(1)

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("PASS: the AI settings page works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
