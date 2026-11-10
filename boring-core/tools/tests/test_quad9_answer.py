#!/usr/bin/env python3
"""Tests for the Quad9 block parser.

components/boring/scam/quad9_answer.cc reads the answer Quad9 gives when it
is asked about a name. A name on Quad9's threat list comes back as "no such
name" with Extended DNS Error 17, which looks nothing like a typo to the
parser and everything like one to the browser's own resolver. It is plain
standard C++, so this compiles the real file, not a copy, into a small
program with the Visual Studio compiler and feeds it answers captured from
Quad9 (quad9_captures.json). No Chromium tree and no browser.

The bytes come off the network into the browser process, so the hostile
cases matter as much as the real ones: cut short, garbage, one byte
changed, counts that promise more than the message holds.

Usage: python -m pytest boring-core/tools/tests/test_quad9_answer.py -s
"""

import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(TESTS)
CORE = os.path.dirname(TOOLS)
SCAM = os.path.join(CORE, "components", "boring", "scam")
VCVARS = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Community"
    r"\VC\Auxiliary\Build\vcvars64.bat"
)
sys.path.insert(0, TOOLS)

import quad9_wire as wire  # noqa: E402

BLOCKED = "blocked"
NOT_BLOCKED = "not_blocked"
INVALID = "invalid"


