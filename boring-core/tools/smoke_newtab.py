#!/usr/bin/env python3
"""Check the new tab page as drawn (ledger item 8, screens C01 and C02).

The page has no search box. It shows the Pinned sites grid (four
columns) with Edit and Done, "Pick up where you left off" (the three
newest web pages from history, none in Incognito, a page title with
markup in it shown as plain text), the Protection line with its Details
link, and an empty reserved row on top for the account chips. A fresh
profile starts with the Reading and Wikipedia pinned sites; a person can
add and remove sites, with removed defaults staying removed, and only web
addresses become sites, never script or local files. The colours are the
TOKENS rows of the compiled design, and the font is the system's (no
Inter, no web font).

Light and dark photographs of the real window (PrintWindow, never the
screen) are written to artifacts/ui-implemented next to the compiled
design's pictures C01 and C02. They need a native window: set
BORING_ALLOW_HEADFUL=1, otherwise that part is skipped and said so.

Usage: python smoke_newtab.py
"""

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import page_checks
from drive import Browser, headful_allowed
from smoke_local import HTML, TEST_SITE, Pages
from smoke_search_menu import TEST_SWITCH

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/ui-implemented"
NEWTAB_CC = Path(__file__).resolve().parents[1] / "components/boring/newtab/newtab_ui.cc"

# TOKENS rows of Window.dc.html, as the page computes them.
LIGHT_PAGE = "rgb(248, 247, 244)"
DARK_PAGE = "rgb(21, 21, 20)"
LIGHT_EDGE = "rgb(138, 134, 125)"

# A title with markup in it must show as the characters, never as markup.
MARKUP_TITLE = "<b>Four</b> <img src=x onerror=alert(1)>"
PAGES = {
    "/one": ("<title>Page one</title><p>one</p>", HTML),
    "/two": ("<title>Page two</title><p>two</p>", HTML),
    "/three": ("<title>Page three</title><p>three</p>", HTML),
    "/four": (
        "<title>&lt;b&gt;Four&lt;/b&gt; &lt;img src=x onerror=alert(1)&gt;</title><p>four</p>",
        HTML,
    ),
}
RESOLVE = f"--host-resolver-rules=MAP {TEST_SITE} 127.0.0.1"


def wait_for(b, condition, timeout_ms=5000):
    """True once the JavaScript expression holds, false at the timeout.

    Polled from here rather than with eval in the page: the page's
    content security policy rightly refuses eval.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        if b.run("return !!(" + condition + ")"):
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)


# The tab icon must be served by the page itself and be a real SVG. Tried
# with fetch first; if a chrome:// page ever refuses to fetch itself, the
# icon must still decode as an image, otherwise the check fails.
ICON_LOADS = r"""
  const done = arguments[arguments.length - 1];
  const link = document.querySelector('link[rel~="icon"]');
  if (!link || link.getAttribute('href') !== 'brand.svg') {
    done('no icon link to brand.svg');
    return;
  }
  function asImage(why) {
    const img = new Image();
    img.src = link.href;
    img.decode().then(() => done('ok'), () => done(why + ', and not an image'));
  }
  fetch(link.href).then(r => r.text().then(t => {
    const type = r.headers.get('content-type') || '';
    if (r.status === 200 && type.includes('image/svg+xml') && t.includes('<svg')) {
      done('ok');
    } else {
      done('status ' + r.status + ', type ' + type + ', ' + t.length + ' bytes');
    }
  })).catch(e => asImage('fetch failed: ' + e));
"""

# What the page shows, read in one go.
RECENT = r"""
  var rows = [...document.querySelectorAll('#recent-list a.recent-row')];
  return {
    shown: !document.getElementById('recent').hidden,
    rows: rows.map(a => ({
      title: a.querySelector('.title').textContent,
      site: a.querySelector('.site').textContent,
      when: a.querySelector('.when').textContent,
      href: a.href,
    })),
    markup: document.querySelectorAll('#recent-list b, #recent-list i, #recent-list img').length,
  };
