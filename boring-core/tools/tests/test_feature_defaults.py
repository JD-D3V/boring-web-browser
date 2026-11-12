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


def feature_name(entry):
    """BoringFeatureName: "*Name<Trial:param/value" -> "Name"."""
    return re.split(r"[<:]", entry.removeprefix("*"), maxsplit=1)[0]


def keep_off(always, default, enabled, disabled):
    """BoringKeepFeaturesOff, step for step, on lists of entries. The test
    above pins the C++ lines this follows."""
    enabled = [e for e in enabled if feature_name(e) not in always]
    disabled = [e for e in disabled if feature_name(e) not in always]
    named = {feature_name(e) for e in enabled + disabled}
    disabled += list(always)
    disabled += [n for n in default if n not in named]
    return enabled, disabled


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

    def test_always_off_ignores_how_the_command_line_names_it(self):
        # 127: "*Name" is "use the default" (on for UseActionsForBrowserCommands
        # on 157), and "Name<Trial" or "Name:param/value" name it too. Every
        # form leaves both lists and the plain name is disabled, with no
        # "already named" shortcut for this list.
        self.assertIn("std::erase_if(enabled, always_off);", self.text)
        self.assertIn("std::erase_if(disabled, always_off);", self.text)
        loop = re.search(
            r"for \(const char\* name : kBoringAlwaysOffFeatures\) \{(.*?)\n  \}",
            self.text,
            re.S,
        ).group(1)
        self.assertEqual(loop.strip(), "disabled.push_back(name);")
        always = names(self.text, "kBoringAlwaysOffFeatures")
        default = names(self.text, "kBoringDefaultOffFeatures")
        cases = [
            ([], ["*UseActionsForBrowserCommands"]),
            (["UseActionsForBrowserCommands<Trial"], []),
            (["UseActionsForBrowserCommands:param/value"], []),
            (["*ContextualTasks"], ["*UseActionsForBrowserCommands<Trial"]),
            (["ContextualTasks"], []),
        ]
        for enable, disable in cases:
            on, off = keep_off(always, default, enable, disable)
            with self.subTest(enable=enable, disable=disable):
                for name in always:
                    self.assertEqual(off.count(name), 1)
                    self.assertFalse([e for e in on if feature_name(e) == name])
                    self.assertEqual(
                        [e for e in off if feature_name(e) == name], [name]
                    )

    def test_default_off_keeps_the_already_named_rule(self):
        default = names(self.text, "kBoringDefaultOffFeatures")
        always = names(self.text, "kBoringAlwaysOffFeatures")
        self.assertIn("if (!named.contains(name)) {", self.text)
        on, off = keep_off(always, default, ["ExtensionsPinnedByDefault"], [])
        self.assertIn("ExtensionsPinnedByDefault", on)
        self.assertNotIn("ExtensionsPinnedByDefault", off)
        on, off = keep_off(always, default, [], ["*SessionRestoreInfobar"])
        self.assertEqual(off.count("SessionRestoreInfobar"), 0)

    def test_default_off_as_on_154(self):
        self.assertEqual(
            names(self.text, "kBoringDefaultOffFeatures"),
            [
                "ExtensionsPinnedByDefault",  # 115
                "IPH_VerticalTabsExpandOnHoverFeature",  # 122
                "NtpSimplificationBookmarkBar",  # 114
                "SessionRestoreInfobar",  # 121
                "SeparateDefaultAndPinPrompt",  # 129, Q52
            ],
        )

    def test_pin_prompt_feature_is_off_unless_named(self):
        # Q52: Chromium's "Pin to your taskbar" infobar on a later start is
        # offered by the separate default and pin prompt feature (on for
        # Windows on 157) even when the browser is not the default one.
        default = names(self.text, "kBoringDefaultOffFeatures")
        always = names(self.text, "kBoringAlwaysOffFeatures")
        self.assertNotIn("SeparateDefaultAndPinPrompt", always)
        on, off = keep_off(always, default, [], [])
        self.assertIn("SeparateDefaultAndPinPrompt", off)
        on, off = keep_off(always, default, ["SeparateDefaultAndPinPrompt"], [])
        self.assertIn("SeparateDefaultAndPinPrompt", on)
        self.assertNotIn("SeparateDefaultAndPinPrompt", off)

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
