#!/usr/bin/env python3
"""Smoke test and photographs for tab groups (compiled UI ledger item 4).

What it checks, on top tabs and on Chromium's own side tabs, light and dark:
- the group's label is a solid chip in the group colour, with its text in
  the ink Chromium picks for it (white on a dark colour, near black on a
  light one);
- a wash of the group colour behind every tab of the group, unbroken from
  the label to the last tab (no separators inside the group);
- one 3 DIP line in the group colour under the whole group (top tabs), or
  down the side of it (side tabs);
- all nine group colours, each with its label, wash and 3 DIP line.

Groups are made by a small test extension loaded with --load-extension: its
page calls chrome.tabs.group and chrome.tabGroups.update, and WebDriver
drives that page. The window is drawn with PrintWindow of our own browser
window only; nothing is sent to the OS as input. Each photograph is put
beside the matching compiled screen in compare.html in the output folder.
With --captures (or BORING_CAPTURES) the top tabs and side tabs pictures are
also saved as <folder>/tabgroups/c01-light.png, c09-light.png and the dark
pair: the real capture on the left, the compiled screen on the right.

    python smoke_tabgroups.py                    # wired: smoke_all
    python smoke_tabgroups.py --out E:/tmp/tg --only dark [--captures FOLDER]

Needs the built browser (BORING_OUT / BORING_CHROME as for the smoke tests)
and BORING_ALLOW_HEADFUL=1.
"""

import argparse
import ctypes
import json
import math
import os
import re
import struct
import sys
import tempfile
import time
import zlib
from collections import Counter
from pathlib import Path

import page_checks

TOOLS = Path(__file__).resolve().parent
CORE = TOOLS.parent
MIXER = CORE / "chromium_src/chrome/browser/ui/color/boring_color_mixer.cc"
DESIGN = page_checks.SHOTS

# (scene, extra switches, matching compiled screens: top tabs, side tabs)
SCENES = [
    ("light", [], ("c01-newtab.png", "c09-sidetabs.png")),
    ("dark", ["--force-dark-mode"], ("dark/c01-newtab.png", "dark/c09-sidetabs.png")),
]
COLOURS = ["grey", "blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange"]
# The label ink Chromium picks (color_utils::GetColorWithMaxContrast).
WHITE = (0xFF, 0xFF, 0xFF)
DARKEST = (0x20, 0x21, 0x24)
LINE_DIP = 3
TOLERANCE = 4

EXTENSION_NAME = "Tab group smoke"
EXTENSION = {
    "manifest.json": json.dumps(
        {
            "manifest_version": 3,
            "name": EXTENSION_NAME,
            "version": "1",
            "permissions": ["tabs", "tabGroups"],
            "background": {"service_worker": "bg.js"},
        }
    ),
    "bg.js": "chrome.runtime.onInstalled.addListener(() =>"
    " chrome.tabs.create({url: 'run.html', active: true}));",
    "run.html": "<!doctype html><title>Group test</title><script src=run.js></script>",
    "page.html": "<!doctype html><title>page</title><script src=page.js></script>",
    "page.js": "document.title = new URLSearchParams(location.search).get('t');",
    "run.js": r"""
const COLOURS = %s;
const cap = (s) => s[0].toUpperCase() + s.slice(1);
const page = (t) => chrome.runtime.getURL('page.html?t=' + encodeURIComponent(t));
async function me() { return chrome.tabs.getCurrent(); }
async function clear() {
  const self = await me();
  const all = await chrome.tabs.query({windowId: self.windowId});
  const others = all.filter((t) => t.id !== self.id).map((t) => t.id);
  if (others.length) await chrome.tabs.remove(others);
}
async function open(titles) {
  const ids = [];
  for (const t of titles) ids.push((await chrome.tabs.create({url: page(t), active: false})).id);
  return ids;
}
async function group(ids, title, color) {
  const g = await chrome.tabs.group({tabIds: ids});
  await chrome.tabGroups.update(g, {title, color, collapsed: false});
}
async function finish() {
  const self = await me();
  await chrome.tabs.move(self.id, {index: -1});
  await chrome.tabs.update(self.id, {active: true});
  const groups = await chrome.tabGroups.query({windowId: self.windowId});
  const tabs = await chrome.tabs.query({windowId: self.windowId});
  return groups.map((g) => ({title: g.title, color: g.color, collapsed: g.collapsed,
                             tabs: tabs.filter((t) => t.groupId === g.id).length}));
}
// Screen 1: Local news, the Trip group of three, Weather, then this page.
window.sceneTrip = async () => {
  await clear();
  await open(['Local news']);
  await group(await open(['Train times', 'Hotel booking', 'City map']), 'Trip', 'cyan');
  await open(['Weather']);
  return finish();
};
window.sceneColours = async () => {
  await clear();
  for (const c of COLOURS) await group(await open([cap(c) + ' page']), cap(c), c);
  return finish();
};
window.openBlank = async () => (await chrome.tabs.create({url: 'about:blank', active: true})).id;
""" % json.dumps(COLOURS),
}


