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


class HeadingPlaceTests(unittest.TestCase):
    """cui-look-4: "Open tabs" between the groups and the loose tabs."""

    LOOK3 = (CORE / "patches/157/cui-look-3.patch").read_text()

    def test_between(self):
        head, above, below = (10, 100, 200, 118), (10, 60, 200, 92), (10, 120, 200, 152)
        self.assertTrue(smoke_sidetabs.heading_between(head, above, below))
        self.assertTrue(smoke_sidetabs.heading_between(head, None, below))
        self.assertFalse(smoke_sidetabs.heading_between(head, (10, 60, 200, 105), below))
        self.assertFalse(smoke_sidetabs.heading_between(head, above, (10, 110, 200, 140)))
        self.assertFalse(smoke_sidetabs.heading_between(None, above, below))

    def test_first_rect_skips_empty(self):
        rects = [("Weather", (0, 0, 0, 0)), ("Weather", (1, 2, 3, 4))]
        self.assertEqual(smoke_sidetabs.first_rect(rects, lambda t: t == "Weather"), (1, 2, 3, 4))
        self.assertIsNone(smoke_sidetabs.first_rect(rects, lambda t: t == "x"))

    def test_heading_moved_into_the_unpinned_container(self):
        self.assertIn("boring_open_heading_ =\n+        AddChildView(std::make_unique<BoringSideTabHeading>(u\"Open tabs\"))",
                      self.LOOK3)
        self.assertIn("-    boring_open_heading_ =", self.LOOK3)
        # Always listed in the layout, shown or hidden.
        self.assertIn("boring_heading, false,", self.LOOK3)
        self.assertIn("first_loose_after_group", self.LOOK3)


class SheetTests(unittest.TestCase):
    """cui-look-4: the page in a rounded sheet, in its own last patch."""

    SHEET = CORE / "patches/157/cui-sheet.patch"

    def test_states(self):
        client = (0, 0, 1000, 800)
        self.assertEqual(smoke_sidetabs.sheet_state((260, 60, 992, 792), client, 1.0)[0], "sheet")
        self.assertEqual(smoke_sidetabs.sheet_state((260, 60, 1000, 800), client, 1.0)[0], "flush")
        self.assertEqual(smoke_sidetabs.sheet_state((260, 60, 980, 800), client, 1.0)[0], "other")
        # 8 DIP at 150 % is 12 pixels.
        self.assertEqual(smoke_sidetabs.sheet_state((390, 90, 1488, 1188), (0, 0, 1500, 1200), 1.5)[0],
                         "sheet")
        self.assertEqual(smoke_sidetabs.sheet_state(None, client, 1.0)[0], "other")

    @staticmethod
    def picture(w, h, box, radius_cut):
        """BGRA bytes: grey, with a magenta box whose four corner pixels are
        grey when radius_cut."""
        px = bytearray(b"\x80\x80\x80\xff" * (w * h))
        for y in range(box[1], box[3]):
            for x in range(box[0], box[2]):
                corner = x in (box[0], box[2] - 1) and y in (box[1], box[3] - 1)
                if not (radius_cut and corner):
                    px[(y * w + x) * 4:(y * w + x) * 4 + 4] = b"\xff\x00\xff\xff"
        return bytes(px)

    def test_colour_box_and_corners(self):
        box = (3, 2, 17, 12)
        rounded = self.picture(20, 15, box, True)
        self.assertEqual(smoke_sidetabs.colour_box(20, 15, rounded, smoke_sidetabs.MAGENTA), box)
        self.assertEqual(smoke_sidetabs.rounded_corners(20, rounded, box, smoke_sidetabs.MAGENTA, 3), 4)
        square = self.picture(20, 15, box, False)
        self.assertEqual(smoke_sidetabs.rounded_corners(20, square, box, smoke_sidetabs.MAGENTA, 3), 0)
        self.assertIsNone(smoke_sidetabs.colour_box(4, 4, b"\x00" * 64, smoke_sidetabs.MAGENTA))

    def test_top_row_tabs(self):
        client = (0, 0, 1280, 800)
        rects = [("Live1", (250, 2, 450, 36)), ("Live2 - Memory usage - 5 MB", (450, 2, 650, 36)),
                 ("Live3", (12, 120, 236, 152)), ("Other", (700, 2, 900, 36))]
        top = smoke_sidetabs.top_row_tabs(rects, ["Live1", "Live2", "Live3"], client, 1.0)
        self.assertEqual([t for t, _r in top], ["Live1", "Live2 - Memory usage - 5 MB"])
        self.assertEqual(smoke_sidetabs.top_row_tabs(rects[2:], ["Live3"], client, 1.0), [])

    def test_expected_follows_the_series(self):
        self.assertEqual(smoke_sidetabs.sheet_expected(), "cui-sheet.patch" in series())

    def test_own_patch_last_and_one_file(self):
        if "cui-sheet.patch" not in series():
            self.skipTest("cui-sheet.patch taken out of the series")
        self.assertEqual(series()[-1], "cui-sheet.patch")
        text = self.SHEET.read_text()
        files = re.findall(r"^\+\+\+ b/(\S+)", text, re.M)
        self.assertEqual(files, ["chrome/browser/ui/views/frame/layout/browser_view_tabbed_layout_impl.cc"])
        added = "\n".join(added_lines(text))
        self.assertIn("boring", added)
        # Side tabs only, never fullscreen, a side panel, split view or glass.
        for word in ("TabStripType::kVertical", "!is_fullscreen(layout_data_->window_state)",
                     "has_side_panel()", "is_split_view", "!in_glass_mode()",
                     "kBoringSheetMargin = 8", "kBoringSheetRadius = 10.0f"):
            self.assertIn(word, added, word)


class PatchTests(unittest.TestCase):
    def test_last_in_series_after_shelf(self):
        names = series()
        at = names.index("sidetabs.patch")
        self.assertEqual(names[at - 1], "shelf.patch")
        # Only later pieces' patches come after it.
        self.assertTrue(set(names[at + 1:]) <= {"earlier.patch", "cui-look-3.patch", "cui-look-5.patch", "cui-sheet.patch"},
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
