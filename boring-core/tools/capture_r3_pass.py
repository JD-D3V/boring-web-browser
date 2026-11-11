#!/usr/bin/env python3
"""Photographs for the Release 3 real-window pass, light and dark.

Three groups, each photographed with PrintWindow of our own browser window
only (capture_native.grab), never the screen, and with nothing sent to the
OS as input. Windows are placed off screen (drive.py).

  webui   the Settings pages the five Settings patches touch (what to look
          at is in .workflow/scratch/port-157-progress.md, "Settings
          patches"), Settings under 800 px wide, the Protection page,
          Welcome, new tab and the screen takeover page
  tabs    the tab strip in the states the four tab patches style (tab-shape,
          tab-underline, tab-mock-metrics, tab-separator-pinned): plain tabs,
          pinned tabs beside plain ones with a plain tab active, and with a
          pinned tab active; and the toolbar with the address bar focused
  quad9   the warning for a site Quad9 blocks, set up as in
          smoke_dns_warning.py (a local stand-in plays the DNS server)

The scam and look-alike warning pages, the app menu and side tabs have
their own capture tools, which the pass runs as well.

    python capture_r3_pass.py --out DIR [--group webui tabs quad9] [--dry-run]

A shot that fails is reported and the rest go on. Exit 0 when every shot
was taken, 1 when some were not. Needs a dedicated test session:
BORING_ALLOW_HEADFUL=1, and BORING_OUT pointing at the build.
"""

import argparse
import contextlib
import ctypes
import json
import os
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SIZE = (1404, 900)
NARROW = (760, 900)
# Same setting as capture_native.py: the browser keeps drawing a window that
# sits off screen, and it photographs from the window, not the screen.
KEEP_DRAWING = [
    "--disable-backgrounding-occluded-windows",
    "--disable-features=CalculateNativeWinOcclusion",
]
FOCUS_HOOK = "--boring-focus-omnibox"
FOCUS_HOOK_WAIT = 6.0

# (file name, address, size). The Settings pages are the ones named in the
# "what to look at" notes of the five Settings patches.
WEBUI_PAGES = [
    ("settings-main", "chrome://settings", SIZE),
    ("settings-protection", "chrome://settings/protection", SIZE),
    ("settings-reading", "chrome://settings/reading", SIZE),
    ("settings-summaries", "chrome://settings/summaries", SIZE),
    ("settings-autofill", "chrome://settings/autofill", SIZE),
    ("settings-payments", "chrome://settings/payments", SIZE),
    ("settings-on-startup", "chrome://settings/onStartup", SIZE),
    ("settings-search-engines", "chrome://settings/searchEngines", SIZE),
    ("settings-performance", "chrome://settings/performance", SIZE),
    ("settings-appearance", "chrome://settings/appearance", SIZE),
    ("settings-appearance-narrow", "chrome://settings/appearance", NARROW),
    ("protection", "chrome://boring-protection", SIZE),
    ("welcome", "chrome://boring-welcome", SIZE),
    ("new-tab", "chrome://boring-newtab", SIZE),
    ("takeover-page", "chrome://boring-takeover/?site=example.com", SIZE),
]

# (file name, plain tabs besides the first, pinned tabs, which one is active)
TAB_STATES = [
    ("tabs-plain", 4, 0, "middle"),
    ("tabs-pinned-plain-active", 3, 2, "last"),
    ("tabs-pinned-pinned-active", 3, 2, "pinned"),
]

SCHEMES = [("light", []), ("dark", ["--force-dark-mode"])]


def plan(groups):
    """Every file this run will write, as (group, name)."""
    out = []
    for scheme, _ in SCHEMES:
        if "webui" in groups:
            out += [("webui", f"{n}-{scheme}.png") for n, _, _ in WEBUI_PAGES]
        if "tabs" in groups:
            out += [("tabs", f"{n}-{scheme}.png") for n, *_ in TAB_STATES]
            out.append(("tabs", f"toolbar-focus-{scheme}.png"))
        if "quad9" in groups:
            out.append(("quad9", f"quad9-warning-{scheme}.png"))
    return out