# --- colours ---------------------------------------------------------------

def hex_rgb(text):
    return tuple(int(v, 16) for v in re.findall(r"0x([0-9a-fA-F]{2})", text))


def group_colours(mixer_text=None):
    """{colour: (light rgb, dark rgb)} from our block in boring_color_mixer.cc."""
    text = mixer_text if mixer_text is not None else MIXER.read_text(encoding="utf-8")
    block = text.split("// boring: cui-tabgroups", 1)[1].split("// boring: end cui-tabgroups", 1)[0]
    found = {}
    for m in re.finditer(
        r"kColorTabGroupTabStripFrameActive(\w+),\s*kColorTabGroupTabStripFrameInactive\1,"
        r"\s*SkColorSetRGB\(([^)]*)\),\s*SkColorSetRGB\(([^)]*)\)",
        block,
    ):
        found[m.group(1).lower()] = (hex_rgb(m.group(2)), hex_rgb(m.group(3)))
    return found


def luminance(rgb):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def is_dark(rgb):
    # color_utils::IsDark: luminance under the midpoint where white and
    # the darkest colour contrast equally.
    return luminance(rgb) < 0.211692036


def label_ink(group_rgb):
    return WHITE if is_dark(group_rgb) else DARKEST


def tint(group_rgb, dark):
    """TabGroupStyle::GetTabTint, for a light or a dark strip."""
    base, alpha = ((0, 0, 0), 0.22) if dark else ((255, 255, 255), 0.15)
    return tuple(round(g * alpha + b * (1 - alpha)) for g, b in zip(group_rgb, base))


# --- pictures --------------------------------------------------------------

def read_png(path):
    """(width, height, rows of RGB tuples) for a PNG written by
    capture_native.write_png (8-bit RGB, filter 0 on every row)."""
    data = Path(path).read_bytes()
    pos, idat, w, h = 8, b"", 0, 0
    while pos < len(data):
        length, tag = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        if tag == b"IHDR":
            w, h = struct.unpack(">II", body[:8])
        elif tag == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    rows, stride = [], 1 + 3 * w
    for y in range(h):
        line = raw[y * stride + 1 : (y + 1) * stride]
        rows.append([tuple(line[i : i + 3]) for i in range(0, len(line), 3)])
    return w, h, rows


def near(a, b, tol=TOLERANCE):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def runs(values):
    """(start, length) of each run of True."""
    out, start = [], None
    for i, v in enumerate(values + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - start))
            start = None
    return out


def top_group(rows, group_rgb, tint_rgb, scale, x0=0, x1=None, band=None):
    """Measure one group of top tabs in the strip between x0 and x1."""
    band = band or int(70 * scale)
    x1 = x1 or len(rows[0])
    found = {"line_px": 0, "line_len": 0, "tint_len": 0, "chip_px": 0, "chip_ink": 0}
    # The line: short vertical runs of the group colour. The chip's runs
    # are taller and left out.
    lengths, tops = Counter(), Counter()
    for x in range(x0, x1):
        column = [near(rows[y][x], group_rgb) for y in range(band)]
        for start, length in runs(column):
            if length <= 6 * scale:
                lengths[length] += 1
                tops[start] += 1
    if not lengths:
        return found
    found["line_px"] = lengths.most_common(1)[0][0]
    line_top = tops.most_common(1)[0][0]
    mid = line_top + found["line_px"] // 2
    found["line_len"] = max(
        (n for _, n in runs([near(p, group_rgb) for p in rows[mid][x0:x1]])), default=0
    )
    above = line_top - max(2, round(2 * scale))
    found["tint_len"] = max(
        (n for _, n in runs([near(p, tint_rgb) for p in rows[above][x0:x1]])), default=0
    )
    # The chip: the group colour above the line, and the ink inside it.
    chip = [
        (x, y)
        for y in range(max(0, line_top - int(30 * scale)), line_top - 1)
        for x in range(x0, x1)
        if near(rows[y][x], group_rgb)
    ]
    found["chip_px"] = len(chip)
    if chip:
        cx0, cx1 = min(x for x, _ in chip), max(x for x, _ in chip)
        cy0, cy1 = min(y for _, y in chip), max(y for _, y in chip)
        ink = label_ink(group_rgb)
        found["chip_ink"] = sum(
            1
            for y in range(cy0, cy1 + 1)
            for x in range(cx0, cx1 + 1)
            if near(rows[y][x], ink, 40)
        )
    return found


