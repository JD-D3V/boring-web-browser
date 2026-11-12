"""Save all tabs (Release 4, ledger item 4): the app menu row, the tab menu
row and the command behind them, checked in the patch and source text.
smoke_save_tabs.py checks the browser.

Chromium's own "Bookmark all tabs" (Ctrl+Shift+D) saves one window only and
asks for a folder in a dialog first, so it is not what this needed; it stays
where Chromium has it, in Bookmarks and lists."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
PATCHES = CORE / "patches"
PATCH = PATCHES / "157" / "save-all-tabs.patch"
BORING = CORE / "chromium_src" / "chrome" / "browser" / "ui" / "views" / "boring"
SOURCE = BORING / "boring_save_tabs.cc"
HEADER = BORING / "boring_save_tabs.h"
SRC = Path(os.environ.get("BORING_SRC_157", r"E:\ung-157\build\src"))
COMMAND_IDS = SRC / "chrome" / "app" / "chrome_command_ids.h"
ROW = "Save all tabs"
ID = 40309


def added(text):
    return "\n".join(
        line[1:]
        for line in text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def hunks_for(text, path):
    """The added lines of the patch for one file."""
    parts = re.split(r"^diff --git ", text, flags=re.M)
    for part in parts:
        if part.startswith(f"a/{path} "):
            return added(part)
    return ""


class SaveAllTabsPatchTest(unittest.TestCase):
    def setUp(self):
        self.patch = PATCH.read_text(encoding="utf-8")
        self.source = SOURCE.read_text(encoding="utf-8")

    def test_in_series_after_forget_session(self):
        series = (PATCHES / "series").read_text(encoding="utf-8").split()
        self.assertIn("save-all-tabs.patch", series)
        # Its context is the forget-session id line.
        self.assertLess(
            series.index("forget-session.patch"), series.index("save-all-tabs.patch")
        )

    def test_command_id_is_ours_alone(self):
        ids = hunks_for(self.patch, "chrome/app/chrome_command_ids.h")
        self.assertIn(f"#define IDC_BORING_SAVE_ALL_TABS {ID}", ids)
        # No other patch of ours takes the number.
        for p in PATCHES.rglob("*.patch"):
            if p.name != PATCH.name:
                self.assertNotIn(str(ID), p.read_text(encoding="utf-8"), p.name)

    @unittest.skipUnless(COMMAND_IDS.is_file(), "no Chromium 157 tree")
    def test_command_id_is_free_in_chromium_157(self):
        text = COMMAND_IDS.read_text(encoding="utf-8")
        taken = re.findall(rf"^#define\s+(\w+)\s+{ID}\b", text, re.M)
        self.assertEqual(taken, [])
        self.assertNotIn("IDC_BORING_SAVE_ALL_TABS", text)

    def test_app_menu_row(self):
        menu = hunks_for(self.patch, "chrome/browser/ui/toolbar/app_menu_model.cc")
        self.assertIn(f'AddItemWithIcon(IDC_BORING_SAVE_ALL_TABS, u"{ROW}"', menu)

    def test_command_runs_and_is_enabled_like_bookmarking(self):
        ctl = hunks_for(self.patch, "chrome/browser/ui/browser_command_controller.cc")
        self.assertIn("case IDC_BORING_SAVE_ALL_TABS:", ctl)
        self.assertIn("boring::SaveAllTabs(browser_);", ctl)
        self.assertIn(
            "UpdateCommandEnabled(IDC_BORING_SAVE_ALL_TABS,\n"
            "                                         CanBookmarkCurrentTab(browser_));",
            ctl,
        )

    def test_tab_menu_row_goes_to_the_browser(self):
        tab = hunks_for(
            self.patch, "chrome/browser/ui/views/tabs/tab/tab_context_menu_controller.cc"
        )
        self.assertIn(f'AddItem(IDC_BORING_SAVE_ALL_TABS, u"{ROW}")', tab)
        self.assertIn("chrome::ExecuteCommand(window, IDC_BORING_SAVE_ALL_TABS)", tab)
        # Checked, enabled, alerted and execute each answer for our id before
        # the id is cast to a tab strip command it is not.
        self.assertEqual(tab.count("if (command_id == IDC_BORING_SAVE_ALL_TABS)"), 4)

    def test_build_files(self):
        toolbar = hunks_for(self.patch, "chrome/browser/ui/views/toolbar/BUILD.gn")
        self.assertIn('"../boring/boring_save_tabs.cc"', toolbar)
        self.assertIn('"../boring/boring_save_tabs.h"', toolbar)
        self.assertIn('"//chrome/common:url_constants"', toolbar)
        tab = hunks_for(self.patch, "chrome/browser/ui/views/tabs/tab/BUILD.gn")
        self.assertIn('"//chrome/app:command_ids"', tab)
        self.assertIn('"//chrome/browser/ui:browser_commands"', tab)

    def test_what_it_saves(self):
        s = self.source
        # Every ordinary window of the same profile, into a new folder under
        # Other bookmarks named for the date and time.
        self.assertIn("GlobalBrowserCollection::GetInstance()->ForEach", s)
        self.assertIn("window->GetProfile() == profile", s)
        self.assertIn("BrowserWindowInterface::TYPE_NORMAL", s)
        self.assertIn("model->other_node()", s)
        self.assertIn('u"Tabs " + base::TimeFormatShortDateAndTime(when)', s)
        self.assertIn('u"Window " + base::NumberToString16(w + 1)', s)
        # New tab pages and blank tabs are not saved.
        self.assertIn("IsAboutBlank()", s)
        self.assertIn("chrome::kChromeUINewTabURL", s)
        # Enter closes the note; it never opens anything by itself.
        self.assertIn("OverrideDefaultButton(ui::mojom::DialogButton::kCancel)", s)

    def test_plain_words(self):
        for text in (self.patch, self.source, HEADER.read_text(encoding="utf-8")):
            self.assertNotIn("\u2014", text)
        for words in ('u"Tabs saved"', 'SetLabel(u"Show")', 'SetLabel(u"Done")'):
            self.assertIn(words, self.source)
        self.assertLessEqual(len(ROW.split()), 3)


@unittest.skipUnless(
    COMMAND_IDS.is_file() and shutil.which("git"), "no Chromium 157 tree or git"
)
class SaveAllTabsAppliesTest(unittest.TestCase):
    """git apply --check against copies of the 157 tree's files, which carry
    the rest of the series. Writes only to a temporary folder."""

    def test_applies_to_the_157_tree(self):
        files = re.findall(r"^\+\+\+ b/(\S+)", PATCH.read_text(encoding="utf-8"), re.M)
        with tempfile.TemporaryDirectory(prefix="save-tabs-") as tmp:
            for rel in files:
                dst = Path(tmp) / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(SRC / rel, dst)
            def check(*extra):
                return subprocess.run(
                    ["git", "apply", "--check", *extra, str(PATCH)],
                    cwd=tmp,
                    capture_output=True,
                    text=True,
                )

            done = check()
            # A tree apply.py has already patched takes it in reverse.
            if done.returncode != 0:
                done = check("-R")
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