class Report:
    def __init__(self):
        self.taken, self.failed = [], []

    def run(self, name, fn):
        try:
            fn()
            self.taken.append(name)
        except Exception as e:  # one bad shot must not stop the others
            self.failed.append((name, repr(e)))
            print(f"FAILED {name}: {e!r}", flush=True)
            traceback.print_exc()


def photograph(b, binary, size, path, settle):
    """One PrintWindow of the browser window this driver started."""
    from capture_native import frame_window, grab, user32
    from drive import OFFSCREEN

    time.sleep(settle)
    hwnd = frame_window(binary, under=b.proc.pid)
    px, py = (
        int(v) for v in os.environ.get("BORING_WINDOW_POSITION", OFFSCREEN).split(",")
    )
    user32.MoveWindow(hwnd, px, py, size[0], size[1], True)
    time.sleep(0.6)
    w, h = grab(hwnd, str(path))
    print(f"saved {path} {w}x{h}", flush=True)


def browser(extra, size, profile):
    from drive import Browser

    args = KEEP_DRAWING + list(extra) + [f"--window-size={size[0]},{size[1]}"]
    # chromedriver's "controlled by automated test software" bar names the
    # wrong product and is not the browser; capture_native.py drops it too.
    return Browser(
        user_data_dir=profile,
        args=args,
        keep_switches=["enable-automation"],
        headful=True,
    )


def tmp_profile(prefix):
    return tempfile.TemporaryDirectory(
        prefix=prefix, dir=os.environ.get("TMP") or None, ignore_cleanup_errors=True
    )


def group_webui(out, binary, report):
    for scheme, flags in SCHEMES:
        # One browser per scheme and size: each page is a navigation.
        for size in (SIZE, NARROW):
            pages = [p for p in WEBUI_PAGES if p[2] == size]
            with contextlib.ExitStack() as stack:
                try:
                    profile = stack.enter_context(tmp_profile("r3pass-webui-"))
                    b = stack.enter_context(browser(flags, size, profile))
                except Exception as e:
                    for name, _, _ in pages:
                        report.failed.append((f"{name}-{scheme}", f"browser: {e!r}"))
                    continue
                for name, url, _ in pages:

                    def shot(name=name, url=url, b=b, size=size, scheme=scheme):
                        b.get(url)
                        photograph(b, binary, size, out / f"{name}-{scheme}.png", 2.5)

                    report.run(f"{name}-{scheme}", shot)


class PageServer:
    """Plain pages with a title, for the tabs that are not the first."""

    def __init__(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                title = self.path.strip("/") or "page"
                body = f"<title>{title}</title><h1>{title}</h1>".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, title):
        return f"http://127.0.0.1:{self.port}/{title.replace(' ', '-')}"

    def close(self):
        self.server.shutdown()


