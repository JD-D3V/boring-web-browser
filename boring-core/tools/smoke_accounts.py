#!/usr/bin/env python3
"""Accounts in the real browser (compiled UI ledger item 11, screen C13).

Accounts are shortcuts: the profile keeps a list (boring.accounts.list) and
the browser opens each company's own pages from it. This checks what the
item says, on scratch profiles under E:\\tmp, each started straight from
chrome.exe with every web address mapped to nowhere (--host-resolver-rules),
so a tab records the address it asked for and nothing leaves the machine:

  1. Light. Two accounts written into Preferences (Google "Personal",
     Proton "Private mail"). The test hook --boring-accounts-test opens the
     panel and reports it: the button "Your accounts" with the initial P,
     the heading and its line, both rows (names, provider lines, Mail,
     Calendar, Files), the six Add buttons, the footer sentence; no text
     says Chrome or Chromium or has a dash. The panel is photographed with
     PrintWindow and saved beside screen C13.
  2. The same panel through UI Automation on our own window: the button
     offers Expand, and the dialog it opens has the rows and the footer.
  3. Mail on row 1, Calendar and Files on row 2: new tabs at
     mail.google.com, calendar.proton.me and drive.proton.me; the panel
     closes.
  4. Add Yahoo: Preferences gains a "yahoo" entry named Yahoo with no
     address in it, a tab asks for login.yahoo.com, the initial stays P;
     the Yahoo row has Mail and Calendar only.
  5. Settings, Accounts through DevTools: the list matches; Other refuses
     javascript:, data:, http://, a name and password, an IP address,
     localhost and a 3000 character address, each with its own words, and
     adds nothing; fastmail.com and a punycode host are added; a 60
     character name is kept to 40; Move and Remove work; ?add=other opens
     the form; the nav has Accounts.
  6. The new tab page: chips in the list's order, then Add account; a chip
     opens that account's mail in the same tab; Add account opens Settings,
     Accounts.
  7. Incognito: no Accounts button, no chips.
  8. Dark (--force-dark-mode): the panel again, photographed beside C13.

Not here: that having accounts reaches no host is net_audit.py --scenario
accounts. Guest windows are not started (they share Incognito's code path:
the profile is off the record).

No synthetic input: the hook, UI Automation on our own window and DevTools.
Every browser started is quit in a finally block.

Usage:
    python smoke_accounts.py [--out DIR] [--captures FOLDER]
"""

import argparse
import contextlib
import ctypes
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import page_checks
from capture_native import frame_window, grab
from drive import CHROME
from smoke_local import Checks
from smoke_memory import close, launch
from smoke_site_panel import COLLAPSE, Window, browser_windows
from smoke_toolbar import read_report as read_toolbar_report

REPORT = "boring-accounts-test.txt"
SEED = [
    {"id": "smoke-1", "provider": "google", "name": "Personal"},
    {"id": "smoke-2", "provider": "proton", "name": "Private mail"},
]
BUTTON = "Your accounts"
HEADER = "Your accounts"
SUBLINE = "The mail and other accounts you are signed in to. One click to each."
FOOTER = (
    "You sign in on each company's own page. Boring Browser never sees your "
    "password and sends nothing to us."
)
PROVIDERS = ["Google", "Proton", "Outlook", "iCloud", "Yahoo", "Other"]
LINKS = ("Mail", "Calendar", "Files")
NOWHERE = "--host-resolver-rules=MAP * ~NOTFOUND"
HTTPS_ONLY = "Use an address that starts with https://"
NAME_AND_PASSWORD = "That address has a name and password in it. Use the plain address."
NOT_WEB = "That does not look like a web address."
BAD_OTHER = [
    ("javascript:alert(1)", HTTPS_ONLY),
    ("data:text/html,hi", HTTPS_ONLY),
    ("http://mail.example.com/", HTTPS_ONLY),
    ("https://user:pw@example.com/", NAME_AND_PASSWORD),
    ("https://192.168.1.1/", NOT_WEB),
    ("localhost", NOT_WEB),
    ("https://example.com/" + "a" * 3000, NOT_WEB),
]

