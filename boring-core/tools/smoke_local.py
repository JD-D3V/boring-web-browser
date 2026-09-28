#!/usr/bin/env python3
"""Shared parts of the cosmetic, scriptlet, redirect and cookie smoke tests.

Each of those tests serves its own pages from 127.0.0.1 and hands the
browser its own filter lists, so what is checked is the engine and the
injection rather than whatever the real lists say this week.

Lists: every file in a --boring-list-dir folder that is newer than the
one shipped beside chrome.dll wins (GetListPath in
components/boring/lists/list_paths.cc). The test lists are written
when the test starts, so they are always the newer ones, and each test
writes easylist.txt, ubo.txt and cookies.txt so none of the real ones
is in play. resources.json is the exception: the real one that shipped
is the thing under test, so it is left in place and required.

Pages: several names under .localhost, all mapped to 127.0.0.1 with
--host-resolver-rules, because cosmetic rules are written per site and
a bare IP address is a poor stand-in for one. Nothing leaves the machine.

Not a test itself.
"""

import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from drive import OUT

# One site with rules, one without, one for third party frames and
# scripts. All three are this machine.
TEST_SITE = "boring-test.localhost"
OTHER_SITE = "boring-other.localhost"
THIRD_PARTY = "boring-ads.localhost"

SHIPPED_RESOURCES = os.path.join(OUT, "boring", "resources.json")


class Pages:
    """A tiny web server answering from a table of paths.

    Every host name maps to the same table, so the same page can be
    opened as the site with rules and as the site without.
    """

    def __init__(self, pages):
        self.pages = pages
        table = pages

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                found = table.get(path)
                if found is None:
                    self.send_error(404)
                    return
                body, kind = found
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, host, path="/"):
        return f"http://{host}:{self.port}{path}"

    def close(self):
        self.server.shutdown()


HTML = "text/html; charset=utf-8"
JS = "text/javascript"


def write_lists(directory, lists):
    """Writes the test lists, {relative path: text}, into the list folder."""
    for name, text in lists.items():
        path = os.path.join(directory, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def list_folder(lists):
    """A temporary list folder holding these lists. Use in a with."""
    folder = tempfile.TemporaryDirectory(
        prefix="boring-lists-", dir=os.environ.get("TMP") or None
    )
    write_lists(folder.name, lists)
    return folder


def browser_args(list_dir, extra=()):
    return [
        f"--boring-list-dir={list_dir}",
        # The test lists must not be replaced by an update mid-test.
        "--disable-boring-list-updates",
        f"--host-resolver-rules=MAP {TEST_SITE} 127.0.0.1, "
        f"MAP {OTHER_SITE} 127.0.0.1, MAP {THIRD_PARTY} 127.0.0.1",
        "--window-size=1360,900",
        *extra,
    ]


def wait_for(b, condition, timeout_ms=10000):
    """True once the JavaScript expression holds, false at the timeout."""
    return b.run_async(
        """
      const [condition, limit, done] = arguments;
      const deadline = performance.now() + limit;
      function check() {
        let ok = false;
        try { ok = !!eval(condition); } catch (e) {}
        if (ok || performance.now() > deadline) done(ok);
        else setTimeout(check, 100);
      }
      check();
    """,
        [condition, timeout_ms],
    )


# True when the element matched by the selector takes no space on the
# page, whatever way the engine chose to hide it.
HIDDEN = (
    "(function(doc, sel) {"
    " var e = doc.querySelector(sel);"
    " if (!e) return false;"
    " var s = getComputedStyle(e);"
    " return e.getClientRects().length === 0 || s.display === 'none' ||"
    " s.visibility === 'hidden';"
    "})"
)


def hidden_expr(selector, doc="document"):
    return f"{HIDDEN}({doc}, {selector!r})"


def shown_expr(selector, doc="document"):
    return f"(!!{doc}.querySelector({selector!r}) && !{HIDDEN}({doc}, {selector!r}))"


class Checks:
    """PASS and FAIL lines, and the exit code they add up to."""

    def __init__(self):
        self.failures = []

    def __call__(self, name, ok, detail=""):
        print(
            f"{'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail else "")
        )
        if not ok:
            self.failures.append(name)
        return ok

    def result(self, summary):
        if self.failures:
            print(f"\nFAIL: {len(self.failures)} check(s) failed")
            return 1
        print(f"\nPASS: {summary}")
        return 0


def set_profile_pref(profile, dotted, value):
    """Writes one pref into a profile the browser has closed.

    The way smoke_siteoff.py sets its site: the profile has to exist, so
    a first run makes it.
    """
    path = os.path.join(profile, "Default", "Preferences")
    with open(path, encoding="utf-8") as f:
        prefs = json.load(f)
    node = prefs
    *parents, leaf = dotted.split(".")
    for key in parents:
        node = node.setdefault(key, {})
    node[leaf] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(prefs, f)


def set_local_state(profile, dotted, value):
    """Writes one pref into Local State (the user-data-dir level file,
    not Default/Preferences), for a profile the browser has closed.

    Local State is read at startup, so a switch that lives there (like
    internal_only_uis_enabled) has to be set before the run that needs
    it, the same way set_profile_pref sets a profile pref.
    """
    path = os.path.join(profile, "Local State")
    state = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
    node = state
    *parents, leaf = dotted.split(".")
    for key in parents:
        node = node.setdefault(key, {})
    node[leaf] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f)


def get_profile_pref(profile, dotted, default=None):
    path = os.path.join(profile, "Default", "Preferences")
    with open(path, encoding="utf-8") as f:
        node = json.load(f)
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def resources_shipped(check):
    """The real resources.json has to be there for scriptlets to exist."""
    return check(
        "resources.json shipped beside the browser",
        os.path.isfile(SHIPPED_RESOURCES),
        SHIPPED_RESOURCES + " (run tools/get_ubo_resources.py)",
    )
