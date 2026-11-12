#!/usr/bin/env python3
"""A local site to sign in to, for checking that a person stays signed in
across a restart and across an update (Release 4, ledger item 4).

One HTTP server on loopback. Signing in (POST /login) sets two cookies the
way real sites do:

  sid       a session cookie (no expiry, HttpOnly): kept across a restart
            only because "Continue where you left off" restores session
            cookies along with the tabs
  remember  a persistent cookie (Max-Age 30 days, HttpOnly)

The server keeps who each cookie belongs to in memory, so "signed in" is
the server's answer to the cookies the browser sends (GET /whoami), not
something the page could fake. The page also leaves a value in
localStorage and in IndexedDB.

Used by smoke_login_restart.py (a plain restart, headless) and by the
Windows Sandbox update test (tools/sbx/login_stages.py). The JavaScript
below is one expression that resolves to a JSON string, so it runs both
through DevTools (Runtime.evaluate) and, wrapped by for_webdriver(),
through WebDriver's execute/async.
"""

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "login.localhost"  # Chromium resolves *.localhost to loopback itself
USER = "tester"
STORED = "kept-" + USER
REMEMBER_SECONDS = 30 * 24 * 3600
MAX_BODY = 4096  # the sign-in body is "user=tester"

SIGN_IN_JS = """(async () => {
  const r = await fetch('/login', {method: 'POST', body: 'user=%s',
                                   credentials: 'same-origin'});
  localStorage.setItem('login-test', '%s');
  await new Promise((ok, bad) => {
    const open = indexedDB.open('login-test', 1);
    open.onupgradeneeded = () => open.result.createObjectStore('kv');
    open.onerror = () => bad(open.error);
    open.onsuccess = () => {
      const tx = open.result.transaction('kv', 'readwrite');
      tx.objectStore('kv').put('%s', 'who');
      tx.oncomplete = () => { open.result.close(); ok(); };
      tx.onerror = () => bad(tx.error);
    };
  });
  return JSON.stringify({status: r.status});
})()""" % (USER, STORED, STORED)

STATE_JS = """(async () => {
  const who = await (await fetch('/whoami', {credentials: 'same-origin',
                                             cache: 'no-store'})).json();
  const idb = await new Promise(ok => {
    const open = indexedDB.open('login-test', 1);
    open.onupgradeneeded = () => open.result.createObjectStore('kv');
    open.onerror = () => ok('error: ' + open.error);
    open.onsuccess = () => {
      const get = open.result.transaction('kv').objectStore('kv').get('who');
      get.onsuccess = () => { open.result.close(); ok(get.result || null); };
      get.onerror = () => ok('error: ' + get.error);
    };
  });
  return JSON.stringify({session: who.session, remember: who.remember,
                         local: localStorage.getItem('login-test'), idb: idb});
})()"""


def for_webdriver(expression):
    """The expression as a WebDriver execute/async script."""
    return (
        "const done = arguments[arguments.length - 1];\n"
        f"({expression}).then(done, e => done(JSON.stringify({{error: String(e)}})));"
    )


PAGE = "<!doctype html><title>Login test</title><h1>Login test</h1>"


class LoginSite:
    """The server. `url` is the home page; start() and stop() bracket it."""

    def __init__(self, port=0, bind="127.0.0.1"):
        self.sessions = {}
        self.remembered = {}
        self.lock = threading.Lock()
        site = self

        class Handler(BaseHTTPRequestHandler):
            def cookies(self):
                out = {}
                for part in (self.headers.get("Cookie") or "").split(";"):
                    name, _, value = part.strip().partition("=")
                    if name:
                        out[name] = value
                return out

            def reply(self, body, kind, extra=(), status=200):
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                for name, value in extra:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def host_ok(self):
                """Only the names this site is reached by. A page in another
                browser that rebinds its own name to 127.0.0.1 sends that
                name as Host, and gets a 403."""
                if self.headers.get("Host") in site.allowed_hosts:
                    return True
                self.reply("wrong host", "text/plain", status=403)
                return False

            def do_GET(self):  # noqa: N802
                if not self.host_ok():
                    return
                path = self.path.split("?")[0]
                if path == "/whoami":
                    c = self.cookies()
                    with site.lock:
                        who = {
                            "session": site.sessions.get(c.get("sid")),
                            "remember": site.remembered.get(c.get("remember")),
                        }
                    self.reply(json.dumps(who), "application/json")
                else:
                    self.reply(PAGE, "text/html; charset=utf-8")

            def do_POST(self):  # noqa: N802
                if not self.host_ok():
                    return
                raw = (self.headers.get("Content-Length") or "0").strip()
                if not (raw.isascii() and raw.isdigit()):
                    return self.reply("bad length", "text/plain", status=400)
                length = int(raw)
                if length > MAX_BODY:
                    return self.reply("too big", "text/plain", status=413)
                body = self.rfile.read(length).decode("utf-8", "replace")
                user = dict(
                    p.partition("=")[::2] for p in body.split("&") if p
                ).get("user", "")
                sid, remember = secrets.token_hex(16), secrets.token_hex(16)
                with site.lock:
                    site.sessions[sid] = user
                    site.remembered[remember] = user
                self.reply(
                    json.dumps({"user": user}),
                    "application/json",
                    [
                        ("Set-Cookie", f"sid={sid}; Path=/; HttpOnly; SameSite=Lax"),
                        (
                            "Set-Cookie",
                            f"remember={remember}; Path=/; Max-Age="
                            f"{REMEMBER_SECONDS}; HttpOnly; SameSite=Lax",
                        ),
                    ],
                )

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer((bind, port), Handler)
        port = self.server.server_port
        self.allowed_hosts = {f"{h}:{port}" for h in (HOST, "127.0.0.1", "localhost")}
        self.url = f"http://{HOST}:{port}/home"

    def start(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        self.server.shutdown()


def signed_in_checks(state):
    """(name, ok, detail) for a STATE_JS answer: what must hold for the
    person to still be signed in, with their site data."""
    s = json.loads(state) if isinstance(state, str) else (state or {})
    detail = json.dumps(s)
    return [
        ("the session cookie is still sent (signed in)", s.get("session") == USER, detail),
        ("the persistent cookie is still sent", s.get("remember") == USER, detail),
        ("localStorage is kept", s.get("local") == STORED, detail),
        ("IndexedDB is kept", s.get("idb") == STORED, detail),
    ]


def cookie_rows(cookies_db, host=HOST):
    """[(name, persistent, prefix of the encrypted value)] from a closed
    profile's Network/Cookies. The prefix says how the value is sealed:
    v10 with the DPAPI-wrapped key in Local State, v20 app-bound."""
    import sqlite3

    con = sqlite3.connect(f"file:{cookies_db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT name, is_persistent, substr(encrypted_value, 1, 3) "
            "FROM cookies WHERE host_key LIKE ?",
            ("%" + host,),
        ).fetchall()
    finally:
        con.close()
    return [
        (name, bool(persistent), bytes(prefix or b"").decode("ascii", "replace"))
        for name, persistent, prefix in rows
    ]


def key_state(local_state_path):
    """What Local State says about the cookie key: the DPAPI-wrapped key
    (its value, to compare across an update) and whether an app-bound key
    is there too."""
    with open(local_state_path, encoding="utf-8") as f:
        crypt = json.load(f).get("os_crypt", {})
    return {
        "encrypted_key": crypt.get("encrypted_key", ""),
        "app_bound": bool(crypt.get("app_bound_encrypted_key")),
    }
