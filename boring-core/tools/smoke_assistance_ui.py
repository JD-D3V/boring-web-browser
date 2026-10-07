#!/usr/bin/env python3
"""Check the Ask Gemini panel against a fake Gemini, through the test hook.

Drives the browser's assistance panel through the new tab page's test hook
(--boring-assistance-test), never through OS input. The panel opens on a
local dashboard in window A, and every command is sent from window B:

  - opening the panel shares nothing: Gemini hears nothing until the person
    presses Send;
  - Find on page runs locally, and showing a match outlines the control
    without clicking it;
  - the preview is the exact text that would be shared;
  - sharing types the question into Gemini and waits; after Send the reply
    names a control, and Show me outlines it on the dashboard;
  - a change of page makes the answer stale, so Show me is off;
  - Close ends the panel, and an internal page has no panel.

Nothing leaves the machine. The provider is a fake Gemini on 127.0.0.1, and
every other host resolves to nothing. The fake reports "input" and "send" to
the local server, so the test can prove what was and was not shared.

Usage: set BORING_OUT to the build's out/Default folder, then run
    python smoke_assistance_ui.py
"""

import os
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.setdefault("TMP", r"E:\tmp" if os.name == "nt" else tempfile.gettempdir())
os.environ.setdefault("TEMP", os.environ["TMP"])
from drive import OFFSCREEN, PROFILE, Browser  # noqa: E402

TEST_SWITCH = "--boring-assistance-test"
PROVIDER_SWITCH = "--boring-assistance-provider-for-test"
OFFLINE = "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"
QUESTION = "Where do I create an API key?"
OUTLINE_JS = (
    "const o = document.documentElement.lastElementChild;"
    "return !!o && o.getAttribute('aria-hidden') === 'true' && "
    "o.style.position === 'fixed';"
)
CLICKED_JS = "return document.body.dataset.clicked || null;"

SOURCE_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Account dashboard</title>
<nav>
  <a href="/settings">Settings</a>
  <a href="/keys"
     onclick="event.preventDefault(); document.body.dataset.clicked='yes'">API keys</a>
  <a href="/billing">Billing</a>
</nav>
<h1>Account</h1>
<p>Manage your account.</p>
"""

# Stands in for Gemini's page. It reads the prompt the adapter put in the
# composer, then appends a completed reply 500 ms after Send. Both the input
# and the Send are reported to the local server, so the test can see them.
FAKE_GEMINI = """<!doctype html>
<meta charset="utf-8">
<title>Fake Gemini</title>
<style>
  message-content { display: block; white-space: pre-line; }
  [role="textbox"] { min-height: 40px; width: 560px; border: 1px solid #888; }
</style>
<main id="chat"></main>
<div contenteditable="true" role="textbox"
     aria-label="Enter a prompt for Gemini"></div>
<button aria-label="Send message">Send</button>
<script>
  document.querySelector('[role="textbox"]').addEventListener('input', () => {
    fetch('/log', {method: 'POST', body: 'input'});
  });
  document.querySelector('button[aria-label="Send message"]')
    .addEventListener('click', () => {
      fetch('/log', {method: 'POST', body: 'send'});
      const text = document.querySelector('[role="textbox"]').textContent;
      // Real Gemini empties its box on Send; the adapter relies on that to
      // know the person sent the prompt.
      document.querySelector('[role="textbox"]').textContent = '';
      const step = /BORING_STEP ([a-zA-Z0-9_-]{6,64}) ([1-9][0-9]*) <candidate-id>/
        .exec(text);
      const marker = 'PAGE SNAPSHOT (JSON):';
      const snapshot = JSON.parse(
        text.slice(text.indexOf(marker) + marker.length));
      const hit = snapshot.candidates.find(c => c.label === 'API keys');
      const id = hit ? hit.id : 'none';
      setTimeout(() => {
        const box = document.createElement('response-container');
        box.innerHTML =
          '<div class="model-response-label-announcer" aria-busy="false"></div>' +
          '<message-content></message-content>' +
          '<button aria-label="Copy">Copy</button>';
        box.querySelector('message-content').textContent =
          'Open API keys in the menu.\\nBORING_STEP ' +
          step[1] + ' ' + step[2] + ' ' + id;
        document.getElementById('chat').append(box);
      }, 500);
    });
</script>
"""

PAGES = {"/source.html": SOURCE_PAGE, "/app/": FAKE_GEMINI}


class Handler(BaseHTTPRequestHandler):
    """Serves the dashboard and the fake Gemini, and records what Gemini hears."""

    def do_GET(self):
        page = PAGES.get(urllib.parse.urlsplit(self.path).path)
        if page is None:
            self.send_error(404)
            return
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path != "/log":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", "0"))
        text = self.rfile.read(size).decode("utf-8", "replace")
        with self.server.log_lock:
            self.server.entries.append(text)
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


class Server(ThreadingHTTPServer):
    """Local only. Keeps the list of what the fake Gemini reported."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.entries = []
        self.log_lock = threading.Lock()


def switch_to(browser, handle):
    """Make `handle` the window that the next WebDriver command acts on."""
    browser._req("POST", f"/session/{browser.sid}/window", {"handle": handle})


def current_window(browser):
    return browser._req("GET", f"/session/{browser.sid}/window")["value"]


def new_window(browser):
    """Open a second window, move it off the desktop, and return its handle."""
    path = f"/session/{browser.sid}/window/new"
    handle = browser._req("POST", path, {"type": "window"})["value"]["handle"]
    switch_to(browser, handle)
    # drive.py keeps the first window off the desktop. Do the same here, so
    # a test run does not put a window over the person's work.
    x, y = os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN).split(",")
    browser._req(
        "POST",
        f"/session/{browser.sid}/window/rect",
        {"x": int(x), "y": int(y)},
    )
    return handle


