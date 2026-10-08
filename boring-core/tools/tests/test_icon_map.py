#!/usr/bin/env python3
"""Tests for icon_map.py against the Chromium 154 tree.

Usage:
  python -m unittest boring-core/tools/tests/test_icon_map.py -v
Set BORING_TREE to use a tree other than E:/ung-154/build/src.
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import icon_map  # noqa: E402
import pristine  # noqa: E402

TREE = os.environ.get("BORING_TREE", r"E:\ung-154\build\src")
CHROMIUM_SRC = TOOLS.parent / "chromium_src"

# Where the default (non-rounded-flag) toolbar, tab strip and address bar
# pick their icons. Every "_old" icon named in these files is either mapped
# or listed in EXEMPT with the reason it stays Chromium's.
DEFAULT_ICON_SOURCES = [
    "chrome/browser/ui/views/toolbar/back_forward_button.cc",
    "chrome/browser/ui/views/toolbar/reload_button.cc",
    "chrome/browser/ui/views/toolbar/home_button.cc",
    "chrome/browser/ui/views/frame/horizontal_tab_strip_region_view.cc",
    "chrome/browser/ui/views/bookmarks/bookmark_page_action_controller.cc",
    "components/omnibox/browser/location_bar_model_util.cc",
    "chrome/browser/ui/views/location_bar/location_icon_view.cc",
]
EXEMPT = {
    "business_chrome_refresh_old": "managed-browser badge, not part of the set",
    "dangerous_chrome_refresh_old": "filled danger state keeps Chromium's stronger cue",
    "no_encryption_old": "filled not-secure state keeps Chromium's stronger cue",
    "not_secure_warning_chrome_refresh_old": "filled warning keeps Chromium's stronger cue",
}


# The rows of the top-level app menu, by the icon each draws in the default
# (non-rounded-flag) window. Each must be one of ours.
APP_MENU_ICONS = [
    "new_tab_refresh_old", "new_window_old", "incognito_refresh_menu_old",
    "account_circle_chrome_refresh_old", "password_manager_old", "history_old",
    "download_menu_old", "bookmarks_lists_menu_old",
    "saved_tab_group_bar_everything_old", "extension_chrome_refresh_old",
    "trash_can_refresh_old", "zoom_in_old", "zoom_plus_menu_refresh_old",
    "zoom_minus_menu_refresh_old", "fullscreen_refresh_old", "print_menu_old",
    "g_translate", "search_menu_old", "cast_chrome_refresh_old",
    "file_save_chrome_refresh_old", "link_chrome_refresh_old",
    "copy_menu_old", "more_tools_menu_old", "info_refresh_old",
    "settings_menu_old", "help_menu_old", "exit_menu_old",
    "submenu_arrow_chrome_refresh_old",
]


def snake(const):
    name = re.sub(r"^k", "", const)
    name = re.sub(r"Icon$", "", name)
    return re.sub(r"(?<!^)(?=[A-Z0-9])", "_", name).lower().replace("__", "_")



@unittest.skipUnless(os.path.isdir(TREE), "Chromium 154 tree not present")
class IconMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resolved = icon_map.resolve(TREE)

    def test_every_mapped_name_exists_in_the_tree(self):
        missing = [n for names in icon_map.ICON_MAP.values() for n in names
                   if not self.resolved.get(n)]
        self.assertEqual(missing, [])

    def test_no_chromium_icon_is_mapped_twice(self):
        seen = {}
        for sid, names in icon_map.ICON_MAP.items():
            for n in names:
                self.assertNotIn(n, seen, "%s and %s both map %s" % (sid, seen.get(n), n))
                seen[n] = sid

    def test_every_mapped_id_is_in_the_svg(self):
        svg = (TOOLS.parents[1] / "design" / "v7" / "icons-dotted" / "icons.svg").read_text(encoding="utf-8")
        for sid in icon_map.ICON_MAP:
            self.assertIn('id="%s"' % sid, svg)

    def test_generated_files_validate_with_the_chromium_aggregator(self):
        with tempfile.TemporaryDirectory() as out:
            written = icon_map.generate(TREE, out)
            self.assertGreater(len(written), 40)
            icon_map.validate(written, TREE)

    def test_validate_rejects_a_broken_icon(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.icon"
            bad.write_text("CANVAS_DIMENSIONS, 20,\nNOT_A_COMMAND, 1, 2,\n")
            with self.assertRaises(Exception):
                icon_map.validate([str(bad)], TREE)

    def test_back_arrow_files_do_not_flip_in_rtl(self):
        with tempfile.TemporaryDirectory() as out:
            icon_map.generate(TREE, out)
            text = (Path(out) / "components" / "vector_icons" / "arrow_back.icon").read_text()
            self.assertNotIn("FLIPS_IN_RTL", text)

    def test_every_default_toolbar_tab_and_address_icon_is_mapped_or_exempt(self):
        mapped = {n for names in icon_map.ICON_MAP.values() for n in names}
        gaps = {}
        for rel in DEFAULT_ICON_SOURCES:
            path = Path(TREE) / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for const in set(re.findall(r"\bk\w+Icon\b", text)):
                if not re.search(r"(OldIcon|ChromeRefreshOldIcon)$", const):
                    continue
                name = snake(const)
                if name not in mapped and name not in EXEMPT:
                    gaps.setdefault(name, []).append(rel)
        self.assertEqual(gaps, {}, "icons the default window draws that nothing maps")

    def test_every_top_level_app_menu_row_icon_is_one_of_ours(self):
        mapped = {n for names in icon_map.ICON_MAP.values() for n in names}
        self.assertEqual(sorted(set(APP_MENU_ICONS) - mapped), [])

    def test_menu_chevrons_keep_chromiums_rtl_flip_and_button_arrows_do_not(self):
        with tempfile.TemporaryDirectory() as out:
            icon_map.generate(TREE, out)
            for dest in icon_map.generate(TREE, out):
                rel = str(Path(dest).relative_to(out)).replace("\\", "/")
                original = pristine.text(TREE, rel)
                got = "FLIPS_IN_RTL" in Path(dest).read_text()
                self.assertEqual(got, "FLIPS_IN_RTL" in original, rel)

    def test_exemptions_are_not_also_mapped(self):
        mapped = {n for names in icon_map.ICON_MAP.values() for n in names}
        self.assertEqual(sorted(mapped & set(EXEMPT)), [])

    def test_filled_warning_icons_stay_chromiums(self):
        self.assertNotIn("b-warning", icon_map.ICON_MAP)
        for rel in ("chrome/app/vector_icons/warning_filled.icon",
                    "components/vector_icons/warning_filled.icon"):
            self.assertFalse((CHROMIUM_SRC / rel).exists(), rel)

    def test_generated_icons_keep_the_canvas_size_of_the_icon_they_replace(self):
        with tempfile.TemporaryDirectory() as out:
            for dest in icon_map.generate(TREE, out):
                rel = Path(dest).relative_to(out)
                original = Path(TREE) / rel  # overlaid by apply.py once it has run
                if rel.name == "boring_menu.icon":  # ours, not Chromium's
                    continue
                # The tree holds our overlays once apply.py has run; the
                # originals are in the pristine store.
                m = re.search(r"CANVAS_DIMENSIONS,\s*(\d+)",
                              pristine.text(TREE, str(rel).replace("\\", "/")))
                want = m.group(1) if m else "48"  # Chromium's default grid
                got = re.search(r"CANVAS_DIMENSIONS,\s*(\d+)", Path(dest).read_text()).group(1)
                self.assertEqual(got, want, str(rel))

    def test_menu_icon_is_dots(self):
        text = (CHROMIUM_SRC / "chrome" / "app" / "vector_icons" / "boring_menu.icon").read_text()
        self.assertEqual(text.count("CIRCLE,"), 3)
        self.assertNotIn("LINE_TO", text)

    def test_committed_icons_match_the_generator(self):
        with tempfile.TemporaryDirectory() as out:
            for rel in icon_map.generate(TREE, out):
                rel_path = Path(rel).relative_to(out)
                committed = CHROMIUM_SRC / rel_path
                self.assertTrue(committed.exists(), str(rel_path))
                self.assertEqual(committed.read_text(), Path(rel).read_text(), str(rel_path))


if __name__ == "__main__":
    unittest.main()