"""

VISIBLE = (
    "(function(e){return !!e && e.getClientRects().length>0 && "
    "getComputedStyle(e).display!=='none'})"
)


def add(b, title, url):
    """The Add a site form, opened the way a person opens it: Edit first."""
    b.run(
        "if(!document.getElementById('pinned').classList.contains('editing'))"
        "document.getElementById('edit').click();"
        "document.getElementById('add-open').click();"
        "document.getElementById('add-title').value=arguments[0];"
        "document.getElementById('add-url').value=arguments[1];"
        "document.getElementById('add-form').requestSubmit()",
        [title, url],
    )


def static_checks(checks):
    """The page's script must at least parse: a missing brace leaves the
    whole page dead and the C++ compile never sees it."""
    text = NEWTAB_CC.read_text(encoding="utf-8")
    js = page_checks.raw_string(text, "kScript")
    checks["page script is found in the source"] = js is not None
    if js is None:
        return
    if not page_checks.have_node():
        print("SKIP: page script syntax (node is not installed)")
        return
    error = page_checks.js_syntax_error(js)
    checks["page script parses"] = error is None
    if error:
        print("  script:", error)
    checks["the page names no web font"] = not re.search(
        r"@import|@font-face|googleapis|gstatic|Inter,", text
    )


def shape_checks(b, checks):
    """The fresh profile's page: what is on it and what is not."""
    b.get("chrome://newtab")
    checks["new tab is our page"] = wait_for(b, "location.host==='boring-newtab'")
    checks["tab title is still New Tab"] = b.run("return document.title==='New Tab'")
    icon = b.run_async(ICON_LOADS)
    checks["tab icon brand.svg loads"] = icon == "ok"
    if icon != "ok":
        print("  icon:", icon)

    # The system font: no Inter, and no font asked for.
    checks["the computed font is not Inter"] = b.run(
        r"return ![document.body, ...document.querySelectorAll('h2,button,a,input')]"
        r".some(e => /\binter\b/i.test(getComputedStyle(e).fontFamily))"
    )
    checks["the page asks for no font"] = b.run(
        r"return document.fonts.size===0 && !performance.getEntriesByType('resource')"
        r".some(r => /\.(woff2?|ttf|otf)(\?|$)|fonts\.g/i.test(r.name))"
    )

    # Nothing from the old page, and no search box.
    checks["no search box"] = b.run(
        "return !document.querySelector('input[type=search], #search, #engine, "
        "form[role=search], .search')"
    )
    checks["no engine button, no Colours button"] = b.run(
        "return !document.getElementById('engine') && !document.getElementById('colours')"
    )
    checks["no heading and no brand mark above the grid"] = b.run(
        "return !document.querySelector('h1') && !document.querySelector('img.home-brand')"
        " && !document.documentElement.outerHTML.includes('Just a Browser')"
    )
    checks["only the hidden add form has fields"] = b.run(
        "var f=[...document.querySelectorAll('input,textarea,select')];"
        "return f.length===2 && f.every(i=>i.closest('#add-form'))"
        " && getComputedStyle(document.getElementById('add-form')).display==='none'"
    )

    # The empty reserved row for the account chips (Accounts, a later piece).
    checks["account row is there, 56 px high and empty"] = b.run(
        "var a=document.getElementById('accounts');"
        "return !!a && a.childElementCount===0 && a.textContent.trim()===''"
        " && Math.round(a.getBoundingClientRect().height)===56"
    )

    # Pinned sites.
    checks["Pinned sites heading and an Edit button"] = b.run(
        "var h=document.getElementById('pinned-label');var e=document.getElementById('edit');"
        "return h.textContent==='Pinned sites' && e.textContent==='Edit'"
        " && e.getAttribute('aria-pressed')==='false'"
    )
    checks["starts with Reading and Wikipedia"] = wait_for(
        b,
        "[...document.querySelectorAll('#shortcuts a')].map(a=>a.href)"
        ".join(' ')==='chrome://settings/reading https://www.wikipedia.org/'",
    )
    checks["the grid has four columns"] = b.run(
        "return getComputedStyle(document.getElementById('shortcuts'))"
        ".gridTemplateColumns.split(' ').length===4"
    )
    checks["tiles sit in one row, 52 px high"] = b.run(
        "var t=[...document.querySelectorAll('#shortcuts a.shortcut')];"
        # Layout boxes, not getBoundingClientRect: the tiles' arrival motion
        # moves each one by a pixel or so for a moment after load.
        "return t.length===2 && t[0].offsetTop===t[1].offsetTop"
        " && t.every(x=>x.offsetHeight===52)"
    )
    checks["outlines use the edge colour"] = b.run(
        "return getComputedStyle(document.querySelector('#shortcuts a.shortcut'))"
        f".boxShadow.includes('{LIGHT_EDGE}')"
    )
    checks["page colour is the light TOKENS page"] = b.run(
        f"return getComputedStyle(document.body).backgroundColor==='{LIGHT_PAGE}'"
    )
    checks["editor is closed on load"] = b.run(
        "return getComputedStyle(document.getElementById('add-form')).display==='none'"
    )
    checks["remove buttons and Add a site are hidden until Edit"] = b.run(
        f"var v={VISIBLE};"
        "var r=[...document.querySelectorAll('#shortcuts .remove')];"
        "return r.length===2 && !r.some(v) && !v(document.getElementById('add-open'))"
    )
    b.run("document.getElementById('edit').click()")
    checks["Edit shows remove buttons and Add a site, and says Done"] = b.run(
        f"var v={VISIBLE};"
        "var e=document.getElementById('edit');"
        "var r=[...document.querySelectorAll('#shortcuts .remove')];"
        "return e.textContent==='Done' && e.getAttribute('aria-pressed')==='true'"
        " && r.length===2 && r.every(v) && v(document.getElementById('add-open'))"
    )
    b.run("document.getElementById('edit').click()")
    checks["Done hides them again"] = b.run(
        f"var v={VISIBLE};"
        "var e=document.getElementById('edit');"
        "return e.textContent==='Edit' && e.getAttribute('aria-pressed')==='false'"
        " && !v(document.getElementById('add-open'))"
        " && ![...document.querySelectorAll('#shortcuts .remove')].some(v)"
    )
    checks["tiles arrive with calm motion"] = b.run(
        "var ul=document.getElementById('shortcuts');"
        "var li=ul.querySelector('li');"
        "if(!li||!ul.classList.contains('appear')) return false;"
        "var a=getComputedStyle(li);"
        "return (a.animationName==='tile-in'&&a.animationDuration==='0.22s')||"
        "(a.animationName==='tile-fade'&&"
        "matchMedia('(prefers-reduced-motion: reduce)').matches)"
    )

    # Nothing visited yet: nothing to pick up.
    checks["no history, no Pick up section"] = b.run(
        "return document.getElementById('recent').hidden"
        " && document.getElementById('recent-list').children.length===0"
    )

    # The Protection line and its link.
    checks["Protection line reports real state"] = wait_for(
        b,
        "!document.getElementById('protection').hidden && "
        "/^Protection (is on|needs attention)\\. Details$/.test("
        "document.getElementById('protection-text').textContent)",
        15000,
    )
    checks["its Details link opens the Protection page"] = b.run(
        "var a=document.querySelector('#protection-text a');"
        "return !!a && a.textContent==='Details' && a.href==='chrome://settings/protection'"
    )

    # Sites: only web addresses, added, kept, removed, and defaults stay removed.
    add(b, "Script", "javascript:alert(1)")
    checks["script address is refused"] = wait_for(
        b,
        "!document.getElementById('add-bad').hidden"
        " && document.querySelectorAll('#shortcuts a').length===2",
    )
    b.run("document.getElementById('add-cancel').click()")
    checks["cancel closes the editor"] = wait_for(
        b, "getComputedStyle(document.getElementById('add-form')).display==='none'"
    )
    add(b, "Example", "example.com")
    checks["web address becomes a site"] = wait_for(
        b,
        "[...document.querySelectorAll('#shortcuts a')].some("
        "a=>a.href==='https://example.com/') && "
        "getComputedStyle(document.getElementById('add-form')).display==='none'",
    )
    b.get("chrome://newtab")
    checks["site survives a reload"] = wait_for(
        b, "document.querySelectorAll('#shortcuts a').length===3"
    )
    for _ in range(3):
        b.run("document.querySelector('#shortcuts .remove').click()")
        wait_for(b, "false", 400)
    checks["sites can be removed"] = wait_for(
        b, "document.querySelectorAll('#shortcuts a').length===0"
    )
    checks["Add a site shows by itself when nothing is pinned"] = b.run(
        f"var v={VISIBLE};return v(document.getElementById('add-open'))"
    )
    b.get("chrome://newtab")
    checks["removed defaults stay removed"] = wait_for(
        b,
        "document.getElementById('shortcuts') && "
        "document.querySelectorAll('#shortcuts a').length===0",
    ) and not wait_for(b, "document.querySelectorAll('#shortcuts a').length>0", 1500)


