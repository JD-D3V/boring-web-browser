#!/usr/bin/env python3
"""Check the small UI fixes that follow the colour choice and the page layout.

Under each colour scheme (Cool is the default; Green is --boring-scheme)
and in light and dark, the colours the browser's own colour provider hands
out must follow the accent:

  * selected text (the address bar's selection and Chromium's own pages)
    is filled with the accent, with the same text colour a filled accent
    button uses, so it no longer stays indigo under Green;
  * the side tab strip's buttons (new tab, tab search) are filled with the
    palette's wash of the accent, not a tone of the seed colour.

The colours are read back as resolved CSS variables from
chrome://theme/colors.css, which comes from the same colour provider the
native views use. The palette values below mirror boring_color_mixer.cc.

Also the Protection page: with no site listed, the "Sites with blocking
off" row is built like every other row (same height apart from its own
description), because an empty list used to add 10px of margin.

Pictures of the real window are taken with capture_native.py.
"""

import json
import re
import sys
import tempfile
import time
from pathlib import Path

from drive import Browser

OUT = Path(__file__).resolve().parents[2] / "artifacts/ui-implemented"

# scheme, dark -> (accent, wash of the accent, window), as in the mixer.
PALETTE = {
    ("cool", False): ((0x4F, 0x46, 0xE5), (0xE6, 0xE5, 0xFB), (0xDC, 0xDE, 0xE8)),
    ("cool", True): ((0x9D, 0x9A, 0xFF), (0x2A, 0x29, 0x50), (0x07, 0x08, 0x0B)),
    ("green", False): ((0x17, 0x6B, 0x5B), (0xE5, 0xEF, 0xED), (0xDC, 0xDE, 0xE8)),
    ("green", True): ((0x4F, 0xC9, 0xAE), (0x26, 0x3D, 0x40), (0x07, 0x08, 0x0B)),
}

NAMES = [
    "--color-sys-state-text-highlight",
    "--color-sys-state-on-text-highlight",
    "--color-omnibox-selection-background",
    "--color-omnibox-selection-foreground",
    "--color-new-tab-button-c-r-background-frame-active",
    "--color-new-tab-button-c-r-background-frame-inactive",
]

RESOLVE = r"""
  const out = {};
  const p = document.createElement('div');
  document.body.appendChild(p);
  for (const n of arguments[0]) {
    p.style.color = 'var(' + n + ')';
    out[n] = getComputedStyle(p).color;
  }
  return out;
"""


def wait_for(b, condition, timeout_ms=5000):
    """True once the JavaScript expression holds, false at the timeout."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        if b.run("return !!(" + condition + ")"):
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)


def rgb(triple):
    return "rgb({}, {}, {})".format(*triple)


def resolved_colours(scheme, dark, profile):
    """The scheme's colours as the colour provider resolves them."""
    args = ["--window-size=1200,700"]
    if scheme != "cool":
        args.append("--boring-scheme=" + scheme)
    if dark:
        args.append("--force-dark-mode")
    with Browser(user_data_dir=profile, args=args) as b:
        # The theme stylesheet is a plain text document at this address;
        # a settings page links it, so the same values resolve there.
        b.get("chrome://theme/colors.css?sets=ui,chrome")
        css = b.run("return document.documentElement.innerText")
        have = set(re.findall(r"(--color-[a-z0-9-]+):", css))
        b.get("chrome://settings/help")
        time.sleep(1.0)
        return have, b.run(RESOLVE, [NAMES])


# A row's own description can wrap, so compare the height of everything
# in the row that is not the description.
ROW_FRAME = r"""
  return [...document.querySelectorAll('.state-row')]
      .filter(row => row.getBoundingClientRect().height > 0)
      .map(row => [
          row.querySelector('strong').textContent,
          row.getBoundingClientRect().height -
              row.querySelector('p').getBoundingClientRect().height]);
"""


def protection_rows(profile):
    with Browser(user_data_dir=profile, args=["--window-size=1200,900"]) as b:
        b.get("chrome://boring-protection")
        ready = wait_for(
            b,
            "document.getElementById('off-sites-state').textContent==='None'"
            " && !document.querySelector('#off-sites li')",
            15000,
        )
        return ready, b.run(ROW_FRAME)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="polish-", dir=OUT) as base:
        for (scheme, dark), (accent, wash, window) in PALETTE.items():
            tag = f"{scheme} {'dark' if dark else 'light'}"
            have, got = resolved_colours(scheme, dark, f"{base}/{scheme}-{dark}")
            checks[f"{tag}: the colour provider has the ids"] = all(
                n in have for n in NAMES
            )
            on_accent = window if dark else (255, 255, 255)
            checks[f"{tag}: selected text is filled with the accent"] = (
                got[NAMES[0]] == rgb(accent) and got[NAMES[2]] == rgb(accent)
            )
            checks[f"{tag}: text on the selection is the on-accent colour"] = (
                got[NAMES[1]] == rgb(on_accent) and got[NAMES[3]] == rgb(on_accent)
            )
            checks[f"{tag}: side strip buttons are a wash of the accent"] = (
                got[NAMES[4]] == rgb(wash) and got[NAMES[5]] == rgb(wash)
            )
            if (scheme, dark) == ("cool", False):
                print("  cool light resolved:", json.dumps(got))

        ready, rows = protection_rows(f"{base}/protection")
        checks["Protection: a fresh profile lists no site with blocking off"] = ready
        frames = {name: height for name, height in rows}
        off = frames.get("Sites with blocking off")
        # The first row has no top border, so it is 1px shorter by design.
        first = rows[0][0] if rows else None
        others = [
            h
            for name, h in frames.items()
            if name not in ("Sites with blocking off", first)
        ]
        checks["Protection: the blocking off row is built like the others"] = bool(
            off is not None
            and others
            and all(abs(off - h) <= 0.5 for h in others)
        )
        if not checks["Protection: the blocking off row is built like the others"]:
            print("  row frames:", json.dumps(frames))

    (OUT / "ui-polish-checks.json").write_text(
        json.dumps(checks, indent=2), encoding="utf-8"
    )
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
    return int(not all(checks.values()))


if __name__ == "__main__":
    sys.exit(main())