def line_width_ok(px, scale):
    """3 DIP in pixels: exactly 3 at 100%, either neighbour at a fractional scale."""
    return px in {math.floor(LINE_DIP * scale), math.ceil(LINE_DIP * scale)}


def top_group_ok(found, scale, min_len):
    return {
        "line is 3 DIP": line_width_ok(found["line_px"], scale),
        "line under the group": found["line_len"] >= min_len * scale,
        "wash unbroken along the group": found["tint_len"] >= 0.85 * found["line_len"] > 0,
        "solid label": found["chip_px"] >= 150 * scale * scale,
        "label text in its ink": found["chip_ink"] >= 8,
    }


def side_group(rows, group_rgb, tint_rgb, scale, x1=None):
    """Measure a group of side tabs in the left part of the window."""
    x1 = x1 or int(120 * scale)
    widths, starts = Counter(), Counter()
    for y in range(len(rows)):
        for start, length in runs([near(p, group_rgb) for p in rows[y][:x1]]):
            if length <= 6 * scale:
                widths[length] += 1
                starts[start] += 1
    found = {"line_px": 0, "line_rows": 0, "tint_px": 0}
    if not widths:
        return found
    found["line_px"] = widths.most_common(1)[0][0]
    x = starts.most_common(1)[0][0] + found["line_px"] // 2
    found["line_rows"] = max(
        (n for _, n in runs([near(r[x], group_rgb) for r in rows])), default=0
    )
    found["tint_px"] = sum(
        1 for r in rows for p in r[x : int(300 * scale)] if near(p, tint_rgb)
    )
    return found


def side_group_ok(found, scale):
    return {
        "side line is 3 DIP": line_width_ok(found["line_px"], scale),
        "side line runs down the group": found["line_rows"] >= 60 * scale,
        "side tabs on the wash": found["tint_px"] >= 1500 * scale * scale,
    }


# --- the browser -------------------------------------------------------------

def write_extension(folder):
    for name, text in EXTENSION.items():
        (folder / name).write_text(text, encoding="utf-8")
    return str(folder)


def extension_id(b):
    """The test extension's id, read from chrome://extensions-internals."""
    b.get("chrome://extensions-internals")
    deadline = time.time() + 10
    while time.time() < deadline:
        text = b.run("return document.body.innerText") or ""
        try:
            for ext in json.loads(text):
                if ext.get("name") == EXTENSION_NAME:
                    return ext["id"]
        except ValueError:
            pass
        time.sleep(0.5)
    return None


def run_page(b, timeout=20):
    """Switch WebDriver to the extension's page and return its handle.

    The extension opens run.html itself when it is installed, but in this
    build onInstalled does not open the tab for an extension loaded from
    the command line, so the page is opened by its address instead.
    """
    deadline = time.time() + timeout
    opened = False
    while time.time() < deadline:
        for hd in b._req("GET", f"/session/{b.sid}/window/handles")["value"]:
            b._req("POST", f"/session/{b.sid}/window", {"handle": hd})
            url = b.current_url()
            if url.startswith("chrome-extension://") and url.endswith("/run.html"):
                return hd
        if not opened and time.time() > deadline - timeout + 3:
            opened = True
            ext = extension_id(b)
            if ext:
                b.get(f"chrome-extension://{ext}/run.html")
        time.sleep(0.5)
    raise RuntimeError("the test extension's page did not open")


def call(b, fn):
    return b.run_async(
        "const done = arguments[arguments.length - 1];"
        f"window.{fn}().then(done, (e) => done({{error: String(e)}}));"
    )


