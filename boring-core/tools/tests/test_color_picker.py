#!/usr/bin/env python3
"""The old colour picker choices are retired (ledger item 61).

Release 2 let people pick Green or Beige through Chromium's colour swatches,
stored as Chromium's user colour. Release 3 picks the palette from the Look
in Settings, Appearance, with an accent. These tests pin the rules:

  * D1: no stored user colour picks or switches off our palette. Every
    window of a profile with no store theme is keyed with our seed
    (theme_service.cc, cui-colours.patch); the mixer has no seed-picked
    palettes.
  * D2: the Customize side panel shows no Appearance card (cui-old-colours
    .patch), and the swatch patch is gone.
  * D3: at startup the colour state the picker wrote goes back to a new
    profile's, Green keeps a green accent (boring_prefs.cc).
  * D4: Beige, Green and their seeds are gone; --boring-scheme takes the
    three Looks only.

smoke_colours.py (old_green, old_grey, side_panel) runs them in the browser.

Usage:
  python -m unittest boring-core/tools/tests/test_color_picker.py -v
"""

import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
SERIES = CORE / "patches" / "series"
OLD_PATCH = "colour-picker-schemes.patch"
NEW_PATCH = CORE / "patches" / "157" / "cui-old-colours.patch"
COLOURS_PATCH = CORE / "patches" / "157" / "cui-colours.patch"
SETTINGS_PATCH = CORE / "patches" / "157" / "cui-settings.patch"
FRAME_PATCH = CORE / "patches" / "157" / "frame-color.patch"
MIXER = CORE / "chromium_src" / "chrome" / "browser" / "ui" / "color" / "boring_color_mixer.cc"
PREFS_CC = CORE / "components" / "boring" / "core" / "boring_prefs.cc"
PREFS_H = CORE / "components" / "boring" / "core" / "boring_prefs.h"
TOOLS = CORE / "tools"

RGB = re.compile(
    r"SkColorSetRGB\(\s*0x([0-9a-fA-F]{2}),\s*0x([0-9a-fA-F]{2}),\s*0x([0-9a-fA-F]{2})\s*\)"
)


def series():
    return [ln.strip() for ln in SERIES.read_text().splitlines() if ln.strip()]


def added(path, file_marker=None):
    """The + lines of a patch, or of one file's section of it."""
    text = path.read_text(encoding="utf-8")
    if file_marker:
        start = text.index("+++ b/" + file_marker)
        end = text.find("\ndiff --git", start)
        text = text[start:end if end != -1 else len(text)]
    return "\n".join(
        ln[1:] for ln in text.splitlines() if ln.startswith("+") and not ln.startswith("+++")
    )


def rgb(text):
    m = RGB.search(text)
    return "#" + "".join(g.lower() for g in m.groups())


def key_block():
    """theme_service.cc's cui-old-colours block in GetColorProviderKey."""
    text = added(COLOURS_PATCH, "chrome/browser/themes/theme_service.cc")
    # The last added lines of the file's section; its closing brace is a
    # context line.
    return text[text.index("// boring: cui-old-colours (ledger 61)."):]


def reset_function():
    src = PREFS_CC.read_text(encoding="utf-8")
    start = src.index("void ResetRetiredColourPrefs(PrefService* prefs) {")
    return src[start:src.index("\n}\n", start)]


