# The B mark

Approved by JD on 2026-09-19, from the review render in
`artifacts/brand-review/unifrakturcook-b.png`. This is the logo, not a
placeholder. **Do not change the shape, the geometry or the colours
without another review.**

## Where the glyph comes from

The B is the capital B of **UnifrakturCook Bold**, a blackletter face
from Google Fonts.

- Copyright 2010 j. 'mach' wust, with Reserved Font Name UnifrakturCook.
- Copyright 2009 Peter Wiegel.
- **SIL Open Font License 1.1.**
- Source: https://github.com/google/fonts/tree/main/ofl/unifrakturcook
- Downloaded 2026-09-19. SHA256 of the font file:
  `ea002fa9c65f1a612af100e00d87ab65f16381f450020ec3d021f3dbf79a6dcd`

The font and its licence are archived here, next to each other, because
the OFL requires the licence to travel with the font:

    source/UnifrakturCook-Bold.ttf
    source/UnifrakturCook-OFL.txt

The font is not modified. Its outline for one glyph is traced into SVG
paths and rasterised; the browser does not ship or load the font at run
time, and no OFL reserved name is used for anything we ship. The OFL
covers the font, not this browser.

`source/chromium_doc.ico` and `source/chromium_pdf.ico` are Chromium's
own document icons (BSD licence). Their page silhouettes are kept and
the Chromium emblem is replaced with the B tile.

## How the files are made

One master drives every slot:

    master/b-tile.svg    plate + B, 64 box, for app icons and favicons
    master/b-glyph.svg   B only, currentColor, for our own pages

From those, `tools/export_brand.py` writes every ICO, PNG, `.icon` and
the `brand_mark.h` header, under `chromium_src/`, so `tools/apply.py`
overlays them onto the build tree. To regenerate and verify:

    python boring-core/tools/export_brand.py
    python boring-core/tools/export_brand.py --check

`--check` regenerates into a temporary directory and compares every
hash against what is checked in, so a hand-edited icon is caught.
`manifest.json` lists every output, its destination in the Chromium tree
and its hash.

Output is deterministic: the same inputs give byte-identical files.

## What still needs looking at

- The 16, 20 and 24 px icons use a slightly larger B and a coverage
  boost so the blackletter strokes do not wash out. Worth a look on a
  real taskbar before release.
- Windows caches shell icons per executable path, so Explorer can keep
  showing an older icon after a rebuild. That is the cache, not the
  build.
