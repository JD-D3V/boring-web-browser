"""Chromium features that flipped on between 154 and 157 and that this
build keeps off (ledger 113, 114, 115, 119, 121, 122). The patch text is
what is checked; the smoke smoke_feature_defaults.py checks the browser."""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PATCHES = CORE / "patches"
PATCH = PATCHES / "157" / "feature-defaults.patch"


def added(path):
    return "\n".join(
        line[1:]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def names(text, array):
    body = re.search(array + r"\[\] = \{(.*?)\};", text, re.S).group(1)
    return re.findall(r'"([^"]+)"', body)


class FeatureDefaultsTest(unittest.TestCase):
    def setUp(self):
        self.text = added(PATCH)

    def test_in_series(self):
        series = (PATCHES / "series").read_text(encoding="utf-8").split()
        self.assertIn("feature-defaults.patch", series)

    def test_always_off_cannot_be_turned_on(self):
        # 113: the contextual tasks panel has none of our tab helpers.
        # 119: with the action path our menu commands are disabled.
        self.assertEqual(
            names(self.text, "kBoringAlwaysOffFeatures"),
            [
                "ContextualTasks",
                "ContextualTasksSidePanel",
                "ContextualTasksRearchitecture",
                "UseActionsForBrowserCommands",
                "AppMenuGlowUp",
            ],
        )
        # Taken out of --enable-features, not just added to the disable list:
        # an enable on the command line wins over a disable.
        self.assertIn("std::erase_if(enabled", self.text)

    def test_default_off_as_on_154(self):
        self.assertEqual(
            names(self.text, "kBoringDefaultOffFeatures"),
            [
                "ExtensionsPinnedByDefault",  # 115
                "IPH_VerticalTabsExpandOnHoverFeature",  # 122
                "NtpSimplificationBookmarkBar",  # 114
                "SessionRestoreInfobar",  # 121
            ],
        )

    def test_runs_before_the_feature_list_is_built(self):
        self.assertIn(
            "BoringKeepFeaturesOff(base::CommandLine::ForCurrentProcess());",
            self.text,
        )
        raw = PATCH.read_text(encoding="utf-8")
        self.assertIn("flags_ui::kAddSentinels);\n+  BoringKeepFeaturesOff", raw)

    def test_side_tabs_do_not_expand_on_hover(self):
        text = added(PATCHES / "157" / "shell-defaults.patch")
        self.assertRegex(
            text,
            r"RegisterBooleanPref\(prefs::kVerticalTabsExpandOnHoverEnabled,\s*false\)",
        )

    def test_no_em_dash(self):
        self.assertNotIn("—", PATCH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
