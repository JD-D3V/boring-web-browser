"""Global Privacy Control: Sec-GPC and navigator.globalPrivacyControl, on by
default, with a switch on the Protection page (ledger r4 item 9).

Chromium 157 already has the whole signal (header on navigations, worker
scripts, subresources and worker fetches; the property on Navigator and
WorkerNavigator), behind the GlobalPrivacyControlApi feature and a renderer
preference. We turn the feature on and feed the preference from our pref.
These are source checks; smoke_gpc.py checks the browser.
"""

import os
import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
BORING = CORE / "components" / "boring"
PATCHES = CORE / "patches"
FEATURES = PATCHES / "157" / "feature-defaults.patch"
GPC_PATCH = PATCHES / "157" / "global-privacy-control.patch"
PREFS_H = BORING / "core" / "boring_prefs.h"
PREFS_CC = BORING / "core" / "boring_prefs.cc"
PROTECTION = BORING / "protection" / "protection_ui.cc"
FOLDER_COPY = BORING / "folder_copy" / "folder_copy_settings.cc"
SRC = Path(os.environ.get("BORING_SRC_157", r"E:\ung-157\build\src"))

PREF = "boring.global_privacy_control"


def read(p):
    return p.read_text(encoding="utf-8")


def added(path):
    return "\n".join(
        line[1:]
        for line in read(path).splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def flat(text):
    return re.sub(r"\s+", " ", text)


def names(text, array):
    body = re.search(array + r"\[\] = \{(.*?)\};", text, re.S).group(1)
    return re.findall(r'"([^"]+)"', body)


def feature_name(entry):
    return re.split(r"[<:]", entry.removeprefix("*"), maxsplit=1)[0]


def default_on(on_list, enabled, disabled):
    """The default-on step of BoringKeepFeaturesOff."""
    named = {feature_name(e) for e in enabled + disabled}
    return enabled + [n for n in on_list if n not in named]


class PrefTest(unittest.TestCase):
    def test_pref_name_and_default_on(self):
        self.assertIn(f'kGlobalPrivacyControl[] = "{PREF}"', read(PREFS_H))
        self.assertIn(
            "RegisterBooleanPref(prefs::kGlobalPrivacyControl, true);", read(PREFS_CC)
        )

    def test_kept_in_the_folder_copy(self):
        self.assertIn("{prefs::kGlobalPrivacyControl,", read(FOLDER_COPY))


class FeatureOnTest(unittest.TestCase):
    def setUp(self):
        self.text = added(FEATURES)

    def test_api_feature_is_on_by_default(self):
        self.assertEqual(
            names(self.text, "kBoringDefaultOnFeatures"), ["GlobalPrivacyControlApi"]
        )
        self.assertNotIn(
            "GlobalPrivacyControlApi", names(self.text, "kBoringAlwaysOffFeatures")
        )
        self.assertNotIn(
            "GlobalPrivacyControlForce", self.text
        )  # Force ignores the switch.
        loop = re.search(
            r"for \(const char\* name : kBoringDefaultOnFeatures\) \{(.*?)\n  \}",
            self.text,
            re.S,
        ).group(1)
        self.assertEqual(
            flat(loop).strip(),
            "if (!named.contains(name)) { enabled.push_back(name); }",
        )

    def test_a_named_rule_wins(self):
        on = names(self.text, "kBoringDefaultOnFeatures")
        self.assertIn("GlobalPrivacyControlApi", default_on(on, [], []))
        self.assertNotIn(
            "GlobalPrivacyControlApi",
            default_on(on, [], ["GlobalPrivacyControlApi"]),
        )
        self.assertEqual(
            default_on(on, ["GlobalPrivacyControlApi"], []).count(
                "GlobalPrivacyControlApi"
            ),
            1,
        )

    def test_enable_switch_written_after_the_lists_are_final(self):
        # The default-on loop runs before the switches are rewritten.
        self.assertLess(
            self.text.index("kBoringDefaultOnFeatures) {"),
            self.text.index("command_line->RemoveSwitch(switches::kEnableFeatures);"),
        )


class RendererPrefTest(unittest.TestCase):
    def setUp(self):
        self.raw = read(GPC_PATCH)
        self.text = added(GPC_PATCH)

    def test_in_series(self):
        series = read(PATCHES / "series").split()
        self.assertIn("global-privacy-control.patch", series)

    def test_renderer_preference_follows_our_pref(self):
        self.assertIn("+++ b/chrome/browser/renderer_preferences_util.cc", self.raw)
        self.assertIn('#include "components/boring/core/boring_prefs.h"', self.text)
        self.assertIn(
            "prefs->is_global_privacy_control_setting_enabled = "
            "pref_service->GetBoolean(boring::prefs::kGlobalPrivacyControl);",
            flat(self.text),
        )
        # After Chrome's universal opt-out block, so ours decides.
        self.assertRegex(
            self.raw,
            r"kUniversalOptOutEnabled\);\n   \}\n\+  // boring: Global Privacy",
        )

    def test_a_change_reaches_open_tabs(self):
        self.assertIn("+++ b/chrome/browser/ui/prefs/pref_watcher.cc", self.raw)
        self.assertIn(
            f'profile_pref_change_registrar_.Add("{PREF}", renderer_callback);',
            flat(self.text),
        )


class ProtectionSwitchTest(unittest.TestCase):
    def setUp(self):
        self.text = read(PROTECTION)

    def test_row(self):
        row = re.search(
            r'<label class="setting-row" for="gpc">(.*?)</label>', self.text, re.S
        ).group(1)
        self.assertIn("<strong>Ask sites not to sell or share your data</strong>", row)
        self.assertIn(
            "Sends the Global Privacy Control signal, which sites in some US "
            "states must follow.",
            flat(row),
        )
        self.assertIn('<input class="switch" type="checkbox" id="gpc">', row)

    def test_wired(self):
        self.assertIn("el('gpc').checked = s.gpc;", self.text)
        self.assertIn("chrome.send('setGlobalPrivacyControl', [e.target.checked]);", self.text)
        self.assertIn('"setGlobalPrivacyControl",', self.text)
        self.assertIn(
            "prefs->SetBoolean(prefs::kGlobalPrivacyControl, args[0].GetBool());",
            self.text,
        )
        self.assertIn(
            'out.Set("gpc", prefs && prefs->GetBoolean(prefs::kGlobalPrivacyControl));',
            self.text,
        )

    def test_no_em_dash(self):
        for path in (FEATURES, GPC_PATCH, PROTECTION, PREFS_H):
            self.assertNotIn("\u2014", read(path), str(path))


@unittest.skipUnless(SRC.exists(), "no Chromium 157 tree (BORING_SRC_157)")
class ChromiumStillHasItTest(unittest.TestCase):
    """What the two patches lean on. A Chromium upgrade that moves any of it
    fails here, not silently in a browser that stops sending the signal."""

    def src(self, rel):
        return (SRC / rel).read_text(encoding="utf-8")

    def test_runtime_feature(self):
        json5 = self.src("third_party/blink/renderer/platform/runtime_enabled_features.json5")
        self.assertRegex(json5, r'name: "GlobalPrivacyControlApi",\s*status: "experimental"')

    def test_header_on_navigations_and_subresources(self):
        nav = self.src("content/browser/loader/browser_initiated_resource_request.cc")
        sub = self.src("content/renderer/render_frame_impl.cc")
        for text in (nav, sub):
            self.assertIn("IsGlobalPrivacyControlFeatureAndSettingEnabled(", text)
            self.assertIn("kGlobalPrivacyControlHeader", text)

    def test_property_in_workers_too(self):
        idl = self.src(
            "third_party/blink/renderer/modules/global_privacy_control/"
            "navigator_global_privacy_control.idl"
        )
        self.assertIn("Navigator includes NavigatorGlobalPrivacyControl;", idl)
        self.assertIn("WorkerNavigator includes NavigatorGlobalPrivacyControl;", idl)

    def test_setting_reads_the_renderer_preference(self):
        util = self.src(
            "third_party/blink/common/global_privacy_control/global_privacy_control_util.cc"
        )
        self.assertIn("is_global_privacy_control_setting_enabled", util)


if __name__ == "__main__":
    unittest.main()