class Quad9Parser(unittest.TestCase):
    exe = None
    workdir = None

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(VCVARS):
            raise unittest.SkipTest("Visual Studio 2022 is not installed here")
        cls.workdir = tempfile.mkdtemp(prefix="quad9-", dir=os.environ.get("TMP"))
        exe = os.path.join(cls.workdir, "quad9_probe.exe")
        bat = os.path.join(cls.workdir, "build.bat")
        with open(bat, "w") as f:
            f.write(
                "@echo off\n"
                f'call "{VCVARS}" >nul\n'
                f'cd /d "{cls.workdir}"\n'
                "cl /nologo /EHsc /std:c++20 /W3 /O1 "
                f'/I "{CORE}" /Fe"{exe}" '
                f'"{os.path.join(TESTS, "quad9_probe.cc")}" '
                f'"{os.path.join(SCAM, "quad9_answer.cc")}"\n'
            )
        done = subprocess.run(
            ["cmd", "/c", bat], capture_output=True, text=True, timeout=300
        )
        if done.returncode != 0 or not os.path.exists(exe):
            raise AssertionError("probe did not compile:\n" + done.stdout + done.stderr)
        cls.exe = exe
        cls.caps = wire.captures()

    @classmethod
    def tearDownClass(cls):
        if cls.workdir:
            shutil.rmtree(cls.workdir, ignore_errors=True)

    def run_lines(self, lines):
        done = subprocess.run(
            [self.exe],
            input="\n".join(lines) + "\n",
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        out = done.stdout.split("\n")[:-1]
        self.assertEqual(len(out), len(lines))
        return out

    def verdicts(self, cases):
        """cases: (host, answer bytes) pairs -> list of verdict strings."""
        return self.run_lines([f"A {host} {data.hex()}" for host, data in cases])

    def verdict(self, host, data):
        return self.verdicts([(host, data)])[0]

    # --- the captured answers ----------------------------------------

    def test_the_captured_blocked_answer_is_blocked(self):
        self.assertEqual(self.verdict("isitblocked.org", self.caps["blocked"]), BLOCKED)

    def test_host_case_and_a_trailing_dot_do_not_matter(self):
        for host in ("IsItBlocked.ORG", "isitblocked.org."):
            self.assertEqual(self.verdict(host, self.caps["blocked"]), BLOCKED)

    def test_a_made_up_name_in_the_blocked_answer_is_blocked(self):
        for name in ("blocked.test", "a.b.c.example.invalid", "x" * 63 + ".test"):
            self.assertEqual(self.verdict(name, wire.blocked_answer(name)), BLOCKED)

    def test_an_answer_about_another_name_is_invalid(self):
        self.assertEqual(self.verdict("example.com", self.caps["blocked"]), INVALID)

    def test_every_other_captured_answer_is_not_blocked(self):
        hosts = {
            "not_found_with_soa": "nxprobe-82734-qzv.com",
            "root_synthesised": "sfaisofnadgre.odafds",
            "normal": "example.com",
            "unfiltered_resolves": "isitblocked.org",
            "servfail_ede": "brokendnssec.net",
        }
        for key, host in hosts.items():
            with self.subTest(key=key):
                self.assertEqual(self.verdict(host, self.caps[key]), NOT_BLOCKED)

    def test_a_real_does_not_exist_is_not_blocked(self):
        name = "gone.test"
        self.assertEqual(self.verdict(name, wire.not_found_answer(name)), NOT_BLOCKED)

    def test_an_address_is_not_blocked(self):
        name = "ok.test"
        self.assertEqual(self.verdict(name, wire.address_answer(name)), NOT_BLOCKED)

    # --- only code 17, only a refusal ---------------------------------

    def test_only_code_17_counts(self):
        blocked = bytearray(self.caps["blocked"])
        self.assertEqual(blocked[-2:], b"\x00\x11")
        for code in (0, 15, 16, 18, 29):
            blocked[-2:] = struct.pack(">H", code)
            with self.subTest(code=code):
                self.assertEqual(
                    self.verdict("isitblocked.org", bytes(blocked)), NOT_BLOCKED
                )

    def test_a_name_that_resolves_is_not_blocked_even_with_code_17(self):
        # NOERROR with the same marker: not a refusal.
        noerror = bytearray(self.caps["blocked"])
        noerror[3] = 0x80
        self.assertEqual(self.verdict("isitblocked.org", bytes(noerror)), NOT_BLOCKED)

    def test_a_query_is_not_an_answer(self):
        blocked = bytearray(self.caps["blocked"])
        blocked[2] = 0x01  # QR clear
        self.assertEqual(self.verdict("isitblocked.org", bytes(blocked)), INVALID)

    # --- hostile bytes ------------------------------------------------

    def test_every_cut_of_every_capture_is_safe(self):
        cases = []
        for key, data in self.caps.items():
            host = {
                "blocked": "isitblocked.org",
                "not_found_with_soa": "nxprobe-82734-qzv.com",
                "root_synthesised": "sfaisofnadgre.odafds",
                "normal": "example.com",
                "unfiltered_resolves": "isitblocked.org",
                "servfail_ede": "brokendnssec.net",
            }[key]
            for n in range(len(data)):
                cases.append((key, n, host, data[:n]))
        out = self.verdicts([(h, d) for _, _, h, d in cases])
        for (key, n, _, _), got in zip(cases, out, strict=True):
            # A cut message is never a verdict of any kind.
            self.assertEqual(got, INVALID, f"{key} cut to {n} bytes")

    def test_extra_bytes_after_the_answer_are_invalid(self):
        self.assertEqual(
            self.verdict("isitblocked.org", self.caps["blocked"] + b"\x00"), INVALID
        )

    def test_counts_that_promise_more_than_the_message_holds(self):
        blocked = bytearray(self.caps["blocked"])
        cases = []
        for offset in (4, 6, 8, 10):  # questions, answers, authority, additional
            data = bytearray(blocked)
            data[offset : offset + 2] = b"\xff\xff"
            cases.append(("isitblocked.org", bytes(data)))
        for got in self.verdicts(cases):
            self.assertNotEqual(got, BLOCKED)

    def test_names_with_pointers_and_odd_lengths(self):
        header = struct.pack(">HHHHHH", 0, 0x8183, 1, 0, 0, 1)
        question = wire.encode_name("a.test") + struct.pack(">HH", 1, 1)
        cases = [
            # An additional record whose name points at itself.
            header + question + b"\xc0\x1c" + struct.pack(">HHIH", 41, 1232, 0, 0),
            # A label with the reserved 01 length bits.
            header + b"\x41" + b"a" * 64 + b"\x00" + struct.pack(">HH", 1, 1),
            # A record whose data length runs past the end.
            header + question + b"\x00" + struct.pack(">HHIH", 41, 1232, 0, 9999),
            # An option whose length runs past the record.
            header
            + question
            + b"\x00"
            + struct.pack(">HHIH", 41, 1232, 0, 8)
            + struct.pack(">HHH", 15, 9999, 17),
        ]
        for i, got in enumerate(self.verdicts([("a.test", d) for d in cases])):
            self.assertNotEqual(got, BLOCKED, f"case {i}")

    def test_random_bytes_and_flipped_bytes_never_say_blocked_by_accident(self):
        rng = random.Random(9)
        cases = []
        for _ in range(3000):
            n = rng.randrange(0, 200)
            cases.append(
                ("isitblocked.org", bytes(rng.randrange(256) for _ in range(n)))
            )
        blocked = self.caps["blocked"]
        flips = []
        for i in range(len(blocked)):
            for value in (0x00, 0x01, 0x7F, 0x80, 0xFF):
                data = bytearray(blocked)
                data[i] = value
                if bytes(data) != blocked:
                    flips.append(("isitblocked.org", bytes(data)))
        out = self.verdicts(cases + flips)
        self.assertTrue(all(v in (BLOCKED, NOT_BLOCKED, INVALID) for v in out))
        # Random noise is never taken for a block.
        self.assertNotIn(BLOCKED, out[: len(cases)])

    # --- the question we send -----------------------------------------

    def test_the_query_matches_the_question_in_the_captured_answer(self):
        blocked = self.caps["blocked"]
        name, end = wire.read_question(blocked)
        want = struct.pack(">HHHHHH", 0, 0x0100, 1, 0, 0, 0) + blocked[12:end]
        self.assertEqual(self.run_lines([f"Q {name}"])[0], want.hex())

    def test_a_trailing_dot_and_case_make_the_same_query(self):
        a, b, c = self.run_lines(["Q example.com", "Q example.com.", "Q Example.COM"])
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_a_name_that_cannot_be_written_has_no_query(self):
        bad = ["a..b", ".", "x" * 64 + ".com", ".".join(["a" * 60] * 5)]
        self.assertEqual(self.run_lines([f"Q {n}" for n in bad]), ["none"] * len(bad))
        # 63 bytes in a label and 253 in a name are the limits, and fit.
        edge = [("x" * 63 + ".com"), ".".join(["a" * 61] * 3 + ["b" * 61])]
        self.assertTrue(
            all(q != "none" for q in self.run_lines([f"Q {n}" for n in edge]))
        )


if __name__ == "__main__":
    unittest.main()