def read_recent(b, want, timeout=20):
    """Reloads the new tab page until it lists want pages (history is
    written a moment after a visit), and returns what it shows."""
    deadline = time.monotonic() + timeout
    got = None
    while time.monotonic() < deadline:
        b.get("chrome://newtab")
        wait_for(b, "location.host==='boring-newtab'")
        wait_for(b, f"document.querySelectorAll('#recent-list a').length>={want}", 1500)
        got = b.run(RECENT)
        if len(got["rows"]) >= want:
            break
    return got


def recent_checks(profile, pages, checks):
    """Four pages visited: the three newest are offered, newest first."""
    args = [RESOLVE, "--window-size=1360,900"]
    with Browser(user_data_dir=profile, args=args, keep_switches=["enable-automation"]) as b:
        for path in ("/one", "/two", "/three", "/four"):
            b.get(pages.url(TEST_SITE, path))
            time.sleep(0.6)
        got = read_recent(b, 3)
        rows = got["rows"]
        urls = [pages.url(TEST_SITE, p) for p in ("/four", "/three", "/two")]
        checks["Pick up where you left off lists the 3 newest pages"] = bool(
            got["shown"] and len(rows) == 3
        )
        checks["newest first, the oldest left out"] = [r["href"] for r in rows] == urls
        checks["a row shows title, site and when"] = bool(
            len(rows) == 3
            and rows[1]["title"] == "Page three"
            and rows[1]["site"] == TEST_SITE
            and rows[1]["when"] == "Today"
        )
        checks["a title with markup shows as plain text"] = bool(
            rows and rows[0]["title"] == MARKUP_TITLE and got["markup"] == 0
        )
        checks["the heading says Pick up where you left off"] = b.run(
            "return document.getElementById('recent-label').textContent"
            "==='Pick up where you left off'"
        )
        print("  recent:", json.dumps(rows)[:400])
        # With three rows the whole page, protection line included, fits a
        # 1404x631 window with no scrollbar.
        b._req(
            "POST",
            f"/session/{b.sid}/window/rect",
            {"x": -32000, "y": -32000, "width": 1404, "height": 631},
        )
        checks["no scrollbar at 631 px window height"] = wait_for(
            b,
            "window.innerHeight<600 && document.documentElement.scrollHeight"
            "<=document.documentElement.clientHeight",
        )
        checks["Protection line is visible at 631 px window height"] = wait_for(
            b,
            "document.getElementById('protection').getBoundingClientRect().height>0"
            " && document.getElementById('protection').getBoundingClientRect().bottom"
            "<=window.innerHeight",
        )
    # The same profile as a private window: none of its past.
    with Browser(
        user_data_dir=profile,
        args=[RESOLVE, "--incognito", "--window-size=1360,900"],
        keep_switches=["enable-automation"],
    ) as b:
        b.get("chrome://boring-newtab")
        wait_for(b, "!document.getElementById('protection').hidden", 15000)
        time.sleep(1.5)
        got = b.run(RECENT)
        checks["Incognito shows no Pick up section"] = bool(
            not got["shown"] and not got["rows"]
        )


