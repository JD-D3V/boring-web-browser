"""The native messaging block (item 51e) is three pieces that must agree:
the pref the Protection page writes, the literal name the Chromium patch
reads, and the series that applies the patch. A mismatch compiles fine and
silently blocks nothing or everything, so check it here."""

import os
import re
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(os.path.dirname(TESTS))
BORING = os.path.join(CORE, "components", "boring")
PATCH = os.path.join(CORE, "patches", "native-hosts-check.patch")


def read(*parts):
    with open(os.path.join(*parts), encoding="utf-8") as f:
        return f.read()


class NativeHostsBlock(unittest.TestCase):
    def test_patch_reads_the_pref_the_page_writes(self):
        header = read(BORING, "core", "boring_prefs.h")
        name = re.search(r'kNativeHostsAllowed\[\] = "([^"]+)"', header).group(1)
        patch = read(PATCH)
        self.assertIn('GetList("%s")' % name, patch)
        self.assertIn("kNativeMessagingBlocklist", patch)
        self.assertIn("kNativeMessagingAllowlist", patch)

    def test_patch_is_in_the_series_once(self):
        series = read(CORE, "patches", "series").split()
        self.assertEqual(series.count("native-hosts-check.patch"), 1)
        # Appended last-in-line behind what was already there.
        self.assertTrue(os.path.exists(PATCH))

    def test_patch_is_small_and_touches_only_the_delegate(self):
        patch = read(PATCH)
        files = re.findall(r"^\+\+\+ b/(\S+)", patch, re.M)
        self.assertEqual(
            files, ["chrome/browser/extensions/api/messaging/chrome_messaging_delegate.cc"]
        )
        added = [l for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++")]
        self.assertLess(len(added), 20)

    def test_prefs_registered_and_migrated(self):
        cc = read(BORING, "core", "boring_prefs.cc")
        self.assertIn("RegisterListPref(prefs::kNativeHostsAllowed)", cc)
        self.assertIn("RegisterBooleanPref(prefs::kNativeHostsDecided, false)", cc)
        # A new pref store starts with none; an existing one keeps the
        # registered hosts.
        self.assertIn("INITIALIZATION_STATUS_CREATED_NEW_PREF_STORE", cc)
        self.assertIn("RegisteredNativeHosts()", cc)

    def test_new_sources_are_in_the_build(self):
        self.assertIn('"native_hosts.cc"', read(BORING, "core", "BUILD.gn"))
        self.assertIn('"native_hosts.cc"', read(BORING, "protection", "BUILD.gn"))

    def test_registry_scan_reads_both_key_families(self):
        cc = read(BORING, "core", "native_hosts.cc")
        for key in ("SOFTWARE\\\\Chromium\\\\NativeMessagingHosts",
                    "SOFTWARE\\\\Google\\\\Chrome\\\\NativeMessagingHosts"):
            self.assertIn(key, cc)
        for root in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
            self.assertIn(root, cc)

    def test_no_em_dashes_in_new_text(self):
        for path in (
            os.path.join(BORING, "core", "native_hosts.cc"),
            os.path.join(BORING, "core", "native_hosts.h"),
            os.path.join(BORING, "protection", "native_hosts.cc"),
            os.path.join(BORING, "protection", "native_hosts.h"),
            PATCH,
        ):
            self.assertNotIn("—", read(path), path)


if __name__ == "__main__":
    unittest.main()
