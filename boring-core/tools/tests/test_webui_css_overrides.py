"""Our WebUI CSS lives in components/boring/webui_css/<upstream path> and is appended
to the upstream file by the css_to_wrapper hook (webui-css-overrides.patch). An
override whose upstream file moved would silently stop applying, so check it."""

import os
import re
import unittest
from pathlib import Path

CORE = Path(__file__).resolve().parents[2]
DIR = CORE / "components" / "boring" / "webui_css"
SRC = Path(os.environ.get("BORING_SRC_157", r"E:\ung-157\build\src"))


def listed():
    text = (DIR / "overrides.gni").read_text(encoding="utf-8")
    return re.findall(r'^\s*"([^"]+\.css)",$', text, flags=re.M)


def on_disk():
    return sorted(
        p.relative_to(DIR).as_posix() for p in DIR.rglob("*.css")
    )


class WebuiCssOverrides(unittest.TestCase):
    def test_list_matches_folder(self):
        self.assertEqual(sorted(listed()), on_disk())

    def test_no_chars_that_break_the_wrapper(self):
        # The text lands inside a JS template literal.
        for rel in on_disk():
            text = (DIR / rel).read_text(encoding="utf-8")
            for bad in ("`", "\\", "${"):
                self.assertNotIn(bad, text, rel)

    @unittest.skipUnless((SRC / "chrome").exists(), "no Chromium tree (BORING_SRC_157)")
    def test_targets_exist_and_are_wrapped(self):
        for rel in listed():
            self.assertTrue((SRC / rel).exists(), "upstream file gone: " + rel)
            # css_to_wrapper only sees files in a css_files list of a BUILD.gn
            # above them; the key is that BUILD.gn's folder plus the list entry.
            d = Path(rel).parent
            found = False
            while str(d) not in ("", "."):
                gn = SRC / d / "BUILD.gn"
                entry = Path(rel).relative_to(d).as_posix()
                if gn.exists() and '"%s"' % entry in gn.read_text(encoding="utf-8"):
                    found = True
                    break
                d = d.parent
            self.assertTrue(found, "not in any css_files list: " + rel)


if __name__ == "__main__":
    unittest.main()