# The page takes the window's colours (item 25): each Look, light or dark,
# and a custom accent recolour it. Values are the mixer's palettes
# (boring_color_mixer.cc): page token, toolbar, field, ink, accent.
LOOKS = (
    ("Slate light", "slate", None, [],
     ("rgb(245, 246, 248)", "rgb(255, 255, 255)", "rgb(238, 240, 246)",
      "rgb(35, 36, 46)", "rgb(79, 70, 229)")),
    ("Dusk dark", "dusk", None, ["--force-dark-mode"],
     ("rgb(20, 21, 32)", "rgb(27, 29, 43)", "rgb(38, 40, 56)",
      "rgb(220, 221, 230)", "rgb(157, 154, 255)")),
    ("Soft white with a teal accent", None, "#12a4b6", [],
     (LIGHT_PAGE, "rgb(255, 255, 255)", "rgb(244, 243, 239)",
      "rgb(31, 30, 28)", "rgb(18, 164, 182)")),
)
LOOK_NAMES = ("page", "surface", "field", "ink", "accent")
LOOK_PROBE = """
  var d = document.createElement('div');
  document.body.appendChild(d);
  var r = {};
  for (var k of arguments[0]) {
    d.style.color = 'var(--' + k + ')';
    r[k] = getComputedStyle(d).color;
  }
  d.remove();
  return r;
"""


