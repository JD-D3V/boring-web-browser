#!/usr/bin/env python3
"""Check filter lists added by address (Protection, "What the browser
connects to", "On its own").

A test server on a *.localhost host serves a small list. HTTPS-Only mode
has no certificate for it, so the browser is started with
--boring-user-lists-allow-http, which lets a list on this machine be plain
http and nothing else. Checked:

  - without that switch, an http address is refused, and so are ftp and a
    bare host name, each with a plain message that names https://
  - a list over 5 MB is refused and its row says so and that it is not used
  - a page that is not a filter list is refused the same way
  - a good list gets its own row with its host, a last update time and
    Remove, and its rules hide a test ad and block a test script
  - the fetch carries no cookie, referrer or credential, though the server
    set a cookie on the first answer
  - Remove stops the blocking and deletes the downloaded copy
  - the list survives a restart, a week-old one is fetched again, and with
    "Keep blocking lists up to date" off it is not

Usage: python smoke_own_lists.py
"""

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from drive import Browser
from smoke_local import (
    HTML,
    JS,
    OTHER_SITE,
    TEST_SITE,
    THIRD_PARTY,
    Checks,
    Pages,
    browser_args,
    hidden_expr,
    list_folder,
    set_profile_pref,
    shown_expr,
    wait_for,
)

PROTECTION = "chrome://boring-protection"
SWITCH = "--boring-user-lists-allow-http"
LIST_PREF = "boring.adblock.user_lists"
UPDATES_PREF = "boring.list_updates"

BUNDLED = {
    "easylist.txt": (
        "[Adblock Plus 2.0]\n! Title: own lists smoke test\n"
        "##.boring-control-ad\n"
    ),
    "ubo.txt": "! Title: own lists smoke test, nothing here\n",
    "cookies.txt": "! Title: own lists smoke test, no cookie rules\n",
}

