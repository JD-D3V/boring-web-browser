#!/usr/bin/env python3
"""The main menu refresh (design/v9-menu, mockup A) keeps every command.

Reads patches/157/app-menu-refresh.patch, the views in
chromium_src/.../boring/boring_app_menu.cc and, once the patch is applied,
the built tree's app_menu_model.cc (BORING_SRC, default E:\\ung-157\\build\\src).

Usage:
  python -m unittest boring-core/tools/tests/test_app_menu_refresh.py -v
"""

import os
import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
REPO = CORE.parent
PATCH = CORE / "patches" / "157" / "app-menu-refresh.patch"
SERIES = CORE / "patches" / "series"
VIEWS = (
    CORE
    / "chromium_src"
    / "chrome"
    / "browser"
    / "ui"
    / "views"
    / "boring"
    / "boring_app_menu.cc"
)
MIXER = (
    CORE
    / "chromium_src"
    / "chrome"
    / "browser"
    / "ui"
    / "color"
    / "boring_color_mixer.cc"
)
MOCK = REPO / "design" / "v9-menu" / "a.html"
SRC = Path(os.environ.get("BORING_SRC", r"E:\ung-157\build\src"))
MODEL = SRC / "chrome" / "browser" / "ui" / "toolbar" / "app_menu_model.cc"

# Every command AppMenuModel::Build() put in the menu before the refresh
# (157.0.8103.38 with patch set 157), the ones only some profiles or
# builds show included.
BEFORE = {
    "IDC_UPGRADE_DIALOG",
    "AddSafetyHubMenuItem",
    "AddGlobalErrorMenuItems",
    "AddDefaultBrowserMenuItems",
    "IDC_NEW_TAB",
    "IDC_NEW_WINDOW",
    "IDC_NEW_INCOGNITO_WINDOW",
    "IDC_NEW_ISOLATED_WINDOW",
    "kPasswordsAndAutofillMenuPlaceholder",
    "kRecentTabsMenuPlaceholder",
    "IDC_SHOW_DOWNLOADS",
    "kBookmarksMenuPlaceholder",
    "kSkillsAndExtensionsMenuPlaceholder",
    "IDC_FIND_EXTENSIONS",
    "kExtensionsSubmenuPlaceholder",
    "IDC_CLEAR_BROWSING_DATA",
    "CreateZoomMenu",
    "IDC_PRINT",
    "IDC_OPEN_GLIC",
    "IDC_SHOW_TTC_MENU",
    "IDC_ASK_GOOGLE_ABOUT_THIS_PAGE",
    "IDC_CONTENT_CONTEXT_LENS_OVERLAY",
    "kContextualTasksMenuPlaceholder",
    "IDC_SHOW_TRANSLATE",
    "CreateFindAndEditSubMenu",
    "kSaveAndShareMenuPlaceholder",
    "IDC_TOGGLE_REQUEST_TABLET_SITE",
    "kMoreToolsMenuPlaceholder",
    "kHelpMenuPlaceholder",
    "IDC_ABOUT",
    "IDC_BORING_PROTECTION",
    "IDC_BORING_FORGET_SESSION",
    "IDC_OPTIONS",
    "IDC_EXIT",
    "IDC_SHOW_MANAGEMENT_PAGE",
    "IDC_CHROME_ENTERPRISE_RELEASE_NOTES",
}
# The order of mockup A, by what Build() adds.
ORDER = [
    "IDC_NEW_TAB",
    "IDC_NEW_WINDOW",
    "IDC_NEW_INCOGNITO_WINDOW",
    "IDC_BORING_APP_MENU_TILES",
    'AddTitle(u"Browse")',
    "kPasswordsAndAutofillMenuPlaceholder",
    "kRecentTabsMenuPlaceholder",
    "IDC_SHOW_DOWNLOADS",
    "kBookmarksMenuPlaceholder",
    "kSkillsAndExtensionsMenuPlaceholder",
    "IDC_CLEAR_BROWSING_DATA",
    'AddTitle(u"Page")',
    "CreateZoomMenu();",
    "IDC_PRINT",
    "IDC_SHOW_TRANSLATE",
    "CreateFindAndEditSubMenu();",
    "kSaveAndShareMenuPlaceholder",
    "kMoreToolsMenuPlaceholder",
    'AddTitle(u"Browser")',
    "IDC_BORING_PROTECTION",
    "IDC_BORING_FORGET_SESSION",
    "IDC_ABOUT",
    "IDC_SHOW_MANAGEMENT_PAGE",
    "IDC_OPTIONS",
    "IDC_EXIT",
    "IDC_BORING_APP_MENU_BAR",
]
TOKEN = re.compile(r"\b(IDC_\w+|k\w+Placeholder|Add\w+MenuItems?|Create\w+Menu)\b")