def look_checks(checks):
    from smoke_colours import seed_profile

    for label, look, accent, extra, values in LOOKS:
        want = dict(zip(LOOK_NAMES, values))
        with tempfile.TemporaryDirectory(prefix="newtab-look-", dir=os.environ.get("TMP") or None) as prof:
            seed_profile(prof, look, accent)
            with Browser(user_data_dir=prof, args=[TEST_SWITCH, *extra]) as b:
                b.get("chrome://newtab")
                wait_for(b, f"getComputedStyle(document.body).backgroundColor==='{want['page']}'", 5000)
                got = b.run(LOOK_PROBE, [list(LOOK_NAMES)])
        print(f"  {label}: {got}")
        checks[f"{label}: page, tiles, field, text and focus ring follow the Look and accent"] = got == want


def capture(profile, checks):
    """Light and dark photographs of our own window, beside C01 and C02."""
    if not headful_allowed():
        print("SKIP: light and dark captures (set BORING_ALLOW_HEADFUL=1)")
        return
    import ctypes

    from capture_native import frame_window, grab
    from drive import CHROME

    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    for name, extra, screen, dark, paper in (
        ("light", [], "C01", False, LIGHT_PAGE),
        ("dark", ["--force-dark-mode"], "C02", True, DARK_PAGE),
    ):
        with Browser(
            user_data_dir=profile,
            args=[RESOLVE, "--window-size=1360,900", *extra],
            headful=True,
        ) as b:
            b.get("chrome://newtab")
            wait_for(b, "!document.getElementById('protection').hidden", 15000)
            wait_for(b, "document.querySelectorAll('#recent-list a').length>0", 5000)
            checks[f"{name}: page colour is the TOKENS page colour"] = b.run(
                f"return getComputedStyle(document.body).backgroundColor==='{paper}'"
            )
            time.sleep(1.0)
            hwnd = frame_window(CHROME, under=b.proc.pid)
            shot = OUT / f"newtab-{name}.png"
            grab(hwnd, str(shot))
            both = page_checks.beside(shot, screen, OUT, dark=dark)
            print(f"saved {shot}" + (f" and {both}" if both else ", no design picture"))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    static_checks(checks)
    with (
        tempfile.TemporaryDirectory(prefix="newtab-", dir=os.environ.get("TMP") or None) as fresh,
        Browser(
            user_data_dir=fresh,
            args=[TEST_SWITCH, "--window-size=1360,900"],
            # The automation infobar would take 56 px off a 631 px window.
            keep_switches=["enable-automation"],
        ) as b,
    ):
        shape_checks(b, checks)
    look_checks(checks)
    pages = Pages(PAGES)
    try:
        with tempfile.TemporaryDirectory(prefix="newtab-hist-", dir=os.environ.get("TMP") or None) as profile:
            recent_checks(profile, pages, checks)
            capture(profile, checks)
    finally:
        pages.close()

    (OUT / "newtab-checks.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
