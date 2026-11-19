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
    "new_tab_refresh_old",
    "new_window_old",
    "incognito_refresh_menu_old",
    "account_circle_chrome_refresh_old",
    "password_manager_old",
    "history_old",
    "download_menu_old",
    "bookmarks_lists_menu_old",
    "saved_tab_group_bar_everything_old",
    "extension_chrome_refresh_old",
    "trash_can_refresh_old",
    "zoom_in_old",
    "zoom_plus_menu_refresh_old",
    "zoom_minus_menu_refresh_old",
    "fullscreen_refresh_old",
    "print_menu_old",
    "g_translate",
    "search_menu_old",
    "cast_chrome_refresh_old",
    "file_save_chrome_refresh_old",
    "link_chrome_refresh_old",
    "copy_menu_old",
    "more_tools_menu_old",
    "info_refresh_old",
    "settings_menu_old",
    "help_menu_old",
    "exit_menu_old",
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
        missing = [
            n
            for names in icon_map.ICON_MAP.values()
            for n in names
            if n not in icon_map.OURS and not self.resolved.get(n)
        ]
        self.assertEqual(missing, [])

    def test_no_chromium_icon_is_mapped_twice(self):
        seen = {}
        for sid, names in icon_map.ICON_MAP.items():
            for n in names:
                self.assertNotIn(n, seen, f"{sid} and {seen.get(n)} both map {n}")
                seen[n] = sid

    def test_every_mapped_id_is_in_the_svg(self):
        svg = (
            TOOLS.parents[1] / "design" / "v7" / "icons-dotted" / "icons.svg"
        ).read_text(encoding="utf-8")
        for sid in icon_map.ICON_MAP:
            self.assertIn(f'id="{sid}"', svg)

    def test_generated_files_validate_with_the_chromium_aggregator(self):
        with tempfile.TemporaryDirectory() as out:
            written = icon_map.generate(TREE, out)
            self.assertGreater(len(written), 40)
            icon_map.validate(written, TREE)

    def test_validate_rejects_a_broken_icon(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "bad.icon"
            bad.write_text("CANVAS_DIMENSIONS, 20,\nNOT_A_COMMAND, 1, 2,\n")
            with self.assertRaises(ValueError):
                icon_map.validate([str(bad)], TREE)

    def test_back_arrow_files_do_not_flip_in_rtl(self):
        with tempfile.TemporaryDirectory() as out:
            icon_map.generate(TREE, out)
            text = (
                Path(out) / "components" / "vector_icons" / "arrow_back.icon"
            ).read_text()
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
                if Path(rel).name in icon_map.OURS_SUFFIXES:
                    continue  # ours alone, nothing to match
                original = pristine.text(TREE, rel)
                got = "FLIPS_IN_RTL" in Path(dest).read_text()
                self.assertEqual(got, "FLIPS_IN_RTL" in original, rel)

    def test_exemptions_are_not_also_mapped(self):
        mapped = {n for names in icon_map.ICON_MAP.values() for n in names}
        self.assertEqual(sorted(mapped & set(EXEMPT)), [])

    def test_filled_warning_icons_stay_chromiums(self):
        self.assertNotIn("b-warning", icon_map.ICON_MAP)
        for rel in (
            "chrome/app/vector_icons/warning_filled.icon",
            "components/vector_icons/warning_filled.icon",
        ):
            self.assertFalse((CHROMIUM_SRC / rel).exists(), rel)

    def test_generated_icons_keep_the_canvas_size_of_the_icon_they_replace(self):
        with tempfile.TemporaryDirectory() as out:
            for dest in icon_map.generate(TREE, out):
                rel = Path(dest).relative_to(out)
                Path(TREE) / rel  # overlaid by apply.py once it has run
                if rel.name in icon_map.OURS_SUFFIXES:  # ours, not Chromium's
                    continue
                # The tree holds our overlays once apply.py has run; the
                # originals are in the pristine store.
                m = re.search(
                    r"CANVAS_DIMENSIONS,\s*(\d+)",
                    pristine.text(TREE, str(rel).replace("\\", "/")),
                )
                want = m.group(1) if m else "48"  # Chromium's default grid
                got = re.search(
                    r"CANVAS_DIMENSIONS,\s*(\d+)", Path(dest).read_text()
                ).group(1)
                self.assertEqual(got, want, str(rel))

    def test_back_forward_reload_and_home_are_solid_strokes_without_the_dot(self):
        # JD chose solid arrows over the dotted set for these four (2026-10-14).
        vi = CHROMIUM_SRC / "chrome" / "app" / "vector_icons"
        for name in (
            "arrow_back_old",
            "arrow_forward_old",
            "autorenew_old",
            "navigate_home_chrome_refresh_old",
            "home",
            "reload_touch_old",
            "back_arrow_touch_old",
            "forward_arrow_touch_old",
            "navigate_home_touch_old",
            "autorenew",
        ):
            self.assertNotIn("CIRCLE,", (vi / (name + ".icon")).read_text(), name)
        svg = (
            TOOLS.parents[1] / "design" / "v7" / "icons-dotted" / "icons.svg"
        ).read_text(encoding="utf-8")
        for sid in ("b-back", "b-forward", "b-reload", "b-home"):
            symbol = re.search(rf'<symbol id="{sid}".*?</symbol>', svg, re.S).group(0)
            self.assertNotIn("<circle", symbol, sid)

    def test_menu_icon_is_dots(self):
        text = (
            CHROMIUM_SRC / "chrome" / "app" / "vector_icons" / "boring_menu.icon"
        ).read_text()
        self.assertEqual(text.count("CIRCLE,"), 3)
        self.assertNotIn("LINE_TO", text)

    def test_protected_is_the_shield_with_the_tick(self):
        # Protected draws the compiled UI's shield with a tick (I.shield);
        # the Protection button's other states, the plain one (I.shieldPlain).
        vi = CHROMIUM_SRC / "chrome" / "app" / "vector_icons"
        on = (vi / "boring_protection_on.icon").read_text()
        plain = (vi / "boring_protection.icon").read_text()
        for text in (on, plain):
            self.assertIn("MOVE_TO, 10, 2.5,", text)  # the shield's top, 12 3 on 24
            self.assertNotIn("CIRCLE,", text)
        self.assertIn("MOVE_TO, 7.5, 10,", on)  # the tick, 9 12 on 24
        self.assertNotIn("MOVE_TO, 7.5, 10,", plain)

    def test_committed_icons_match_the_generator(self):
        with tempfile.TemporaryDirectory() as out:
            for rel in icon_map.generate(TREE, out):
                rel_path = Path(rel).relative_to(out)
                committed = CHROMIUM_SRC / rel_path
                self.assertTrue(committed.exists(), str(rel_path))
                self.assertEqual(
                    committed.read_text(), Path(rel).read_text(), str(rel_path)
                )


SVG = TOOLS.parents[1] / "design" / "v7" / "icons-dotted" / "icons.svg"
PATCH = TOOLS.parent / "patches" / "157" / "compiled-icons.patch"


def compiled_symbols():
    """The compiled UI's c- symbols in the set, by id."""
    text = SVG.read_text(encoding="utf-8")
    return {
        m.group(1): m.group(0)
        for m in re.finditer(r'<symbol id="(c-[^"]+)".*?</symbol>', text, re.S)
    }


class CompiledSetTest(unittest.TestCase):
    """The compiled UI's icons: needs no Chromium tree."""

    def test_every_compiled_glyph_has_an_icon_of_ours(self):
        symbols = compiled_symbols()
        self.assertGreaterEqual(len(symbols), 45)
        for sid in symbols:
            self.assertIn(sid, icon_map.ICON_MAP, sid)
            self.assertTrue(
                any(n.startswith("boring_") for n in icon_map.ICON_MAP[sid]), sid
            )

    def test_compiled_glyphs_are_a_2px_line_in_full_ink(self):
        # Thinner only where the master draws it so: the 13px close and
        # 14px chevron at 1.8, the warning page's shield at 1.7.
        thinner = {"c-close": "1.8", "c-chevron-right": "1.8", "c-shield-alert": "1.7"}
        for sid, xml in compiled_symbols().items():
            head = xml[: xml.index(">")]
            self.assertIn('viewBox="0 0 24 24"', head, sid)
            self.assertIn('stroke-width="2"', head, sid)
            self.assertIn('stroke-linecap="round"', head, sid)
            self.assertIn('stroke-linejoin="round"', head, sid)
            self.assertNotIn("opacity", xml, sid)
            widths = set(re.findall(r'<path[^>]*stroke-width="([^"]+)"', xml))
            self.assertEqual(widths, {thinner[sid]} if sid in thinner else set(), sid)

    def test_incognito_is_the_ghost(self):
        ghost = icon_map.ICON_MAP["c-priv"]
        for name in (
            "incognito",
            "incognito_old",
            "incognito_refresh_menu_old",
            "incognito_circle_filled",
            "incognito_cr2023_old",
        ):
            self.assertIn(name, ghost)
        self.assertNotIn("b-incognito", icon_map.ICON_MAP)
        # The hem of the ghost: the wavy bottom edge of I.priv.
        self.assertIn("l-2.2-1.7-2.1 1.7", compiled_symbols()["c-priv"])

    def test_menu_protection_row_is_the_plain_shield(self):
        self.assertIn("shield", icon_map.ICON_MAP["c-shield-plain"])
        self.assertEqual(icon_map.ICON_MAP["c-shield"], ["boring_protection_on"])

    def test_forget_does_not_take_over_chromiums_delete_icon(self):
        # kDeleteIcon is also autofill's, the tab group editor's and site
        # data's delete button; Forget draws boring_erase instead.
        mapped = {n for names in icon_map.ICON_MAP.values() for n in names}
        self.assertNotIn("delete", mapped)
        self.assertNotIn("delete_old", mapped)
        self.assertEqual(icon_map.ICON_MAP["c-erase"], ["boring_erase"])

    def test_our_icons_declare_the_toolbar_canvas(self):
        for name in icon_map.OURS:
            text = (CHROMIUM_SRC / "chrome" / "app" / "vector_icons" / (name + ".icon")).read_text()
            self.assertIn("CANVAS_DIMENSIONS, 20,", text, name)

    def test_build_gn_patch_lists_every_new_icon_of_ours_once(self):
        added = re.findall(r'^\+    "(boring_\w+)\.icon",$', PATCH.read_text(), re.M)
        want = sorted(set(icon_map.OURS) - {"boring_menu", "boring_protection"})
        self.assertEqual(added, want)
        self.assertIn("# boring:", PATCH.read_text())

    def test_series_applies_the_patch(self):
        series = (TOOLS.parent / "patches" / "series").read_text().split()
        self.assertIn("compiled-icons.patch", series)


if __name__ == "__main__":
    unittest.main()
