#!/usr/bin/env python3
"""Check importing bookmarks, history and search engines from Chrome.

Builds a made up Chrome "User Data" folder under E:\\tmp (Local State,
two profiles, a Bookmarks file, a History database and a Web Data
database) and points the browser at it with --boring-import-chrome-dir.
Edge is pointed at a folder that does not exist, so the test never reads
the Chrome or Edge data of whoever uses this computer.

The import runs through chrome://settings/importData, driven over
WebDriver the way a person would use it. Then the new profile's own
files are read back after the browser has closed.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from drive import Browser

OUT = Path(__file__).resolve().parents[2] / "artifacts/ui-implemented"

PERSON = "Test Person"
WORK = "Work"
BAR_URL = "https://bar.boring-import.test/"
FOLDER_URL = "https://folder.boring-import.test/page"
OTHER_URL = "https://other.boring-import.test/"
WORK_URL = "https://work.boring-import.test/"
EXTENSION_URL = "chrome-extension://abcdefghijklmnopabcdefghijklmnop/x.html"
HISTORY_URL = "https://history.boring-import.test/visited"
HISTORY_TITLE = "Boring import history page"
KEYWORD = "boringtest"
ENGINE_URL = "https://search.boring-import.test/?q={searchTerms}"
PREPOPULATED_KEYWORD = "prepopulated.test"

# Chrome keeps times as microseconds since 1601.
EPOCH_1601 = datetime(1601, 1, 1, tzinfo=UTC)


def chromium_time(when):
    return int((when - EPOCH_1601) / timedelta(microseconds=1))


def scratch_root():
    """A folder on the build drive, as the other tests use."""
    base = r"E:\tmp" if os.path.isdir(r"E:\tmp") else os.environ.get("TMP")
    return tempfile.mkdtemp(prefix="boring-import-", dir=base)


def bookmark(name, url, added):
    return {"type": "url", "name": name, "url": url, "date_added": str(added)}


def write_bookmarks(path, bar, other):
    root = {
        "version": 1,
        "roots": {
            "bookmark_bar": {
                "type": "folder",
                "name": "Bookmarks bar",
                "children": bar,
            },
            "other": {"type": "folder", "name": "Other bookmarks", "children": other},
            "synced": {"type": "folder", "name": "Mobile bookmarks", "children": []},
        },
    }
    path.write_text(json.dumps(root), encoding="utf-8")


def write_history(path, visited):
    # The columns Chrome's own History database has in its urls table,
    # which is all the importer reads.
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE urls (id INTEGER PRIMARY KEY, url LONGVARCHAR, "
            "title LONGVARCHAR, visit_count INTEGER DEFAULT 0 NOT NULL, "
            "typed_count INTEGER DEFAULT 0 NOT NULL, "
            "last_visit_time INTEGER NOT NULL, hidden INTEGER DEFAULT 0 NOT NULL)"
        )
        db.executemany(
            "INSERT INTO urls (url, title, visit_count, typed_count, "
            "last_visit_time, hidden) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (HISTORY_URL, HISTORY_TITLE, 3, 1, visited, 0),
                ("chrome://settings/", "Settings", 1, 0, visited, 0),
            ],
        )
    db.close()


def write_web_data(path):
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE keywords (id INTEGER PRIMARY KEY, short_name VARCHAR, "
            "keyword VARCHAR, url VARCHAR, prepopulate_id INTEGER DEFAULT 0, "
            "created_by_policy INTEGER DEFAULT 0, is_active INTEGER DEFAULT 0, "
            "starter_pack_id INTEGER DEFAULT 0)"
        )
        db.executemany(
            "INSERT INTO keywords (short_name, keyword, url, prepopulate_id) "
            "VALUES (?, ?, ?, ?)",
            [
                ("Boring test search", KEYWORD, ENGINE_URL, 0),
                (
                    "Built in",
                    PREPOPULATED_KEYWORD,
                    "https://pre.test/?q={searchTerms}",
                    7,
                ),
            ],
        )
    db.close()


def make_fake_user_data(root=None):
    """A Chrome "User Data" folder with two profiles. Returns its path."""
    root = Path(root or scratch_root())
    user_data = root / "Chrome" / "User Data"
    person = user_data / "Default"
    work = user_data / "Profile 1"
    person.mkdir(parents=True)
    work.mkdir(parents=True)
    now = datetime.now(UTC)
    added = chromium_time(now - timedelta(days=30))

    local_state = {
        "profile": {
            "info_cache": {
                "Default": {"name": PERSON},
                "Profile 1": {"name": WORK},
                # Local State is not ours: a name that tries to leave
                # the User Data folder must not be followed.
                "../Outside": {"name": "Outside"},
            }
        }
    }
    (user_data / "Local State").write_text(json.dumps(local_state), encoding="utf-8")
    outside = root / "Chrome" / "Outside"
    outside.mkdir()
    write_bookmarks(outside / "Bookmarks", [bookmark("Outside", OTHER_URL, added)], [])

    write_bookmarks(
        person / "Bookmarks",
        [
            bookmark("Bar page", BAR_URL, added),
            {
                "type": "folder",
                "name": "Reading",
                "children": [bookmark("Folder page", FOLDER_URL, added)],
            },
            bookmark("Extension page", EXTENSION_URL, added),
        ],
        [bookmark("Other page", OTHER_URL, added)],
    )
    write_history(person / "History", chromium_time(now - timedelta(days=1)))
    write_web_data(person / "Web Data")
    write_bookmarks(work / "Bookmarks", [bookmark("Work page", WORK_URL, added)], [])
    return user_data


def import_switches(chrome_dir, missing_root):
    """Both switches, always, so the real Chrome and Edge stay unread."""
    return [
        "--boring-import-chrome-dir=" + str(chrome_dir),
        "--boring-import-edge-dir=" + str(Path(missing_root) / "no-edge"),
    ]


# Settings is built from nested shadow roots.
FIND_DIALOG = """
  function find(root) {
    var hit = root.querySelector('settings-import-data-dialog');
    if (hit) return hit;
    for (var el of root.querySelectorAll('*')) {
      if (el.shadowRoot) {
        hit = find(el.shadowRoot);
        if (hit) return hit;
      }
    }
    return null;
  }
  window.__importDialog = find(document);