USER_LIST = (
    "[Adblock Plus 2.0]\n! Title: my added list\n"
    f"{TEST_SITE}##.boring-user-ad\n"
    f"||{THIRD_PARTY}^*/tracker.js$script\n"
)
NOT_A_LIST = "<!doctype html><html><body><p>Not a filter list.</p></body></html>\n"
BIG_LIST = "! padding padding padding padding padding padding\n" * 120000

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>own lists test</title>
<div class="boring-control-ad">control ad</div>
<div class="boring-user-ad">ad from my own list</div>
<p id="content">The article.</p>
"""

LOAD_TRACKER = """
var done = arguments[1];
var s = document.createElement('script');
s.src = arguments[0] + '?t=' + Date.now();
s.onload = function() { done('loaded'); };
s.onerror = function() { done('blocked'); };
document.head.appendChild(s);
"""

ROWS = (
    "return Array.from(document.querySelectorAll("
    "'#user-list-rows .setting-row')).map(r => r.innerText)"
)


class ListServer:
    """Serves the lists and remembers what each request carried."""

    def __init__(self):
        self.requests = []
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                with owner.lock:
                    owner.requests.append((path, dict(self.headers)))
                bodies = {
                    "/list.txt": USER_LIST,
                    "/notalist.txt": NOT_A_LIST,
                    "/big.txt": BIG_LIST,
                }
                if path not in bodies:
                    self.send_error(404)
                    return
                body = bodies[path].encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                # A cookie to carry back, if the browser were to.
                self.send_header("Set-Cookie", "tracking=1; Path=/")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, path):
        return f"http://{OTHER_SITE}:{self.port}{path}"

    def count(self, path=None):
        with self.lock:
            return len([r for r in self.requests if path in (None, r[0])])

    def close(self):
        self.server.shutdown()


def add(b, address):
    """Types an address and presses Add. Returns the page's message, empty
    when the list was accepted."""
    b.run(
        "document.getElementById('user-list-address').value = arguments[0];"
        "document.getElementById('add-user-list').click();",
        [address],
    )
    wait_for(
        b,
        "document.getElementById('user-list-status').textContent !== 'Adding.'",
        timeout_ms=10000,
    )
    return b.run("return document.getElementById('user-list-status').textContent")


def row_with(b, text, timeout_ms=20000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if any(text in row for row in b.run(ROWS)):
            return True
        time.sleep(0.4)
    return False


def remove_all(b):
    b.run(
        "document.querySelectorAll('#user-list-rows button').forEach("
        "x => x.click())"
    )
    return wait_for(
        b, "document.querySelectorAll('#user-list-rows .setting-row').length === 0"
    )


def blocked_now(b, page, pages):
    """True once the added list hides the test ad and blocks the script.
    The engine is built in the background, so give it a few page loads."""
    for _ in range(10):
        b.get(page)
        wait_for(b, hidden_expr(".boring-control-ad"), timeout_ms=30000)
        if wait_for(b, hidden_expr(".boring-user-ad"), timeout_ms=1500):
            return (
                b.run_async(LOAD_TRACKER, [pages.url(THIRD_PARTY, "/tracker.js")])
                == "blocked"
            )
    return False


def unblocked_now(b, page, pages):
    for _ in range(10):
        b.get(page)
        wait_for(b, hidden_expr(".boring-control-ad"), timeout_ms=30000)
        if wait_for(b, shown_expr(".boring-user-ad"), timeout_ms=1500):
            return (
                b.run_async(LOAD_TRACKER, [pages.url(THIRD_PARTY, "/tracker.js")])
                == "loaded"
            )
    return False


def main():
    check = Checks()
    pages = Pages({"/page.html": (PAGE, HTML), "/tracker.js": ("window.t = 1;\n", JS)})
    server = ListServer()
    page = pages.url(TEST_SITE, "/page.html")
    try:
        with (
            list_folder(BUNDLED) as lists,
            tempfile.TemporaryDirectory(prefix="own-lists-", dir=os.environ.get("TMP")) as profile,
        ):
            args = browser_args(lists)
            user_dir = os.path.join(profile, "Default", "Boring User Lists")

            # Without the test switch, even a local http address is refused.
            with Browser(user_data_dir=profile, args=args) as b:
                b.get(PROTECTION)
                wait_for(b, "!!document.getElementById('add-user-list')")
                check(
                    "the add box warns that a list can change any site",
                    "Add lists only from people you trust"
                    in b.run("return document.getElementById('user-list-desc').textContent"),
                )
                for address in (
                    server.url("/list.txt"),
                    "http://example.com/list.txt",
                    "ftp://example.com/list.txt",
                    "example.com/list.txt",
                ):
                    message = add(b, address)
                    check(
                        f"refused with a plain message: {address}",
                        "https://" in message and message.endswith("."),
                        message,
                    )
                check("nothing was fetched", server.count() == 0)
                check("and no row was added", b.run(ROWS) == [])

            with Browser(user_data_dir=profile, args=[*args, SWITCH]) as b:
                b.get(PROTECTION)
                wait_for(b, "!!document.getElementById('add-user-list')")

                check("big list is accepted for a try", add(b, server.url("/big.txt")) == "")
                check(
                    "a list over 5 MB is refused on its row",
                    row_with(b, "bigger than 5 MB")
                    and row_with(b, "Not used"),
                    str(b.run(ROWS)),
                )
                check(
                    "html is not a filter list",
                    add(b, server.url("/notalist.txt")) == ""
                    and row_with(b, "did not return a filter list"),
                    str(b.run(ROWS)),
                )
                check("Remove clears the failed rows", remove_all(b))

                check("a good list is accepted", add(b, server.url("/list.txt")) == "")
                check(
                    "its row shows host, update time and Remove",
                    row_with(b, "Updated")
                    and row_with(b, OTHER_SITE)
                    and b.run(
                        "return !!document.querySelector("
                        "'#user-list-rows button.app-remove')"
                    ),
                    str(b.run(ROWS)),
                )
                check(
                    "adding the same list again is refused",
                    "already added" in add(b, server.url("/list.txt")),
                )
                check(
                    "the copy is on disk",
                    os.path.isdir(user_dir) and len(os.listdir(user_dir)) == 1,
                )
                check(
                    "the list hides the test ad and blocks the test script",
                    blocked_now(b, page, pages),
                )

                b.get(PROTECTION)
                wait_for(b, "!!document.getElementById('add-user-list')")
                row_with(b, "Updated")
                remove_all(b)
                check(
                    "Remove deletes the downloaded copy",
                    wait_for_gone(user_dir),
                )
                check(
                    "and the test ad and script are let through again",
                    unblocked_now(b, page, pages),
                )

                # Added once more, to carry through a restart.
                b.get(PROTECTION)
                wait_for(b, "!!document.getElementById('add-user-list')")
                check("added again", add(b, server.url("/list.txt")) == "")
                row_with(b, "Updated")

            with Browser(user_data_dir=profile, args=[*args, SWITCH]) as b:
                check("the list is still applied after a restart", blocked_now(b, page, pages))

            before = server.count("/list.txt")
            # A week-old copy is fetched again when the browser next looks.
            old = time.time() - 8 * 24 * 3600
            set_profile_pref(
                profile,
                LIST_PREF,
                [{"url": server.url("/list.txt"), "updated": old, "tried": old}],
            )
            with Browser(user_data_dir=profile, args=[*args, SWITCH]) as b:
                b.get(page)
                fetched = wait_until(lambda: server.count("/list.txt") > before)
                check("a week-old list is fetched again", fetched)
                wait_until(lambda: refreshed(profile, old))

            # With list updates off, it is not.
            before = server.count("/list.txt")
            set_profile_pref(
                profile,
                LIST_PREF,
                [{"url": server.url("/list.txt"), "updated": old, "tried": old}],
            )
            set_profile_pref(profile, UPDATES_PREF, False)
            with Browser(user_data_dir=profile, args=[*args, SWITCH]) as b:
                for _ in range(3):
                    b.get(page)
                    time.sleep(1.5)
                check(
                    "with list updates off, nothing is fetched",
                    server.count("/list.txt") == before,
                )

            # Whatever the browser sent, it carried nothing about the person.
            carried = [
                name.lower()
                for _, headers in server.requests
                for name in headers
                if name.lower() in ("cookie", "referer", "authorization")
            ]
            check(
                "no cookie, referrer or credential was sent",
                server.count() > 0 and not carried,
                str(carried),
            )
    finally:
        pages.close()
        server.close()
    return check.result("lists added by address block, refresh and can be removed")


def wait_until(condition, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.3)
    return False


def wait_for_gone(folder):
    return wait_until(lambda: not os.path.isdir(folder) or not os.listdir(folder), 10)


def refreshed(profile, old):
    try:
        with open(os.path.join(profile, "Default", "Preferences"), encoding="utf-8") as f:
            entries = json.load(f)["boring"]["adblock"]["user_lists"]
    except (OSError, ValueError, KeyError):
        return False
    return bool(entries) and entries[0].get("updated", 0) > old + 24 * 3600


if __name__ == "__main__":
    sys.exit(main())
