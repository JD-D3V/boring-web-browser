#!/usr/bin/env python3
"""Check "Keep a copy in a folder" on the Protection page.

The folder picker cannot be driven, so the test folder is set with
--boring-folder-copy-dir. Everything else goes through the real page.

  - Profile A has an empty folder: bookmarks.html and boring-settings.json
    appear at startup.
  - Adding a bookmark rewrites bookmarks.html within the debounce; changing
    a setting shows up in the settings file.
  - Neither file holds a password, cookie, history or key.
  - Profile B starts fresh on the same folder. The folder already has a
    copy, so B writes nothing until told to; Load from folder adds the
    bookmarks that are new (not the same address twice, no javascript:
    bookmarklet), keeps B's own, and lists the settings without applying
    them. Only "Change them" applies; the files then follow B.
  - Turning the row off stops the writes.
  - The switch is for one run: nothing about it reaches the profile's
    Preferences, and a folder outside the temp directory is ignored.
  - A settings file that adds an @@ exception rule is flagged in the
    preview as turning blocking off for some sites.
  - One that adds only a ## cosmetic rule, a ##+js rule, a #?#, #$# or #%#
    rule, or a network rule with $redirect, $csp or $replace (no @@ line)
    is flagged as changing how some sites look or act,
    and one that adds only an ordinary blocking rule is not.
  - One that takes a regional list away is flagged "(less protection)";
    one that only adds regional lists is not.
"""

import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time

from drive import Browser

URL = "chrome://boring-protection"
# The switch is honoured only under the temp directory the browser sees,
# and the browser inherits ours, so the test folders go under that.
TMP = tempfile.gettempdir()
ROOT = os.path.join(TMP, "feat-folder-copy")
RULES = "boring.adblock.custom_rules"
SETTINGS = "boring-settings.json"
BOOKMARKS = "bookmarks.html"
SECRET_COOKIE = "ZZSECRETCOOKIE9"
SECRET_KEY = "AIzaFCOPYSECRETKEY0123456789"
HISTORY_MARK = "fcopy-history-marker"
KNOWN = {
    "boring.protection.stop_takeovers",
    "boring.protection.warn_scam_tricks",
    "boring.protection.no_scam_bypass",
    "boring.hide_sponsored_results",
    "boring.list_updates",
    "boring.fingerprint_noise",
    "boring.strip_tracking_params",
    "boring.privacy.skip_redirects",
    "boring.privacy.block_cookie_banners",
    "boring.block_annoyances",
    "boring.adblock.regional_lists",
    "boring.adblock.level",
    "boring.adblock.custom_rules",
    "boring.performance.never_sleep_sites",
    "boring.ai.provider",
}
FAILURES = []


def check(ok, what):
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        FAILURES.append(what)
    return ok


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def wait_until(fn, seconds=25, step=0.4):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            value = fn()
        except Exception:
            value = None
        if value:
            return value
        time.sleep(step)
    return None


def wait_js(b, script, seconds=25):
    return wait_until(lambda: b.run(script), seconds)


def wait_file(path, text, seconds=25):
    return wait_until(lambda: text in (read(path) or ""), seconds)