def pinned_extension(root, urls):
    """A tiny add-on that opens pinned tabs once, as smoke_tabs.py drives
    tabs through chrome.tabs. A loaded unpacked add-on can make the browser
    show its developer-mode bubble, which then appears in these shots."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 3,
                "name": "Boring pass pinned tabs",
                "version": "1.0",
                "permissions": ["tabs"],
                "background": {"service_worker": "bg.js"},
            }
        ),
        encoding="utf-8",
    )
    (root / "bg.js").write_text(
        "chrome.runtime.onInstalled.addListener(async () => {\n"
        f"  for (const url of {json.dumps(urls)}) {{\n"
        "    await chrome.tabs.create({url, pinned: true, active: false});\n"
        "  }\n"
        "});\n",
        encoding="utf-8",
    )
    return str(root)


def handles(b):
    return b._req("GET", f"/session/{b.sid}/window/handles")["value"]


def switch(b, handle):
    b._req("POST", f"/session/{b.sid}/window", {"handle": handle})


def titles(b):
    found = {}
    for h in handles(b):
        switch(b, h)
        found[h] = b.run("return document.title")
    return found


def wait_for_tabs(b, count, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        if len(handles(b)) >= count:
            return True
        time.sleep(0.3)
    return False


def group_tabs(out, binary, report):
    pages = PageServer()
    try:
        for scheme, flags in SCHEMES:
            for name, plain, pinned, active in TAB_STATES:

                def shot(
                    name=name,
                    plain=plain,
                    pinned=pinned,
                    active=active,
                    flags=flags,
                    scheme=scheme,
                ):
                    with tmp_profile("r3pass-tabs-") as profile:
                        extra = list(flags)
                        if pinned:
                            urls = [pages.url(f"Pinned {n + 1}") for n in range(pinned)]
                            ext = pinned_extension(Path(profile) / "ext", urls)
                            extra.append(f"--load-extension={ext}")
                        with browser(extra, SIZE, profile) as b:
                            b.get(pages.url("First tab"))
                            for n in range(plain):
                                b.run(
                                    "window.open(arguments[0])",
                                    [pages.url(f"Tab {n + 2}")],
                                )
                                time.sleep(0.3)
                            if not wait_for_tabs(b, 1 + plain + pinned):
                                raise RuntimeError(
                                    f"only {len(handles(b))} tabs opened"
                                )
                            by_title = titles(b)
                            want = {
                                "middle": f"Tab-{2 + plain // 2}",
                                "last": f"Tab-{1 + plain}",
                                "pinned": "Pinned-1",
                            }[active]
                            target = [h for h, t in by_title.items() if t == want]
                            if not target:
                                raise RuntimeError(
                                    f"no tab titled {want!r}: {sorted(by_title.values())}"
                                )
                            switch(b, target[0])
                            photograph(
                                b, binary, SIZE, out / f"{name}-{scheme}.png", 2.0
                            )

                report.run(f"{name}-{scheme}", shot)

            def toolbar(scheme=scheme, flags=flags):
                with (
                    tmp_profile("r3pass-toolbar-") as profile,
                    browser([*flags, FOCUS_HOOK], SIZE, profile) as b,
                ):
                    b.get("chrome://boring-newtab")
                    photograph(
                        b,
                        binary,
                        SIZE,
                        out / f"toolbar-focus-{scheme}.png",
                        FOCUS_HOOK_WAIT,
                    )

            report.run(f"toolbar-focus-{scheme}", toolbar)
    finally:
        pages.close()


def group_quad9(out, binary, report):
    import smoke_dns_warning as dns
    from smoke_local import wait_for

    doh, pages = dns.FakeDoh(), dns.Pages()
    try:
        for scheme, flags in SCHEMES:

            def shot(scheme=scheme, flags=flags):
                from drive import Browser

                with tmp_profile("r3pass-quad9-") as profile:
                    dns.seed_profile(profile, "secure", dns.QUAD9)
                    args = dns.browser_args(doh, pages) + list(flags)
                    with Browser(user_data_dir=profile, args=args, headful=True) as b:
                        dns.open_url(b, pages.url())
                        wait_for(b, "!!document.getElementById('ok')")
                        dns.open_url(b, f"http://{dns.BLOCKED}/")
                        if not wait_for(b, dns.WARNED):
                            raise RuntimeError("the Quad9 warning never appeared")
                        photograph(
                            b, binary, SIZE, out / f"quad9-warning-{scheme}.png", 1.5
                        )

            report.run(f"quad9-warning-{scheme}", shot)
    finally:
        doh.close()
        pages.close()


GROUPS = {"webui": group_webui, "tabs": group_tabs, "quad9": group_quad9}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="folder for the pictures")
    ap.add_argument(
        "--group", nargs="+", choices=sorted(GROUPS), default=sorted(GROUPS)
    )
    ap.add_argument("--dry-run", action="store_true", help="print the files and stop")
    args = ap.parse_args()

    files = plan(args.group)
    if args.dry_run:
        print(f"{len(files)} pictures into {args.out}:")
        for group, name in files:
            print(f"  [{group}] {name}")
        return 0

    from drive import CHROME, require_headful

    require_headful()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    binary = os.environ.get("BORING_CHROME", CHROME)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = Report()
    for group in args.group:
        print(f"\n=== {group} ===", flush=True)
        GROUPS[group](out, binary, report)

    print(f"\n{len(report.taken)} taken, {len(report.failed)} failed")
    for name, why in report.failed:
        print(f"  not taken: {name}: {why}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