# Finds the Accounts page inside Settings' shadow roots.
DEEP = """
function deep(root, sel) {
  const hit = root.querySelector(sel);
  if (hit) return hit;
  for (const el of root.querySelectorAll('*')) {
    if (el.shadowRoot) {
      const found = deep(el.shadowRoot, sel);
      if (found) return found;
    }
  }
  return null;
}
"""
PAGE = DEEP + "deep(document, 'boring-accounts-page')"
SEND = (
    "(async () => { const {sendWithPromise} = await import("
    "'chrome://resources/js/cr.js'); return await sendWithPromise(%s); })()"
)


def seed_prefs(accounts):
    """Preferences holding these accounts, as the browser stores them."""
    return {"boring": {"accounts": {"list": accounts}}}


def stored_accounts(prefs):
    """The list from a Preferences dict, or []."""
    return ((prefs.get("boring") or {}).get("accounts") or {}).get("list") or []


def bad_text(text):
    """Visible text that says Chrome or Chromium, or has an em or en dash."""
    return bool(re.search(r"chrom(e|ium)|\u2014|\u2013", text, re.I))


def parse_report(text):
    """The hook's report: {"button": (name, initial), "panel": bool,
    "hwnd": int or None, "width": int, "labels": [...], "buttons":
    [(name, on)]}. None until its closing "end" line is there."""
    lines = text.splitlines()
    if "end" not in lines:
        return None
    out = {"button": ("", ""), "panel": False, "hwnd": None, "width": 0,
           "labels": [], "buttons": []}
    for line in lines:
        kind, _, rest = line.partition("\t")
        fields = rest.split("\t")
        if kind == "button" and len(fields) >= 2:
            if fields[-1] in ("on", "off"):
                out["buttons"].append((fields[0], fields[-1] == "on"))
            else:
                out["button"] = (fields[0], fields[1])
        elif kind == "panel":
            out["panel"] = rest == "1"
        elif kind == "hwnd":
            out["hwnd"] = int(rest)
        elif kind == "width":
            out["width"] = int(rest)
        elif kind == "label":
            out["labels"].append(rest)
    return out


def wait_report(profile, timeout=30):
    path = Path(profile) / "Default" / REPORT
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError):
            report = parse_report(path.read_text(encoding="utf-8"))
            if report is not None:
                return report
        time.sleep(0.2)
    return None