class D1StoredColourNeverPicksThePalette(unittest.TestCase):
    def test_every_window_of_a_profile_without_a_theme_gets_our_seed(self):
        block = key_block()
        self.assertIn(
            "if (!is_incognito && !is_isolated && !key.custom_theme &&\n"
            "      !GetThemeSupplier() && !UsingPolicyTheme()) {",
            block,
        )
        self.assertIn("key.user_color = kBoringSeed;", block)
        self.assertIn(
            "key.user_color_source = ui::ColorProviderKey::UserColorSource::kAccent;", block
        )
        self.assertIn("GetSchemeVariant(ui::mojom::BrowserColorVariant::kTonalSpot);", block)

    def test_it_runs_last_so_nothing_after_it_puts_the_stored_colour_back(self):
        text = added(COLOURS_PATCH, "chrome/browser/themes/theme_service.cc")
        tail = text[text.index("// boring: cui-old-colours (ledger 61)."):]
        self.assertNotIn("key.user_color = user_color", tail)
        patch = COLOURS_PATCH.read_text(encoding="utf-8")
        # The block is followed by the function's own return.
        self.assertRegex(
            patch,
            r"\+        GetSchemeVariant\(ui::mojom::BrowserColorVariant::kTonalSpot\);\n"
            r"   \}\n \n   return key;",
        )

    def test_the_seed_is_the_mixers_and_the_registered_default(self):
        theme = rgb(re.search(r"kBoringSeed = (SkColorSetRGB\([^)]*\))",
                              added(COLOURS_PATCH)).group(1))
        mixer = rgb(re.search(r"kCoolSeed = (SkColorSetRGB\([^)]*\))",
                              MIXER.read_text(encoding="utf-8")).group(1))
        default = rgb(next(ln for ln in added(FRAME_PATCH).splitlines() if "SkColorSetRGB" in ln))
        self.assertEqual({theme, mixer, default}, {"#4f46e5"})

    def test_the_mixer_recognises_only_that_seed_and_no_store_theme(self):
        src = MIXER.read_text(encoding="utf-8")
        body = re.search(r"bool UsingOurTheme\(.*?\n\}", src, re.S).group(0)
        self.assertIn("!key.custom_theme", body)
        self.assertIn("key.user_color == kCoolSeed", body)
        self.assertEqual(body.count("key.user_color =="), 1)

    def test_the_palette_comes_from_the_look_alone(self):
        src = MIXER.read_text(encoding="utf-8")
        self.assertIn("const Palette& look = LookPalette(key, dark);", src)
        # The accent never depends on the seed either.
        self.assertNotIn("user_color", re.search(
            r"bool HasCustomAccent\(.*?\n\}", src, re.S).group(0))


class D2NoSwatchesInTheSidePanel(unittest.TestCase):
    def test_the_swatch_patch_is_gone(self):
        self.assertNotIn(OLD_PATCH, series())
        self.assertFalse((CORE / "patches" / OLD_PATCH).exists())
        self.assertFalse((CORE / "patches" / "157" / OLD_PATCH).exists())

    def test_the_appearance_card_and_its_line_are_not_shown(self):
        self.assertIn("cui-old-colours.patch", series())
        css = added(NEW_PATCH, "chrome/browser/resources/side_panel/customize_chrome/app.css")
        self.assertIn("#appearance,\n#appearance + .sp-cards-separator {\n  display: none;\n}", css)

    def test_the_toolbar_card_is_untouched(self):
        text = NEW_PATCH.read_text(encoding="utf-8")
        self.assertNotIn("toolbar", added(NEW_PATCH).replace("Toolbar card", ""))
        files = [ln for ln in text.splitlines() if ln.startswith("+++ ")]
        self.assertEqual(
            files, ["+++ b/chrome/browser/resources/side_panel/customize_chrome/app.css"]
        )

    def test_the_new_patch_sits_before_the_tail_other_tests_pin(self):
        names = series()
        self.assertLess(names.index("cui-settings.patch"), names.index("cui-old-colours.patch"))
        self.assertLess(names.index("cui-old-colours.patch"), names.index("sidetabs.patch"))


