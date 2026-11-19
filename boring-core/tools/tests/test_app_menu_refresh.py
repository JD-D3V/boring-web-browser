#!/usr/bin/env python3
"""The main menu refresh (design/v9-menu, mockup A) keeps every command.

Reads patches/157/app-menu-refresh.patch, the views in
chromium_src/.../boring/boring_app_menu.cc and the tree's app_menu_model.cc
(BORING_SRC, default E:\\ung-157\\build\\src), patched or not: the patch is
applied to, or undone from, a scratch copy, so the commands before and
after it are compared whenever a tree is here.

Usage:
  python -m unittest boring-core/tools/tests/test_app_menu_refresh.py -v
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CORE = Path(__file__).resolve().parents[2]
REPO = CORE.parent
TOOLS = CORE / "tools"
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
MODEL_PATH = "chrome/browser/ui/toolbar/app_menu_model.cc"
MODEL = SRC / MODEL_PATH
# The files the patch changes. Submenu models live in app_menu_model.cc or
# files of their own that are not here, so the patch cannot drop a row
# inside a submenu unless app_menu_model.cc changes outside Build().
PATCHED_FILES = {
    "chrome/app/chrome_command_ids.h",
    "chrome/browser/ui/toolbar/app_menu_model.h",
    MODEL_PATH,
    "chrome/browser/ui/views/toolbar/app_menu.cc",
    "chrome/browser/ui/views/toolbar/BUILD.gn",
    "ui/views/controls/menu/menu_item_view.h",
    "ui/views/controls/menu/menu_item_view.cc",
    "ui/views/controls/menu/menu_controller.cc",
}

# Every command AppMenuModel::Build() put in the menu before the refresh
# (157.0.8103.38 with patch set 157), the ones only some profiles or
# builds show included. ParityTest checks it against the tree.
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


def apply_patch(text, reverse=False):
    """`text` (an app_menu_model.cc) with the patch's hunks for it applied,
    or undone, in a scratch repository of its own."""
    with tempfile.TemporaryDirectory(prefix="app-menu-parity-") as tmp:
        subprocess.run(["git", "init", "-q", tmp], check=True)
        path = Path(tmp) / MODEL_PATH
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        args = ["git", "apply", "--include=" + MODEL_PATH]
        if reverse:
            args.append("--reverse")
        subprocess.run([*args, str(PATCH)], cwd=tmp, check=True, capture_output=True)
        return path.read_text(encoding="utf-8")


# Mockup A's numbers as they were when JD picked it. LookTest checks the
# constants against these always, and these against design/v9-menu/a.html
# whenever that page is here (design/ is kept out of the repository).
MOCK_NUMBERS = {
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
    "row_font": 13,
}


def page_numbers():
    """The same numbers, read from the mockup page."""
    numbers = {}
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
    numbers["row_font"] = int(re.search(r"font:(\d+)px", rule(".menu")).group(1))
    return numbers


def constant(name):
    m = re.search(rf"constexpr int {name} = (\d+);", VIEWS.read_text(encoding="utf-8"))
    assert m, name
    return int(m.group(1))


class PatchTest(unittest.TestCase):
    def test_patch_comes_after_every_patch_on_its_files(self):
        # It is made against the tree with every patch before it applied, so
        # no patch after it may touch its files. The quick buttons patch also
        # edits views/toolbar/BUILD.gn, so it must come first.
        names = [n.strip() for n in SERIES.read_text().splitlines() if n.strip()]
        self.assertEqual(names.count("app-menu-refresh.patch"), 1)
        at = names.index("app-menu-refresh.patch")
        self.assertLess(names.index("toolbar-quick-buttons.patch"), at)
        for name in names[at + 1 :]:
            path = CORE / "patches" / "157" / name
            if not path.exists():
                path = CORE / "patches" / name
            text = path.read_text(encoding="utf-8", errors="replace")
            touched = set(re.findall(r"^\+\+\+ b/(\S+)", text, re.M))
            self.assertEqual(touched & PATCHED_FILES, set(), name)

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
        for path, most in (
            ("ui/views/controls/menu/menu_item_view.h", 15),
            ("ui/views/controls/menu/menu_item_view.cc", 16),
            ("ui/views/controls/menu/menu_controller.cc", 17),
        ):
            removed, added = file_hunks(path)
            self.assertEqual(removed, [], path)
            self.assertLessEqual(len(added), most, path)
            self.assertTrue(any("boring:" in ln for ln in added), path)

    def test_patch_changes_only_its_files(self):
        files = re.findall(r"^diff --git a/(\S+) ", patch_text(), re.M)
        self.assertEqual(sorted(files), sorted(PATCHED_FILES))

    def test_only_the_main_menus_headings_look_new(self):
        # Titles in submenus share kTitleId with the headings; the headings
        # get an id of their own, and the stock title look stays.
        removed, added = file_hunks("chrome/browser/ui/views/toolbar/app_menu.cc")
        self.assertFalse(any("STYLE_HEADLINE_5" in ln for ln in removed))
        text = "\n".join(added)
        self.assertEqual(text.count("command_id == boring::kAppMenuHeadingId"), 2)
        views = VIEWS.read_text(encoding="utf-8")
        self.assertIn("item->SetCommand(kAppMenuHeadingId);", views)

    def test_headings_are_headings_and_not_selection_stops(self):
        views = VIEWS.read_text(encoding="utf-8")
        self.assertIn("SetRole(ax::mojom::Role::kHeading)", views)
        _, added = file_hunks("ui/views/controls/menu/menu_item_view.cc")
        text = "\n".join(added)
        self.assertIn("GetCachedRole() == ax::mojom::Role::kHeading", text)

    def test_left_and_right_move_across_a_row_of_buttons(self):
        _, added = file_hunks("ui/views/controls/menu/menu_controller.cc")
        text = "\n".join(added)
        self.assertIn("key_code == ui::VKEY_LEFT || key_code == ui::VKEY_RIGHT", text)
        self.assertIn("GetNextFocusableView(row, button, forward)", text)
        self.assertIn("SetHotTrackedButton(next);", text)

    def test_first_tile_shows_the_models_label(self):
        # An Incognito or isolated window's model says "New Incognito tab".
        views = VIEWS.read_text(encoding="utf-8")
        self.assertNotIn("GetStringUTF16(IDS_NEW_TAB)", views)
        self.assertIn("ShownLabel(command_id, model->GetLabelAt(index))", views)

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


class ParityTest(unittest.TestCase):
    """The menu's commands before the patch against after it, read from the
    tree's app_menu_model.cc with the patch undone or applied in a scratch
    copy, whichever the tree lacks."""

    @classmethod
    def setUpClass(cls):
        if not MODEL.exists():
            raise unittest.SkipTest(f"no tree at {SRC}")
        text = MODEL.read_text(encoding="utf-8")
        if "IDC_BORING_APP_MENU_TILES" in text:
            cls.before, cls.after = apply_patch(text, reverse=True), text
        else:
            cls.before, cls.after = text, apply_patch(text)

    def test_checked_in_list_is_the_menu_before_the_patch(self):
        self.assertEqual(
            sorted(set(TOKEN.findall(build_body(self.before)))), sorted(BEFORE)
        )

    def test_every_command_is_still_in_the_menu(self):
        after = set(TOKEN.findall(build_body(self.after)))
        self.assertEqual(sorted(BEFORE - after), [])

    def test_submenus_are_as_they_were(self):
        # Everything outside Build(), the submenu models in this file
        # included, is untouched.
        # The one change outside it is More tools' "Customize" row, which
        # takes the branded label so that no menu string says Chrome.
        mine = (
            "    // boring: the branded label, so More tools does not say Chrome.\n"
            "    AddItemWithStringIdAndVectorIcon(this, IDC_SHOW_CUSTOMIZE_CHROME_SIDE_PANEL,\n"
            "                                     IDS_SIDE_PANEL_CUSTOMIZE_CHROME_TITLE,\n"
        )
        stock = (
            "    AddItemWithStringIdAndVectorIcon(this, IDC_SHOW_CUSTOMIZE_CHROME_SIDE_PANEL,\n"
            "                                     IDS_SHOW_CUSTOMIZE_CHROME_SIDE_PANEL,\n"
        )
        self.assertEqual(self.after.count(mine), 1)
        self.assertEqual(
            self.before.replace(build_body(self.before), ""),
            self.after.replace(mine, stock).replace(build_body(self.after), ""),
        )

    def test_rows_are_in_the_mockups_order(self):
        body = build_body(self.after)
        at = [body.find(t) for t in ORDER]
        self.assertNotIn(-1, at, [t for t, i in zip(ORDER, at, strict=True) if i < 0])
        self.assertEqual(at, sorted(at))


def press(after, prefix, before=None):
    """smoke_app_menu.press_opens_tab("Settings") with the browser faked:
    the tabs are `before` ({handle: url}, one New tab page by default), and
    `after` once the button is pressed."""
    before = before or {"a": "chrome://newtab/"}
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    try:
        import smoke_app_menu as smoke
    except (ImportError, OSError, AttributeError) as e:
        raise unittest.SkipTest(f"smoke_app_menu does not import here: {e}") from e
    pressed = []

    class Clock:
        now = 0.0

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    class FakeWindow:
        def __init__(self, hwnd):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def press(self, wanted):
            pressed.append(wanted("Settings"))

    class FakeBrowser:
        sid = "s"
        on = None

        def _req(self, method, path, body=None):
            if body and "handle" in body:
                self.on = body["handle"]
            return {"value": None}

        def current_url(self):
            return (after if pressed else before)[self.on]

    with (
        mock.patch.object(smoke, "time", Clock()),
        mock.patch.object(smoke, "Window", FakeWindow),
        mock.patch.object(smoke, "window_names", return_value=(1, [])),
        mock.patch.object(
            smoke, "handles", lambda b: list(after if pressed else before)
        ),
    ):
        return smoke.press_opens_tab(FakeBrowser(), 0, "Settings", prefix)


class SmokeWiringTest(unittest.TestCase):
    def test_the_window_pass_checks_the_smokes_height(self):
        smoke = (TOOLS / "smoke_app_menu.py").read_text(encoding="utf-8")
        height = re.search(r"^MENU_HEIGHT = (\d+)$", smoke, re.M).group(1)
        wiring = (TOOLS / "run_window_pass.py").read_text(encoding="utf-8")
        self.assertEqual(
            re.findall(r'"--expect-height",\s*"(\d+)"', wiring), [height, height]
        )

    def test_settings_may_open_in_the_new_tab_page_in_front(self):
        # Settings over a New tab page loads in that tab, no new handle
        # (singleton_tabs.cc ShowSingletonTabOverwritingNTP).
        self.assertIsNone(press({"a": "chrome://settings/"}, "chrome://settings"))

    def test_a_new_tab_at_the_same_url_counts(self):
        after = {"a": "chrome://newtab/", "b": "chrome://newtab/"}
        self.assertIsNone(press(after, "chrome://"))

    def test_a_tab_that_was_already_open_and_moved_counts(self):
        # About reuses the open Settings tab, not the one the driver is on.
        before = {"a": "chrome://settings/", "b": "chrome://boring-protection/"}
        after = {"a": "chrome://settings/help", "b": "chrome://boring-protection/"}
        self.assertIsNone(press(after, "chrome://settings/help", before))

    def test_a_press_that_opens_nothing_fails(self):
        self.assertEqual(
            press({"a": "chrome://newtab/"}, "chrome://settings"),
            "Settings opened nothing",
        )

    def test_a_page_that_was_there_before_does_not_count(self):
        same = {"a": "chrome://settings/help"}
        self.assertEqual(
            press(same, "chrome://settings/help", same), "Settings opened nothing"
        )

    def test_the_smoke_checks_the_keys_the_hook_sends(self):
        if str(TOOLS) not in sys.path:
            sys.path.insert(0, str(TOOLS))
        try:
            import smoke_app_menu as smoke
        except (ImportError, OSError, AttributeError) as e:
            raise unittest.SkipTest(f"smoke_app_menu does not import here: {e}") from e
        sent = re.search(
            r'kKeys\[\] =\s*"([A-Z]+)";', VIEWS.read_text(encoding="utf-8")
        )
        self.assertEqual(sent.group(1), smoke.KEYS)

    def test_the_menu_tools_turn_updates_off(self):
        for name in ("smoke_app_menu.py", "capture_app_menu.py"):
            src = (TOOLS / name).read_text(encoding="utf-8")
            self.assertIn('"--disable-boring-updates"', src, name)
            self.assertIn('"--disable-boring-list-updates"', src, name)


def smoke_module():
    if str(TOOLS) not in sys.path:
        sys.path.insert(0, str(TOOLS))
    try:
        import smoke_app_menu as smoke
    except (ImportError, OSError, AttributeError) as e:
        raise unittest.SkipTest(f"smoke_app_menu does not import here: {e}") from e
    return smoke


class SmokeLayoutTest(unittest.TestCase):
    """check_layout fails on any entry that is extra, repeated or moved."""

    def setUp(self):
        self.smoke = smoke_module()

    def problems(self, top):
        menu = {"top": top, "submenus": {}, "height": self.smoke.MENU_HEIGHT}
        return self.smoke.check_layout(menu)

    def test_the_layout_itself_passes(self):
        self.assertEqual(self.problems(list(self.smoke.LAYOUT)), [])

    def test_an_extra_entry_fails(self):
        top = [*self.smoke.LAYOUT[:3], "Update now", *self.smoke.LAYOUT[3:]]
        self.assertTrue(any("extra" in p for p in self.problems(top)))

    def test_a_repeated_entry_fails(self):
        top = [*self.smoke.LAYOUT, "Settings"]
        self.assertTrue(any("repeated" in p for p in self.problems(top)))

    def test_a_moved_entry_fails(self):
        top = list(self.smoke.LAYOUT)
        top[-2], top[-1] = top[-1], top[-2]
        self.assertTrue(any("order" in p for p in self.problems(top)))

    def test_a_missing_entry_fails(self):
        top = [n for n in self.smoke.LAYOUT if n != "History"]
        self.assertTrue(any("missing" in p for p in self.problems(top)))

    def test_chrome_or_chromium_in_any_menu_fails(self):
        menu = {"top": ["Settings"], "submenus": {"More tools": ["Customize Chrome"]}}
        self.assertEqual(len(self.smoke.check_upstream_names(menu)), 1)
        menu = {"top": ["Chromium"], "submenus": {}}
        self.assertEqual(len(self.smoke.check_upstream_names(menu)), 1)
        menu = {
            "top": ["Settings"],
            "submenus": {"More tools": ["Customize Boring Browser"]},
        }
        self.assertEqual(self.smoke.check_upstream_names(menu), [])


class LookTest(unittest.TestCase):
    def test_checked_in_numbers_are_the_mockups(self):
        if not MOCK.exists():
            self.skipTest(
                f"{MOCK} is not here (design/ is kept out of the repository); "
                "the sizes are checked against MOCK_NUMBERS only"
            )
        self.assertEqual(page_numbers(), MOCK_NUMBERS)

    def test_sizes_are_the_mockups(self):
        m = MOCK_NUMBERS
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
            ("kRowFontSize", "row_font"),
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

    def test_high_contrast_keeps_the_system_menu_colours(self):
        # As the stock menu: in Windows high contrast the menu ids keep what
        # ui/color/win/native_color_mixers_win.cc maps them to.
        src = MIXER.read_text(encoding="utf-8")
        stop = src.index("ContrastMode::kHigh")
        for name in (
            "mixer[ui::kColorMenuBackground]",
            "mixer[ui::kColorMenuItemForeground]",
            "mixer[kColorAppMenuToolsAndActionsBackground]",
            "mixer[ui::kColorAppMenuRowBackgroundHovered]",
            "mixer[ui::kColorMenuButtonBackground]",
        ):
            self.assertGreater(src.index(name), stop, name)
        # Our popups' row hover is not a menu id; it stays as it was.
        self.assertLess(src.index("mixer[kColorHoverButtonBackgroundHovered]"), stop)
        # A hovered tile's text is a hovered row's (HighlightText there).
        views = VIEWS.read_text(encoding="utf-8")
        self.assertIn("IsHot() ? ui::kColorMenuItemForegroundSelected", views)


if __name__ == "__main__":
    unittest.main()
