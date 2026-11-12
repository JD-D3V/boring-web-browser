"""Where the download site sends reports (Release 4, security review T60).

No page shows a personal email address or a mailto link. Ordinary problems
go to GitHub issues; security problems go to GitHub's private
vulnerability reporting. Nothing here needs a browser.
"""

import re
import unittest
from pathlib import Path

SITE = Path(__file__).resolve().parents[3] / "docs" / "download"
ADVISORY = "https://github.com/JD-D3V/boring-web-browser/security/advisories/new"
ISSUES = "https://github.com/JD-D3V/boring-web-browser/issues"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")


def site_files():
    return [p for p in SITE.rglob("*") if p.suffix in (".html", ".js", ".txt", ".xml")]


class ReportChannels(unittest.TestCase):
    def test_site_is_there(self):
        self.assertTrue((SITE / "report.html").is_file())

    def test_no_page_shows_an_email_address_or_mailto(self):
        for path in site_files():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("mailto:", text, path.name)
            self.assertIsNone(EMAIL.search(text), f"{path.name}: {EMAIL.search(text)}")

    def test_security_page_names_the_private_channel(self):
        text = (SITE / "security-fixes.html").read_text(encoding="utf-8")
        self.assertIn(f'href="{ADVISORY}"', text)
        self.assertNotIn("by email", text)

    def test_report_form_opens_github(self):
        html = (SITE / "report.html").read_text(encoding="utf-8")
        js = (SITE / "report.js").read_text(encoding="utf-8")
        self.assertIn(ISSUES, html)
        self.assertIn('id="open-issue"', html)
        self.assertIn("/issues/new?title=", js)
        self.assertIn("/security/advisories/new", js)
        # The type that goes to the private form is the one the page offers.
        self.assertIn('<option value="Security problem">', html)
        self.assertIn("'Security problem'", js)


if __name__ == "__main__":
    unittest.main()