class D3UpgradedProfilesStartFresh(unittest.TestCase):
    def test_it_runs_from_the_profile_migration_before_theme_service(self):
        src = PREFS_CC.read_text(encoding="utf-8")
        body = src[src.index("void MigrateObsoleteProfilePrefs(PrefService* prefs) {"):]
        self.assertIn("ResetRetiredColourPrefs(prefs);", body[: body.index("\n}\n")])
        # chrome-browser-prefs.patch calls it from Chromium's own migration,
        # which profile_impl.cc runs before any keyed service is made.
        prefs_patch = (CORE / "patches" / "157" / "chrome-browser-prefs.patch").read_text(
            encoding="utf-8")
        self.assertIn("+  boring::MigrateObsoleteProfilePrefs(profile_prefs);", prefs_patch)
        self.assertIn("ThemeService exists", PREFS_H.read_text(encoding="utf-8"))

    def test_the_pref_names_are_chromiums(self):
        src = PREFS_CC.read_text(encoding="utf-8")
        for name, value in (
            ("kThemeIdPref", "extensions.theme.id"),
            ("kUserColorThemeId", "user_color_theme_id"),
            ("kUserColorPref", "browser.theme.user_color2"),
            ("kColorVariantPref", "browser.theme.color_variant2"),
            ("kGrayscalePref", "browser.theme.is_grayscale2"),
            ("kFollowsSystemColorsPref", "browser.theme.follows_system_colors"),
            ("kAutogeneratedColorPref", "autogenerated.theme.color"),
        ):
            self.assertRegex(src, rf'constexpr char {name}\[\] =\s*"{re.escape(value)}";')

    def test_it_clears_every_picker_pref_and_keeps_light_or_dark(self):
        body = reset_function()
        for name in ("kThemeIdPref", "kUserColorPref", "kColorVariantPref",
                     "kGrayscalePref", "kFollowsSystemColorsPref", "kAutogeneratedColorPref"):
            self.assertIn(f"prefs->ClearPref({name});", body)
        # No name for Light or dark (browser.theme.color_scheme2) is declared.
        self.assertNotRegex(PREFS_CC.read_text(encoding="utf-8"),
                            r'constexpr char \w+\[\] =\s*"browser\.theme\.color_scheme')
        self.assertNotIn("color_scheme", body)

    def test_a_store_autogenerated_or_policy_theme_is_left_alone(self):
        body = reset_function()
        self.assertIn("if (!theme_id.empty() && theme_id != kUserColorThemeId) {\n    return;", body)
        # Nothing is cleared before that check.
        self.assertLess(body.index("theme_id != kUserColorThemeId"), body.index("ClearPref"))

    def test_green_gets_the_accent_rows_green_only_over_the_default(self):
        src = PREFS_CC.read_text(encoding="utf-8")
        self.assertIn("constexpr uint32_t kRetiredGreenSeed = 0xFF1F8A72u;", src)
        green = re.search(r'kAccentGreen\[\] = "(#[0-9a-f]{6})";', src).group(1)
        rows = re.findall(r"\{value: '(#[0-9a-f]{6})', name: '(\w+)'",
                          SETTINGS_PATCH.read_text(encoding="utf-8"))
        self.assertIn((green, "Green"), rows)
        body = reset_function()
        # Read before the clear, applied after it, and only over the default.
        self.assertLess(body.index("const bool had_green"), body.index("ClearPref"))
        self.assertIn(
            "if (had_green && prefs->GetString(prefs::kAppearanceAccent) ==\n"
            "                       prefs::kAccentDefault) {\n"
            "    prefs->SetString(prefs::kAppearanceAccent, kAccentGreen);", body)

    def test_the_green_seed_is_release_2s_swatch(self):
        # The swatch colour.patch put in the picker was 0x1f8a72; ThemeService
        # stores the SkColor (opaque) as a pref int.
        self.assertEqual(0xFF1F8A72 - (1 << 32), -14710158)
        self.assertEqual((0xFF << 24) | (0x1F << 16) | (0x8A << 8) | 0x72, 0xFF1F8A72)


class D4OldSchemesAreGone(unittest.TestCase):
    def test_no_beige_or_green_palette_or_seed_is_left(self):
        src = MIXER.read_text(encoding="utf-8")
        for name in ("kBeigeLight", "kBeigeDark", "kGreenLight", "kGreenDark", "kBeigeSeed",
                     "kLegacyBeigeSeed", "kGreenSeed", "WantsBeige", "WantsGreen"):
            self.assertNotIn(name, src)

    def test_the_switch_takes_the_looks_only(self):
        src = MIXER.read_text(encoding="utf-8")
        values = re.findall(r'scheme == "(\w+)"', src)
        self.assertEqual(sorted(values), ["dusk", "slate", "soft_white"])
        self.assertNotIn('"beige"', src)
        self.assertNotIn('"green"', src)

    def test_no_tool_asks_for_an_old_scheme(self):
        for path in TOOLS.glob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotRegex(text, r"boring-scheme=(green|beige|cool)\b", path.name)
            self.assertNotRegex(text, r'"--boring-scheme=" \+ args\.scheme\b.*beige', path.name)


if __name__ == "__main__":
    unittest.main()
