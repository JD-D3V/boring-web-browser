"""Signed in across a restart and an update (Release 4, ledger item 4).

The local test site (login_site.py) is checked here without a browser; the
browser is checked by smoke_login_restart.py (restart) and by the Sandbox
run's login stages (update). The last class pins the Chromium code that
the analysis of post-update logouts rests on, so a Chromium bump that
changes it fails here instead of logging people out."""

import ast
import base64
import contextlib
import io
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TOOLS), str(TOOLS / "sbx")]

import login_site  # noqa: E402

SRC = Path(os.environ.get("BORING_SRC_157", r"E:\ung-157\build\src"))


class LoginSiteTest(unittest.TestCase):
    def setUp(self):
        self.site = login_site.LoginSite().start()
        self.base = f"http://127.0.0.1:{self.site.server.server_port}"

    def tearDown(self):
        self.site.stop()

    def whoami(self, cookie=""):
        req = urllib.request.Request(self.base + "/whoami", headers={"Cookie": cookie})
        return json.loads(urllib.request.urlopen(req, timeout=5).read())

    def test_sign_in_sets_a_session_and_a_persistent_cookie(self):
        req = urllib.request.Request(
            self.base + "/login", data=b"user=tester", method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            set_cookies = r.headers.get_all("Set-Cookie")
        sid = next(c for c in set_cookies if c.startswith("sid="))
        remember = next(c for c in set_cookies if c.startswith("remember="))
        self.assertNotIn("Max-Age", sid)
        self.assertNotIn("Expires", sid)
        self.assertIn(f"Max-Age={login_site.REMEMBER_SECONDS}", remember)
        for c in (sid, remember):
            self.assertIn("HttpOnly", c)
        jar = "; ".join(c.split(";")[0] for c in set_cookies)
        self.assertEqual(self.whoami(jar), {"session": "tester", "remember": "tester"})
        # Only the cookies say who it is.
        self.assertEqual(self.whoami(), {"session": None, "remember": None})
        self.assertEqual(
            self.whoami("sid=forged; remember=forged"),
            {"session": None, "remember": None},
        )

    def test_url_uses_a_localhost_name(self):
        self.assertTrue(self.site.url.startswith("http://login.localhost:"))


class LoginSiteRequestsTest(unittest.TestCase):
    """What the server answers to requests that are not from our own pages."""

    def setUp(self):
        self.site = login_site.LoginSite().start()
        self.port = self.site.server.server_port

    def tearDown(self):
        self.site.stop()

    def raw(self, method, path, host, extra="", body=b""):
        """The status code for a hand-written request, so the Host and
        Content-Length headers are exactly what the test says."""
        head = f"{method} {path} HTTP/1.0\r\n"
        if host is not None:
            head += f"Host: {host}\r\n"
        head += extra + "\r\n"
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as s:
            s.sendall(head.encode() + body)
            data = b""
            while chunk := s.recv(4096):
                data += chunk
        return int(data.split(b" ", 2)[1])

    def test_other_host_names_get_403(self):
        for path in ("/whoami", "/home"):
            self.assertEqual(self.raw("GET", path, f"evil.example:{self.port}"), 403)
            self.assertEqual(self.raw("GET", path, "login.localhost"), 403)
            self.assertEqual(self.raw("GET", path, f"login.localhost:{self.port + 1}"), 403)
            self.assertEqual(self.raw("GET", path, None), 403)
        # A rebinding page cannot sign in either.
        self.assertEqual(
            self.raw("POST", "/login", f"evil.example:{self.port}",
                     "Content-Length: 11\r\n", b"user=tester"),
            403,
        )
        self.assertEqual(self.site.sessions, {})

    def test_our_own_host_names_work(self):
        for host in ("login.localhost", "127.0.0.1", "localhost"):
            self.assertEqual(self.raw("GET", "/whoami", f"{host}:{self.port}"), 200, host)
        self.assertEqual(
            self.raw("POST", "/login", f"login.localhost:{self.port}",
                     "Content-Length: 11\r\n", b"user=tester"),
            200,
        )

    def test_content_length_is_checked_and_capped(self):
        host = f"127.0.0.1:{self.port}"

        def post(length):
            # A body as long as it claims, when that is small enough to send.
            size = length if isinstance(length, int) and 5 <= length <= 5000 else 11
            body = b"user=" + b"a" * (size - 5)
            return self.raw("POST", "/login", host, f"Content-Length: {length}\r\n", body)

        self.assertEqual(post(11), 200)
        self.assertEqual(post(login_site.MAX_BODY), 200)
        self.assertEqual(post(login_site.MAX_BODY + 1), 413)
        self.assertEqual(post(10**12), 413)
        for bad in ("-1", "abc", "1.5", "0x10", "+5"):
            self.assertEqual(post(bad), 400, bad)
        # No Content-Length at all is an empty body, not a hang.
        self.assertEqual(self.raw("POST", "/login", host), 200)


class RestartSmokeCleanupTest(unittest.TestCase):
    """smoke_login_restart.py deletes its temporary profile, pass or fail."""

    def test_work_folder_is_deleted_when_the_run_fails(self):
        import smoke_login_restart
        from unittest import mock

        seen = []

        def boom(work):
            seen.append(work)
            (work / "profile").mkdir()
            raise RuntimeError("browser would not start")

        with mock.patch.object(smoke_login_restart, "run", boom):
            with self.assertRaises(RuntimeError):
                smoke_login_restart.main()
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].exists())

    def test_work_folder_is_deleted_when_the_run_exits(self):
        import smoke_login_restart
        from unittest import mock

        seen = []

        def done(work):
            seen.append(work)
            sys.exit(0)

        with mock.patch.object(smoke_login_restart, "run", done):
            with self.assertRaises(SystemExit):
                smoke_login_restart.main()
        self.assertFalse(seen[0].exists())