def patch_text():
    return PATCH.read_text(encoding="utf-8")


def file_hunks(path):
    """(removed, added) lines of one file in the patch."""
    removed, added, inside = [], [], False
    for line in patch_text().splitlines():
        if line.startswith("diff --git "):
            inside = line.endswith(" b/" + path)
        elif inside and line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
        elif inside and line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    return removed, added


def build_body(text):
    start = text.index("void AppMenuModel::Build() {")
    return text[start : text.index("\n}\n", start)]


def mock_numbers():
    """Mockup A's numbers, read from the page when it is here (design/v9-menu
    is kept out of the repository), else the ones it had when JD picked it."""
    numbers = {
        "row_radius": 8,
        "card_radius": 12,
        "card_padding": 4,
        "tile_height": 76,
        "tile_radius": 12,
        "tile_gap": 8,
        "menu_padding": 8,
        "bar_height": 36,
        "bar_radius": 9,
        "bar_padding": 12,
    }
    if not MOCK.exists():
        return numbers
    css = MOCK.read_text(encoding="utf-8")

    def rule(selector):
        return re.search(re.escape(selector) + r"\{(.*?)\}", css, re.S).group(1)

    def px(text, prop):
        return int(re.search(rf"(?:^|;){prop}:(\d+)px", text).group(1))

    numbers["row_radius"] = px(rule(".va"), "--rr")
    card = rule(".va .card")
    numbers["card_radius"] = px(card, "border-radius")
    numbers["card_padding"] = px(card, "padding")
    tile = rule(".va .tile")
    numbers["tile_height"] = px(tile, "height")
    numbers["tile_radius"] = px(tile, "border-radius")
    numbers["tile_gap"] = px(rule(".va .tiles"), "gap")
    numbers["menu_padding"] = px(rule(".menu"), "padding")
    bb = rule(".bb")
    numbers["bar_height"] = px(bb, "height")
    numbers["bar_radius"] = px(bb, "border-radius")
    numbers["bar_padding"] = int(re.search(r"padding:0 (\d+)px", bb).group(1))
    return numbers


def constant(name):
    m = re.search(rf"constexpr int {name} = (\d+);", VIEWS.read_text(encoding="utf-8"))
    assert m, name
    return int(m.group(1))