def wait_for_newtab(browser, timeout=10.0):
    """Wait until the current window shows the new tab page."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if browser.run("return location.host === 'boring-newtab'"):
            return True
        time.sleep(0.1)
    return False


class AssistanceUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = Server()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        port = cls.server.server_address[1]
        cls.source_url = f"http://127.0.0.1:{port}/source.html"
        cls.provider_url = f"http://127.0.0.1:{port}/app/"
        try:
            cls.browser = Browser(
                user_data_dir=PROFILE,
                args=[
                    TEST_SWITCH,
                    f"{PROVIDER_SWITCH}={cls.provider_url}",
                    OFFLINE,
                ],
            )
            # Window A holds the dashboard. Every command runs from window B.
            cls.source = current_window(cls.browser)
            cls.browser.get(cls.source_url)
            cls.newtab = new_window(cls.browser)
            cls.browser.get("chrome://newtab")
            if not wait_for_newtab(cls.browser):
                raise RuntimeError("the new tab page did not load")
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        # setUpClass calls this too when it fails part way, so check each part.
        if hasattr(cls, "browser"):
            cls.browser.quit()
        if hasattr(cls, "server"):
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join()

    def setUp(self):
        # Every test starts with the panel closed, an empty log and a fresh
        # dashboard, so no earlier test's answer can leak into this one.
        self.close_panel()
        with self.server.log_lock:
            self.server.entries.clear()
        self.go_source(self.source_url)
        opened = self.hook("open", "source.html") or {}
        self.assertTrue(opened.get("found"), "the dashboard tab was not found")
        self.assertTrue(opened.get("available"), "the dashboard is not available")
        state = self.wait_state(lambda s: s.get("open"))
        self.assertTrue(state.get("open"), "the panel did not open")

    # Test helpers. Each one leaves the current window on window B.

    def hook(self, *command, timeout=5.0):
        """Run one test command from window B and return the answer it gives."""
        self.browser.run(
            "window.lastAssistanceTest = '__pending__';"
            "chrome.send('assistanceTest', arguments[0]);",
            [list(command)],
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.browser.run("return window.lastAssistanceTest")
            if result != "__pending__":
                return result
            time.sleep(0.05)
        return None

    def close_panel(self):
        """Close the panel if one is open; "close" on a closed one opens it."""
        if (self.hook("state") or {}).get("showing"):
            self.hook("close")
        self.wait_state(lambda s: not s.get("open"))

    def wait_state(self, predicate, timeout=10.0):
        """The panel's state once `predicate` holds, or the last one seen."""
        deadline = time.monotonic() + timeout
        while True:
            state = self.hook("state") or {}
            if predicate(state) or time.monotonic() >= deadline:
                return state
            time.sleep(0.1)

    def source_js(self, script):
        """Run `script` in window A, the dashboard, then come back to window B."""
        switch_to(self.browser, self.source)
        try:
            return self.browser.run(script)
        finally:
            switch_to(self.browser, self.newtab)

    def go_source(self, url):
        """Load `url` in the dashboard's window, then come back to window B."""
        switch_to(self.browser, self.source)
        try:
            self.browser.get(url)
        finally:
            switch_to(self.browser, self.newtab)

    def log_entries(self):
        """What the fake Gemini has reported so far, oldest first."""
        with self.server.log_lock:
            return list(self.server.entries)

    def wait_for_entry(self, entry, timeout=5.0):
        """Wait until the fake Gemini reports `entry`, then return the log."""
        deadline = time.monotonic() + timeout
        while entry not in self.log_entries() and time.monotonic() < deadline:
            time.sleep(0.05)
        return self.log_entries()

    def assert_outlined_not_clicked(self):
        """The outline is on the dashboard, and no link was clicked."""
        self.assertTrue(self.source_js(OUTLINE_JS), "no outline on the dashboard")
        self.assertIsNone(
            self.source_js(CLICKED_JS), "a link on the dashboard was clicked"
        )

    def ask_and_answer(self, question):
        """Share `question` and press Send, as the person would.

        Checks the two halves on the way: waiting for Send before, and the
        answer after. Returns the state once the answer is in.
        """
        self.assertTrue(self.hook("setQuestion", question))
        self.assertTrue(self.hook("share"))
        waiting = self.wait_state(lambda s: s.get("state") == "waitingForSend")
        self.assertEqual(waiting.get("state"), "waitingForSend")
        self.assertIn("input", self.wait_for_entry("input"))
        self.assertNotIn("send", self.log_entries())

        self.assertTrue(self.hook("pressSend"))
        state = self.wait_state(
            lambda s: s.get("state") == "answered" and s.get("canShowMe")
        )
        self.assertEqual(state.get("state"), "answered")
        self.assertTrue(state.get("canShowMe"))
        self.assertIn("send", self.wait_for_entry("send"))
        return state

    # Tests

    def test_open_shares_nothing(self):
        state = self.wait_state(lambda s: s.get("state") == "idle")
        self.assertTrue(state.get("showing"))
        self.assertTrue(state.get("available"))
        self.assertEqual(state.get("state"), "idle")
        self.assertTrue(state.get("providerUrl", "").startswith(self.provider_url))
        self.assertIn("Temporary chat", state.get("status", ""))
        self.assertEqual(self.log_entries(), [])

    def test_find_is_local_and_highlights(self):
        self.assertTrue(self.hook("setQuestion", "where is the api key"))
        self.assertTrue(self.hook("find"))
        state = self.wait_state(
            lambda s: (
                s.get("state") == "found"
                and (s.get("matches") or [None])[0] == "API keys"
            )
        )
        self.assertEqual(state.get("state"), "found")
        self.assertEqual((state.get("matches") or [None])[0], "API keys")

        self.assertTrue(self.hook("showMatch", 0))
        self.assert_outlined_not_clicked()
        self.assertEqual(self.log_entries(), [])

    def test_preview_shows_exact_text_and_shares_nothing(self):
        self.assertTrue(self.hook("setQuestion", QUESTION))
        self.assertTrue(self.hook("preview"))
        state = self.wait_state(
            lambda s: s.get("state") == "ready" and s.get("previewing")
        )
        self.assertEqual(state.get("state"), "ready")
        self.assertTrue(state.get("previewing"))
        prompt = state.get("prompt", "")
        self.assertIn(QUESTION, prompt)
        self.assertIn("API keys", prompt)
        self.assertEqual(self.log_entries(), [])

    def test_share_waits_for_person_then_show_me(self):
        state = self.ask_and_answer(QUESTION)
        self.assertTrue(state.get("canShowMe"))

        self.assertTrue(self.hook("showMe"))
        self.assert_outlined_not_clicked()

    def test_page_change_makes_answer_stale(self):
        self.ask_and_answer(QUESTION)

        self.source_js("history.pushState({}, '', '/source.html?changed')")
        state = self.wait_state(lambda s: s.get("state") == "stale")
        self.assertEqual(state.get("state"), "stale")
        self.assertFalse(state.get("canShowMe"))

    def test_close_ends_panel(self):
        self.assertTrue(self.hook("close"))
        state = self.wait_state(lambda s: not s.get("open"))
        self.assertFalse(state.get("open"))

    def test_not_available_on_internal_pages(self):
        # The panel belongs to its tab and stays open across a navigation, so
        # close it first and ask for a fresh one on the internal page.
        self.close_panel()
        self.go_source("about:blank")

        opened = self.hook("open", "about:blank") or {}
        self.assertTrue(opened.get("found"))
        self.assertFalse(opened.get("available"))
        state = self.hook("state") or {}
        self.assertFalse(state.get("showing"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