class LoginChecksTest(unittest.TestCase):
    def test_signed_in_checks(self):
        good = {
            "session": "tester",
            "remember": "tester",
            "local": login_site.STORED,
            "idb": login_site.STORED,
        }
        self.assertTrue(all(ok for _, ok, _ in login_site.signed_in_checks(good)))
        for key in good:
            bad = dict(good, **{key: None})
            failed = [n for n, ok, _ in login_site.signed_in_checks(json.dumps(bad)) if not ok]
            self.assertEqual(len(failed), 1, key)

    def test_scripts_are_one_expression(self):
        for js in (login_site.SIGN_IN_JS, login_site.STATE_JS):
            self.assertTrue(js.startswith("(async () => {") and js.endswith("})()"))
        self.assertIn("arguments[arguments.length - 1]", login_site.for_webdriver("x"))

    def test_disk_readers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "Cookies"
            con = sqlite3.connect(db)
            con.execute(
                "CREATE TABLE cookies (host_key TEXT, name TEXT, "
                "is_persistent INTEGER, encrypted_value BLOB)"
            )
            con.executemany(
                "INSERT INTO cookies VALUES (?, ?, ?, ?)",
                [
                    ("login.localhost", "sid", 0, b"v10abc"),
                    ("login.localhost", "remember", 1, b"v10def"),
                    ("other.localhost", "x", 1, b"v20ghi"),
                ],
            )
            con.commit()
            con.close()
            self.assertEqual(
                sorted(login_site.cookie_rows(db)),
                [("remember", True, "v10"), ("sid", False, "v10")],
            )
            state = Path(tmp) / "Local State"
            key = base64.b64encode(b"DPAPI" + b"\0" * 8).decode()
            state.write_text(json.dumps({"os_crypt": {"encrypted_key": key}}))
            self.assertEqual(
                login_site.key_state(state), {"encrypted_key": key, "app_bound": False}
            )