class Pages(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><title>fcopy</title><p>page"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def add_bookmarks(b, items):
    """items: [(title, url)] into the bookmarks bar, from chrome://bookmarks."""
    b.get("chrome://bookmarks")
    wait_js(b, "return !!(window.chrome && chrome.bookmarks)")
    b.run_async(
        """
        var done = arguments[arguments.length - 1];
        var items = arguments[0];
        Promise.all(items.map(function(i) {
          return chrome.bookmarks.create({parentId: '1', title: i[0], url: i[1]});
        })).then(function() { done('ok'); }, function(e) { done(String(e)); });
        """,
        [items],
    )


def bookmark_hits(b, url):
    b.get("chrome://bookmarks")
    wait_js(b, "return !!(window.chrome && chrome.bookmarks)")
    return b.run_async(
        """
        var done = arguments[arguments.length - 1];
        chrome.bookmarks.search({url: arguments[0]}).then(function(hits) {
          done(hits.map(function(h) { return h.title; }));
        }, function(e) { done(String(e)); });
        """,
        [url],
    )


def folder_row(b):
    """What the row shows right now."""
    return b.run(
        """
        var q = function(id) { return document.getElementById(id); };
        var shown = function(id) { return !!q(id) && !q(id).hidden; };
        if (!q('folder-copy')) { return null; }
        return {on: q('folder-copy').checked,
                disabled: q('folder-copy').disabled,
                line: q('folder-copy-line').innerText,
                status: q('folder-copy-status').innerText,
                load: shown('folder-load'), loadDisabled: q('folder-load').disabled,
                saveOver: shown('folder-save-over'),
                change: shown('folder-change'),
                preview: shown('folder-preview') ? q('folder-preview').innerText : '',
                weakFirst: Array.prototype.map.call(
                    document.querySelectorAll('#folder-preview li'),
                    function(li) { return li.className === 'weakens'; })};
        """
    )


def open_protection(b):
    b.get(URL)
    wait_js(b, "return !!document.getElementById('folder-copy')")


def saved_folder_pref(profile):
    """The folder copy pref in the profile's Preferences, or None."""
    text = read(os.path.join(profile, "Default", "Preferences"))
    if text is None:
        return None
    prefs = json.loads(text)
    return (prefs.get("boring", {}).get("folder_copy", {}) or {}).get("dir")


def run_outside(folder, profile):
    """A folder outside temp is ignored: the row stays off and nothing is written."""
    with Browser(user_data_dir=profile, args=["--boring-folder-copy-dir=" + folder]) as b:
        open_protection(b)
        time.sleep(9)
        row = folder_row(b)
        check(bool(row) and not row["on"],
              f"C: a folder outside temp leaves the row off ({row and row['line']!r})")
        check(not os.path.exists(os.path.join(folder, SETTINGS))
              and not os.path.exists(os.path.join(folder, BOOKMARKS)),
              "C: nothing is written to a folder outside temp")
    check(not saved_folder_pref(profile), "C: and nothing is saved in the profile")


def run_a(folder, profile, server_port):
    settings = os.path.join(folder, SETTINGS)
    bookmarks = os.path.join(folder, BOOKMARKS)
    args = ["--boring-folder-copy-dir=" + folder]
    with Browser(user_data_dir=profile, args=args) as b:
        open_protection(b)
        row = folder_row(b)
        check(bool(row) and row["on"] and row["line"] == folder,
              f"A: the row is on and names the folder ({row and row['line']!r})")
        check(bool(row) and row["load"] and row["change"] and not row["saveOver"],
              "A: Load from folder and Change folder show, Save over it does not")

        # At startup.
        check(bool(wait_until(lambda: os.path.exists(settings) and os.path.exists(bookmarks), 30)),
              "A: both files appear at startup")
        start_settings = json.loads(read(settings) or "{}")
        check(start_settings.get("version") == 1 and isinstance(start_settings.get("settings"), dict),
              f"A: the settings file has the expected shape ({start_settings})")

        # Things that must never reach the folder.
        b.get(f"http://127.0.0.1:{server_port}/{HISTORY_MARK}")
        b.run(f"document.cookie = 'fcopy_secret={SECRET_COOKIE}; path=/'; return 1")
        b.get("chrome://boring-ai")
        wait_js(b, "return !!document.getElementById('p-gemini')")
        b.run(
            "document.getElementById('p-gemini').click();"
            f"document.getElementById('api-key').value = '{SECRET_KEY}';"
            "document.getElementById('save').click(); return 1"
        )
        time.sleep(1.5)

        # A bookmark, within the debounce.
        add_bookmarks(
            b,
            [
                ("FCopy One", "https://example.com/fcopy-one"),
                ("FCopy Two", "https://example.com/fcopy-two"),
                ("FCopy Bookmarklet", "javascript:alert(1)"),
            ],
        )
        began = time.monotonic()
        got = wait_file(bookmarks, "FCopy Two", 20)
        took = time.monotonic() - began
        check(bool(got) and took < 12, f"A: a new bookmark is in bookmarks.html in {took:.1f}s")

        # A setting.
        open_protection(b)
        b.run("document.getElementById('fingerprint').click();"
              "document.getElementById('skip-redirects').click(); return 1")
        check(bool(wait_until(
            lambda: json.loads(read(settings) or "{}").get("settings", {}).get(
                "boring.fingerprint_noise") is False, 20)),
            "A: a changed setting appears in the settings file")
        check(bool(wait_until(
            lambda: json.loads(read(settings) or "{}").get("settings", {}).get(
                "boring.ai.provider") == "gemini", 5)),
            "A: the AI provider name is in the settings file")

        # Nothing private.
        files = (read(settings) or "") + "\n" + (read(bookmarks) or "")
        saved = json.loads(read(settings) or "{}").get("settings", {})
        check(set(saved) <= KNOWN, f"A: settings names are all on the list ({sorted(set(saved) - KNOWN)})")
        for what in (SECRET_COOKIE, SECRET_KEY, HISTORY_MARK, "api_key", "password"):
            check(what.lower() not in files.lower(), f"A: the files hold no {what!r}")
        first = read(settings)
    check(not saved_folder_pref(profile),
          f"A: the switch folder is not saved in the profile ({saved_folder_pref(profile)!r})")
    return first


def add_exception_rules(folder):
    """A synced second PC could put an exception rule in the settings file."""
    path = os.path.join(folder, SETTINGS)
    data = json.loads(read(path) or "{}")
    data.setdefault("settings", {})[RULES] = "||ads.example^\n@@||example.org^$document"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# What a synced second PC could add besides an @@ exception: rules that hide
# parts of a page or run script on it. (label, one rule of that kind)
COSMETIC_RULES = [
    ("##", "example.org##.ad-banner"),
    ("##+js", "example.org##+js(abort-on-property-read, adsEnabled)"),
    ("#?#", "example.org#?#div:has(> .sponsor)"),
    ("#$#", "example.org#$#body { overflow: auto !important }"),
    ("#%#", "example.org#%#//scriptlet('abort-on-property-read', 'adsEnabled')"),
    ("$redirect", "||bank.example/fraud.js$script,redirect=noopjs"),
    ("$csp", "||bank.example^$csp=script-src 'self'"),
    ("$replace", "||bank.example/app.js$replace=/check/skip/"),
]
COSMETIC_NOTE = "change how certain sites look or act (less protection)"


def set_folder_rules(folder, lines):
    """The folder's settings file, with only these filter rules in it."""
    path = os.path.join(folder, SETTINGS)
    data = json.loads(read(path) or "{}")
    data["settings"] = {RULES: chr(10).join(lines)}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def run_d(folder, profile):
    """A fresh profile loads settings files that add one kind of rule each.
    The number of rules differs per case, so the preview line of one case
    can be told from the one before it."""
    cases = [(f"adds a {label} rule", label, [rule]) for label, rule in COSMETIC_RULES]
    cases.append(("adds only an ordinary blocking rule", None, ["||ads.example^"]))
    args = ["--boring-folder-copy-dir=" + folder]
    with Browser(user_data_dir=profile, args=args) as b:
        open_protection(b)
        wait_until(lambda: (lambda r: r if r and r["saveOver"] else None)(folder_row(b)), 15)
        for count, (what, label, special) in enumerate(cases, start=1):
            set_folder_rules(folder, special + [f"||plain{n}.example^" for n in range(count - 1)])
            b.run("document.getElementById('folder-load').click(); return 1")
            row = wait_until(
                lambda: (lambda r: r if r and f"to {count} rule" in r["preview"] else None)(
                    folder_row(b)),
                20)
            check(bool(row), f"D: a settings file that {what} is listed ({count} rules)")
            if not row:
                continue
            print("   preview:", row["preview"].replace(chr(10), " / "))
            if label:
                check("My filter rules" in row["preview"] and COSMETIC_NOTE in row["preview"],
                      f"D: a {label} rule is flagged as changing how sites look or act")
                check("turn blocking off" not in row["preview"],
                      f"D: and a {label} rule is not called turning blocking off")
            else:
                check("My filter rules" in row["preview"] and "look or act" not in row["preview"]
                      and "less protection" not in row["preview"],
                      "D: an ordinary blocking rule carries no warning")
        run_regional(b, folder)


def set_folder_settings(folder, settings):
    """The folder's settings file, with only these settings in it."""
    path = os.path.join(folder, SETTINGS)
    data = json.loads(read(path) or "{}")
    data["settings"] = settings
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def load_preview(b, needle, seconds=20):
    """Click Load from folder; the preview row once it holds needle."""
    b.run("document.getElementById('folder-load').click(); return 1")
    return wait_until(
        lambda: (lambda r: r if r and needle in r["preview"] else None)(folder_row(b)),
        seconds)


def run_regional(b, folder):
    """S6 part: a settings file that takes regional lists away is flagged
    as less protection; one that adds lists is not."""
    regional = "boring.adblock.regional_lists"
    set_folder_settings(folder, {regional: ["de", "fr"]})
    row = load_preview(b, "Regional lists: 0 lists to 2 lists")
    check(bool(row), "D: a settings file that adds regional lists is listed")
    check(bool(row) and "less protection" not in row["preview"],
          "D: adding regional lists carries no warning")
    b.run("document.getElementById('folder-apply').click(); return 1")
    wait_until(lambda: (lambda r: r if r and not r["preview"] else None)(folder_row(b)), 15)
    # The folder follows the browser once applied; let that write land
    # before the next file is put there.
    wait_file(os.path.join(folder, SETTINGS), '"fr"', 25)
    time.sleep(1)
    set_folder_settings(folder, {regional: ["de"]})
    row = load_preview(b, "Regional lists: 2 lists to 1 list")
    check(bool(row), "D: a settings file that drops a regional list is listed")
    check(bool(row) and "Regional lists: 2 lists to 1 list (less protection)" in row["preview"],
          "D: dropping a regional list is flagged as less protection")
    if row:
        print("   preview:", row["preview"].replace(chr(10), " / "))
    set_folder_settings(folder, {regional: ["de", "fr", "it"]})
    row = load_preview(b, "Regional lists: 2 lists to 3 lists")
    check(bool(row) and "less protection" not in row["preview"],
          "D: a file with every list it has plus another carries no warning")


def run_b(folder, profile):
    settings = os.path.join(folder, SETTINGS)
    bookmarks = os.path.join(folder, BOOKMARKS)
    args = ["--boring-folder-copy-dir=" + folder]
    with Browser(user_data_dir=profile, args=args) as b:
        add_bookmarks(
            b,
            [
                ("Mine Existing", "https://example.com/fcopy-existing"),
                ("Mine One", "https://example.com/fcopy-one"),
            ],
        )
        open_protection(b)
        before_settings = read(settings)
        before_bookmarks = read(bookmarks)
        mtime = os.path.getmtime(bookmarks)
        row = wait_until(lambda: (lambda r: r if r and r["saveOver"] else None)(folder_row(b)), 15)
        check(bool(row) and row["on"], "B: the row is on")
        check(bool(row) and "already has a copy" in row["status"],
              f"B: it says the folder already has a copy ({row and row['status']!r})")

        # Wait past the startup write and a debounce: B must write nothing.
        time.sleep(11)
        check(read(bookmarks) == before_bookmarks and os.path.getmtime(bookmarks) == mtime
              and read(settings) == before_settings,
              "B: a folder with a copy is left alone until B is told")

        # Load from folder.
        b.run("document.getElementById('folder-load').click(); return 1")
        row = wait_until(lambda: (lambda r: r if r and r["preview"] else None)(folder_row(b)), 30)
        check(bool(row), "B: Load from folder lists the settings that differ")
        if row:
            print("   status:", row["status"].replace("\n", " "), "| preview:", row["preview"].replace("\n", " / "))
            check("Added 1 bookmark" in row["status"], f"B: one new bookmark added ({row['status']!r})")
            check("Fingerprint noise: On to Off (less protection)" in row["preview"]
                  and "Skip tracking redirects: On to Off (less protection)" in row["preview"],
                  "B: protections that would turn off are listed")
            check("AI assistant: Off to Gemini" in row["preview"], "B: the AI provider change is listed")
            check("My filter rules" in row["preview"]
                  and "turn blocking off for certain sites (less protection)" in row["preview"],
                  "B: an added @@ exception rule is flagged as turning blocking off")
            check(row["weakFirst"] == sorted(row["weakFirst"], reverse=True),
                  f"B: the ones that lower protection come first ({row['weakFirst']})")
        applied_early = b.run("return !document.getElementById('fingerprint').checked")
        check(not applied_early, "B: nothing is applied before the confirm")

        titles_two = bookmark_hits(b, "https://example.com/fcopy-two")
        titles_one = bookmark_hits(b, "https://example.com/fcopy-one")
        titles_mine = bookmark_hits(b, "https://example.com/fcopy-existing")
        bookmarklet = bookmark_hits(b, "javascript:alert(1)")
        check(titles_two == ["FCopy Two"], f"B: the new bookmark is there ({titles_two})")
        check(titles_one == ["Mine One"], f"B: a bookmark B had is kept, and not added twice ({titles_one})")
        check(titles_mine == ["Mine Existing"], f"B: B's other bookmark is still there ({titles_mine})")
        check(bookmarklet == [], f"B: the javascript: bookmarklet was dropped ({bookmarklet})")

        # Unconfirmed: still nothing written over the folder's settings.
        time.sleep(8)
        check(read(settings) == before_settings, "B: the folder's settings are not replaced before the confirm")

        # Confirm.
        open_protection(b)
        wait_js(b, "return !!document.getElementById('folder-copy')")
        # The page was reloaded; the pending list lives in the browser.
        row = wait_until(lambda: (lambda r: r if r and r["preview"] else None)(folder_row(b)), 10)
        check(bool(row), "B: the list is still waiting after the page reloads")
        b.run("document.getElementById('folder-apply').click(); return 1")
        check(bool(wait_js(b, "return !document.getElementById('fingerprint').checked"
                              " && !document.getElementById('skip-redirects').checked", 15)),
              "B: Change them applies the settings")
        row = folder_row(b)
        check(bool(row) and "Changed " in row["status"] and not row["preview"],
              f"B: the row says what changed ({row and row['status']!r})")
        check(bool(wait_file(bookmarks, "Mine Existing", 25)),
              "B: after the confirm the folder follows B (its own bookmark is in bookmarks.html)")
        check(bool(wait_file(bookmarks, "FCopy Two", 5)),
              "B: and still holds the loaded one")

        # Off stops the writes.
        b.run("document.getElementById('folder-copy').click(); return 1")
        row = wait_until(lambda: (lambda r: r if r and not r["on"] else None)(folder_row(b)), 10)
        check(bool(row) and "Off" in row["line"] and not row["load"],
              f"B: the row reads Off ({row and row['line']!r})")
        time.sleep(1)
        frozen_b = read(bookmarks)
        frozen_s = read(settings)
        frozen_m = os.path.getmtime(bookmarks)
        add_bookmarks(b, [("FCopy After Off", "https://example.com/fcopy-after-off")])
        open_protection(b)
        b.run("document.getElementById('hide-cookies').click(); return 1")
        time.sleep(12)
        check(read(bookmarks) == frozen_b and os.path.getmtime(bookmarks) == frozen_m
              and read(settings) == frozen_s and "After Off" not in (read(bookmarks) or ""),
              "B: turned off, a new bookmark and a changed setting are not written")


def main():
    os.makedirs(ROOT, exist_ok=True)
    work = tempfile.mkdtemp(prefix="smoke-", dir=ROOT)
    folder = os.path.join(work, "folder")
    os.makedirs(folder)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        run_a(folder, os.path.join(work, "A"), server.server_address[1])
        add_exception_rules(folder)
        run_b(folder, os.path.join(work, "B"))
        run_d(folder, os.path.join(work, "D"))
        outside = tempfile.mkdtemp(prefix="smoke-outside-", dir=os.path.dirname(TMP.rstrip("/" + os.sep)))
        try:
            run_outside(outside, os.path.join(work, "C"))
        finally:
            shutil.rmtree(outside, ignore_errors=True)
    finally:
        server.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    if FAILURES:
        print(f"{len(FAILURES)} failed")
        return 1
    print("ok: keep a copy in a folder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