def links_of(report):
    return [name for name, _on in report["buttons"] if name in LINKS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"E:\tmp\cui-accounts\shots", help="folder for the photographs")
    page_checks.add_captures_option(ap)
    args = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    checks = Checks()
    work = Path(tempfile.mkdtemp(prefix="boring-accounts-", dir=os.environ.get("TMP", r"E:\tmp")))
    flags = ["--disable-features=CalculateNativeWinOcclusion", "--window-size=1280,800", NOWHERE]
    proc = cdp = None

    def new_profile(name, accounts=SEED):
        where = work / name
        (where / "Default").mkdir(parents=True)
        (where / "Default" / "Preferences").write_text(json.dumps(seed_prefs(accounts)), encoding="utf-8")
        return where

    def start(where, extra=(), urls=("about:blank",)):
        nonlocal proc, cdp
        with contextlib.suppress(OSError):
            (Path(where) / "Default" / REPORT).unlink()
        proc, cdp = launch(CHROME, where, [*flags, *extra], urls)
        time.sleep(3)

    def stop():
        nonlocal proc, cdp
        if proc:
            close(proc, cdp)
        proc = cdp = None

    def hook(where, steps, extra=()):
        start(where, [f"--boring-accounts-test={steps}", *extra])
        report = wait_report(where)
        print("report:", report)
        return report

    def page_urls():
        return [t["url"] for t in cdp.send("Target.getTargets")["targetInfos"] if t["type"] == "page"]

    def wait_url(wanted, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if wanted in page_urls():
                return True
            time.sleep(0.3)
        return False

    def prefs_of(where):
        return json.loads((Path(where) / "Default" / "Preferences").read_text(encoding="utf-8"))

    def check_panel(report, theme):
        checks(f"{theme}: the hook reported", report is not None)
        if not report:
            return
        checks(f"{theme}: the button is named Your accounts and shows P", report["button"] == (BUTTON, "P"), str(report["button"]))
        checks(f"{theme}: the panel is open", report["panel"])
        labels = report["labels"]
        for text in (HEADER, SUBLINE, "Personal", "Google account", "Private mail", "Proton account", "Add an account", FOOTER):
            checks(f"{theme}: the panel says {text[:40]}", text in labels, str(labels))
        checks(f"{theme}: rows in the list's order", labels.index("Personal") < labels.index("Private mail") if "Personal" in labels and "Private mail" in labels else False)
        checks(f"{theme}: Mail, Calendar, Files on each row", links_of(report) == [*LINKS, *LINKS], str(links_of(report)))
        adds = [(n, on) for n, on in report["buttons"] if n in PROVIDERS]
        checks(f"{theme}: the six Add buttons, all on", adds == [(p, True) for p in PROVIDERS], str(adds))
        words = labels + [n for n, _ in report["buttons"]]
        checks(f"{theme}: no text says Chrome or has a dash", not [w for w in words if bad_text(w)], str(words))
        checks(f"{theme}: the panel is at least 360 wide", report["width"] >= 360, str(report["width"]))

    def shoot_panel(report, dark):
        theme = "dark" if dark else "light"
        if not report or not report["hwnd"]:
            checks(f"{theme}: the panel has a window to photograph", False)
            return
        time.sleep(1)  # past the panel's fade in
        path = out / f"panel-{theme}.png"
        grab(report["hwnd"], str(path))
        print("saved", path)
        both = page_checks.save_capture(path, "accounts", "C13", dark=dark, folder=args.captures)
        if both:
            print("saved", both)

    try:
        # 1. Light: the panel, read by the hook and photographed.
        light = new_profile("light")
        report = hook(light, "open,report")
        check_panel(report, "light")
        shoot_panel(report, False)
        with Window(frame_window(CHROME, under=os.getpid())) as w:
            names = w.names()
        checks("the toolbar has the Your accounts button", BUTTON in names, str(names))
        stop()

        # 2. Through UI Automation on our own window.
        start(light, ["--boring-accounts-test=noop"])
        try:
            with Window(frame_window(CHROME, under=os.getpid())) as w:
                how = w.press(lambda n: n == BUTTON)
            checks("the button opens a dialog (Expand)", how == "expand", str(how))
        except (LookupError, RuntimeError, OSError) as e:
            checks("the button can be pressed through UI Automation", False, str(e))
        time.sleep(1.5)
        found = []
        for hwnd in browser_windows(os.getpid()):
            with contextlib.suppress(OSError), Window(hwnd) as w:
                if FOOTER in w.names():
                    found = w.names()
        checks("the dialog it opens has both rows and the footer",
               all(t in found for t in (HEADER, "Personal", "Private mail", "Mail", FOOTER)), str(found))
        with contextlib.suppress(LookupError, RuntimeError, OSError), \
                Window(frame_window(CHROME, under=os.getpid())) as w:
            w.press(lambda n: n == BUTTON, COLLAPSE)
        stop()

        # 3. The links open each company's own pages in new tabs.
        links = new_profile("links")
        report = hook(links, "open,mail=1,calendar=2,files=2,report")
        for url in ("https://mail.google.com/", "https://calendar.proton.me/", "https://drive.proton.me/"):
            checks(f"a tab asked for {url}", wait_url(url), str(page_urls()))
        checks("the panel closed after a link", bool(report) and not report["panel"])
        stop()

        # 4. Add Yahoo.
        yahoo = new_profile("yahoo")
        report = hook(yahoo, "add=yahoo,report")
        checks("a tab asked for Yahoo's sign-in page", wait_url("https://login.yahoo.com/"), str(page_urls()))
        checks("the initial stays P (first account first)", bool(report) and report["button"][1] == "P")
        stop()
        stored = stored_accounts(prefs_of(yahoo))
        last = stored[-1] if stored else {}
        checks("Preferences gained a yahoo entry named Yahoo", len(stored) == 3 and last.get("provider") == "yahoo" and last.get("name") == "Yahoo", str(stored))
        checks("a known company's entry holds no address", not {"mail", "calendar", "files"} & set(last), str(last))
        report = hook(yahoo, "open,report")
        checks("the Yahoo row has Mail and Calendar only",
               bool(report) and links_of(report) == [*LINKS, *LINKS, "Mail", "Calendar"],
               str(report and links_of(report)))
        checks("the Yahoo row says Yahoo account", bool(report) and "Yahoo account" in report["labels"])
        stop()

        # 5. Settings, Accounts.
        settings = new_profile("settings")
        start(settings)
        tab = cdp.open_tab("chrome://settings/accounts", background=False)
        s = cdp.attach(tab)
        ready = cdp.wait_for(s, "(() => { " + DEEP + " const p = deep(document, 'boring-accounts-page');"
                             " return !!p && p.accounts_ && p.accounts_.length === 2; })()", 20)
        checks("Settings, Accounts lists the two accounts", ready)

        def send(*message):
            return cdp.evaluate(s, SEND % ", ".join(json.dumps(m) for m in message)) or {}

        names = [a["name"] for a in send("boringAccountsGet").get("accounts", [])]
        checks("Settings lists them in order", names == ["Personal", "Private mail"], str(names))
        for typed, words in BAD_OTHER:
            answer = send("boringAccountsAddOther", "Bad", typed, "", "")
            checks(f"Other refuses {typed[:30]}",
                   answer.get("ok") is False and answer.get("field") == "mail" and answer.get("error") == words
                   and len(answer.get("accounts", [])) == 2, str({k: answer.get(k) for k in ("ok", "field", "error")}))
        answer = send("boringAccountsAddOther", "", "fastmail.com", "", "")
        added = answer.get("accounts", [])
        checks("Other adds fastmail.com, named after its host",
               answer.get("ok") is True and len(added) == 3 and added[-1]["providerLine"] == "fastmail.com"
               and added[-1]["name"] == "fastmail.com", str(added[-1:]))
        answer = send("boringAccountsAddOther", "Puny", "https://xn--80ak6aa92e.com/", "", "")
        added = answer.get("accounts", [])
        checks("a punycode host is shown as punycode",
               answer.get("ok") is True and added and added[-1]["providerLine"] == "xn--80ak6aa92e.com", str(added[-1:]))
        first = added[0]["id"] if added else ""
        answer = send("boringAccountsRename", first, "N" * 60)
        checks("a 60 character name is kept to 40",
               [a["name"] for a in answer.get("accounts", [])][:1] == ["N" * 40])
        last_id = added[-1]["id"] if added else ""
        answer = send("boringAccountsMove", last_id, -1)
        order = [a["id"] for a in answer.get("accounts", [])]
        checks("Move up moves it one place", len(order) == 4 and order[2] == last_id, str(order))
        answer = send("boringAccountsRemove", last_id)
        checks("Remove takes it out", last_id not in [a["id"] for a in answer.get("accounts", [])])
        text = cdp.evaluate(s, "(() => { " + DEEP + " const p = deep(document, 'boring-accounts-page');"
                            " return p ? p.shadowRoot.textContent : ''; })()") or ""
        checks("the page has the footer sentence", FOOTER in " ".join(text.split()))
        checks("no page text says Chrome or has a dash", not bad_text(text))
        menu = cdp.evaluate(s, "(() => { " + DEEP + " const a = deep(document, 'a#accounts');"
                            " return a ? a.textContent.trim() + '|' + a.getAttribute('href') : ''; })()")
        checks("the nav has Accounts", menu == "Accounts|/accounts", str(menu))
        other = cdp.open_tab("chrome://settings/accounts?add=other", background=False)
        o = cdp.attach(other)
        checks("?add=other opens the Other form", cdp.wait_for(
            o, "(() => { " + DEEP + " return !!deep(document, '#otherForm'); })()", 20))
        stop()
        stored = stored_accounts(prefs_of(settings))
        checks("Preferences keep the result", len(stored) == 3 and stored[0]["name"] == "N" * 40
               and stored[2].get("mail") == "https://fastmail.com/", str(stored))

        # 6. The new tab page.
        newtab = new_profile("newtab")
        start(newtab)
        tab = cdp.open_tab("chrome://boring-newtab", background=False)
        s = cdp.attach(tab)
        cdp.wait_for(s, "document.querySelectorAll('#accounts .chip').length === 3", 15)
        chips = cdp.evaluate(s, "[...document.querySelectorAll('#accounts .chip')].map(c => ["
                             "c.tagName, (c.querySelector('.name') || {}).textContent || '',"
                             "(c.querySelector('.provider') || {}).textContent || '', c.textContent.trim(),"
                             "c.getAttribute('href') || ''])") or []
        print("chips:", chips)
        checks("chips follow the list, then Add account",
               [c[1] for c in chips[:2]] == ["Personal", "Private mail"] and [c[2] for c in chips[:2]] == ["Google", "Proton"]
               and len(chips) == 3 and chips[2][3] == "Add account", str(chips))
        checks("account chips are buttons, not links", [c[0] for c in chips[:2]] == ["BUTTON", "BUTTON"])
        checks("Add account opens Settings, Accounts", len(chips) == 3 and chips[2][4] == "chrome://settings/accounts")
        cdp.evaluate(s, "document.querySelector('#accounts .chip').click(); 'ok'")
        deadline = time.monotonic() + 15
        url = ""
        while time.monotonic() < deadline and url != "https://mail.google.com/":
            url = next((t["url"] for t in cdp.send("Target.getTargets")["targetInfos"] if t["targetId"] == tab), "")
            time.sleep(0.3)
        checks("a chip opens that account's mail in the same tab", url == "https://mail.google.com/", url)
        stop()

        # 7. Incognito: no button, no chips.
        incognito = new_profile("incognito")
        start(incognito, ["--incognito", "--boring-toolbar-test=buttons"])
        buttons = read_toolbar_report(incognito) or []
        checks("the toolbar hook reported in Incognito", bool(buttons))
        checks("no Accounts button in Incognito", not any(e[0] == "button" and e[1] == "BoringAccountsButton" for e in buttons), str(buttons))
        page = next((t["targetId"] for t in cdp.send("Target.getTargets")["targetInfos"] if t["type"] == "page"), None)
        if page:
            s = cdp.attach(page)
            cdp.send("Page.navigate", s, url="chrome://boring-newtab")
            cdp.wait_for(s, "document.readyState === 'complete' && !!document.getElementById('accounts')", 15)
            time.sleep(1.5)
            count = cdp.evaluate(s, "document.getElementById('accounts').childElementCount")
            checks("no chips in Incognito", count == 0, str(count))
        else:
            checks("an Incognito tab to look at", False)
        stop()

        # 8. Dark.
        dark = new_profile("dark")
        report = hook(dark, "open,report", ["--force-dark-mode"])
        check_panel(report, "dark")
        shoot_panel(report, True)
        stop()
    finally:
        stop()

    print(f"\npictures in {out}")
    return checks.result("Accounts: panel, links, Add, Settings, new tab chips, Incognito")


if __name__ == "__main__":
    sys.exit(main())
