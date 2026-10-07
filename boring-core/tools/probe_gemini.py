#!/usr/bin/env python3
"""Run the page assistance scripts against Gemini, the way the browser will.

Every script runs in its own isolated JavaScript world, reached through CDP
on chromedriver, never in the page's own world. Tab A holds a local account
dashboard. Tab B holds Gemini.

Usage:
    python probe_gemini.py --fixture
        Offline. Tab B is a fake Gemini served on 127.0.0.1, and Chromium
        cannot resolve any other host. Exit 0 only if the reply names the
        "API keys" control and the highlight is accepted.

    python probe_gemini.py --live --profile E:/tmp/assist-probe-profile
    python probe_gemini.py --live --profile DIR --send --timeout 120
        Opens https://gemini.google.com/app in that profile, which must be
        signed in already. Without --send, press Send in the Gemini window
        yourself. Exit 0 only if a reply was read.

Each run writes E:/tmp/assist-probe/result-<UTC time>.json. Cookies and
storage are never read. Set BORING_OUT to the build's out/Default folder.
"""

import argparse
import functools
import http.server
import json
import os
import secrets
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("TMP", r"E:\tmp" if os.name == "nt" else tempfile.gettempdir())
os.environ.setdefault("TEMP", os.environ["TMP"])

from drive import PROFILE, Browser  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "components/boring/assistance"
RESULT_DIR = Path("E:/tmp/assist-probe")
WORLD = "boring-assist-probe"
QUESTION = "Where do I create an API key?"
GEMINI_URL = "https://gemini.google.com/app"
STATUS_WAIT = 30
FIXTURE_REPLY_WAIT = 20

SOURCE_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Account dashboard</title>
<nav>
  <a href="/settings">Settings</a>
  <a href="/keys">API keys</a>
  <a href="/billing">Billing</a>
</nav>
<main>
  <h1>Account</h1>
  <p>Your plan includes 100 requests per day. Usage resets at midnight UTC.</p>
  <table>
    <tr><th>Plan</th><th>Limit</th></tr>
    <tr><td>Free</td><td>100</td></tr>
  </table>
</main>
"""

# Stands in for Gemini's page. It reads the prompt the adapter put in the
# composer, then appends a completed reply 500 ms after Send.
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
  document.querySelector('button[aria-label="Send message"]')
    .addEventListener('click', () => {
      const text = document.querySelector('[role="textbox"]').textContent;
      const step = /BORING_STEP ([a-zA-Z0-9_-]{6,64}) ([1-9][0-9]*) <candidate-id>/
        .exec(text);
      const marker = 'PAGE SNAPSHOT (JSON):';
      const snapshot = JSON.parse(text.slice(text.indexOf(marker) + marker.length));
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


class ProbeError(RuntimeError):
    """A script threw, or the browser refused a command the probe needed."""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:
        pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def read_script(name: str) -> str:
    path = SCRIPTS / name
    if not path.is_file():
        raise ProbeError(f"missing script: {path}")
    return path.read_text(encoding="utf-8")


def write_site(root: Path) -> None:
    (root / "app").mkdir(parents=True)
    (root / "index.html").write_text(SOURCE_PAGE, encoding="utf-8")
    (root / "app" / "index.html").write_text(FAKE_GEMINI, encoding="utf-8")


def serve(root: Path) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(_Quiet, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def cdp(browser: Browser, cmd: str, params: dict[str, Any] | None = None) -> Any:
    """One DevTools command, sent to the tab that is current."""
    body = {"cmd": cmd, "params": params or {}}
    path = f"/session/{browser.sid}/goog/cdp/execute"
    return browser._req("POST", path, body)["value"]


class Tab:
    """One browser tab and the isolated probe world made in it."""

    def __init__(self, browser: Browser, handle: str) -> None:
        self.browser = browser
        self.handle = handle
        self.context = 0

    def focus(self) -> None:
        # CDP commands go to the current tab, so every call switches first.
        path = f"/session/{self.browser.sid}/window"
        self.browser._req("POST", path, {"handle": self.handle})

    def open_world(self) -> None:
        self.focus()
        frame = cdp(self.browser, "Page.getFrameTree")["frameTree"]["frame"]["id"]
        made = cdp(
            self.browser,
            "Page.createIsolatedWorld",
            {"frameId": frame, "worldName": WORLD},
        )
        self.context = made["executionContextId"]

    def run(self, expression: str) -> Any:
        self.focus()
        res = cdp(
            self.browser,
            "Runtime.evaluate",
            {
                "expression": expression,
                "contextId": self.context,
                "returnByValue": True,
            },
        )
        if "exceptionDetails" in res:
            details = res["exceptionDetails"]
            exception = details.get("exception") or {}
            text = exception.get("description") or details.get("text")
            raise ProbeError(f"script threw in tab {self.handle}: {text}")
        return res["result"].get("value")

    def load(self, global_name: str, source: str, call: str = "") -> None:
        """Install a script once as a global in this tab's isolated world."""
        self.run(f"globalThis.{global_name} = ({source}){call}; true")


