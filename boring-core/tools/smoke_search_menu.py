#!/usr/bin/env python3
"""Check the search engine menu on the address bar and the new tab page.

Drives the browser's native menu through the new tab page's test hook
(--boring-search-menu-test), never through OS input. The new tab page has
no engine button of its own any more (it has no search box), so the menu
is the address bar's alone:

  - the address bar's engine icon is a button on the new tab page, and
    pressing it opens the menu, which lists the browser's engines;
  - choosing an engine with words typed searches with that engine once,
    and the default does not change;
  - "Make default" changes the default and the address bar placeholder;
  - Escape and Done roll the menu up;
  - on a real web page the icon is still Chromium's page info.

Nothing leaves the machine: every host except 127.0.0.1 resolves to
nothing, so a search lands on an error page whose address is still the
engine's.

Usage: python smoke_search_menu.py
"""

import json
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from drive import Browser

OUT = Path(__file__).resolve().parents[2] / "artifacts/ui-implemented"
TEST_SWITCH = "--boring-search-menu-test"
BAR_HINT = "Search, or type a site, a tab, or what you want to do"
OFFLINE = "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"
QUERY = "boring smoke query"


def hook(b, *command, timeout=5.0):
    """Run one test command on the new tab page and return its answer."""
    b.run(
        "window.lastSearchMenuTest = '__pending__';"
        "chrome.send('searchMenuTest', arguments[0]);",
        [list(command)],
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = b.run("return window.lastSearchMenuTest")
        if result != "__pending__":
            return result
        time.sleep(0.05)
    return None


def wait_state(b, predicate, timeout=5.0):
    """The menu's state once `predicate` holds, or the last one seen."""
    deadline = time.monotonic() + timeout
    state = None
    while time.monotonic() < deadline:
        state = hook(b, "state") or {}
        if predicate(state):
            return state
        time.sleep(0.1)
    return state


def open_newtab(b):
    b.get("chrome://newtab")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if b.run(
            "return location.host === 'boring-newtab' && "
            "typeof window.searchMenuTestResult === 'function'"
        ):
            return True
        time.sleep(0.1)
    return False


def open_from_icon(b):
    """Press the address bar's engine icon on an empty bar."""
    hook(b, "openFromOmnibox")
    return wait_state(b, lambda s: s.get("open") and s.get("progress") == 1)


class _Page(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><title>plain page</title><p>A page.</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    server = serve()
    page_url = f"http://127.0.0.1:{server.server_address[1]}/plain"
    with (
        tempfile.TemporaryDirectory(prefix="search-menu-", dir=OUT) as profile,
        Browser(
            user_data_dir=profile,
            args=[TEST_SWITCH, OFFLINE, "--window-size=1360,900"],
        ) as b,
    ):
        checks["new tab page is ready"] = open_newtab(b)

        icon = hook(b, "iconState") or {}
        checks["engine icon is a button on the new tab page"] = bool(
            icon.get("available") and icon.get("focusable")
        )

        # The address bar: type a search, press the engine icon.
        opened = hook(b, "openFromOmnibox", QUERY) or {}
        checks["typing a search makes the icon the engine button"] = bool(
            opened.get("available")
        )
        state = wait_state(b, lambda s: s.get("open") and s.get("progress") == 1)
        engines = state.get("engines", [])
        checks["menu opens from the address bar"] = bool(opened.get("shown"))
        checks["menu lists the browser's engines"] = len(engines) >= 2 and all(
            e.get("name") and e.get("keyword") for e in engines
        )
        checks["exactly one engine is the default"] = (
            sum(1 for e in engines if e.get("isDefault")) == 1
        )
        print("engines:", [e.get("name") for e in engines])
        print("motion:", "unroll" if state.get("rich") else "fade")

        default = next((e for e in engines if e.get("isDefault")), {})
        other_index, other = next(
            ((i, e) for i, e in enumerate(engines) if not e.get("isDefault")),
            (-1, {}),
        )
        hook(b, "pick", other_index)
        deadline = time.monotonic() + 10
        landed = ""
        while time.monotonic() < deadline:
            landed = b.current_url()
            if not landed.startswith("chrome://"):
                break
            time.sleep(0.2)
        host = urllib.parse.urlsplit(landed).hostname or ""
        keyword = other.get("keyword", "")
        checks["a pick searches with that engine"] = bool(keyword) and (
            host == keyword or host.endswith("." + keyword) or keyword in host
        )
        checks["the pick searched for the typed words"] = (
            "boring" in urllib.parse.unquote_plus(landed)
            and "smoke" in urllib.parse.unquote_plus(landed)
        )
        print("one-time search went to:", landed)

        open_newtab(b)
        state = open_from_icon(b)
        engines = state.get("engines", [])
        still = next((e for e in engines if e.get("isDefault")), {})
        checks["a one-time search leaves the default alone"] = still.get(
            "keyword"
        ) == default.get("keyword")

        # Make default.
        before = (hook(b, "iconState") or {}).get("placeholder", "")
        index, target = next(
            (
                (i, e)
                for i, e in enumerate(engines)
                if not e.get("isDefault") and e.get("hasMakeDefault")
            ),
            (-1, {}),
        )
        hook(b, "makeDefault", index)
        state = wait_state(
            b,
            lambda s: any(
                e.get("isDefault") and e.get("keyword") == target.get("keyword")
                for e in s.get("engines", [])
            ),
        )
        checks["make default changes the default"] = index >= 0 and any(
            e.get("isDefault") and e.get("keyword") == target.get("keyword")
            for e in state.get("engines", [])
        )
        after = state.get("placeholder", "")
        # The Bar (bar.md, change 9) gives the field one plain hint that
        # names no engine, so it stays the same when the default changes.
        checks["address bar keeps the Bar's hint after make default"] = (
            after == before == BAR_HINT
        )
        print(f"placeholder: {before!r} -> {after!r}")
        checks["menu stays open after make default"] = state.get("open") is True

        hook(b, "escape")
        state = wait_state(b, lambda s: not s.get("open"))
        checks["Escape rolls the menu up"] = state.get("open") is False
        open_from_icon(b)
        hook(b, "done")
        state = wait_state(b, lambda s: not s.get("open"))
        checks["Done rolls the menu up"] = state.get("open") is False

        # A real web page: the icon must be Chromium's page info, as before.
        hook(b, "openTab", page_url)
        deadline = time.monotonic() + 10
        icon = {}
        while time.monotonic() < deadline:
            icon = hook(b, "iconState") or {}
            if icon.get("url", "").startswith(page_url):
                break
            time.sleep(0.2)
        checks["on a web page the icon is not the engine button"] = (
            icon.get("url", "").startswith(page_url)
            and not icon.get("editingOrEmpty")
            and not icon.get("available")
        )
        pressed = hook(b, "pressIcon") or {}
        checks["on a web page the icon opens page info"] = bool(
            pressed.get("handled")
            and pressed.get("pageInfoShowing")
            and not pressed.get("menuShowing")
        )
        hook(b, "closePageInfo")
        hook(b, "closeTab")

    server.shutdown()
    (OUT / "search-menu-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
