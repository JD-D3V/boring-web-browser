"""Earlier tabs (ledger item 16): the pure part of smoke_earlier.py, and checks
on the patch, the overlay files and the safety rules that need no browser."""

import json
import re
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
CORE = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import smoke_earlier  # noqa: E402

PATCH = CORE / "patches/157/earlier.patch"
VIEWS = CORE / "chromium_src/chrome/browser/ui/views"
SERVICE = (VIEWS / "boring/boring_earlier_tabs_service.cc").read_text(encoding="utf-8")
SERVICE_H = (VIEWS / "boring/boring_earlier_tabs_service.h").read_text(encoding="utf-8")
STORE = (CORE / "components/boring/earlier/earlier_store.cc").read_text(encoding="utf-8")
STORE_H = (CORE / "components/boring/earlier/earlier_store.h").read_text(encoding="utf-8")
PREFS = (CORE / "components/boring/core/boring_prefs.cc").read_text(encoding="utf-8")
WELCOME = (CORE / "components/boring/welcome/welcome_ui.cc").read_text(encoding="utf-8")


def series():
    return [ln.strip() for ln in (CORE / "patches/series").read_text().splitlines() if ln.strip()]


class HelperTests(unittest.TestCase):
    def test_entry_round_trips_through_the_file_text(self):
        e = smoke_earlier.make_entry("a", "https://x.example/", 1700000000000)
        entries = smoke_earlier.parse_file(smoke_earlier.file_text([e]))
        self.assertEqual(entries[0]["id"], "a")
        self.assertEqual(entries[0]["moved"], "1700000000000")

    def test_parse_refuses_what_is_not_ours(self):
        self.assertIsNone(smoke_earlier.parse_file("not json"))
        self.assertIsNone(smoke_earlier.parse_file("[]"))
        self.assertIsNone(smoke_earlier.parse_file(json.dumps({"version": 1})))

    def test_web_only(self):
        good = smoke_earlier.make_entry("a", "http://x.example/", 1)
        bad = smoke_earlier.make_entry("b", "chrome://version", 1)
        self.assertTrue(smoke_earlier.web_only([good]))
        self.assertFalse(smoke_earlier.web_only([good, bad]))

    def test_chip_count_reads_the_chip_name(self):
        self.assertEqual(smoke_earlier.chip_count(["New tab", "Earlier 23"]), 23)
        self.assertIsNone(smoke_earlier.chip_count(["Earlier tabs", "Earlier"]))
        self.assertIsNone(smoke_earlier.chip_count([]))

    def test_seeded_prefs_default_to_off(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            smoke_earlier.seed_prefs(tmp, False)
            off = json.loads((Path(tmp) / "Default" / "Preferences").read_text())
            smoke_earlier.seed_prefs(tmp, True)
            on = json.loads((Path(tmp) / "Default" / "Preferences").read_text())
        self.assertEqual(off, {})
        self.assertTrue(on["boring"]["earlier"]["enabled"])


class PatchTests(unittest.TestCase):
    def test_last_in_series(self):
        names = series()
        # Only the look round's patches may come after it.
        self.assertTrue(set(names[names.index("earlier.patch") + 1:]) <= {"cui-look-3.patch", "cui-look-5.patch", "cui-sheet.patch"},
                        names[names.index("earlier.patch") + 1:])
        self.assertTrue(PATCH.exists())

    def test_command_ids_are_in_our_block_and_free(self):
        added = "\n".join(ln for ln in PATCH.read_text().splitlines() if ln.startswith("+"))
        ids = re.findall(r"#define IDC_BORING_\w+ (\d+)", added)
        self.assertEqual(ids, ["40321", "40322"])

    def test_every_chromium_hunk_is_marked(self):
        text = PATCH.read_text()
        self.assertIn("boring:", text)
        # Each file's added lines carry a boring comment somewhere.
        for chunk in text.split("diff --git ")[1:]:
            added = "\n".join(ln for ln in chunk.splitlines() if ln.startswith("+"))
            self.assertIn("boring", added, chunk.splitlines()[0])

    def test_settings_allowlist_names_the_pref(self):
        self.assertIn('boring.earlier.enabled', PATCH.read_text())


class LookTests(unittest.TestCase):
    def test_popup_rows_and_show_all_are_drawn_to_the_design(self):
        # Window.dc.html: rows 34 high with a 12px gap, "Show all" weight 500.
        popup = (VIEWS / "boring/boring_earlier_popup.cc").read_text(encoding="utf-8")
        self.assertIn("kRowHeight = 34;", popup)
        self.assertIn("kRowGap = 12;", popup)
        self.assertIn("kRowHeight, kRowGap", popup)
        show_all = popup[popup.index("OnShowAll,"):]
        self.assertIn("gfx::Font::Weight::MEDIUM", show_all[:300])
        # The Shelf's own rows keep 32 and 10.
        row_h = (VIEWS / "side_panel/boring_shelf/shelf_row.h").read_text(encoding="utf-8")
        self.assertIn("kHeight = 32;", row_h)
        self.assertIn("kGap = 10;", row_h)


class SideSectionTests(unittest.TestCase):
    """Side tabs (screen C09): the Earlier section in the list (cui-look-4)."""

    SECTION = (VIEWS / "boring/boring_side_earlier_section.cc").read_text(encoding="utf-8")
    LOOK3 = (CORE / "patches/157/cui-look-3.patch").read_text(encoding="utf-8")

    def test_names_say_what_the_section_shows(self):
        names = ["Earlier", "kept 30 days", "Soup", "Show all 3", "Open tabs"]
        s = smoke_earlier.side_section(names, ["Soup", "Gone"])
        self.assertTrue(s["shown"])
        self.assertEqual(s["rows"], ["Soup"])
        self.assertEqual(s["show_all"], "Show all 3")
        none = smoke_earlier.side_section(["Open tabs", "Earlier 3"], ["Soup"])
        self.assertFalse(none["shown"])
        self.assertEqual(none["rows"], [])

    def test_side_prefs_turn_side_tabs_on(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            smoke_earlier.seed_side_prefs(tmp, False)
            prefs = json.loads((Path(tmp) / "Default" / "Preferences").read_text())
        self.assertTrue(prefs["vertical_tabs"]["enabled"])
        self.assertFalse(prefs["boring"]["earlier"]["enabled"])

    def test_reuses_the_shelf_and_the_service(self):
        for piece in ("ShelfSectionHeading", "ShelfRow", "GetEarlierState", "ShowAllText",
                      "AddObserver(this)", "->Reopen(id, browser_)"):
            self.assertIn(piece, self.SECTION, piece)
        self.assertIn('u"Earlier", u"kept 30 days"', self.SECTION)
        # Show all runs the existing command; with side tabs it opens the section out.
        self.assertIn("IDC_BORING_EARLIER_SHOW_ALL", self.SECTION)
        coord = (VIEWS / "side_panel/boring_shelf/boring_shelf_coordinator.cc").read_text(encoding="utf-8")
        self.assertIn("BoringSideEarlierSection::ShowAllFor(browser)", coord)
        chip = (VIEWS / "boring/boring_earlier_chip.cc").read_text(encoding="utf-8")
        self.assertIn("BoringSideEarlierSection::RevealFor(browser_)", chip)

    def test_only_when_on_with_tabs_and_wide(self):
        self.assertIn("!state.enabled || state.total == 0", self.SECTION)
        self.assertIn("boring::prefs::kEarlierEnabled", self.SECTION)
        self.assertIn("RegisterOnCollapseChanged", self.SECTION)
        self.assertIn("TYPE_NORMAL", self.SECTION)

    def test_placed_above_the_new_tab_row(self):
        self.assertIn("std::make_unique<BoringSideEarlierSection>", self.LOOK3)
        self.assertIn("GetIndexOf(bottom_button_container_)", self.LOOK3)
        self.assertIn('"../boring/boring_side_earlier_section.cc"', self.LOOK3)


class SafetyTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertRegex(PREFS, r"RegisterBooleanPref\(prefs::kEarlierEnabled, false\)")

    def test_nothing_moves_while_off(self):
        self.assertRegex(SERVICE, r"!IsEnabled\(\)\s*\|\|\s*read_only_")

    def test_only_regular_profiles_get_a_service(self):
        for needle in ("IsOffTheRecord()", "IsGuestSession()", "IsRegularProfile()"):
            self.assertIn(needle, SERVICE.split("EarlierTabsService* EarlierTabsService::Get")[1][:400])

    def test_write_first_close_second(self):
        # The tab is closed in OnMoveWritten only, never in Check().
        check = SERVICE.split("void EarlierTabsService::Check()")[1].split("void EarlierTabsService::OnMoveWritten")[0]
        self.assertNotIn("CloseWebContentsAt", check)
        self.assertIn("CloseWebContentsAt", SERVICE.split("void EarlierTabsService::OnMoveWritten")[1])
        self.assertIn("WriteFileAtomically", SERVICE)

    def test_no_recently_closed_record(self):
        self.assertIn("TabCloseTypes::CLOSE_NONE", SERVICE)
        self.assertNotIn("CLOSE_CREATE_HISTORICAL_TAB", SERVICE)

    def test_uses_chromiums_discard_rules_and_skips_pinned_and_grouped(self):
        self.assertIn("CanDiscardWithCustomRecentVisibilityWindow", SERVICE)
        for needle in ("IsTabPinned", "GetTabGroupForTab", "IsSplit", "NeedToFireBeforeUnload"):
            self.assertIn(needle, SERVICE)

    def test_only_web_addresses_are_kept_or_reopened(self):
        self.assertIn("SchemeIsHTTPOrHTTPS", STORE)
        self.assertGreaterEqual(SERVICE.count("IsKeepableUrl"), 3)

    def test_a_newer_file_is_never_written(self):
        self.assertIn("read_only_ = true", SERVICE)
        write = SERVICE.split("void EarlierTabsService::WriteList")[1][:300]
        self.assertIn("read_only_", write)

    def test_history_deletions_remove_entries(self):
        self.assertIn("OnHistoryDeletions", SERVICE)
        self.assertIn("IsAllHistory", SERVICE)

    def test_no_network(self):
        for text in (SERVICE, STORE):
            self.assertNotRegex(text, r"URLLoader|SimpleURLLoader|network::|HttpRequest")

    def test_test_switches_only_shorten_timers(self):
        for name in ("idle", "keep", "check", "settle"):
            self.assertIn(f"boring-earlier-{name}-seconds", STORE_H)
        # No switch turns the feature on or seeds entries.
        self.assertNotIn("test-seed", STORE_H + SERVICE)

    def test_first_run_offers_it_and_preselects_nothing(self):
        self.assertIn("earlier-on", WELCOME)
        self.assertIn("kEarlierEnabled", WELCOME)

    def test_clear_asks_first(self):
        popup = (VIEWS / "boring/boring_earlier_popup.cc").read_text(encoding="utf-8")
        self.assertIn("The pages stay in your history.", popup)
        self.assertIn("OnAskClear", popup)

    def test_no_em_dashes_or_browser_names_in_strings(self):
        for p in (VIEWS / "boring").glob("boring_earlier_*"):
            text = p.read_text(encoding="utf-8")
            self.assertNotIn("—", text, p.name)
            for line in text.splitlines():
                if '"' in line and not line.strip().startswith("//"):
                    self.assertNotRegex(line, r'u?"[^"]*\b(Chrome|Chromium)\b[^"]*"', p.name)


class PromiseTests(unittest.TestCase):
    """Item 54: the 30-day and deletion promises."""

    def deletions(self):
        at = SERVICE.index("void EarlierTabsService::OnHistoryDeletions(")
        return SERVICE[at:SERVICE.index("void EarlierTabsService::HistoryServiceBeingDeleted(")]

    def test_history_deletion_checks_the_back_and_forward_list(self):
        body = self.deletions()
        self.assertIn("e.navigations", body)
        self.assertIn("deleted(nav.url)", body)

    def test_corrupt_file_is_deleted_never_kept(self):
        self.assertNotIn("base::Move(", SERVICE)
        self.assertNotIn("MoveAside", SERVICE + SERVICE_H)
        clear = SERVICE[SERVICE.index("void EarlierTabsService::ClearAll()"):]
        self.assertIn("DeleteFiles", clear[:clear.index("\n}\n")])
        self.assertIn("DeleteFiles", self.deletions())
        read = SERVICE[SERVICE.index("EarlierTabsService::ReadFile("):]
        self.assertIn('AddExtension(FILE_PATH_LITERAL("bad"))', read[:read.index("\n}\n")])

    def test_clear_all_before_the_file_is_read_is_kept(self):
        self.assertIn("clear_when_loaded_ = true", self.deletions())
        self.assertIn("if (clear_when_loaded_)", SERVICE)

    def test_switches_only_shorten_and_future_times_expire(self):
        for name in ("idle", "keep", "check", "settle"):
            self.assertIn(f"limits.{name} = std::min(limits.{name}, ", STORE)
        self.assertRegex(STORE, r"e\.moved > now \|\| e\.last_used > now")

    def test_no_credentials_are_kept(self):
        self.assertIn("ClearPassword()", STORE)
        self.assertIn("WithoutCredentials(GURL(*url_text))", STORE)
        self.assertIn("WithoutCredentials(contents->GetLastCommittedURL())", SERVICE)
        self.assertIn("WithoutCredentials(nav->GetURL())", SERVICE)


if __name__ == "__main__":
    unittest.main()
