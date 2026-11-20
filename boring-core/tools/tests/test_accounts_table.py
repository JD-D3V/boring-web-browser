#!/usr/bin/env python3
"""Tests for Accounts (ledger item 11): the table of companies and the checks.

components/boring/accounts/accounts_rules.cc holds the five companies' own
pages and the text level checks on an address typed for "Other". It is
plain standard C++, so the probe below compiles the real file, not a copy,
with the Visual Studio compiler and asks it questions. No Chromium tree and
no browser. The parser level checks (accounts_store.cc, GURL and the public
suffix list) only run in the browser: smoke_accounts.py covers those.

Usage: python -m pytest boring-core/tools/tests/test_accounts_table.py -s
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit

TESTS = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(os.path.dirname(TESTS))
ACCOUNTS = os.path.join(CORE, "components", "boring", "accounts")
VCVARS = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Community"
    r"\VC\Auxiliary\Build\vcvars64.bat"
)


def read(*parts):
    with open(os.path.join(CORE, *parts), encoding="utf-8") as f:
        return f.read()


def table_rows():
    """(key, name, sign_in, mail, calendar, files) from the source itself."""
    text = read("components", "boring", "accounts", "accounts_rules.cc")
    block = text.split("constexpr KnownProvider kKnown[] = {", 1)[1]
    block = block.split("};", 1)[0]
    rows = []
    for row in re.findall(r"\{Provider::k\w+,(.*?)\}", block, re.S):
        rows.append(tuple(re.findall(r'"([^"]*)"', row)))
    return rows


class Table(unittest.TestCase):
    def test_five_companies_in_the_drawn_order(self):
        names = [r[1] for r in table_rows()]
        self.assertEqual(names, ["Google", "Proton", "Outlook", "iCloud", "Yahoo"])

    def test_every_address_is_plain_https(self):
        for row in table_rows():
            for url in row[2:]:
                if not url:
                    continue
                with self.subTest(url=url):
                    parts = urlsplit(url)
                    self.assertEqual(parts.scheme, "https")
                    self.assertEqual(parts.query, "", "no query strings")
                    self.assertEqual(parts.fragment, "")
                    self.assertIsNone(parts.username)
                    self.assertNotIn("authuser", url)
                    self.assertNotIn("login_hint", url)

    def test_outlook_is_the_personal_service(self):
        outlook = [r for r in table_rows() if r[0] == "outlook"][0]
        self.assertTrue(outlook[3].startswith("https://outlook.live.com/"))
        self.assertNotIn("office.com", " ".join(outlook))

    def test_yahoo_has_no_files_service(self):
        yahoo = [r for r in table_rows() if r[0] == "yahoo"][0]
        self.assertEqual(yahoo[5], "")
        for row in table_rows():
            if row[0] != "yahoo":
                self.assertTrue(row[5], row[0])


class Sources(unittest.TestCase):
    """What the C++ must keep doing, read from the files."""

    def test_known_providers_never_store_an_address(self):
        store = read("components", "boring", "accounts", "accounts_store.cc")
        add_known = store.split("std::optional<std::string> AddKnown(", 1)[1]
        add_known = add_known.split("\n}\n", 1)[0]
        self.assertNotIn("kMailKey", add_known)
        self.assertIn("account.links = KnownLinks(*provider);", store)

    def test_other_addresses_are_checked_on_read(self):
        store = read("components", "boring", "accounts", "accounts_store.cc")
        read_entry = store.split("std::optional<Account> ReadEntry(", 1)[1]
        read_entry = read_entry.split("\n}\n", 1)[0]
        self.assertIn("CheckOtherUrl(*mail)", read_entry)
        self.assertIn("ReadOptionalUrl(dict, kCalendarKey", read_entry)

    def test_parser_checks(self):
        store = read("components", "boring", "accounts", "accounts_store.cc")
        for needle in ("url::kHttpsScheme", "has_username()", "has_password()",
                       "HostIsIPAddress()", 'DomainIs("localhost")',
                       "GetDomainAndRegistry", "FormatUrlForSecurityDisplay"):
            self.assertIn(needle, store)

    def test_pref_is_not_syncable(self):
        store = read("components", "boring", "accounts", "accounts_store.cc")
        self.assertIn("registry->RegisterListPref(kAccountsPref);", store)
        self.assertNotIn("SYNCABLE_PREF", store)
        self.assertIn('"boring.accounts.list"',
                      read("components", "boring", "accounts", "accounts_store.h"))


def run_probe(exe, lines):
    done = subprocess.run([exe], input="\n".join(lines) + "\n",
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.split("\n")[:-1]


class Probe(unittest.TestCase):
    exe = None
    workdir = None

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(VCVARS):
            raise unittest.SkipTest("Visual Studio 2022 is not installed here")
        cls.workdir = tempfile.mkdtemp(prefix="accounts-", dir=os.environ.get("TMP"))
        exe = os.path.join(cls.workdir, "accounts_probe.exe")
        bat = os.path.join(cls.workdir, "build.bat")
        with open(bat, "w") as f:
            f.write(
                "@echo off\n"
                f'call "{VCVARS}" >nul\n'
                f'cd /d "{cls.workdir}"\n'
                "cl /nologo /EHsc /std:c++20 /utf-8 /W3 /O1 "
                f'/I "{CORE}" /Fe"{exe}" '
                f'"{os.path.join(TESTS, "accounts_probe.cc")}" '
                f'"{os.path.join(ACCOUNTS, "accounts_rules.cc")}"\n'
            )
        done = subprocess.run(["cmd", "/c", bat], capture_output=True, text=True,
                              timeout=300)
        if done.returncode != 0 or not os.path.exists(exe):
            raise AssertionError("probe did not compile:\n" + done.stdout + done.stderr)
        cls.exe = exe

    @classmethod
    def tearDownClass(cls):
        if cls.workdir:
            shutil.rmtree(cls.workdir, ignore_errors=True)

    def url(self, typed):
        return run_probe(self.exe, ["U " + typed])[0]

    def test_refused_addresses(self):
        cases = {
            "javascript:alert(1)": "not_https",
            "JavaScript:alert(1)": "not_https",
            "data:text/html,hi": "not_https",
            "file:///C:/x": "not_https",
            "chrome://settings": "not_https",
            "about:blank": "not_https",
            "blob:https://x.com/1": "not_https",
            "http://mail.example.com/": "not_https",
            "ftp://example.com/": "not_https",
            "https://user:pw@x.com/": "credentials",
            "user:pw@x.com": "credentials",
            "https://bank.com@evil.com/": "credentials",
            "https://192.168.1.1/": "not_web_address",
            "8.8.8.8": "not_web_address",
            "https://[::1]/": "not_web_address",
            "localhost": "not_web_address",
            "https://localhost:8080/": "not_web_address",
            "mail.localhost": "not_web_address",
            "intranet": "not_web_address",
            "https://": "not_web_address",
            "https://a..com/": "not_web_address",
            "mail example.com": "not_web_address",
            "https://x.com/\tpath": "not_web_address",
            "": "empty",
            "   ": "empty",
            "https://x.com/" + "a" * 3000: "too_long",
        }
        answers = run_probe(self.exe, ["U " + k for k in cases])
        for (typed, want), got in zip(cases.items(), answers, strict=True):
            with self.subTest(typed=typed[:40]):
                self.assertEqual(got.split(" ")[0], want)

    def test_accepted_addresses(self):
        cases = {
            "fastmail.com": "https://fastmail.com",
            "  app.fastmail.com/mail/  ": "https://app.fastmail.com/mail/",
            "https://mail.example.org/": "https://mail.example.org/",
            "HTTPS://Mail.Example.org/": "HTTPS://Mail.Example.org/",
            "https://xn--80ak6aa92e.com/": "https://xn--80ak6aa92e.com/",
            "fastmail.com:443/x": "https://fastmail.com:443/x",
            "https://example.com./": "https://example.com./",
        }
        answers = run_probe(self.exe, ["U " + k for k in cases])
        for (typed, want), got in zip(cases.items(), answers, strict=True):
            with self.subTest(typed=typed):
                self.assertEqual(got, "ok " + want)

    def test_backslash_cannot_hide_the_real_host(self):
        # A URL parser reads "\" as "/", so the host here is evil.com and
        # the "@good.com" is path. Either way it must not pass as good.com.
        got = self.url("https://evil.com\\@good.com/")
        self.assertTrue(got == "ok https://evil.com\\@good.com/" or
                        got.startswith("not_"), got)

    def test_names_are_cleaned(self):
        cases = {
            "  Personal  ": "[Personal]",
            "Work mail": "[Workmail]",
            "Tab\tname": "[Tabname]",
            "Bell\x07name\x85": "[Bellname]",
            "Bank\u202Emoc.live": "[Bankmoc.live]",
            "Zero\u200Bwidth": "[Zerowidth]",
            "x" * 60: "[" + "x" * 40 + "]",
            "\u00e9" * 50: "[" + "\u00e9" * 40 + "]",
            "": "[]",
            "\t\r": "[]",
            "Ünïcödé ok": "[Ünïcödé ok]",
        }
        answers = run_probe(self.exe, ["N " + k for k in cases])
        for (typed, want), got in zip(cases.items(), answers, strict=True):
            with self.subTest(typed=repr(typed[:20])):
                self.assertEqual(got, want)

    def test_default_names(self):
        answers = run_probe(self.exe, [
            "D Google",
            "D Google|Google",
            "D Google|Google|Google 2",
            "D Google|Google 2",
            "D Yahoo|Google",
        ])
        self.assertEqual(answers, ["Google", "Google 2", "Google 3", "Google",
                                   "Yahoo"])

    def test_limit_is_twelve(self):
        self.assertEqual(run_probe(self.exe, ["M"]), ["12"])

    def test_probe_table_matches_source(self):
        lines = run_probe(self.exe, ["T"])
        self.assertEqual(lines[-1], "end")
        rows = [tuple(line.split("\t")) for line in lines[:-1]]
        self.assertEqual(rows, table_rows())


if __name__ == "__main__":
    unittest.main()
