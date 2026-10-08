#!/usr/bin/env python3
"""Convert our SVG icon symbols to Chromium vector icon (.icon) files.

The input is design/v7/icons-full/icons.svg: one <symbol> per icon on a
20x20 grid, built from path, circle and rect elements. Chromium's
.icon format is a list of drawing commands, so every path is flattened
to absolute commands (CUBIC_TO_SHORTHAND has no relative form, and
mixing the two is how icons end up a pixel off).

Usage:
  python svg_to_icon.py <icons.svg> <out_dir>
"""

import os
import re
import sys
import xml.etree.ElementTree as ET

COPYRIGHT = "// Copyright 2026 boring. BSD style license.\n"

# Only the arrows need to mirror in right-to-left languages. Reload and
# the rest are drawn the same both ways, as in Chromium.
FLIPS_IN_RTL = {"back", "forward"}

NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
TOKEN = re.compile(r"[A-Za-z]|" + NUMBER.pattern)
ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "A": 7, "Z": 0}


def fmt(x):
    """A number the way .icon files write it: short, no trailing zeros."""
    s = ("%.4f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def line(name, *nums):
    if not nums:
        return name + ","
    return name + ", " + ", ".join(fmt(n) for n in nums) + ","


def path_commands(d):
    """Flatten an SVG path to absolute .icon commands."""
    tokens = TOKEN.findall(d)
    out = []
    i = 0
    cx = cy = sx = sy = 0.0
    last_c2 = None  # second control point of the previous cubic
    op = None
    while i < len(tokens):
        if tokens[i].isalpha():
            op = tokens[i]
            i += 1
            if op in "Zz":
                out.append("CLOSE,")
                cx, cy = sx, sy
                last_c2 = None
                continue
        up = op.upper()
        rel = op.islower()
        n = ARGS[up]
        a = [float(t) for t in tokens[i:i + n]]
        i += n
        if len(a) < n:
            raise ValueError("path ends mid-command: " + d)
        ox, oy = (cx, cy) if rel else (0.0, 0.0)
        c2 = None
        if up == "M":
            cx, cy = ox + a[0], oy + a[1]
            sx, sy = cx, cy
            out.append(line("MOVE_TO", cx, cy))
            op = "l" if rel else "L"  # extra pairs after M are lineto
        elif up == "L":
            cx, cy = ox + a[0], oy + a[1]
            out.append(line("LINE_TO", cx, cy))
        elif up == "H":
            cx = (cx if rel else 0.0) + a[0]
            out.append(line("H_LINE_TO", cx))
        elif up == "V":
            cy = (cy if rel else 0.0) + a[0]
            out.append(line("V_LINE_TO", cy))
        elif up == "C":
            x1, y1 = ox + a[0], oy + a[1]
            x2, y2 = ox + a[2], oy + a[3]
            cx, cy = ox + a[4], oy + a[5]
            out.append(line("CUBIC_TO", x1, y1, x2, y2, cx, cy))
            c2 = (x2, y2)
        elif up == "S":
            if last_c2 is None:
                x1, y1 = cx, cy
            else:
                x1, y1 = 2 * cx - last_c2[0], 2 * cy - last_c2[1]
            x2, y2 = ox + a[0], oy + a[1]
            ex, ey = ox + a[2], oy + a[3]
            out.append(line("CUBIC_TO", x1, y1, x2, y2, ex, ey))
            c2 = (x2, y2)
            cx, cy = ex, ey
        elif up == "A":
            cx, cy = ox + a[5], oy + a[6]
            out.append(line("ARC_TO", a[0], a[1], a[2], a[3], a[4], cx, cy))
        last_c2 = c2
    return out


def element_geometry(el):
    tag = el.tag.split("}")[-1]
    f = lambda k, default=0.0: float(el.get(k, default))
    if tag == "path":
        return path_commands(el.get("d"))
    if tag == "circle":
        return [line("CIRCLE", f("cx"), f("cy"), f("r"))]
    if tag == "rect":
        r = f("rx") if el.get("rx") else f("ry")
        return [line("ROUND_RECT", f("x"), f("y"), f("width"), f("height"), r)]
    raise ValueError("unsupported element: " + tag)


def convert_symbol(symbol_xml, name):
    """The text of one .icon file for a <symbol> element."""
    sym = ET.fromstring(symbol_xml)
    view = sym.get("viewBox", "0 0 20 20").split()
    size = int(float(view[2]))
    base_fill = sym.get("fill", "none")
    base_stroke = sym.get("stroke", "none")
    base_width = float(sym.get("stroke-width", "2"))

    body = []
    first = True
    for el in sym:
        filled = el.get("fill", base_fill) != "none"
        stroked = el.get("stroke", base_stroke) != "none"
        width = float(el.get("stroke-width", base_width))
        geometry = element_geometry(el)
        # A path in a .icon file is either filled or stroked, so an element
        # that is both (SVG's default) is drawn twice with the same shape.
        if filled:
            if not first:
                body.append("NEW_PATH,")
            body.extend(geometry)
            first = False
        if stroked:
            if not first:
                body.append("NEW_PATH,")
            body.append(line("STROKE", width))
            body.extend(geometry)
            first = False

    head = [COPYRIGHT.rstrip("\n"), "",
            "// %s, from the rounded icon set (design/v7/icons-full/icons.svg)." % name,
            "// 2 px stroke on a %d grid, round caps; the dot is the signature." % size,
            "", line("CANVAS_DIMENSIONS", size)]
    if name in FLIPS_IN_RTL:
        head.append("FLIPS_IN_RTL,")
    return "\n".join(head + body) + "\n"


def icon_file_name(symbol_id):
    """b-new-tab -> new_tab"""
    return re.sub(r"^b-", "", symbol_id).replace("-", "_")


def convert_file(svg_path, out_dir, only=None):
    """Write one .icon per symbol; returns the paths written."""
    with open(svg_path, encoding="utf-8") as f:
        text = f.read()
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for m in re.finditer(r"<symbol\b.*?</symbol>", text, re.S):
        xml = m.group(0)
        sid = re.search(r'id="([^"]+)"', xml).group(1)
        if only is not None and sid not in only:
            continue
        name = icon_file_name(sid)
        path = os.path.join(out_dir, name + ".icon")
        with open(path, "w", encoding="utf-8", newline="\n") as out:
            out.write(convert_symbol(xml, name))
        written.append(path)
    return written


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    for p in convert_file(sys.argv[1], sys.argv[2]):
        print(p)
