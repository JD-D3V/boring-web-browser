#!/usr/bin/env python3
"""Native geometry and menu rows follow the approved mock (design/v7/icons-dotted).

Usage:
  python -m unittest boring-core/tools/tests/test_native_gaps.py -v
"""

import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PATCHES = CORE / "patches"
SETS = ("", "153", "154")


def text(subdir, name):
    return (PATCHES / subdir / name).read_text(encoding="utf-8")


class NativeGapsTest(unittest.TestCase):
    def test_address_bar_stays_chromiums_full_pill_at_34(self):
        self.assertNotIn("kFieldCornerRadius", text("", "omnibox-shape.patch"))
        for d in SETS:
            self.assertNotIn("kLocationBarHeight", text(d, "toolbar-buttons.patch"))

    def test_toolbar_buttons_are_the_mocks_32_circles(self):
        for d in SETS:
            t = text(d, "toolbar-buttons.patch")
            self.assertIn("return touch_ui ? 48 : 32;", t)
            self.assertIn("gfx::Insets(touch_ui ? 12 : 6)", t)
            self.assertIn(".SetViewHidden(toolbar_divider_, true);", t)

    def test_menu_drops_profile_tab_groups_and_cast(self):
        self.assertIn("app-menu-rows.patch", text("", "series").split())
        for d in SETS:
            t = text(d, "app-menu-rows.patch")
            self.assertIn("-  sub_menus_.push_back(std::make_unique<ProfileSubMenuModel>(", t)
            self.assertIn("-    auto saved_tab_groups_model", t)
            self.assertIn("+  int string_id = IDS_SAVE_AND_SHARE_MENU;", t)

    def test_address_bar_focus_is_the_mocks_3px_soft_accent_glow(self):
        # .pill:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
        mock = (CORE.parent / "design" / "v7" / "icons-dotted" / "index.html").read_text(encoding="utf-8")
        self.assertIn("box-shadow:0 0 0 3px var(--accent-soft)", mock)
        self.assertIn("location-bar-focus-glow.patch", text("", "series").split())
        t = text("", "location-bar-focus-glow.patch")
        self.assertIn("SetHaloThickness(3.0f)", t)
        self.assertIn("SetHaloInset(-1.5f)", t)  # wholly outside the border
        self.assertIn("border_color = color_provider->GetColor(ui::kColorSysPrimary);", t)
        mixer = (CORE / "chromium_src" / "chrome" / "browser" / "ui" / "color" / "boring_color_mixer.cc").read_text(encoding="utf-8")
        self.assertIn("mixer[kColorLocationBarBorderOnMismatch] = {", mixer)
        self.assertIn("dark ? 0x24 : 0x1A", mixer)  # 14% dark, 10% light

    def test_menu_row_icon_turns_accent_on_hover(self):
        # .menu button:hover svg{color:var(--accent)}
        mock = (CORE.parent / "design" / "v7" / "icons-dotted" / "index.html").read_text(encoding="utf-8")
        self.assertIn(".menu button:hover svg{color:var(--accent)}", mock)
        self.assertIn("menu-icon-hover.patch", text("", "series").split())
        t = text("", "menu-icon-hover.patch")
        self.assertIn("+            icon_color = GetColorProvider()->GetColor(ui::kColorSysPrimary);", t)
        self.assertIn("-            icon_color = colors.icon_color;", t)

    def test_toolbar_press_scales_to_the_mocks_94_percent_and_respects_reduced_motion(self):
        # .tb:active{transform:scale(.94)...}
        mock = (CORE.parent / "design" / "v7" / "icons-dotted" / "index.html").read_text(encoding="utf-8")
        self.assertIn(".tb:active{transform:scale(.94)", mock)
        self.assertIn("toolbar-press-scale.patch", text("", "series").split())
        t = text("", "toolbar-press-scale.patch")
        self.assertIn("0.94f", t)
        self.assertIn("PrefersReducedMotion()", t)
        self.assertIn("ShouldRenderRichAnimation()", t)
        self.assertIn("IMMEDIATELY_ANIMATE_TO_NEW_TARGET", t)  # interruptible
        self.assertIn("pressed ? 70 : 120", t)  # short
        self.assertNotIn("OnMousePressed", t.replace("+", ""))  # input path untouched


if __name__ == "__main__":
    unittest.main()