"""

OPTIONS = (
    FIND_DIALOG
    + """
  var d = window.__importDialog;
  if (!d || !d.shadowRoot) return null;
  var select = d.shadowRoot.querySelector('#browserSelect');
  if (!select || !select.options.length) return null;
  return Array.from(select.options).map(function(o) {
    return o.textContent.trim();
  });
"""
)

CHOOSE = (
    FIND_DIALOG
    + """
  var d = window.__importDialog;
  var select = d.shadowRoot.querySelector('#browserSelect');
  var want = arguments[0];
  var index = Array.from(select.options).findIndex(function(o) {
    return o.textContent.trim() === want;
  });
  if (index < 0) return null;
  select.selectedIndex = index;
  select.dispatchEvent(new Event('change'));
  return index;
"""
)

CHECKBOXES = (
    FIND_DIALOG
    + """
  var r = window.__importDialog.shadowRoot;
  var out = {};
  ['importDialogHistory', 'importDialogBookmarks', 'importDialogSearchEngine',
   'importDialogSavedPasswords', 'importDialogAutofillFormData'].forEach(
      function(id) {
        var box = r.querySelector('#' + id);
        out[id] = box ? {shown: !box.hidden, checked: !!box.checked} : null;
      });
  return out;
"""
)

CLICK_IMPORT = (
    FIND_DIALOG
    + """
  var button = window.__importDialog.shadowRoot.querySelector('#import');
  if (!button || button.disabled) return false;
  button.click();
  return true;
"""
)

DONE = (
    FIND_DIALOG
    + """
  var r = window.__importDialog.shadowRoot;
  var done = r.querySelector('#done');
  var dialog = r.querySelector('#dialog');
  if (done && !done.hidden) return 'succeeded';
  if (dialog && !dialog.open) return 'closed';
  return 'waiting';
"""
)

BOOKMARKS = """
  var done = arguments[arguments.length - 1];
  var urls = arguments[0];
  Promise.all(urls.map(function(url) {
    return chrome.bookmarks.search({url: url}).then(function(hits) {
      return hits.length;
    });
  })).then(done, function(e) { done(String(e)); });
