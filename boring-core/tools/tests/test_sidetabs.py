"""Side tabs in the Shelf (ledger item 14), and the Shelf's pinned tile mark
(item 15): the pure part of smoke_sidetabs.py, and checks on the patch and
overlay files that need no browser."""

import re
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
CORE = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import smoke_sidetabs  # noqa: E402

PATCH = CORE / "patches/157/sidetabs.patch"
SRC = CORE / "chromium_src/chrome/browser/ui/views"
OVERLAY = [
    SRC / "tabs/common/boring_side_tab_heading.h",
    SRC / "tabs/common/boring_side_tab_heading.cc",
    SRC / "tabs/vertical/boring_new_tab_row.h",
    SRC / "tabs/vertical/boring_new_tab_row.cc",
]
SHELF = SRC / "side_panel/boring_shelf"


def series():
    return [ln.strip() for ln in (CORE / "patches/series").read_text().splitlines() if ln.strip()]


def added_lines(text):
    return [ln[1:] for ln in text.splitlines() if ln.startswith("+") and not ln.startswith("+++")]


class StateTests(unittest.TestCase):
    NAMES = [smoke_sidetabs.TOGGLE, "Open tabs", "New tab", "Weather"]

    def test_everything_present(self):
        s = smoke_sidetabs.side_tabs_state(self.NAMES)
        self.assertTrue(s["toggle"] and s["open_heading"] and s["new_tab"])
        self.assertFalse(s["pinned_heading"])
        self.assertFalse(s["tab_search"])

    def test_tab_search_is_noticed(self):
        s = smoke_sidetabs.side_tabs_state(self.NAMES + ["Search tabs"])
        self.assertTrue(s["tab_search"])

    def test_top_tabs_have_no_heading(self):
        s = smoke_sidetabs.side_tabs_state([smoke_sidetabs.TOGGLE, "Weather"])
        self.assertFalse(s["open_heading"])


class PatchTests(unittest.TestCase):
    def test_last_in_series_after_shelf(self):
        names = series()
        at = names.index("sidetabs.patch")
        self.assertEqual(names[at - 1], "shelf.patch")
        # Only later pieces' patches come after it.
        self.assertTrue(set(names[at + 1:]) <= {"earlier.patch", "cui-look-3.patch"},
                        names[at + 1:])

    def test_top_tabs_stay_the_default(self):
        text = PATCH.read_text()
        self.assertNotIn("kVerticalTabsEnabled", text)
        self.assertNotIn("tab_strip_prefs", text)

    def test_every_changed_file_is_marked(self):
        for chunk in PATCH.read_text().split("diff --git ")[1:]:
            name = chunk.split(" ", 1)[0]
            self.assertIn("boring", "\n".join(added_lines(chunk)).lower(), name)

    def test_no_new_command_id(self):
        self.assertNotIn("chrome_command_ids.h", PATCH.read_text())

    def test_visible_words(self):
        files = [PATCH, *OVERLAY]
        for f in files:
            text = f.read_text()
            self.assertNotIn("—", text, f.name)
            self.assertNotIn("–", text, f.name)
        # Strings a person reads: the quoted text of added lines.
        for f in [*OVERLAY, PATCH]:
            for ln in (added_lines(f.read_text()) if f == PATCH else f.read_text().splitlines()):
                for lit in re.findall(r'u"([^"]*)"', ln):
                    self.assertNotRegex(lit, r"(?i)chrom", f"{f.name}: {lit}")

    def test_no_network(self):
        for f in OVERLAY:
            text = f.read_text()
            for word in ("URLLoader", "SimpleURLLoader", "NetworkContext", "http://", "https://"):
                self.assertNotIn(word, text, f.name)

    def test_sizes_from_the_design(self):
        text = PATCH.read_text()
        self.assertIn("kVerticalTabStripDefaultUncollapsedWidth = 248", text)
        self.assertIn("return 32;", text)  # tab row
        self.assertIn("return 40;", text)  # pinned tile
        self.assertIn("kTabPadding = 6", text)

    def test_names(self):
        row = (SRC / "tabs/vertical/boring_new_tab_row.cc").read_text()
        self.assertIn('u"New tab"', row)
        self.assertIn("GetAcceleratorForCommandId", row)  # not a typed shortcut
        self.assertNotIn("Ctrl", row)
        self.assertIn("Show or hide the Shelf", PATCH.read_text())
        self.assertIn('u"Open tabs"', PATCH.read_text())
        self.assertIn('u"Pinned"', PATCH.read_text())

    def test_toggle_routes_to_the_collapse_command(self):
        text = (SHELF / "boring_shelf_coordinator.cc").read_text()
        self.assertIn("IDC_TOGGLE_VERTICAL_TABS_COLLAPSE", text)
        self.assertIn("kVerticalTabsEnabled", text)


class PinnedTileMarkTests(unittest.TestCase):
    """Item 15: the tile shows the letter the new tab page shows."""

    def test_tile_takes_a_mark_not_the_link_glyph(self):
        data = (SHELF / "shelf_data.cc").read_text()
        self.assertIn("item.mark = TileMark(item.title)", data)
        view = (SHELF / "boring_shelf_view.cc").read_text()
        self.assertIn("items[i].mark, items[i].title", view)
        row = (SHELF / "shelf_row.cc").read_text()
        self.assertIn("views::Label>(mark)", row)

    def test_same_fallbacks_as_the_new_tab_page(self):
        data = (SHELF / "shelf_data.cc").read_text()
        # '?' when there is no name, and upper case, as charAt(0).toUpperCase().
        self.assertIn('u"?"', data)
        self.assertIn("base::i18n::ToUpper", data)
        page = (CORE / "components/boring/newtab/newtab_ui.cc").read_text()
        self.assertIn("(name || '?').charAt(0).toUpperCase()", page)


if __name__ == "__main__":
    unittest.main()
