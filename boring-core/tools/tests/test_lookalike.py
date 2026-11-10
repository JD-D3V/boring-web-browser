#!/usr/bin/env python3
"""Tests for the look-alike address matcher.

components/boring/scam/lookalike_brands.cc decides whether a plain-letter
address (paypa1.com) is dressed up as a well known site (paypal.com). It is
plain standard C++, so this compiles the real file, not a copy, into a
small program with the Visual Studio compiler and asks it a table of
questions. No Chromium tree and no browser.

Two kinds of case matter equally. The positives are what scammers register.
The negatives are every ordinary site, and a warning that cries wolf on
them gets turned off, so they are as much of the contract as the positives.

Addresses with letters of other alphabets (xn--) are Chromium's job, using
its own spoof checks and top-site list. They are covered by the real
browser in smoke_lookalike.py; here they only have to be left alone.

Usage: python -m pytest boring-core/tools/tests/test_lookalike.py -s
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(os.path.dirname(TESTS))
SCAM = os.path.join(CORE, "components", "boring", "scam")
VCVARS = (
    r"C:\Program Files\Microsoft Visual Studio\2022\Community"
    r"\VC\Auxiliary\Build\vcvars64.bat"
)
# Chromium's own list of the 10,000 most visited sites. A real, unbiased
# sample of ordinary addresses. Used when the build tree is here.
TOP_DOMAINS = os.path.join(
    "E:\\", "ung-154", "build", "src", "components", "url_formatter",
    "spoof_checks", "top_domains", "domains.list",
)  # fmt: skip

# (address, the site it copies)
HITS = [
    # Free hosting platforms count as registries (pass 2, T1).
    ("paypa1-login.github.io", "paypal.com"),
    ("amaz0n.netlify.app", "amazon.com"),
    ("paypa1.pages.dev", "paypal.com"),
    ("paypa1.com", "paypal.com"),
    ("rnicrosoft.com", "microsoft.com"),
    ("micros0ft.com", "microsoft.com"),
    ("g00gle.com", "google.com"),
    ("goog1e.com", "google.com"),
    ("amaz0n.com", "amazon.com"),
    ("arnazon.com", "amazon.com"),
    ("app1e.com", "apple.com"),
    ("faceb00k.com", "facebook.com"),
    ("netf1ix.com", "netflix.com"),
    ("1nstagram.com", "instagram.com"),
    ("instagrarn.com", "instagram.com"),
    ("vvalmart.com", "walmart.com"),
    ("c0inbase.com", "coinbase.com"),
    ("z00m.us", "zoom.us"),
    ("wellsfarg0.com", "wellsfargo.com"),
    ("rbcroya1bank.com", "rbcroyalbank.com"),
    # Another ending is no help: the name is what people read.
    ("paypa1.net", "paypal.com"),
    ("paypa1.co.uk", "paypal.com"),
    ("paypa1.shop", "paypal.com"),
    # Words added around the copy, the shape the plan names.
    ("paypa1-support.com", "paypal.com"),
    ("secure-paypa1.com", "paypal.com"),
    ("micros0ft-account-verify.com", "microsoft.com"),
    ("login-rnicrosoft.com", "microsoft.com"),
    # A hyphen put inside the name.
    ("pay-pal.com", "paypal.com"),
    ("e-bay.com", "ebay.com"),
    ("face-book.com", "facebook.com"),
    ("goo-gle.com", "google.com"),
]

# Ordinary addresses: nothing to say about any of these.
CLEAN = [
    "paypal.github.io",
    "my-notes.github.io",
    # The brands themselves, on their own and other endings.
    "paypal.com",
    "paypal.org",
    "paypal.me",
    "microsoft.com",
    "microsoft.ca",
    "google.co.uk",
    "amazon.co.uk",
    "amazon.de",
    "apple.com",
    "ebay.com",
    "t-mobile.com",
    "canadapost-postescanada.ca",
    # The brand's own name plus words: a different trouble, left alone.
    "paypal-support.com",
    "apple-tree.com",
    "google-analytics.com",
    "amazon-prime-day.com",
    "my-microsoft.net",
    # Ordinary words and names that share letters with brands.
    "appie.com",
    "apples.com",
    "learn.com",
    "turnip.com",
    "northern.com",
    "corner.com",
    "modern.org",
    "rnartin.com",
    "bigcorn.com",
    "wellsfargo-fans.com",
    "vivid.com",
    "ovvio.it",
    "gooogle.com",
    "gogle.com",
    "faceboook.com",
    "wise-owl.com",
    "ledgerlive.org",
    "bookings.com",
    "example.com",
    "wikipedia.org",
    "nytimes.com",
    "bbc.co.uk",
    "mtroyal.ca",
    "kelpie.dev",
    # Digits that belong in the name.
    "web2.com",
    "2020census.org",
    "b2b-shop.com",
    "route66.com",
    "1password.com",
    "7-eleven.com",
    "100percent.com",
    "mp3tunes.com",
    "h1ghway.org",
    # Too short to say anything about.
    "g00.com",
    "a1.com",
    "",
    "com",
    # Other alphabets are Chromium's, not ours.
    "xn--pple-43d.com",
    "xn--80ak6aa92e.com",
    "xn--paypa1-9xa.com",
    # Not the shape of a name at all.
    "UPPER.COM",
    "under_score.com",
    "a.b.c.d",
]


def run_probe(exe, names):
    done = subprocess.run(
        [exe], input="\n".join(names) + "\n", capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    answers = done.stdout.split("\n")[:-1]
    assert len(answers) == len(names), (len(answers), len(names))
    return [a.strip() for a in answers]


def brands():
    """The (name, domain) pairs from the real list file."""
    with open(os.path.join(SCAM, "lookalike_brands.inc"), encoding="utf-8") as f:
        text = f.read()
    return re.findall(r'\{"([^"]*)",\s*"([^"]*)"\}', text)


def mutations(name):
    """Spellings a scammer would try for a brand name, with the swap used.

    Only swaps that exist in the name are produced. Each is one swap, so
    the result is what a person could still mistake for the brand."""
    out = []
    for old, new in (("o", "0"), ("l", "1"), ("m", "rn"), ("w", "vv")):
        if old in name:
            out.append((name.replace(old, new, 1), f"{old}->{new}"))
    return out


class LookalikeMatcher(unittest.TestCase):
    exe = None
    workdir = None

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(VCVARS):
            raise unittest.SkipTest("Visual Studio 2022 is not installed here")
        cls.workdir = tempfile.mkdtemp(prefix="lookalike-", dir=os.environ.get("TMP"))
        exe = os.path.join(cls.workdir, "lookalike_probe.exe")
        bat = os.path.join(cls.workdir, "build.bat")
        with open(bat, "w") as f:
            f.write(
                "@echo off\n"
                f'call "{VCVARS}" >nul\n'
                f'cd /d "{cls.workdir}"\n'
                "cl /nologo /EHsc /std:c++20 /W3 /O1 "
                f'/I "{CORE}" /Fe"{exe}" '
                f'"{os.path.join(TESTS, "lookalike_probe.cc")}" '
                f'"{os.path.join(SCAM, "lookalike_brands.cc")}"\n'
            )
        done = subprocess.run(
            ["cmd", "/c", bat], capture_output=True, text=True, timeout=300
        )
        if done.returncode != 0 or not os.path.exists(exe):
            raise AssertionError("probe did not compile:\n" + done.stdout + done.stderr)
        cls.exe = exe

    @classmethod
    def tearDownClass(cls):
        if cls.workdir:
            shutil.rmtree(cls.workdir, ignore_errors=True)

    def ask(self, names):
        return run_probe(self.exe, names)

    def test_lookalikes_name_the_real_site(self):
        answers = self.ask([d for d, _ in HITS])
        for (domain, want), got in zip(HITS, answers, strict=True):
            with self.subTest(domain=domain):
                self.assertEqual(got, want)

    def test_ordinary_addresses_are_left_alone(self):
        answers = self.ask(CLEAN)
        for domain, got in zip(CLEAN, answers, strict=True):
            with self.subTest(domain=domain):
                self.assertEqual(got, "")

    def test_the_brand_list_is_well_formed(self):
        pairs = brands()
        self.assertGreater(len(pairs), 80)
        names = [n for n, _ in pairs]
        self.assertEqual(len(names), len(set(names)), "a name is listed twice")
        for name, domain in pairs:
            with self.subTest(name=name):
                self.assertRegex(name, r"^[a-z0-9]{4,}$")
                self.assertRegex(domain, r"^[a-z0-9.-]+\.[a-z]+$")
        # Each brand's own address is never warned about.
        for (_name, domain), got in zip(
            pairs, self.ask([d for _, d in pairs]), strict=True
        ):
            with self.subTest(domain=domain):
                self.assertEqual(got, "")

    def test_every_brand_is_caught_when_dressed_up(self):
        """For each brand, each one-swap spelling that exists in its name."""
        cases = []
        for name, domain in brands():
            tld = domain.split(".", 1)[1]
            for spelled, swap in mutations(name):
                cases.append((f"{spelled}.{tld}", domain, swap))
        self.assertGreater(len(cases), 80)
        answers = self.ask([c[0] for c in cases])
        missed = [
            f"{c[0]} ({c[2]}) -> {a or 'nothing'}, want {c[1]}"
            for c, a in zip(cases, answers, strict=True)
            if a != c[1]
        ]
        # A swap can land on another listed brand's name or leave a name too
        # short; the numbers are printed. Any real miss is listed here.
        caught = len(cases) - len(missed)
        print(f"\nlook-alikes: {caught}/{len(cases)} generated spellings caught")
        for line in missed:
            print("  missed:", line)
        self.assertLessEqual(len(missed), len(cases) // 100)

    def test_report_the_false_positive_count(self):
        """Counts how many ordinary addresses the matcher would warn about."""
        wrong = [d for d, a in zip(CLEAN, self.ask(CLEAN), strict=True) if a]
        print(
            f"\nlook-alikes: curated ordinary addresses {len(CLEAN)} "
            f"with {len(wrong)} false positives"
        )
        self.assertEqual(wrong, [])

        if not os.path.exists(TOP_DOMAINS):
            print("look-alikes: the Chromium top-site list is not here; skipped")
            return
        with open(TOP_DOMAINS, encoding="utf-8") as f:
            lines = f.read().splitlines()
        sites = [x.strip() for x in lines if x.strip() and not x.startswith("#")]
        own = {d for _, d in brands()}
        answers = self.ask(sites)
        flagged = [
            (s, a) for s, a in zip(sites, answers, strict=True) if a and s not in own
        ]
        print(
            f"look-alikes: Chromium's top {len(sites)} sites with {len(flagged)} "
            f"flagged ({len(flagged) / len(sites) * 100:.3f}%)"
        )
        for site, brand in flagged:
            print(f"  flagged: {site} -> {brand}")
        # The browser also skips any address on that same list (see
        # lookalike_navigation_throttle.cc), so these would not warn anyway.
        self.assertEqual(flagged, [])


class ThrottleUsesPrivateRegistries(unittest.TestCase):
    """Pass 2, T1. The check sees the name on a hosting platform."""

    def test_domain_counts_private_registries(self):
        with open(
            os.path.join(SCAM, "lookalike_navigation_throttle.cc"), encoding="utf-8"
        ) as f:
            cc = f.read()
        self.assertIn("INCLUDE_PRIVATE_REGISTRIES", cc)
        self.assertIn("IsDomainAndRegistryATopDomain(domain)", cc)
        self.assertIn("FindLookalikeBrand(domain)", cc)
        self.assertNotIn("IsTopDomain(url)", cc)


class AllowListIsWrittenAtOnce(unittest.TestCase):
    def test_continue_anyway_commits_the_pref_write(self):
        path = os.path.join(SCAM, "lookalike_blocking_page.cc")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        body = text[text.index("void AllowLookalike(") :]
        body = body[: body.index("\n}\n")]
        self.assertIn("prefs::kLookalikeAllowedSites", body)
        # Closing the browser right after the click must not lose it.
        self.assertIn("prefs->CommitPendingWrite();", body)


if __name__ == "__main__":
    unittest.main()