class PatchTest(unittest.TestCase):
    def test_patch_is_last_in_the_series(self):
        names = [n.strip() for n in SERIES.read_text().splitlines() if n.strip()]
        self.assertEqual(names[-1], "app-menu-refresh.patch")

    def test_no_command_the_patch_removes_is_lost(self):
        removed, added = file_hunks("chrome/browser/ui/toolbar/app_menu_model.cc")
        gone = set(TOKEN.findall("\n".join(removed)))
        kept = set(TOKEN.findall("\n".join(added)))
        self.assertEqual(sorted(gone - kept), [])

    def test_app_menu_treats_both_rows_like_the_zoom_row(self):
        _, added = file_hunks("chrome/browser/ui/views/toolbar/app_menu.cc")
        text = "\n".join(added)
        # IsCommandEnabled, ExecuteCommand, GetAccelerator, PopulateMenu.
        self.assertEqual(text.count("command_id == IDC_BORING_APP_MENU_TILES"), 3)
        self.assertEqual(text.count("command_id == IDC_BORING_APP_MENU_BAR"), 3)
        self.assertIn("case IDC_BORING_APP_MENU_TILES:", text)
        self.assertIn("boring::StyleAppMenu(root_);", text)

    def test_new_files_are_built(self):
        _, added = file_hunks("chrome/browser/ui/views/toolbar/BUILD.gn")
        self.assertIn('    "../boring/boring_app_menu.cc",', added)
        self.assertIn('    "../boring/boring_app_menu.h",', added)

    def test_ui_views_change_is_small_and_marked(self):
        for path in (
            "ui/views/controls/menu/menu_item_view.h",
            "ui/views/controls/menu/menu_item_view.cc",
        ):
            removed, added = file_hunks(path)
            self.assertEqual(removed, [], path)
            self.assertLess(len(added), 16, path)
            self.assertTrue(any("boring:" in ln for ln in added), path)

    def test_text_is_plain(self):
        added = []
        for path in (
            "chrome/browser/ui/toolbar/app_menu_model.cc",
            "chrome/browser/ui/views/toolbar/app_menu.cc",
        ):
            added += file_hunks(path)[1]
        shown = re.findall(r'u"([^"]*)"', "\n".join(added))
        shown += re.findall(r'u"([^"]*)"', VIEWS.read_text(encoding="utf-8"))
        self.assertIn("Browse", shown)
        self.assertIn("Page", shown)
        self.assertIn("Browser", shown)
        for text in shown:
            self.assertNotRegex(text, r"Chrom(e|ium)")
            self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2014", patch_text())


class BuiltModelTest(unittest.TestCase):
    def setUp(self):
        if not MODEL.exists():
            self.skipTest(f"no tree at {SRC}")
        self.body = build_body(MODEL.read_text(encoding="utf-8"))
        if "IDC_BORING_APP_MENU_TILES" not in self.body:
            self.skipTest("app-menu-refresh.patch is not applied in " + str(SRC))

    def test_every_command_is_still_in_the_menu(self):
        self.assertEqual(sorted(BEFORE - set(TOKEN.findall(self.body))), [])

    def test_rows_are_in_the_mockups_order(self):
        at = [self.body.find(t) for t in ORDER]
        self.assertNotIn(-1, at, [t for t, i in zip(ORDER, at, strict=True) if i < 0])
        self.assertEqual(at, sorted(at))


class LookTest(unittest.TestCase):
    def test_sizes_are_the_mockups(self):
        m = mock_numbers()
        for name, key in (
            ("kRowRadius", "row_radius"),
            ("kCardRadius", "card_radius"),
            ("kCardPadding", "card_padding"),
            ("kTileHeight", "tile_height"),
            ("kTileRadius", "tile_radius"),
            ("kTileGap", "tile_gap"),
            ("kMenuPadding", "menu_padding"),
            ("kBarButtonHeight", "bar_height"),
            ("kBarButtonRadius", "bar_radius"),
            ("kBarButtonPadding", "bar_padding"),
        ):
            self.assertEqual(constant(name), m[key], name)

    def test_card_and_hover_colours_come_from_the_palette(self):
        src = MIXER.read_text(encoding="utf-8")
        self.assertIn("mixer[kColorAppMenuToolsAndActionsBackground]", src)
        # The mock's hover: the accent at 14% in light, 20% in dark.
        self.assertIn("SkColorSetA(p.accent, dark ? 0x33 : 0x24)", src)
        self.assertIn("mixer[ui::kColorAppMenuRowBackgroundHovered]", src)
        views = VIEWS.read_text(encoding="utf-8")
        self.assertIn("kColorAppMenuToolsAndActionsBackground", views)
        self.assertIn("ui::kColorAppMenuRowBackgroundHovered", views)


if __name__ == "__main__":
    unittest.main()