PAGE_WORLD_CHECK = (
    "return ['__probePage', '__probeProtocol', '__probeSnapshot', "
    "'__probeGemini'].some(name => name in window);"
)


def assert_isolated(browser: Browser, tab: Tab) -> None:
    """Fail loudly if the probe's globals are visible in the page's world."""
    tab.focus()
    if browser.run(PAGE_WORLD_CHECK):
        raise ProbeError(f"probe globals visible in page world of {tab.handle}")


def new_tab(browser: Browser) -> str:
    path = f"/session/{browser.sid}/window/new"
    return browser._req("POST", path, {"type": "tab"})["value"]["handle"]


def current_tab(browser: Browser) -> str:
    return browser._req("GET", f"/session/{browser.sid}/window")["value"]


def poll(
    read: Callable[[], dict[str, Any]],
    seconds: float,
    timeline: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    """Call read() once a second until it reports ok or time runs out.

    Each change of reason is printed with a timestamp and kept in timeline.
    """
    deadline = time.monotonic() + seconds
    last = None
    while True:
        state = read()
        if state["reason"] != last:
            last = state["reason"]
            timeline.append({"at": utc_now(), "ok": state["ok"], "reason": last})
            print(f"  {utc_now()} {label}: {last}", flush=True)
        if state["ok"] or time.monotonic() >= deadline:
            return state
        time.sleep(1)


def probe(
    browser: Browser,
    *,
    source_url: str,
    gemini_url: str,
    gemini_location: str,
    send: bool,
    reply_wait: float,
    record: dict[str, Any],
) -> bool:
    """Run one question through both tabs. Returns True if a reply was read."""
    # Tab A: the source page, its snapshot, and the prompt.
    tab_a = Tab(browser, current_tab(browser))
    browser.get(source_url)
    tab_a.open_world()
    tab_a.load("__probePage", read_script("page_context.js"))
    tab_a.load("__probeProtocol", read_script("protocol.js"))
    assert_isolated(browser, tab_a)
    request_id = secrets.token_hex(6)
    snapshot = tab_a.run(
        "(globalThis.__probeSnapshot = globalThis.__probePage.capture("
        f"{json.dumps(request_id)}))"
    )
    prompt = tab_a.run(
        "globalThis.__probeProtocol.makePrompt("
        f"{json.dumps(QUESTION)}, globalThis.__probeSnapshot)"
    )
    expected = next(
        (c["id"] for c in snapshot["candidates"] if c["label"] == "API keys"),
        None,
    )
    record.update(
        request_id=request_id,
        revision=snapshot["revision"],
        snapshot_candidates=len(snapshot["candidates"]),
        snapshot_bytes=tab_a.run(
            "new TextEncoder().encode(JSON.stringify(globalThis.__probeSnapshot))"
            ".length"
        ),
        prompt_bytes=len(prompt.encode("utf-8")),
        expected_candidate=expected,
    )

    # Tab B: Gemini, with the adapter installed as the only way in.
    tab_b = Tab(browser, new_tab(browser))
    tab_b.focus()
    browser.get(gemini_url)
    tab_b.open_world()
    tab_b.load(
        "__probeGemini",
        read_script("gemini_adapter.js"),
        f"(document, () => {gemini_location})",
    )
    assert_isolated(browser, tab_b)
    record["page_world_clean"] = True
    timeline: list[dict[str, Any]] = []
    poll(
        lambda: tab_b.run("globalThis.__probeGemini.status()"),
        STATUS_WAIT,
        timeline,
        "status",
    )
    record["status_timeline"] = timeline
    prepared = tab_b.run(f"globalThis.__probeGemini.prepare({json.dumps(prompt)})")
    record["prepare"] = prepared
    record["submit"] = None
    if not prepared["ok"]:
        return False

    sent = time.monotonic()
    if send:
        record["submit"] = tab_b.run("globalThis.__probeGemini.submit()")
        if not record["submit"]["ok"]:
            return False
    else:
        # readReply() notices the prompt leaving the composer, so a Send
        # pressed by hand counts the same as submit().
        print("Press Send in the Gemini window", flush=True)

    reply_timeline: list[dict[str, Any]] = []
    reply = poll(
        lambda: tab_b.run("globalThis.__probeGemini.readReply()"),
        reply_wait,
        reply_timeline,
        "reply",
    )
    record["reply_timeline"] = reply_timeline
    record["reply_text"] = reply.get("text") if reply["ok"] else None
    if not reply["ok"]:
        return False
    record["seconds_to_reply"] = round(time.monotonic() - sent, 2)

    # Tab A again: the reply must parse to an observed control, then highlight.
    text = json.dumps(reply["text"])
    candidate = tab_a.run(
        f"globalThis.__probeProtocol.parseGuidance({text}, globalThis.__probeSnapshot)"
    )
    record["parse"] = candidate
    record["highlight"] = None
    if candidate is not None:
        record["highlight"] = tab_a.run(
            "globalThis.__probePage.highlight("
            f"{json.dumps(request_id)}, {snapshot['revision']}, "
            f"{json.dumps(candidate)})"
        )
    return True


def run_fixture(record: dict[str, Any]) -> bool:
    with tempfile.TemporaryDirectory(
        prefix="boring-probe-", dir=os.environ["TMP"]
    ) as root:
        write_site(Path(root))
        server = serve(Path(root))
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            args = [
                "--headless=new",
                "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
            ]
            with Browser(user_data_dir=PROFILE, args=args) as browser:
                replied = probe(
                    browser,
                    source_url=f"{base}/index.html",
                    gemini_url=f"{base}/app/",
                    gemini_location='new URL("https://gemini.google.com/app")',
                    send=True,
                    reply_wait=FIXTURE_REPLY_WAIT,
                    record=record,
                )
        finally:
            server.shutdown()
            server.server_close()
    expected = record.get("expected_candidate")
    highlight = record.get("highlight") or {}
    return (
        replied
        and expected is not None
        and record.get("parse") == expected
        and highlight.get("ok") is True
    )


def run_live(args: argparse.Namespace, record: dict[str, Any]) -> bool:
    with tempfile.TemporaryDirectory(
        prefix="boring-probe-", dir=os.environ["TMP"]
    ) as root:
        write_site(Path(root))
        server = serve(Path(root))
        try:
            profile = str(Path(args.profile).resolve())
            with Browser(user_data_dir=profile) as browser:
                return probe(
                    browser,
                    source_url=f"http://127.0.0.1:{server.server_port}/index.html",
                    gemini_url=GEMINI_URL,
                    gemini_location="new URL(location.href)",
                    send=args.send,
                    reply_wait=args.timeout,
                    record=record,
                )
        finally:
            server.shutdown()
            server.server_close()


def write_result(record: dict[str, Any], started: datetime) -> Path:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    path = RESULT_DIR / f"result-{stamp}.json"
    text = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the assistance scripts against Gemini through CDP."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--fixture", action="store_true", help="offline run against a fake Gemini"
    )
    mode.add_argument(
        "--live", action="store_true", help="run against gemini.google.com"
    )
    parser.add_argument(
        "--profile", help="--live: Chrome profile folder, already signed in"
    )
    parser.add_argument(
        "--send", action="store_true", help="--live: let the tool press Send"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="--live: seconds to wait for the reply (default 120)",
    )
    args = parser.parse_args(argv)
    if args.live and not args.profile:
        parser.error("--live needs --profile")

    started = datetime.now(UTC)
    record: dict[str, Any] = {
        "mode": "fixture" if args.fixture else "live",
        "started": started.isoformat(timespec="seconds"),
        "send_by_tool": bool(args.fixture or args.send),
    }
    passed = False
    try:
        passed = run_fixture(record) if args.fixture else run_live(args, record)
    except Exception as exc:  # recorded and reported below, then exit 1
        record["error"] = str(exc)
        print(f"error: {exc}", file=sys.stderr)
        if not isinstance(exc, ProbeError):
            traceback.print_exc()
    finally:
        record["passed"] = passed
        path = write_result(record, started)
    print(f"passed: {passed}")
    print(f"result: {path}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
