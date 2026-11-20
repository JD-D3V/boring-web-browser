#!/usr/bin/env python3
"""The page smoke helpers, and the pages' own scripts.

Usage:
  python -m unittest boring-core/tools/tests/test_page_checks.py -v
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import page_checks  # noqa: E402

CORE = TOOLS.parent
NEWTAB = CORE / "components" / "boring" / "newtab" / "newtab_ui.cc"
WARNING = CORE / "components" / "boring" / "scam" / "warning_page.cc"

SAMPLE = (
    'constexpr char kA[] = R"A(<p>one</p>)A";\n'
    'constexpr char kB[] = R"SCRIPT(\nvar x = ")";\n)SCRIPT";\n'
)


class RawStringTest(unittest.TestCase):
    def test_finds_a_constant_by_name(self):
        self.assertEqual(page_checks.raw_string(SAMPLE, "kA"), "<p>one</p>")

    def test_a_close_paren_and_quote_inside_does_not_end_it(self):
        self.assertEqual(
            page_checks.raw_string(SAMPLE, "kB"), '\nvar x = ")";\n'
        )

    def test_unknown_name_is_none(self):
        self.assertIsNone(page_checks.raw_string(SAMPLE, "kC"))

    def test_script_blocks(self):
        html = "<script>a()</script><p>x</p><script>\nb()\n</script>"
        self.assertEqual(page_checks.script_blocks(html), ["a()", "\nb()\n"])


@unittest.skipUnless(page_checks.have_node(), "node is not installed")
class SyntaxTest(unittest.TestCase):
    def test_good_script_passes(self):
        self.assertIsNone(page_checks.js_syntax_error("var a = {b: 1};\n"))

    def test_a_missing_closing_brace_is_caught(self):
        # The mistake that left the new tab page's script dead.
        self.assertIsNotNone(
            page_checks.js_syntax_error("window.f = function() {\n  if (a) {\n  }\n")
        )


@unittest.skipUnless(page_checks.have_node(), "node is not installed")
class PagesOwnScriptsTest(unittest.TestCase):
    def test_new_tab_script_parses(self):
        js = page_checks.raw_string(NEWTAB.read_text(encoding="utf-8"), "kScript")
        self.assertIsNotNone(js)
        self.assertIsNone(page_checks.js_syntax_error(js))

    def test_warning_page_script_parses(self):
        text = WARNING.read_text(encoding="utf-8")
        bottom = page_checks.raw_string(text, "kPageBottom")
        blocks = page_checks.script_blocks(bottom)
        self.assertEqual(len(blocks), 1)
        self.assertIsNone(page_checks.js_syntax_error(blocks[0]))


SCAM = CORE / "components" / "boring" / "scam"


class WarningPageContractTest(unittest.TestCase):
    """What the two page smokes rely on in the C++ source."""

    def test_report_a_mistake_goes_to_the_issue_list_and_nowhere_else(self):
        header = (SCAM / "warning_page.h").read_text(encoding="utf-8")
        self.assertIn(
            'kReportMistakeUrl[] =\n    "https://github.com/JD-D3V/boring-web-browser/issues";',
            header,
        )
        for name in ("scam_blocking_page.cc", "lookalike_blocking_page.cc"):
            text = (SCAM / name).read_text(encoding="utf-8")
            self.assertIn("CMD_OPEN_HELP_CENTER", text)
            self.assertIn("OpenUrlInNewForegroundTab(GURL(kReportMistakeUrl))", text)
        page = WARNING.read_text(encoding="utf-8")
        self.assertIn("Report a mistake</button>", page)
        self.assertIn("certificateErrorPageController.openHelpCenter()", page)

    def test_the_report_link_is_not_an_address(self):
        # A link or a prefetch would be a request before the press.
        page = WARNING.read_text(encoding="utf-8")
        self.assertNotIn("github", page.lower())
        self.assertNotRegex(page, r"<a [^>]*href")

    def test_both_pages_use_the_system_font(self):
        for path in (WARNING, NEWTAB):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\bInter\b")
            self.assertNotRegex(text, r"@import|@font-face|googleapis|gstatic")
            self.assertIn("system-ui", text)

    def test_the_calm_line_is_the_drawn_wording(self):
        page = WARNING.read_text(encoding="utf-8")
        self.assertIn('<p class="calm">%CALM%</p>', page)
        self.assertIn("base::EscapeForHTML(text.calm)", page)
        header = re.sub(r'"\s*\n\s*"', "", (SCAM / "warning_page.h").read_text(encoding="utf-8"))
        self.assertIn(
            '"Your computer is fine. Nothing was sent, and you do not need to call anyone."',
            header,
        )

    def test_the_quad9_page_does_not_say_nothing_was_sent(self):
        # The name did go to Quad9, as its DNS question.
        text = (SCAM / "scam_blocking_page.cc").read_text(encoding="utf-8")
        quad9 = text.split("if (quad9_block_) {")[1].split("return BuildWarningPage")[0]
        quad9 = re.sub(r'"\s*\n\s*"', "", quad9)
        self.assertIn("text.calm =", quad9)
        self.assertIn("Only the site's name went to Quad9", quad9)
        self.assertNotIn("Nothing was sent", quad9)

    def test_continue_is_inside_the_closed_why_part(self):
        # Two presses past a warning (ledger 36): Continue sits in #why,
        # which starts hidden, and never in the footer.
        page = WARNING.read_text(encoding="utf-8")
        self.assertIn(
            'kContinueTop[] = "<div class=\\"why\\" id=\\"why\\" hidden><p>";', page
        )
        bottom = page.split("kContinueBottom[] =")[1].split(";\n")[0]
        self.assertIn("proceedAnyway()", bottom)
        self.assertNotIn("footer", bottom)
        self.assertTrue(bottom.rstrip().endswith('"</div>"'))
        self.assertIn("[hidden] { display: none !important; }", page)

    def test_report_a_mistake_is_on_every_warning(self):
        # Ledger 37: with a way past and without one (no way past, Quad9).
        page = WARNING.read_text(encoding="utf-8")
        build = page.split("std::string BuildWarningPage(")[1]
        self.assertEqual(build.count("kReportButton"), 2)
        self.assertEqual(page.count("reportMistake()\\\">Report a mistake</button>"), 1)


class NewTabRecentTest(unittest.TestCase):
    """Ledger 38: "Pick up where you left off" rows."""

    def test_titles_are_cut_on_a_character_boundary(self):
        text = NEWTAB.read_text(encoding="utf-8")
        self.assertIn("base::TruncateUTF8ToByteSize(title, kMaxRecentTitleLength)", text)
        self.assertNotIn("title.resize(kMaxRecentTitleLength)", text)

    def test_shortcut_titles_are_cut_on_a_character_boundary(self):
        # Ledger 51 (S-B5).
        text = NEWTAB.read_text(encoding="utf-8")
        self.assertIn("base::TruncateUTF8ToByteSize(title, kMaxTitleLength)", text)
        self.assertNotIn("title.resize(kMaxTitleLength)", text)

    def test_the_host_is_never_hidden(self):
        css = page_checks.raw_string(NEWTAB.read_text(encoding="utf-8"), "kPage")
        self.assertIsNotNone(css)
        rules = re.findall(r"\.recent-row \.site\s*\{([^}]*)\}", css)
        self.assertTrue(rules)
        for rule in rules:
            self.assertNotIn("display: none", rule)
            self.assertNotIn("overflow", rule)
        self.assertIn("flex: none", rules[0])


class BesideTest(unittest.TestCase):
    def test_every_reference_is_in_the_shots_folder(self):
        for name in page_checks.REFERENCES.values():
            self.assertFalse(name.startswith(("/", "..")))

    def test_no_picture_means_none(self):
        with tempfile.TemporaryDirectory() as folder:
            ours = Path(folder) / "ours.png"
            ours.write_bytes(b"x")
            with mock.patch.object(page_checks, "reference", return_value=None):
                self.assertIsNone(page_checks.beside(ours, "C99", folder))

    def test_without_pil_the_design_is_copied_beside(self):
        with tempfile.TemporaryDirectory() as folder:
            ours = Path(folder) / "ours.png"
            ours.write_bytes(b"x")
            ref = Path(folder) / "ref.png"
            ref.write_bytes(b"design")
            out = Path(folder) / "out"
            with (
                mock.patch.object(page_checks, "reference", return_value=ref),
                mock.patch.dict(sys.modules, {"PIL": None}),
            ):
                dest = page_checks.beside(ours, "C01", out)
            self.assertEqual(dest.name, "ours-design.png")
            self.assertEqual(dest.read_bytes(), b"design")

    def test_with_pil_one_image_holds_both(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL is not installed")
        with tempfile.TemporaryDirectory() as folder:
            ours = Path(folder) / "ours.png"
            ref = Path(folder) / "ref.png"
            Image.new("RGB", (100, 80), (255, 0, 0)).save(ours)
            Image.new("RGB", (40, 40), (0, 0, 255)).save(ref)
            with mock.patch.object(page_checks, "reference", return_value=ref):
                dest = page_checks.beside(ours, "C01", Path(folder) / "out")
            with Image.open(dest) as sheet:
                self.assertEqual(sheet.height, 80)
                self.assertEqual(sheet.width, 100 + 24 + 80)
                self.assertEqual(sheet.getpixel((10, 10)), (255, 0, 0))
                self.assertEqual(sheet.getpixel((sheet.width - 5, 10)), (0, 0, 255))

    def test_the_real_pictures_exist_when_the_folder_does(self):
        if not page_checks.SHOTS.is_dir():
            self.skipTest("no shots-final folder here")
        self.assertIsNotNone(page_checks.reference("C01"))
        self.assertIsNotNone(page_checks.reference("C12", dark=True))


class SaveCaptureTest(unittest.TestCase):
    """The shared capture folder (compiled UI ledger item 30)."""

    def shots(self, folder):
        shots = Path(folder) / "shots"
        (shots / "dark").mkdir(parents=True)
        return shots

    def test_the_option_is_named_captures(self):
        import argparse

        ap = argparse.ArgumentParser()
        page_checks.add_captures_option(ap)
        self.assertEqual(ap.parse_args(["--captures", "x"]).captures, "x")
        self.assertIsNone(ap.parse_args([]).captures)

    def test_the_folder_comes_from_the_option_then_the_environment(self):
        with mock.patch.dict("os.environ", {page_checks.CAPTURES_ENV: "from-env"}):
            self.assertEqual(page_checks.captures_folder("from-option"), Path("from-option"))
            self.assertEqual(page_checks.captures_folder(), Path("from-env"))
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(page_checks.captures_folder())

    def test_the_design_folder_can_be_named(self):
        with mock.patch.dict("os.environ", {page_checks.DESIGN_ENV: "somewhere"}):
            self.assertEqual(page_checks.shots_folder(), Path("somewhere"))

    def test_a_screen_is_found_by_its_number_in_light_and_dark(self):
        with tempfile.TemporaryDirectory() as folder:
            shots = self.shots(folder)
            (shots / "c10-settings.png").write_bytes(b"l")
            (shots / "dark" / "c10-settings.png").write_bytes(b"d")
            with mock.patch.object(page_checks, "SHOTS", shots):
                self.assertEqual(page_checks.screen_picture("C10").parent, shots)
                self.assertEqual(page_checks.screen_picture("c10", dark=True).parent, shots / "dark")
                self.assertIsNone(page_checks.screen_picture("c99"))

    def test_no_folder_means_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as folder:
            ours = Path(folder) / "ours.png"
            ours.write_bytes(b"x")
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertIsNone(page_checks.save_capture(ours, "menu", "c07"))

    def test_no_compiled_screen_or_no_capture_means_none(self):
        with tempfile.TemporaryDirectory() as folder:
            shots = self.shots(folder)
            with mock.patch.object(page_checks, "SHOTS", shots):
                missing = Path(folder) / "none.png"
                self.assertIsNone(page_checks.save_capture(missing, "menu", "c07", folder=folder))
                ours = Path(folder) / "ours.png"
                ours.write_bytes(b"x")
                self.assertIsNone(page_checks.save_capture(ours, "menu", "c07", folder=folder))

    def test_one_image_per_screen_and_theme_ours_on_the_left(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("PIL is not installed")
        with tempfile.TemporaryDirectory() as folder:
            shots = self.shots(folder)
            Image.new("RGB", (40, 40), (0, 0, 255)).save(shots / "c07-menuopen.png")
            Image.new("RGB", (40, 40), (0, 255, 0)).save(shots / "dark" / "c07-menuopen.png")
            ours = Path(folder) / "ours.png"
            Image.new("RGB", (100, 80), (255, 0, 0)).save(ours)
            out = Path(folder) / "caps"
            with mock.patch.object(page_checks, "SHOTS", shots):
                light = page_checks.save_capture(ours, "menu", "c07", folder=out)
                dark = page_checks.save_capture(ours, "menu", "c07", dark=True, folder=out, label="c07-x")
            self.assertEqual(light, out / "menu" / "c07-light.png")
            self.assertEqual(dark, out / "menu" / "c07-x-dark.png")
            with Image.open(light) as sheet:
                self.assertEqual(sheet.getpixel((10, 10)), (255, 0, 0))
                self.assertEqual(sheet.getpixel((sheet.width - 5, 10)), (0, 0, 255))
            with Image.open(dark) as sheet:
                self.assertEqual(sheet.getpixel((sheet.width - 5, 10)), (0, 255, 0))

    def test_without_pil_both_files_are_kept_side_by_side(self):
        with tempfile.TemporaryDirectory() as folder:
            shots = self.shots(folder)
            (shots / "c07-menuopen.png").write_bytes(b"design")
            ours = Path(folder) / "ours.png"
            ours.write_bytes(b"real")
            out = Path(folder) / "caps"
            with (
                mock.patch.object(page_checks, "SHOTS", shots),
                mock.patch.dict(sys.modules, {"PIL": None}),
            ):
                dest = page_checks.save_capture(ours, "menu", "c07", folder=out)
            self.assertEqual(dest.read_bytes(), b"real")
            self.assertEqual((out / "menu" / "c07-light-design.png").read_bytes(), b"design")


if __name__ == "__main__":
    unittest.main()