"""


def wait_for(b, script, args=None, ok=lambda v: v, timeout=20):
    end = time.time() + timeout
    value = None
    while time.time() < end:
        value = b.run(script, args)
        if ok(value):
            return value
        time.sleep(0.5)
    return value


def wait_closed(profile, timeout=30):
    """Chrome holds this file until it has written everything out."""
    lock = Path(profile) / "lockfile"
    end = time.time() + timeout
    while time.time() < end:
        try:
            if not lock.exists():
                return True
            lock.unlink()
            return True
        except OSError:
            time.sleep(0.5)
    return False


def rows(db_path, query, args=()):
    """Read the browser's own database from a copy, never the original."""
    copy = Path(str(db_path) + ".read")
    shutil.copyfile(db_path, copy)
    db = sqlite3.connect(copy)
    try:
        return db.execute(query, args).fetchall()
    finally:
        db.close()
        copy.unlink()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    root = scratch_root()
    try:
        chrome_dir = make_fake_user_data(root)
        profile = Path(root) / "profile"
        chrome_person = "Google Chrome - " + PERSON
        chrome_work = "Google Chrome - " + WORK
        with Browser(
            user_data_dir=str(profile),
            args=["--window-size=1360,900"] + import_switches(chrome_dir, root),
        ) as b:
            b.get("chrome://settings/importData")
            options = wait_for(b, OPTIONS) or []
            print("  sources:", options)
            checks["dialog lists the Chrome profile"] = chrome_person in options
            checks["dialog lists every Chrome profile"] = chrome_work in options
            checks["Chrome comes first"] = bool(options) and options[0] == chrome_person
            checks["no Edge without an Edge profile"] = not any(
                o.startswith("Microsoft Edge") for o in options
            )
            checks["Local State cannot point outside User Data"] = not any(
                "Outside" in o for o in options
            )

            checks["can choose the Chrome profile"] = (
                b.run(CHOOSE, [chrome_person]) is not None
            )
            time.sleep(0.5)
            boxes = b.run(CHECKBOXES) or {}
            print("  items:", boxes)
            for box, label in (
                ("importDialogHistory", "history"),
                ("importDialogBookmarks", "bookmarks"),
                ("importDialogSearchEngine", "search engines"),
            ):
                state = boxes.get(box) or {}
                checks[f"offers {label}"] = bool(state.get("shown"))
                checks[f"{label} ticked by default"] = bool(state.get("checked"))
            for box, label in (
                ("importDialogSavedPasswords", "passwords"),
                ("importDialogAutofillFormData", "form data"),
            ):
                state = boxes.get(box) or {}
                checks[f"does not offer {label}"] = not state.get("shown")
            b.screenshot(str(OUT / "import-dialog.png"))

            checks["import starts"] = b.run(CLICK_IMPORT) is True
            result = wait_for(b, DONE, ok=lambda v: v != "waiting", timeout=60)
            checks["import succeeds"] = result == "succeeded"
            b.screenshot(str(OUT / "import-done.png"))

            b.get("chrome://bookmarks")
            time.sleep(1)
            wanted = [BAR_URL, FOLDER_URL, OTHER_URL, EXTENSION_URL, WORK_URL]
            found = b.run_async(BOOKMARKS, [wanted])
            print("  bookmarks found:", found)
            counts = {}
            if isinstance(found, list):
                counts = dict(zip(wanted, found, strict=False))
            checks["bookmark bar page imported"] = counts.get(BAR_URL) == 1
            checks["bookmark in a folder imported"] = counts.get(FOLDER_URL) == 1
            checks["other bookmarks imported"] = counts.get(OTHER_URL) == 1
            checks["extension page not imported"] = counts.get(EXTENSION_URL) == 0
            checks["other profile left alone"] = counts.get(WORK_URL) == 0

        checks["browser closed cleanly"] = wait_closed(profile)
        own = profile / "Default"
        history = rows(
            own / "History",
            "SELECT title, visit_count FROM urls WHERE url = ?",
            (HISTORY_URL,),
        )
        print("  history:", history)
        checks["history imported"] = bool(history) and history[0][0] == HISTORY_TITLE
        checks["history skips browser pages"] = not rows(
            own / "History", "SELECT url FROM urls WHERE url LIKE 'chrome://%'"
        )
        keywords = rows(own / "Web Data", "SELECT keyword, url FROM keywords")
        found = {k: u for k, u in keywords}
        checks["search engine imported"] = found.get(KEYWORD) == ENGINE_URL
        checks["built in engines not imported"] = PREPOPULATED_KEYWORD not in found
    finally:
        shutil.rmtree(root, ignore_errors=True)

    (OUT / "import-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