def run_scene(name, extra, design, out, size, binary, captures=None):
    from capture_native import frame_window, grab, user32
    from drive import OFFSCREEN, Browser
    from smoke_vtabs import set_pref

    dark = name == "dark"
    palette = group_colours()
    w, h = size
    results, shots = {}, []
    with tempfile.TemporaryDirectory(prefix="tabgroups-", dir=os.environ.get("TMP")) as work:
        ext = Path(work) / "ext"
        ext.mkdir()
        args = [
            f"--window-size={w},{h}",
            "--window-position=" + OFFSCREEN,
            "--load-extension=" + write_extension(ext),
        ] + extra
        with Browser(
            user_data_dir=str(Path(work) / "profile"),
            args=args,
            keep_switches=["enable-automation"],
            headful=True,
        ) as b:
            hwnd = frame_window(binary, under=b.proc.pid)
            scale = user32.GetDpiForWindow(hwnd) / 96.0
            px, py = (int(v) for v in OFFSCREEN.split(","))

            def shoot(label, against):
                user32.MoveWindow(hwnd, px, py, w, h, True)
                time.sleep(1.2)
                path = out / f"tabgroups-{label}-{name}.png"
                grab(hwnd, str(path))
                shots.append((path, DESIGN / against))
                screen = {"top": "c01", "side": "c09"}.get(label)
                if screen:
                    saved = page_checks.save_capture(path, "tabgroups", screen, dark=dark, folder=captures)
                    if saved:
                        print("saved", saved)
                return read_png(path)[2]

            run_page(b)
            groups = call(b, "sceneTrip")
            results["trip group made"] = groups == [
                {"title": "Trip", "color": "cyan", "collapsed": False, "tabs": 3}
            ]
            light_rgb, dark_rgb = palette["cyan"]
            g = dark_rgb if dark else light_rgb
            found = top_group(shoot("top", design[0]), g, tint(g, dark), scale)
            print(name, "top Trip", found)
            for k, v in top_group_ok(found, scale, 300).items():
                results["top: " + k] = v

            groups = call(b, "sceneColours")
            results["nine groups made"] = sorted(x["color"] for x in groups) == sorted(COLOURS)
            rows = shoot("colours", design[0])
            for colour in COLOURS:
                light_rgb, dark_rgb = palette[colour]
                g = dark_rgb if dark else light_rgb
                found = top_group(rows, g, tint(g, dark), scale)
                print(name, colour, found)
                for k, v in top_group_ok(found, scale, 40).items():
                    results[f"{colour}: {k}"] = v

            # Side tabs: switch them on the way Settings does, on a tab of
            # its own, then go back to the extension's page.
            page_handle = run_page(b)
            call(b, "openBlank")
            for hd in b._req("GET", f"/session/{b.sid}/window/handles")["value"]:
                if hd != page_handle:
                    b._req("POST", f"/session/{b.sid}/window", {"handle": hd})
                    break
            ok, val = set_pref(b, True)
            results["side tabs on"] = bool(ok) and val is True
            b._req("POST", f"/session/{b.sid}/window", {"handle": page_handle})
            call(b, "sceneTrip")
            light_rgb, dark_rgb = palette["cyan"]
            g = dark_rgb if dark else light_rgb
            found = side_group(shoot("side", design[1]), g, tint(g, dark), scale)
            print(name, "side Trip", found)
            results.update(side_group_ok(found, scale))
    return results, shots


def write_compare(out, shots):
    cells = "".join(
        f'<tr><td><img src="{ours.as_uri()}" width="640"><br>{ours.name}</td>'
        f'<td><img src="{theirs.as_uri()}" width="640"><br>compiled {theirs.name}</td></tr>'
        for ours, theirs in shots
    )
    page = f"<!doctype html><title>Tab groups</title><table>{cells}</table>"
    (out / "compare.html").write_text(page, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=os.path.join(os.environ.get("TMP") or tempfile.gettempdir(), "smoke-tabgroups"),
        help="output folder (default: smoke-tabgroups under TMP)",
    )
    ap.add_argument("--only", help="one scene name: light or dark")
    ap.add_argument("--size", default="1404x800")
    page_checks.add_captures_option(ap)
    args = ap.parse_args()
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    from drive import CHROME

    size = tuple(int(v) for v in args.size.lower().split("x"))
    binary = os.environ.get("BORING_CHROME", CHROME)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    bad, shots = [], []
    for name, extra, design in SCENES:
        if args.only and args.only != name:
            continue
        res, taken = run_scene(name, extra, design, out, size, binary, args.captures)
        shots += taken
        for k, v in res.items():
            print("ok  " if v else "FAIL", name, k)
            if not v:
                bad.append(f"{name}: {k}")
    write_compare(out, shots)
    print("pictures and compare.html in", out)
    if bad:
        print("FAIL: tab groups,", len(bad), "failed")
        sys.exit(1)
    print("PASS: tab groups")


if __name__ == "__main__":
    main()
