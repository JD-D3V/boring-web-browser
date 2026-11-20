"""The Shelf (ledger item 15): the pure parts of smoke_shelf.py, and checks on
the patch and overlay files that need no browser."""

import re
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
CORE = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import smoke_shelf  # noqa: E402

PATCHES = CORE / "patches/157"
SHELF_PATCH = PATCHES / "shelf.patch"
OVERLAY = [
    *(CORE / "chromium_src/chrome/browser/ui/views/side_panel/boring_shelf").glob("*.*"),
    CORE / "chromium_src/chrome/browser/ui/views/frame/boring_shelf_toggle.cc",
    CORE / "chromium_src/chrome/browser/ui/views/frame/boring_shelf_toggle.h",
]


def series():
    return [ln.strip() for ln in (CORE / "patches/series").read_text().splitlines() if ln.strip()]


class ShelfStateTests(unittest.TestCase):
    NAMES = [smoke_shelf.TOGGLE, smoke_shelf.PANE, "Pinned", "Local Library", "Local News",
             "Saved and downloaded", smoke_shelf.FILE_NAME]

    def test_everything_present(self):
        state = smoke_shelf.shelf_state(self.NAMES, ["Local Library", "Local News"], smoke_shelf.FILE_NAME)
        self.assertTrue(all([state["toggle"], state["pane"], state["pinned_heading"], state["saved_heading"],
                             state["file"]]))
        self.assertEqual(state["tiles"], ["Local Library", "Local News"])
        self.assertFalse(state["earlier_heading"])

    def test_missing_tile_is_missing(self):
        state = smoke_shelf.shelf_state(["Pinned", "Local News"], ["Local Library", "Local News"])
        self.assertEqual(state["tiles"], ["Local News"])
        self.assertFalse(state["toggle"])
        self.assertFalse(state["file"])

    def test_no_file_asked_means_no_file(self):
        self.assertFalse(smoke_shelf.shelf_state(self.NAMES, [])["file"])


class PatchTests(unittest.TestCase):
    def test_shelf_patch_follows_passport_and_precedes_side_tabs(self):
        names = series()
        # Side tabs (item 14) go right after the Shelf; Earlier tabs (item 16)
        # come after them.
        self.assertEqual(names[-3:], ["shelf.patch", "sidetabs.patch", "earlier.patch"])
        self.assertLess(names.index("passport.patch"), names.index("shelf.patch"))
        self.assertTrue(SHELF_PATCH.exists())

    def test_command_id_is_in_the_shelf_block(self):
        text = SHELF_PATCH.read_text()
        added = "\n".join(ln for ln in text.splitlines() if ln.startswith("+"))
        ids = re.findall(r"#define IDC_BORING_\w+ (\d+)", added)
        self.assertEqual(ids, ["40320"])
        self.assertTrue(40320 <= int(ids[0]) <= 40329)

    def test_every_color_id_is_declared_defined_and_used(self):
        patch = SHELF_PATCH.read_text()
        declared = set(re.findall(r"E_CPONLY\((kColorBoringShelf\w+)\)", patch))
        mixer = (CORE / "chromium_src/chrome/browser/ui/color/boring_color_mixer.cc").read_text()
        for name in declared:
            self.assertGreaterEqual(mixer.count(f"[{name}]"), 2, f"{name}: mixer sets it under any theme and ours")
        self.assertEqual(len(declared), 8)

    def test_every_chromium_hunk_is_marked(self):
        added = [ln[1:] for ln in SHELF_PATCH.read_text().splitlines() if ln.startswith("+") and not ln.startswith("+++")]
        self.assertTrue(any("boring:" in ln for ln in added))
        # Each changed file's added block carries the marker.
        for chunk in SHELF_PATCH.read_text().split("diff --git ")[1:]:
            plus = "\n".join(ln for ln in chunk.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
            self.assertIn("boring", plus, chunk.splitlines()[0])


class WordsTests(unittest.TestCase):
    def test_no_em_dash_and_no_browser_name_in_what_people_see(self):
        for path in OVERLAY:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("—", text, path.name)
            for literal in re.findall(r'u"([^"]*)"', text):
                self.assertNotRegex(literal, r"(?i)chrom(e|ium)", f"{path.name}: {literal}")

    def test_the_words_match_the_design(self):
        text = "".join(p.read_text(encoding="utf-8") for p in OVERLAY if p.suffix == ".cc")
        for words in ("Show or hide the Shelf", "The Shelf", "Pinned", "Groups", "Earlier", "kept 30 days",
                      "Saved and downloaded", "Read later", "Today", "Show all "):
            self.assertIn(f'u"{words}', text)


if __name__ == "__main__":
    unittest.main()
