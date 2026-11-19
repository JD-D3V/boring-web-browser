#!/usr/bin/env python3
"""Quick buttons on the toolbar: Settings and Extensions in the picker, the
toolbar's right click menu, and what the picker stops offering. The patch text
is checked here; smoke_quick_buttons.py checks the real window."""

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
TOOLS = CORE / "tools"
PATCH = CORE / "patches" / "157" / "toolbar-quick-buttons.patch"
SERIES = CORE / "patches" / "series"
MENU = CORE / "chromium_src" / "chrome" / "browser" / "ui" / "views" / "toolbar"
sys.path.insert(0, str(TOOLS))
os.environ.setdefault("BORING_OUT", r"E:\ung-157\build\src\out\Default")

import smoke_quick_buttons as sqb  # noqa: E402

ACTIONS = "chrome/browser/ui/browser_actions.cc"
HANDLER = (
    "chrome/browser/ui/webui/side_panel/customize_chrome/customize_toolbar/"
    "customize_toolbar_handler.cc"
)
MOJOM = (
    "chrome/browser/ui/webui/side_panel/customize_chrome/customize_toolbar/"
    "customize_toolbar.mojom"
)
VIEW_CC = "chrome/browser/ui/views/toolbar/toolbar_view.cc"
VIEW_H = "chrome/browser/ui/views/toolbar/toolbar_view.h"
BUILD = "chrome/browser/ui/views/toolbar/BUILD.gn"
ID_MAP = "chrome/browser/ui/actions/chrome_actions.cc"
CONTROLLER = "chrome/browser/ui/browser_command_controller.cc"


def sections(text):
    parts = re.split(r"^diff --git ", text, flags=re.M)[1:]
    return {p.split(" b/", 1)[0].removeprefix("a/"): p for p in parts}