class SandboxStagesTest(unittest.TestCase):
    def test_login_stages_bracket_the_update(self):
        tree = ast.parse((TOOLS / "sbx" / "run.py").read_text(encoding="utf-8"))
        stages = next(
            n.value
            for n in tree.body
            if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "STAGES"
        )
        names = [ast.unparse(e) for e in stages.elts]
        self.assertLess(names.index("login_stages.login_before_update"), names.index("update_test"))
        self.assertLess(names.index("tabs_after_update"), names.index("login_stages.login_after_update"))
        self.assertLess(names.index("login_stages.login_after_update"), names.index("uninstall"))

    def test_it_refuses_to_run_outside_windows_sandbox(self):
        # Security review R4: run.py kills browsers, edits the hosts file and
        # force-uninstalls the first matching browser, so on a real machine
        # it must stop before doing or even reading anything.
        for env in ({"USERNAME": "JD"}, {"USERNAME": "wdagutilityaccount2"}, {}):
            with self.subTest(env=env):
                run_env = {k: v for k, v in os.environ.items() if k != "USERNAME"}
                run_env.update(env)
                done = subprocess.run(
                    [sys.executable, "-I", str(TOOLS / "sbx" / "run.py")],
                    env=run_env,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    cwd=tempfile.gettempdir(),
                )
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("only inside Windows Sandbox", done.stderr)
                self.assertIn("Nothing was done", done.stderr)
                # No traceback: nothing after the check ran.
                self.assertNotIn("Traceback", done.stderr)

    def test_the_check_comes_before_any_other_statement(self):
        tree = ast.parse((TOOLS / "sbx" / "run.py").read_text(encoding="utf-8"))
        body = [
            n
            for n in tree.body
            if not isinstance(n, (ast.Import, ast.ImportFrom))
            and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
        ]
        names = [ast.unparse(n).splitlines()[0] for n in body[:3]]
        self.assertEqual(
            names,
            [
                "SANDBOX_USER = 'WDAGUtilityAccount'",
                "def require_sandbox():",
                "require_sandbox()",
            ],
        )
        # And every import that follows it is not run first: the only imports
        # before the call are the standard library's.
        call_line = body[2].lineno
        for n in tree.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)) and n.lineno < call_line:
                module = getattr(n, "module", None) or n.names[0].name
                self.assertNotIn(module.split(".")[0], {"login_stages", "login_site"})

    def test_the_sandbox_account_passes_the_check(self):
        tree = ast.parse((TOOLS / "sbx" / "run.py").read_text(encoding="utf-8"))
        keep = [
            n
            for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "require_sandbox")
            or (isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "SANDBOX_USER")
        ]
        scope = {"os": os, "sys": sys}
        exec(compile(ast.Module(body=keep, type_ignores=[]), "run.py", "exec"), scope)
        saved = os.environ.get("USERNAME")
        os.environ["USERNAME"] = "WDAGUtilityAccount"
        try:
            self.assertIsNone(scope["require_sandbox"]())
            os.environ["USERNAME"] = "JD"
            with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(
                io.StringIO()
            ):
                scope["require_sandbox"]()
            self.assertEqual(caught.exception.code, 2)
        finally:
            if saved is None:
                os.environ.pop("USERNAME", None)
            else:
                os.environ["USERNAME"] = saved

    def test_stages_use_only_what_the_harness_has(self):
        text = (TOOLS / "sbx" / "login_stages.py").read_text(encoding="utf-8")
        used = set(re.findall(r"\bH\.(\w+)", text))
        harness = (TOOLS / "sbx" / "run.py").read_text(encoding="utf-8")
        for name in used:
            self.assertRegex(
                harness, rf"(?m)^(def {name}\b|class {name}\b|{name} = |import {name}\b)", name
            )


@unittest.skipUnless((SRC / "chrome").is_dir(), "no Chromium 157 tree")
class ChromiumFactsTest(unittest.TestCase):
    """What the analysis relies on, read from the Chromium source."""

    def read(self, rel):
        return (SRC / rel).read_text(encoding="utf-8")

    def test_app_bound_encryption_needs_a_system_install(self):
        text = self.read("chrome/browser/os_crypt/app_bound_encryption_win.cc")
        self.assertRegex(
            text,
            r"if \(!install_static::IsSystemInstall\(\)\) \{\s*"
            r"return SupportLevel::kNotSystemLevel;",
        )

    def test_dpapi_failure_does_not_make_a_new_key(self):
        text = self.read("components/os_crypt/async/browser/dpapi_key_provider.cc")
        self.assertRegex(
            text,
            r"case KeyStatus::kDPAPIDecryptFailure:\s*"
            r"status = KeyError::kTemporarilyUnavailable;",
        )

    def test_session_files_are_still_read_in_the_clear(self):
        # 157 writes encrypted copies but reads the clear files. A later
        # stage reads the encrypted copy first; check session safety again
        # when this changes.
        text = self.read("components/sessions/core/command_storage_features.cc")
        self.assertRegex(text, r'"stage",\s*"write_both_read_only_clear"\)')

    def test_session_cookies_follow_continue_where_you_left_off(self):
        text = self.read("chrome/browser/profiles/profile_impl.cc")
        self.assertIn("startup_pref.ShouldRestoreLastSession();", text)


if __name__ == "__main__":
    unittest.main()
