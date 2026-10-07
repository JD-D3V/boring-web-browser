#!/usr/bin/env python3
"""Offline browser tests for assistance scripts; never opens an AI provider.

Uses a fresh headless profile and synthetic localhost pages. Run with
BORING_OUT pointing at a built chrome.exe/chromedriver.exe pair.
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

FIXTURE = (
    "<!doctype html><title>Example Dashboard</title>\n"
    '<nav><a id="settings" href="/settings?secret=private#token">Settings</a>\n'
    '<button id="api" onclick="document.body.dataset.clicked=\'yes\'">'
    "API documentation</button></nav>\n"
    "<main><h1>Welcome</h1><p>Find developer tools using the menu.</p>\n"
    '<label for="password">Password</label>'
    '<input id="password" value="PASSWORD_SECRET" type="password">\n'
    '<textarea>TEXTAREA_SECRET</textarea><input value="INPUT_SECRET">\n'
    '<div contenteditable="true"><span>EDITABLE_SECRET</span>'
    "<button>EDITABLE_BUTTON_SECRET</button></div>\n"
    '<div hidden>HIDDEN_SECRET</div><div style="visibility:hidden">'
    "INVISIBLE_SECRET</div>\n"
    "<p>Token: sk-abcdefghijklmnopqrstuvwxyz012345</p>\n"
    "<table><tr><th>Plan</th><th>Limit</th></tr><tr><td>Free</td>"
    "<td>100</td></tr></table>\n"
    '<div id="shadow"></div><iframe srcdoc="<p>FRAME_SECRET</p>"></iframe></main>\n'
    "<script>document.getElementById('shadow').attachShadow({mode:'open'})"
    '.innerHTML=\'<a href="/docs">Shadow docs</a>'
    '<input value="SHADOW_SECRET">\';</script>'
)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


class AssistanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(
            prefix="boring-assistance-", dir=os.environ["TMP"]
        )
        Path(cls.tmp.name, "index.html").write_text(FIXTURE, encoding="utf8")
        cls.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=cls.tmp.name)
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.browser = Browser(user_data_dir=PROFILE, args=["--headless=new"])
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/index.html"

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
        self.browser.run(
            f"window.{target} = ("
            + file.read_text(encoding="utf8")
            + ")"
            + suffix
            + ";"
        )

    def capture(self):
        self.install("page_context.js", "reader")
        return self.browser.run('return reader.capture("abc123")')

    def test_snapshot_excludes_secrets_and_preserves_navigation(self):
        snap = self.capture()
        serialized = json.dumps(snap)
        for secret in [
            "PASSWORD_SECRET",
            "TEXTAREA_SECRET",
            "INPUT_SECRET",
            "EDITABLE_SECRET",
            "EDITABLE_BUTTON_SECRET",
            "HIDDEN_SECRET",
            "INVISIBLE_SECRET",
            "SHADOW_SECRET",
            "FRAME_SECRET",
            "sk-abcdefghijklmnopqrstuvwxyz012345",
            "secret=private",
            "#token",
        ]:
            self.assertNotIn(secret, serialized)
        labels = [c["label"] for c in snap["candidates"]]
        self.assertIn("Settings", labels)
        self.assertIn("API documentation", labels)
        self.assertIn("Shadow docs", labels)
        self.assertTrue(snap["coverage"]["partial"])
        self.assertIn("100", serialized)

    def test_unslotted_light_text_is_left_out(self):
        # A shadow host's light children render only through a slot; the rest
        # is hidden text the person never sees.
        self.browser.run(
            'const host=document.createElement("div");'
            "host.innerHTML=`<p>UNSLOTTED_SECRET</p>"
            '<span slot="s">Slotted text</span>`;'
            'host.attachShadow({mode:"open"}).innerHTML='
            '`<slot name="s"></slot><p>Shadow text</p>`;'
            "document.body.append(host);"
        )
        serialized = json.dumps(self.capture())
        self.assertNotIn("UNSLOTTED_SECRET", serialized)
        self.assertIn("Slotted text", serialized)
        self.assertIn("Shadow text", serialized)

    def test_highlight_never_clicks_and_rejects_changed_targets(self):
        snap = self.capture()
        target = next(
            c["id"] for c in snap["candidates"] if c["label"] == "API documentation"
        )
        result = self.browser.run(
            'return reader.highlight("abc123",arguments[0],arguments[1])',
            [snap["revision"], target],
        )
        self.assertTrue(result["ok"])
        self.assertIsNone(
            self.browser.run("return document.body.dataset.clicked || null")
        )
        self.browser.run('document.getElementById("api").textContent="Delete account"')
        self.assertFalse(
            self.browser.run(
                'return reader.highlight("abc123",arguments[0],arguments[1])',
                [snap["revision"], target],
            )["ok"]
        )
        self.browser.run("reader.dispose()")
        self.assertFalse(
            self.browser.run(
                'return reader.highlight("abc123",arguments[0],arguments[1])',
                [snap["revision"], target],
            )["ok"]
        )

    def test_same_document_navigation_invalidates_targets(self):
        snap = self.capture()
        self.browser.run('history.pushState({},"","/other")')
        self.assertFalse(
            self.browser.run(
                'return reader.highlight("abc123",arguments[0],"c1")',
                [snap["revision"]],
            )["ok"]
        )

    def test_context_is_bounded_utf8_and_candidate_count(self):
        self.browser.run(
            'for(let i=0;i<1000;i++){let p=document.createElement("p");'
            'p.textContent="界".repeat(200);document.body.append(p);'
            'let a=document.createElement("a");a.href="/"+i;'
            'a.textContent="Tool "+i;document.body.append(a)}'
        )
        snap = self.capture()
        size = self.browser.run(
            "return new TextEncoder().encode(JSON.stringify("
            'reader.capture("def456"))).length'
        )
        self.assertLessEqual(size, 48 * 1024)
        self.assertLessEqual(len(snap["candidates"]), 160)
        self.assertTrue(snap["coverage"]["partial"])

    def target_id(self, snap, label):
        return next(c["id"] for c in snap["candidates"] if c["label"] == label)

    def highlight(self, snap, candidate):
        return self.browser.run(
            'return reader.highlight("abc123",arguments[0],arguments[1])',
            [snap["revision"], candidate],
        )

    def test_unrelated_changes_keep_target(self):
        snap = self.capture()
        target = self.target_id(snap, "API documentation")
        self.browser.run(
            'document.body.insertAdjacentHTML("beforeend","<div>tick</div>");document.body.dataset.tick="1"'
        )
        self.assertTrue(self.highlight(snap, target)["ok"])

    def test_removed_target_is_rejected(self):
        snap = self.capture()
        target = self.target_id(snap, "API documentation")
        self.browser.run('document.getElementById("api").remove()')
        self.assertEqual(
            self.highlight(snap, target),
            {"ok": False, "reason": "stale_or_unknown_target"},
        )

    def test_outline_follows_scroll(self):
        self.browser.run('document.body.style.height="4000px"')
        snap = self.capture()
        target = self.target_id(snap, "API documentation")
        self.assertTrue(self.highlight(snap, target)["ok"])
        self.browser.run("window.scrollBy(0,300)")
        self.browser.run_async(
            "const done=arguments[arguments.length-1];"
            "requestAnimationFrame(()=>requestAnimationFrame(()=>done(true)))"
        )
        outline, api = self.browser.run(
            "const o=[...document.documentElement.children]"
            '.filter(e=>e.getAttribute("aria-hidden")==="true").pop();'
            "return [o.getBoundingClientRect().top,"
            'document.getElementById("api").getBoundingClientRect().top-4]'
        )
        self.assertLessEqual(abs(outline - api), 1)

    def test_escape_removes_outline(self):
        snap = self.capture()
        self.assertTrue(
            self.highlight(snap, self.target_id(snap, "API documentation"))["ok"]
        )
        self.browser.run(
            'document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape"}))'
        )
        self.assertEqual(
            self.browser.run(
                "return [...document.documentElement.children]"
                '.filter(e=>e.getAttribute("aria-hidden")==="true").length'
            ),
            0,
        )

    def test_navigation_text_left_out_of_narrative(self):
        snap = self.capture()
        for block in snap["blocks"]:
            for word in ["Settings", "API documentation"]:
                self.assertNotIn(word, block["text"])
        labels = [c["label"] for c in snap["candidates"]]
        self.assertIn("Settings", labels)
        self.assertIn("API documentation", labels)

    def test_capture_time_on_long_page(self):
        self.browser.run(
            "for(let i=0;i<2000;i++){let host=document.body;"
            "for(let d=0;d<5;d++){"
            'const div=document.createElement("div");host.append(div);host=div}'
            'const section=document.createElement("section"),'
            'h2=document.createElement("h2"),p=document.createElement("p"),'
            'ul=document.createElement("ul");h2.textContent="Section "+i;'
            'p.textContent="Notes for section "+i;for(let j=0;j<3;j++){'
            'const a=document.createElement("a");a.href="/item/"+i+"/"+j;'
            'a.textContent="Tool "+i+"."+j;ul.append(a)}section.append(h2,p,ul);'
            "host.append(section)}"
        )
        self.install("page_context.js", "reader")
        ms, size, elements, snap = self.browser.run(
            'const count=document.getElementsByTagName("*").length;'
            'const t=performance.now();const s=reader.capture("long01");'
            "const ms=performance.now()-t;return [ms,"
            "new TextEncoder().encode(JSON.stringify(s)).length,count,s]"
        )
        print(
            f"\ncapture on {elements} elements: {ms:.1f} ms, {size} bytes, "
            f"{len(snap['candidates'])} candidates"
        )
        self.assertLess(ms, 1500)
        self.assertLessEqual(len(snap["candidates"]), 160)
        self.assertLessEqual(size, 49152)

    def adapter(self, origin="https://gemini.google.com/app"):
        self.browser.run(
            'document.body.innerHTML=`<div contenteditable="true" '
            'role="textbox" aria-label="Enter a prompt for Gemini"></div>'
            '<button aria-label="Send message">Send</button>`;'
            'window.sends=0;document.querySelector("button")'
            ".onclick=()=>window.sends++;window.inputs=0;"
            'document.querySelector("[role=textbox]")'
            '.addEventListener("input",()=>window.inputs++);'
        )
        self.install(
            "gemini_adapter.js",
            "adapter",
            "(document, () => new URL(" + json.dumps(origin) + "))",
        )

    def test_adapter_preserves_drafts_and_requires_exact_destination(self):
        for origin in [
            "https://gemini.google.com.evil.test/app",
            "http://gemini.google.com/app",
            "https://gemini.google.com:444/app",
            "https://accounts.google.com/app",
        ]:
            self.adapter(origin)
            self.assertFalse(self.browser.run('return adapter.prepare("test")')["ok"])
        self.adapter()
        self.browser.run(
            'document.querySelector("[role=textbox]").textContent="My own draft"'
        )
        self.assertFalse(self.browser.run('return adapter.prepare("test")')["ok"])
        self.assertEqual(
            self.browser.run(
                'return document.querySelector("[role=textbox]").textContent'
            ),
            "My own draft",
        )

    def test_adapter_delivers_input_and_submits_once(self):
        self.adapter()
        self.assertTrue(
            self.browser.run('return adapter.prepare("Synthetic page question")')["ok"]
        )
        self.assertGreater(self.browser.run("return window.inputs"), 0)
        self.assertTrue(self.browser.run("return adapter.submit()")["ok"])
        self.assertFalse(self.browser.run("return adapter.submit()")["ok"])
        self.assertEqual(self.browser.run("return window.sends"), 1)

    def test_adapter_rejects_ambiguity_replacement_and_busy_generation(self):
        self.adapter()
        self.browser.run(
            'document.body.append(document.querySelector("[role=textbox]").cloneNode(true))'
        )
        self.assertFalse(self.browser.run('return adapter.prepare("test")')["ok"])

    def test_adapter_reads_only_new_completed_assistant_responses(self):
        self.adapter()
        self.browser.run(
            'document.body.insertAdjacentHTML("beforeend", '
            '`<response-container><div class="model-response-label-announcer" '
            'aria-busy="false"></div><message-content>Old answer</message-content>'
            '<button aria-label="Copy">Copy</button></response-container>`)'
        )
        self.assertTrue(
            self.browser.run('return adapter.prepare("BORING_STEP abc123 1 c1")')["ok"]
        )
        self.assertTrue(self.browser.run("return adapter.submit()")["ok"])
        self.browser.run(
            'document.body.insertAdjacentHTML("beforeend", '
            '`<div class="user-message">BORING_STEP abc123 1 c1</div>`)'
        )
        self.assertFalse(self.browser.run("return adapter.readReply()")["ok"])
        self.browser.run(
            'document.body.insertAdjacentHTML("beforeend", '
            '`<response-container id="answer">'
            '<div class="model-response-label-announcer" '
            'aria-busy="true"></div>'
            "<message-content>Open Settings.\nBORING_STEP "
            "abc123 1 c1</message-content></response-container>`)"
        )
        self.assertFalse(self.browser.run("return adapter.readReply()")["ok"])
        self.browser.run(
            'document.querySelector("#answer .model-response-label-announcer")'
            '.setAttribute("aria-busy","false"); '
            'document.getElementById("answer")'
            '.insertAdjacentHTML("beforeend",'
            '`<button aria-label="Copy">Copy</button>`)'
        )
        reply = self.browser.run("return adapter.readReply()")
        self.assertTrue(reply["ok"])
        self.assertIn("Open Settings.", reply["text"])
        self.assertNotIn("Old answer", reply["text"])

    def test_adapter_refuses_modified_draft_and_duplicate_send_controls(self):
        self.adapter()
        self.assertTrue(self.browser.run('return adapter.prepare("test")')["ok"])
        self.browser.run(
            'document.querySelector("[role=textbox]").textContent="changed"'
        )
        self.assertFalse(self.browser.run("return adapter.submit()")["ok"])
        self.adapter()
        self.assertTrue(self.browser.run('return adapter.prepare("test")')["ok"])
        self.browser.run(
            'document.body.append(document.querySelector("button").cloneNode(true))'
        )
        self.assertFalse(self.browser.run("return adapter.submit()")["ok"])
        self.adapter()
        self.assertTrue(self.browser.run('return adapter.prepare("test")')["ok"])
        self.browser.run(
            'document.querySelector("[role=textbox]").replaceWith(document.querySelector("[role=textbox]").cloneNode(true))'
        )
        self.assertFalse(self.browser.run("return adapter.submit()")["ok"])
        self.adapter()
        self.browser.run(
            'document.querySelector("button")'
            '.setAttribute("aria-label","Stop response")'
        )
        self.assertFalse(self.browser.run('return adapter.prepare("test")')["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
