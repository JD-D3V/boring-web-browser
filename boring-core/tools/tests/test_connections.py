"""connections.json is the one list of what the browser reaches on its own,
and tools/check_connections.py fails the build when code or config reaches
for a host that is not in it. These tests run the real check on the real
tree, then break copies of it in the ways that matter."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import check_connections  # noqa: E402

CORE = TOOLS.parent
JSON_REL = check_connections.JSON_REL

# The files the check reads, copied into a scratch tree so a test can add
# a host to one of them without touching the real thing.
COPIED = [
    JSON_REL,
    check_connections.HEADER_REL,
    "components/boring/core/boring_prefs.h",
    "components/boring/lists/list_updater.cc",
    "components/boring/lists/list_updater.h",
    "components/boring/adblock/custom_rules.cc",
    "components/boring/update/browser_updater.cc",
    "components/boring/ai/ai_summary_service.cc",
    "components/boring/ai/ai_summary_service.h",
    "components/boring/scam/quad9_block_checker.cc",
    "components/boring/scam/quad9_block_checker.h",
    "chromium_src/chrome/browser/boring/privacy_bridge.cc",
    "patches/154/privacy-defaults.patch",
    "patches/157/privacy-defaults.patch",
    "patches/privacy-defaults.patch",
    "tools/net_audit.py",
]


class ConnectionsCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="connections-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for rel in COPIED:
            dest = self.tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(CORE / rel, dest)

    def append(self, rel, text):
        with open(self.tmp / rel, "a", encoding="utf-8", newline="") as f:
            f.write(text)

    def test_real_tree_is_clean(self):
        self.assertEqual(check_connections.check(CORE), [])

    def test_copy_is_clean(self):
        self.assertEqual(check_connections.check(self.tmp), [])

    def test_unlisted_host_in_a_claimed_file_fails(self):
        self.append(
            "components/boring/lists/list_updater.cc",
            '\nconstexpr char kExtra[] = "https://tracker.example.net/ping";\n',
        )
        errors = check_connections.check(self.tmp)
        self.assertTrue(any("tracker.example.net" in e for e in errors), errors)

    def test_user_list_code_may_fetch_but_not_name_a_host(self):
        # The user lists fetch from addresses people type, so the file is
        # claimed with no hosts of its own. It passes as it is...
        self.assertEqual(check_connections.check(self.tmp), [])
        # ...but a host written into that code is still caught.
        self.append(
            "components/boring/adblock/custom_rules.cc",
            '\nconstexpr char kExtra[] = "https://lists.example.net/x.txt";\n',
        )
        errors = check_connections.check(self.tmp)
        self.assertTrue(any("lists.example.net" in e for e in errors), errors)

    def test_unclaimed_user_list_fetch_fails(self):
        path = self.tmp / JSON_REL
        data = json.loads(path.read_text(encoding="utf-8"))
        data["user_connections"][0]["code"] = []
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        (self.tmp / check_connections.HEADER_REL).write_text(
            check_connections.header_text(self.tmp), encoding="utf-8"
        )
        errors = check_connections.check(self.tmp)
        self.assertTrue(any("custom_rules.cc" in e for e in errors), errors)

    def test_unlisted_host_in_net_audit_fails(self):
        self.append("tools/net_audit.py", '\nSNEAKY = "telemetry.example.io"\n')
        errors = check_connections.check(self.tmp)
        self.assertTrue(any("telemetry.example.io" in e for e in errors), errors)

    def test_new_file_that_fetches_fails(self):
        new = self.tmp / "components/boring/news/news_fetcher.cc"
        new.parent.mkdir(parents=True)
        new.write_text(
            "auto loader = network::SimpleURLLoader::Create(std::move(req));\n",
            encoding="utf-8",
        )
        errors = check_connections.check(self.tmp)
        self.assertTrue(any("news_fetcher.cc" in e for e in errors), errors)

    def test_host_added_by_a_patch_fails(self):
        self.append(
            "patches/154/privacy-defaults.patch",
            '+  base::Value("https://dns.other-resolver.org/dns-query");\n',
        )
        errors = check_connections.check(self.tmp)
        self.assertTrue(any("dns.other-resolver.org" in e for e in errors), errors)

    def test_stale_compiled_copy_fails(self):
        path = self.tmp / JSON_REL
        data = json.loads(path.read_text(encoding="utf-8"))
        data["connections"][0]["why"] = "Changed text."
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        errors = check_connections.check(self.tmp)
        self.assertTrue(any("out of date" in e for e in errors), errors)

    def test_missing_pref_fails(self):
        path = self.tmp / JSON_REL
        data = json.loads(path.read_text(encoding="utf-8"))
        data["connections"][1]["switch"]["pref"] = "boring.no_such_pref"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        (self.tmp / check_connections.HEADER_REL).write_text(
            check_connections.header_text(self.tmp), encoding="utf-8"
        )
        errors = check_connections.check(self.tmp)
        self.assertTrue(any("boring.no_such_pref" in e for e in errors), errors)

    def test_all_off_seed_covers_the_file_switches(self):
        sys.path.insert(0, str(TOOLS))
        import ast

        tree = ast.parse((TOOLS / "net_audit.py").read_text(encoding="utf-8"))
        names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
        self.assertIn("all_off_seed", names)
        self.assertIn("all-off", check_connections.scenario_names(CORE))

    def test_secure_dns_off_note_names_the_hidden_tracker_check(self):
        # 131: the check for trackers hidden behind a site's own address
        # (cname_uncloaker.cc) runs only in secure mode, so turning Secure DNS
        # off stops it as well as weakening scam blocking.
        data = json.loads((CORE / JSON_REL).read_text(encoding="utf-8"))
        row = next(c for c in data["connections"] if c["id"] == "secure_dns")
        note = row["off_note"]
        self.assertIn("scam blocking gets weaker", note)
        self.assertIn("trackers hidden behind a site's own address", note)
        self.assertIn("also stops", note)
        self.assertNotIn("—", note)
        self.assertIn(
            note, (CORE / check_connections.HEADER_REL).read_text(encoding="utf-8")
        )
        self.assertFalse(check_connections.check(CORE))

    def test_automatic_mode_row_says_the_same(self):
        # The row counts automatic as on (any mode but off), so the note about
        # "this off" never shows for it; the row's detail line does.
        ui = (CORE / "components/boring/protection/protection_ui.cc").read_text(
            encoding="utf-8"
        )
        start = ui.index("GetPrivacyState(context);")
        branch = ui[start : ui.index('} else if (*kind == "profile")', start)]
        self.assertIn('privacy.dns_mode == "automatic"', branch)
        self.assertIn("trackers hidden behind a", branch)
        self.assertIn("need secure mode", branch)
        self.assertIn('!privacy.dns_mode.empty() && privacy.dns_mode != "off"', branch)


if __name__ == "__main__":
    unittest.main()