def added(section):
    return "\n".join(
        line[1:]
        for line in section.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def removed(section):
    return "\n".join(
        line[1:]
        for line in section.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )


class PatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = PATCH.read_text(encoding="utf-8")
        cls.files = sections(cls.text)

    def test_touches_only_the_files_it_should(self):
        self.assertEqual(
            set(self.files),
            {ACTIONS, HANDLER, MOJOM, VIEW_CC, VIEW_H, BUILD, ID_MAP, CONTROLLER},
        )

    def test_pinned_buttons_follow_their_commands(self):
        # Guest mode and the incognito policy turn the commands off; the
        # pinned buttons run the actions, so the actions follow.
        text = added(self.files[CONTROLLER])
        self.assertIn("FindAction(kActionOptions, browser_)", text)
        self.assertIn("IsCommandEnabled(IDC_OPTIONS)", text)
        self.assertIn("FindAction(kActionManageExtensions, browser_)", text)
        self.assertIn("IsCommandEnabled(IDC_MANAGE_EXTENSIONS)", text)
        self.assertEqual(removed(self.files[CONTROLLER]), "")

    def test_both_ids_get_a_string_both_ways(self):
        # Pinning writes the id's string to the pinned_actions pref and
        # CHECKs that it has one; a restart reads the string back. Neither
        # id is in Chromium's pinnable list, so both mappings are added.
        text = added(self.files[ID_MAP])
        self.assertEqual(text.count("AddActionIdToStringMappings"), 1)
        self.assertEqual(text.count("AddStringToActionIdMappings"), 1)
        self.assertEqual(text.count("E(kActionOptions)"), 2)
        self.assertEqual(text.count("E(kActionManageExtensions)"), 2)

    def test_it_stays_small(self):
        self.assertLess(len(self.text.splitlines()), 250)

    def test_settings_and_extensions_become_pinnable(self):
        text = added(self.files[ACTIONS])
        self.assertEqual(text.count("kActionItemPinnableKey"), 2)
        self.assertEqual(text.count("ActionPinnableState::kPinnable"), 2)
        # Nothing is pinned by default: no pinned-by-default list is touched.
        self.assertNotIn("DefaultPinned", self.text)

    def test_two_enum_values_go_on_the_end(self):
        text = self.files[MOJOM]
        self.assertIn("+  kShowSettings,", text)
        self.assertIn("+  kShowExtensions,", text)
        # Appended after the last Chromium value, so no existing value moves.
        self.assertLess(
            text.index(" kContextualTasks,"), text.index("+  kShowSettings,")
        )
        self.assertEqual(removed(text), "")

    def test_the_handler_maps_both_ways(self):
        text = added(self.files[HANDLER])
        for needle in (
            "case kActionOptions:",
            "case kActionManageExtensions:",
            "mojom::ActionId::kShowSettings;",
            "mojom::ActionId::kShowExtensions;",
            "return kActionOptions;",
            "return kActionManageExtensions;",
        ):
            self.assertIn(needle, text)

    def test_the_handler_lists_both_with_a_plain_extensions_label(self):
        text = added(self.files[HANDLER])
        self.assertIn("add_action(kActionOptions,", text)
        self.assertIn("add_action(kActionManageExtensions,", text)
        self.assertIn("IDS_EXTENSIONS_MENU_TITLE", text)
        self.assertIn("kYourChrome", text)

    def test_candidates_that_do_nothing_leave_the_picker(self):
        gone = removed(self.files[HANDLER])
        for action in (
            "kActionShowTranslate",
            "kActionRouteMedia",
            "kActionSendTabToSelf",
        ):
            self.assertIn(f"add_action({action},", gone)
        # And only those three: every other entry keeps its line.
        self.assertEqual(gone.count("add_action("), 3)

    def test_the_toolbar_creates_the_menu_for_normal_windows_only(self):
        text = added(self.files[VIEW_CC])
        self.assertIn("boring_toolbar_menu.h", text)
        self.assertIn("DisplayMode::kNormal", text)
        self.assertIn("IsRegularProfile()", text)
        self.assertIn("make_unique<BoringToolbarMenu>(browser_, this)", text)
        self.assertEqual(removed(self.files[VIEW_CC]), "")

    def test_build_gn_lists_both_new_files(self):
        text = added(self.files[BUILD])
        self.assertIn('"boring_toolbar_menu.h"', text)
        self.assertIn('"boring_toolbar_menu.cc"', text)

    def test_series_lists_it_once_after_the_toolbar_patch(self):
        names = [
            line.strip()
            for line in SERIES.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        self.assertEqual(names.count("toolbar-quick-buttons.patch"), 1)
        self.assertGreater(
            names.index("toolbar-quick-buttons.patch"),
            names.index("toolbar-buttons.patch"),
        )

    def test_no_em_dash_anywhere_in_what_we_add(self):
        everything = self.text + "".join(
            p.read_text(encoding="utf-8") for p in MENU.glob("boring_toolbar_menu.*")
        )
        self.assertNotIn("\u2014", everything)
        self.assertNotIn("\u2013", everything)


class MenuTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cc = (MENU / "boring_toolbar_menu.cc").read_text(encoding="utf-8")

    def test_one_item_that_runs_the_customize_command(self):
        self.assertEqual(self.cc.count("model_.AddItem("), 1)
        self.assertIn("IDC_SHOW_CUSTOMIZE_CHROME_TOOLBAR", self.cc)
        self.assertIn("IDS_SHOW_CUSTOMIZE_CHROME_TOOLBAR", self.cc)

    def test_visible_text_is_not_hard_coded(self):
        # Every visible string comes from a resource, so none can say Chrome.
        literals = re.findall(r'u?"([^"\n]*)"', re.sub(r"#include .*", "", self.cc))
        shown = [s for s in literals if re.search(r"[A-Z][a-z]+ [a-z]+", s)]
        for s in shown:
            self.assertFalse(sqb.bad_text(s), s)

    def test_the_test_hook_does_nothing_without_its_switch(self):
        self.assertIn('HasSwitch("boring-toolbar-test")', self.cc)

    def test_the_test_hook_runs_once_per_process(self):
        self.assertIn("static bool test_step_posted = false;", self.cc)
        self.assertIn("!test_step_posted && command_line.HasSwitch(", self.cc)
        self.assertIn("test_step_posted = true;", self.cc)

    def test_the_item_is_off_where_the_panel_cannot_open(self):
        self.assertIn("BoringToolbarMenu::IsCommandIdEnabled", self.cc)
        self.assertIn("IsCustomizeChromeEntryAvailable()", self.cc)

    def test_the_menu_steps_send_a_real_right_click(self):
        # Through the root view, so hit testing and the registered menu
        # controllers are what the smoke test checks.
        self.assertIn("root->OnMousePressed(press);", self.cc)
        self.assertIn("root->OnMouseReleased(release);", self.cc)
        self.assertIn("EF_RIGHT_MOUSE_BUTTON", self.cc)
        self.assertNotIn("ShowContextMenuForView(", self.cc)


class HelperTest(unittest.TestCase):
    def test_parse_report_waits_for_the_end_line(self):
        self.assertIsNone(sqb.parse_report("ours\t1\n"))
        report = sqb.parse_report(
            "hit\tToolbarView\nours\t1\nhwnd\t123\nitem\tCustomize toolbar\ton\n"
            "button\tPinnedActionToolbarButton\tSettings\tSettings\toff\nend\n"
        )
        self.assertEqual(report["hit"], "ToolbarView")
        self.assertEqual(report["ours"], "1")
        self.assertEqual(report["hwnd"], 123)
        self.assertEqual(report["items"], [("Customize toolbar", True)])
        self.assertEqual(
            report["buttons"], [("PinnedActionToolbarButton", "Settings", "Settings", False)]
        )

    def test_find_key_looks_anywhere(self):
        self.assertEqual(
            sqb.find_key({"a": {"b": [{"pinned_actions": [1]}]}}, "pinned_actions"), [1]
        )
        self.assertIsNone(sqb.find_key({"a": 1}, "pinned_actions"))

    def test_pinned_actions_reads_a_closed_profile(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "Default").mkdir()
            (Path(d) / "Default" / "Preferences").write_text(
                json.dumps({"x": {"pinned_actions": ["kActionPrint"]}}),
                encoding="utf-8",
            )
            self.assertEqual(sqb.pinned_actions(d), ["kActionPrint"])
            (Path(d) / "Default" / "Preferences").write_text("{}", encoding="utf-8")
            self.assertEqual(sqb.pinned_actions(d), [])

    def test_bad_text_catches_the_browser_names_and_dashes(self):
        for s in ("Chrome", "Customize Chromium", "a \u2014 b", "a \u2013 b"):
            self.assertTrue(sqb.bad_text(s), s)
        for s in (
            "Settings",
            "Extensions",
            "Customize toolbar",
            "New Incognito window",
        ):
            self.assertFalse(sqb.bad_text(s), s)


if __name__ == "__main__":
    unittest.main()
