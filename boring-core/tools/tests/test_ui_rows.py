"""Protection page rows share one vertical rhythm; the empty bookmarks
bar hint patch is in the series."""
import pathlib
import re
import unittest

CORE = pathlib.Path(__file__).resolve().parents[2]


class ProtectionRows(unittest.TestCase):
    def test_rows_use_one_padding(self):
        css = (CORE / "components/boring/protection/protection_ui.cc").read_text(
            encoding="utf-8")
        rows = re.findall(
            r"\.(?:state-row|setting-row|regional|choice)\s*\{[^}]*?"
            r"padding:\s*([^;]+);", css)
        self.assertGreaterEqual(len(rows), 4)
        self.assertEqual({"16px 0"}, set(rows))


class BookmarkBarHint(unittest.TestCase):
    def test_patch_listed_after_bookmark_bar(self):
        series = (CORE / "patches/series").read_text().split()
        self.assertLess(series.index("bookmark-bar.patch"),
                        series.index("bookmark-bar-hint.patch"))
        self.assertTrue((CORE / "patches/bookmark-bar-hint.patch").exists())


if __name__ == "__main__":
    unittest.main()
