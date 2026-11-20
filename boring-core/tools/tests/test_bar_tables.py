"""The Bar's two tables (boring_bar_provider.cc, boring_bar_run.cc) and the
pure parts of smoke_bar.py, without a browser."""

import re
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
CORE = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import smoke_bar  # noqa: E402

PROVIDER = CORE / "chromium_src/chrome/browser/autocomplete/boring_bar_provider.cc"
RUNNER = CORE / "chromium_src/chrome/browser/ui/omnibox/boring_bar_run.cc"
PATCHES = CORE / "patches/157"
TREE = Path(r"E:\ung-157\build\src")
ROUTES = TREE / "chrome/browser/resources/settings/route.ts"
COMMAND_IDS = TREE / "chrome/app/chrome_command_ids.h"

BANNED = re.compile(r"\bchrom(e|ium)\b|google|\u2014|\u2013", re.IGNORECASE)
# The glyphs the results page may show (unit 6 maps each to an SVG).
GLYPHS = {"moon", "plus", "win", "priv", "clock", "down", "print", "find", "zoom",
          "trash", "erase", "sliders", "tab"}  # fmt: skip
DO_ROW = re.compile(r'\{"(\w+)",\s*u"([^"]*)",\s*u"([^"]*)",\s*"(\w+)",\s*(true|false)\}')
SETTINGS_ROW = re.compile(r'\{u"([^"]*)",\s*u"([^"]*)",\s*"([^"]+)"\}')
COMMAND = re.compile(r'\{"(\w+)",\s*(IDC_\w+)\}')


def do_rows():
    return DO_ROW.findall(PROVIDER.read_text(encoding="utf-8"))


def settings_rows():
    return SETTINGS_ROW.findall(PROVIDER.read_text(encoding="utf-8"))


def commands():
    return COMMAND.findall(RUNNER.read_text(encoding="utf-8"))


class Tables(unittest.TestCase):
    def test_tables_parse(self):
        self.assertGreaterEqual(len(do_rows()), 14)  # the table plus dark and light
        self.assertGreaterEqual(len(settings_rows()), 10)
        self.assertGreaterEqual(len(commands()), 12)

    def test_every_do_row_runs_a_command(self):
        rows = {r[0] for r in do_rows()} - {"dark", "light"}
        self.assertEqual(rows, {c[0] for c in commands()})

    def test_only_dark_and_light_take_enter(self):
        takes = {r[0] for r in do_rows() if r[4] == "true"}
        self.assertEqual(takes, {"dark", "light"})

    def test_glyphs_are_known(self):
        used = {r[3] for r in do_rows()}
        self.assertLessEqual(used, GLYPHS, used - GLYPHS)

    def test_text_is_plain(self):
        texts = [t for r in do_rows() for t in r[1:3]] + [t for r in settings_rows() for t in r[:2]]
        bad = [t for t in texts if BANNED.search(t)]
        self.assertEqual(bad, [])
        self.assertTrue(all(t == t.strip() and t for t in texts))

    def test_settings_rows_are_local_pages(self):
        for title, _, url in settings_rows():
            self.assertRegex(url, r"^chrome://(settings/[a-z]+|password-manager)$", title)

    @unittest.skipUnless(ROUTES.is_file(), "no 157 tree")
    def test_settings_routes_exist(self):
        text = ROUTES.read_text(encoding="utf-8")
        for patch in PATCHES.glob("*.patch"):
            text += patch.read_text(encoding="utf-8", errors="replace")
        paths = set(re.findall(r"createSection\(\s*'(/[a-z-]+)'", text))
        for title, _, url in settings_rows():
            if url.startswith("chrome://settings/"):
                self.assertIn("/" + url.rsplit("/", 1)[1], paths, title)

    @unittest.skipUnless(COMMAND_IDS.is_file(), "no 157 tree")
    def test_commands_exist(self):
        text = COMMAND_IDS.read_text(encoding="utf-8")
        for patch in PATCHES.glob("*.patch"):
            text += patch.read_text(encoding="utf-8", errors="replace")
        for row_id, name in commands():
            self.assertRegex(text, rf"#define {name}\b", row_id)


class SmokeHelpers(unittest.TestCase):
    REPORT = (
        "row\tDo\tTurn on dark mode\t\tselected\n"
        "row\tOpen tabs\t<b>Turn on dark mode</b>\tSwitch to tab\t-\n"
        "row\tSettings\tAppearance: light or dark\tOpen\t-\n"
        "row\tSearch\tdark\tDuckDuckGo Search\t-\n"
        "row\t\texample.com\t\t-\n"
        "state\tctrl+k\tfocused=yes\tall_selected=yes\tkeyword=no\ttext=a=b\thint=Esc to close\n"
        "after\tfield=\turl=about:blank\n"
        "end\n"
    )

    def test_parse_report(self):
        report = smoke_bar.parse_report(self.REPORT)
        self.assertEqual(report["rows"][0], ("Do", "Turn on dark mode", "", True))
        self.assertEqual(report["state"]["ctrl+k"]["text"], "a=b")
        self.assertEqual(report["state"]["ctrl+k"]["hint"], "Esc to close")
        self.assertEqual(report["after"], {"field": "", "url": "about:blank"})

    def test_unfinished_report_is_none(self):
        self.assertIsNone(smoke_bar.parse_report(self.REPORT.replace("end\n", "")))

    def test_group_order_and_under(self):
        rows = smoke_bar.parse_report(self.REPORT)["rows"]
        self.assertEqual(smoke_bar.group_order(rows), smoke_bar.GROUPS)
        self.assertEqual(smoke_bar.under(rows, smoke_bar.HOSTILE), ["Open tabs"])

    def test_net_log_hosts(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "log.json"
            path.write_text('{"params":{"url":"http://127.0.0.1:5/weather"}},'
                            '{"params":{"url":"https://example.com/"}}', encoding="utf-8")
            self.assertEqual(smoke_bar.net_log_hosts(path), ["127.0.0.1", "example.com"])
        self.assertIsNone(smoke_bar.net_log_hosts(Path(folder) / "missing.json"))


if __name__ == "__main__":
    unittest.main()
