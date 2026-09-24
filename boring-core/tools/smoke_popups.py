#!/usr/bin/env python3
"""Check pop-up blocking and the per site exception that lifts it.

Everything is local: a small HTTP server on 127.0.0.1 serves a page that
calls window.open() on load, with no user gesture. Chromium blocks that
by default (the POPUPS content setting is registered as BLOCK in
components/content_settings/core/browser/content_settings_registry.cc),
and a per site "allow" exception lets it through. We drive the real
machinery, so this also proves our build has not weakened it.

Three passes, each with the browser closed in between so the profile
file can be read and written:

  1. fresh profile          -> window.open returns null, one window open
  2. allow exception set    -> window.open succeeds, two windows open
  3. exception removed      -> blocked again

The address bar's blocked pop-up icon and its "always allow" bubble
cannot be opened from WebDriver without synthetic input, so they are
left to native verification.
"""

import json
import os
import socket
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from drive import Browser

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>waiting</title>
<h1>pop-up test</h1>
<script>
  var opened = window.open('popup.html', 'boringpopup', 'width=220,height=160');
  window.__boringPopup = opened ? 'opened' : 'blocked';
  document.title = window.__boringPopup;
</script>
"""

POPUP = "<!doctype html><meta charset=\"utf-8\"><title>popup</title><p>pop-up\n"

ALLOW = 1  # CONTENT_SETTING_ALLOW


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(directory, port):
    handler = partial(SimpleHTTPRequestHandler, directory=directory)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def preferences_path(profile):
    return os.path.join(profile, "Default", "Preferences")


def set_popup_exception(profile, origin, setting):
    """Write, or with setting None remove, the per site pop-up rule."""
    path = preferences_path(profile)
    with open(path, encoding="utf-8") as f:
        prefs = json.load(f)
    exceptions = (
        prefs.setdefault("profile", {})
        .setdefault("content_settings", {})
        .setdefault("exceptions", {})
        .setdefault("popups", {})
    )
    key = origin + ",*"
    if setting is None:
        exceptions.pop(key, None)
    else:
        exceptions[key] = {"setting": setting}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def open_page(profile, url):
    """Load the test page once and report what window.open did."""
    # chromedriver starts the browser with --disable-popup-blocking, so
    # without this the test would be asking a browser with the pop-up
    # blocker switched off whether it blocks pop-ups.
    with Browser(
        user_data_dir=profile, keep_switches=["disable-popup-blocking"]
    ) as b:
        b.get(url)
        time.sleep(2)
        result = b.run("return window.__boringPopup || ''")
        title = b.run("return document.title")
        handles = b._req("GET", f"/session/{b.sid}/window/handles")["value"]
        return result, title, len(handles)


def main():
    failures = []
    with tempfile.TemporaryDirectory() as root:
        pages = os.path.join(root, "pages")
        profile = os.path.join(root, "profile")
        os.makedirs(pages)
        with open(os.path.join(pages, "index.html"), "w", encoding="utf-8") as f:
            f.write(PAGE)
        with open(os.path.join(pages, "popup.html"), "w", encoding="utf-8") as f:
            f.write(POPUP)
        port = free_port()
        server = serve(pages, port)
        origin = f"http://127.0.0.1:{port}"
        url = origin + "/index.html"
        try:
            result, title, windows = open_page(profile, url)
            print(f"default profile: window.open {result}, {windows} window(s)")
            if result != "blocked" or title != "blocked":
                failures.append("a pop-up was not blocked in a fresh profile")
            if windows != 1:
                failures.append(f"a blocked pop-up still opened a window ({windows})")

            if not os.path.exists(preferences_path(profile)):
                failures.append("no Preferences file to set the exception in")
            else:
                set_popup_exception(profile, origin, ALLOW)
                result, title, windows = open_page(profile, url)
                print(f"site allowed: window.open {result}, {windows} window(s)")
                if result != "opened" or title != "opened":
                    failures.append("the per site allow rule did not let a pop-up through")
                if windows != 2:
                    failures.append(f"the allowed pop-up did not open a window ({windows})")

                set_popup_exception(profile, origin, None)
                result, title, windows = open_page(profile, url)
                print(f"exception removed: window.open {result}, {windows} window(s)")
                if result != "blocked" or windows != 1:
                    failures.append("removing the rule did not restore blocking")
        finally:
            server.shutdown()

    for failure in failures:
        print("FAIL:", failure)
    if failures:
        return 1
    print("PASS: pop-ups are blocked by default and per site allow works")
    return 0


if __name__ == "__main__":
    sys.exit(main())
