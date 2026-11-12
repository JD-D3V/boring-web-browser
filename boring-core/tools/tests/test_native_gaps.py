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

    def test_157_sizes_live_in_one_header_behind_one_hook(self):
        self.assertIn("layout-constants.patch", text("", "series").split())
        hook = text("157", "layout-constants.patch")
        self.assertIn("boring::LayoutConstantOverride(constant, touch_ui)", hook)
        self.assertIn("boring::LayoutInsetsOverride(inset, touch_ui)", hook)
        self.assertNotIn("layout_constants.cc", text("157", "toolbar-buttons.patch"))
        header = (
            CORE / "chromium_src" / "chrome" / "browser" / "ui"
            / "boring_layout_constants.h"
        ).read_text(encoding="utf-8")
        for want in (
            "LayoutConstant::kToolbarButtonHeight) {\n    return 32;",
            "LayoutConstant::kLocationBarMargin) {\n    return 10;",
            "TOOLBAR_BUTTON) {\n    return gfx::Insets(6);",
        ):
            self.assertIn(want, header)

    def test_157_toolbar_dividers_are_hidden_by_colour_not_views_code(self):
        t = text("157", "toolbar-buttons.patch")
        changed = [ln for ln in t.splitlines() if ln[:1] in "+-"]
        self.assertFalse([ln for ln in changed if "toolbar_divider_" in ln])
        self.assertNotIn("pinned_toolbar_actions_container.cc", t)
        mixer = (
            CORE / "chromium_src" / "chrome" / "browser" / "ui" / "color"
            / "boring_color_mixer.cc"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "mixer[kColorToolbarExtensionSeparatorEnabled] = {SK_ColorTRANSPARENT};",
            mixer,
        )

    def test_157_toolbar_build_and_menu_commands_each_have_one_owner(self):
        names = text("", "series").split()
        for gone in ("forget-session.patch", "protection-menu.patch"):
            self.assertNotIn(gone, names)
        owners = {}
        for name in names:
            p = PATCHES / "157" / name
            body = (p if p.exists() else PATCHES / name).read_text(encoding="utf-8")
            for rel in ("chrome/browser/ui/views/toolbar/BUILD.gn",
                        "chrome/browser/ui/browser_command_controller.cc"):
                if "+++ b/" + rel in body:
                    owners.setdefault(rel, []).append(name)
        self.assertEqual(
            owners["chrome/browser/ui/views/toolbar/BUILD.gn"], ["toolbar-build-gn.patch"]
        )
        self.assertEqual(
            owners["chrome/browser/ui/browser_command_controller.cc"],
            ["menu-commands.patch"],
        )

    def test_menu_drops_profile_tab_groups_and_cast(self):
        self.assertIn("app-menu-rows.patch", text("", "series").split())
        for d in SETS:
            t = text(d, "app-menu-rows.patch")
            self.assertIn(
                "-  sub_menus_.push_back(std::make_unique<ProfileSubMenuModel>(", t
            )
            self.assertIn("-    auto saved_tab_groups_model", t)
            self.assertIn("+  int string_id = IDS_SAVE_AND_SHARE_MENU;", t)

    def test_address_bar_focus_is_the_mocks_3px_soft_accent_glow(self):
        # .pill:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
        mock = (
            CORE.parent / "design" / "v7" / "icons-dotted" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("box-shadow:0 0 0 3px var(--accent-soft)", mock)
        self.assertIn("location-bar-focus-glow.patch", text("", "series").split())
        t = text("", "location-bar-focus-glow.patch")
        self.assertIn("SetHaloThickness(3.0f)", t)
        self.assertIn(
            "SetHaloInset(-3.0f)", t
        )  # full thickness: stroke wholly outside the border
        self.assertIn(
            "border_color = color_provider->GetColor(ui::kColorSysPrimary);", t
        )
        mixer = (
            CORE
            / "chromium_src"
            / "chrome"
            / "browser"
            / "ui"
            / "color"
            / "boring_color_mixer.cc"
        ).read_text(encoding="utf-8")
        self.assertIn("mixer[kColorLocationBarBorderOnMismatch] = {", mixer)
        self.assertIn("dark ? 0x24 : 0x1A", mixer)  # 14% dark, 10% light

    def test_menu_row_icon_turns_accent_on_hover(self):
        # .menu button:hover svg{color:var(--accent)}
        mock = (
            CORE.parent / "design" / "v7" / "icons-dotted" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn(".menu button:hover svg{color:var(--accent)}", mock)
        self.assertIn("menu-icon-hover.patch", text("", "series").split())
        t = text("", "menu-icon-hover.patch")
        self.assertIn(
            "+            icon_color = GetColorProvider()->GetColor(ui::kColorSysPrimary);",
            t,
        )
        self.assertIn("-            icon_color = colors.icon_color;", t)

    def test_toolbar_press_scales_to_the_mocks_94_percent_and_respects_reduced_motion(
        self,
    ):
        # .tb:active{transform:scale(.94)...}
        mock = (
            CORE.parent / "design" / "v7" / "icons-dotted" / "index.html"
        ).read_text(encoding="utf-8")
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
