#!/usr/bin/env python3
"""Offline browser tests for gemini_adapter.js; never opens Gemini.

Serves a synthetic /app/ page from localhost in a fresh headless profile.
Usage: BORING_OUT=E:/ung-154/build/src/out/Default python smoke_assistance_gemini.py
"""

import functools
import http.server
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "components/boring/assistance"
os.environ.setdefault("TMP", r"E:\tmp" if os.name == "nt" else tempfile.gettempdir())
os.environ.setdefault("TEMP", os.environ["TMP"])
from drive import PROFILE, Browser  # noqa: E402

PAGE = "<!doctype html><title>Synthetic app</title><main>Synthetic page</main>"
COMPOSER = (
    '<div contenteditable="true" role="textbox" '
    'aria-label="Enter a prompt for Gemini"></div>'
    '<button aria-label="Send message">Send</button>'
)
SIGNED_OUT = '<a href="https://accounts.google.com/ServiceLogin">Sign in</a>'
REPLY = (
    '<response-container><div class="model-response-label-announcer" '
    'aria-busy="false"></div><message-content>Open API keys.</message-content>'
    '<button aria-label="Copy">Copy</button></response-container>'
)
GEMINI = 'new URL("https://gemini.google.com/app")'
HERE = "new URL(location.href)"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


class GeminiAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(
            prefix="boring-gemini-", dir=os.environ["TMP"]
        )
        app = Path(cls.tmp.name, "app")
        app.mkdir()
        (app / "index.html").write_text(PAGE, encoding="utf8")
        cls.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=cls.tmp.name)
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.browser = Browser(user_data_dir=PROFILE, args=["--headless=new"])
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"
        cls.url = cls.origin + "/app/"

    @classmethod
    def tearDownClass(cls):
        cls.browser.quit()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def setUp(self):
        self.browser.get(self.url)

    def install(self, name, target, suffix=""):
        file = SCRIPTS / name
        self.assertTrue(file.is_file(), f"{name} must exist")
        # Synthetic fixtures only. Native code installs these in an isolated world.
        source = file.read_text(encoding="utf8")
        self.browser.run(f"window.{target} = (" + source + ")" + suffix + ";")

    def start(self, body=COMPOSER, location=GEMINI, origin=None):
        # Build the page first, then the adapter, so each test starts clean.
        self.browser.run(
            "document.body.innerHTML="
            + json.dumps(body)
            + ';window.sends=0;const b=document.querySelector("button");'
            "if(b)b.onclick=()=>window.sends++;"
        )
        args = "document, () => " + location
        if origin is not None:
            args += ", " + json.dumps(origin)
        self.install("gemini_adapter.js", "adapter", f"({args})")

    def call(self, expression):
        return self.browser.run("return adapter." + expression)

    def append(self, markup):
        self.browser.run(
            'document.body.insertAdjacentHTML("beforeend", ' + json.dumps(markup) + ")"
        )

    def test_existing_contract_still_holds(self):
        self.start(location=GEMINI)
        self.assertTrue(self.call('prepare("x")')["ok"])
        self.assertTrue(self.call("submit()")["ok"])
        self.assertFalse(self.call("submit()")["ok"])
        self.assertEqual(self.browser.run("return window.sends"), 1)

    def test_test_origin_only_when_passed(self):
        self.start(location=HERE)
        self.assertEqual(self.call("status().reason"), "unexpected_destination")
        self.start(location=HERE, origin=self.origin)
        state = self.call("status()")
        self.assertTrue(state["ok"])
        self.assertEqual(state["reason"], "ready")

    def test_bad_expected_origin_rejected(self):
        self.start(location=GEMINI, origin="https://gemini.google.com.evil.test/x")
        self.assertEqual(self.call("status().reason"), "unexpected_destination")
        self.assertFalse(self.call('prepare("test")')["ok"])
        # A well-formed look-alike host still must equal the page origin exactly.
        self.start(location=GEMINI, origin="https://gemini.google.com.evil.test")
        self.assertEqual(self.call("status().reason"), "unexpected_destination")

    def test_signed_out_is_reported(self):
        self.start(body=SIGNED_OUT, location=GEMINI)
        state = self.call("status()")
        self.assertFalse(state["ok"])
        self.assertEqual(state["reason"], "signed_out")
        self.assertEqual(self.call('prepare("test")')["reason"], "signed_out")

    def test_person_presses_send(self):
        self.start()
        self.assertTrue(self.call('prepare("Synthetic question")')["ok"])
        self.assertEqual(self.call("readReply().reason"), "waiting")
        self.browser.run('document.querySelector("[role=textbox]").textContent=""')
        self.append(REPLY)
        reply = self.call("readReply()")
        self.assertTrue(reply["ok"])
        self.assertIn("Open API keys.", reply["text"])
        # The person already sent it: the adapter must not send or re-prepare.
        self.assertFalse(self.call("submit()")["ok"])
        self.assertFalse(self.call('prepare("again")')["ok"])
        self.assertEqual(self.browser.run("return window.sends"), 0)

    def test_prompt_still_in_composer_keeps_waiting(self):
        self.start()
        self.assertTrue(self.call('prepare("Synthetic question")')["ok"])
        self.append(REPLY)
        self.assertEqual(self.call("readReply().reason"), "waiting")

    def test_dispose_ends_the_request(self):
        # A reply that was already on screen must not pass as a new one
        # once the session is gone.
        self.start()
        self.append(REPLY)
        self.call("dispose()")
        self.assertEqual(self.call("readReply().reason"), "disposed")
        self.assertEqual(self.call("status().reason"), "disposed")
        self.assertEqual(self.call('prepare("Synthetic question").reason'), "disposed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
