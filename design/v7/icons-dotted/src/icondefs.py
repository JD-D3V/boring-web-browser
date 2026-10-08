import math

def n(v):
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    return s

def dot(x, y):
    return '<circle cx="%s" cy="%s" r="1.25" fill="currentColor" stroke="none"/>' % (n(x), n(y))

def poly(points, close=True):
    d = "M" + " ".join("%s %s" % (n(x), n(y)) for x, y in points[:1])
    d += "".join("L%s %s" % (n(x), n(y)) for x, y in points[1:])
    return d + ("z" if close else "")

def fillet(points, r):
    """rounded polygon path"""
    out = []
    cnt = len(points)
    segs = []
    for i in range(cnt):
        p0 = points[i - 1]
        p1 = points[i]
        p2 = points[(i + 1) % cnt]
        v1 = (p0[0] - p1[0], p0[1] - p1[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1 = math.hypot(*v1)
        l2 = math.hypot(*v2)
        u1 = (v1[0] / l1, v1[1] / l1)
        u2 = (v2[0] / l2, v2[1] / l2)
        ang = math.acos(u1[0] * u2[0] + u1[1] * u2[1])
        d = r / math.tan(ang / 2)
        a = (p1[0] + u1[0] * d, p1[1] + u1[1] * d)
        b = (p1[0] + u2[0] * d, p1[1] + u2[1] * d)
        cross = u1[0] * u2[1] - u1[1] * u2[0]
        sweep = 1 if cross < 0 else 0
        segs.append((a, b, sweep))
    d = "M%s %s" % (n(segs[0][0][0]), n(segs[0][0][1]))
    for i, (a, b, sw) in enumerate(segs):
        if i > 0:
            d += "L%s %s" % (n(a[0]), n(a[1]))
        d += "A%s %s 0 0 %d %s %s" % (n(r), n(r), sw, n(b[0]), n(b[1]))
    return d + "z"

def star(cx, cy, R, r):
    pts = []
    for k in range(5):
        a = math.radians(-90 + k * 72)
        pts.append((cx + R * math.cos(a), cy + R * math.sin(a)))
        a2 = math.radians(-90 + k * 72 + 36)
        pts.append((cx + r * math.cos(a2), cy + r * math.sin(a2)))
    return pts

def gear(cnt=6, Rt=7.2, Rr=5.0, ta=11, ra=17):
    pts = []
    for k in range(cnt):
        th = k * 360.0 / cnt - 90
        for rad, a in ((Rr, -ra), (Rt, -ta), (Rt, ta), (Rr, ra)):
            ang = math.radians(th + a)
            pts.append((10 + rad * math.cos(ang), 10 + rad * math.sin(ang)))
    return pts

STAR_PTS = star(10, 10.8, 7.4, 3.8)
STAR_D = poly(STAR_PTS)
STAR_HOLE = "M10 9.55a1.25 1.25 0 1 0 0 2.5 1.25 1.25 0 1 0 0-2.5z"
GEAR_D = poly(gear())
WARN_D = fillet([(10, 1.2), (18, 17), (2, 17)], 2)

# category -> list of (name, markup)
CATS = [
 ("Toolbar", [
  ("back", '<path d="M9 5l-5 5 5 5M4 10h8"/>' + dot(16, 10)),
  ("forward", '<path d="M11 5l5 5-5 5M16 10H8"/>' + dot(4, 10)),
  ("reload", '<path d="M15.4 12.5a6 6 0 1 1-1.2-6.8L16 7.5"/><path d="M16 3.5v4h-4"/>' + dot(10, 10)),
  ("stop", '<path d="M4 4l3 3M13 13l3 3M16 4l-3 3M7 13l-3 3"/>' + dot(10, 10)),
  ("home", '<path d="M3 10l7-6 7 6"/><path d="M5 9v6a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V9"/>' + dot(10, 13)),
  ("star", '<path d="%s"/>' % STAR_D + dot(10, 10.8)),
  ("star-filled", '<path fill="currentColor" fill-rule="evenodd" stroke="none" d="%s%s"/><path d="%s"/>' % (STAR_D, STAR_HOLE, STAR_D)),
  ("download", '<path d="M10 3v9M6 8l4 4 4-4"/>' + dot(10, 16)),
  ("extensions", '<path d="M5 7h1a2.5 2.5 0 1 1 4 0h1a2 2 0 0 1 2 2a2.5 2.5 0 1 1 0 4v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z"/>' + dot(8, 12)),
  ("menu", dot(10, 4) + dot(10, 10) + dot(10, 16)),
  ("zoom", '<circle cx="9" cy="9" r="6"/><path d="M14 14l3 3M9 7v4M7 9h4"/>'),
  ("protection", '<path d="M10 3L4 5v5c0 3.5 2.5 5.7 6 7 3.5-1.3 6-3.5 6-7V5z"/>' + dot(10, 10)),
  ("split-view", '<rect x="3" y="4" width="14" height="12" rx="3"/><path d="M10 4v2.5M10 13.5V16"/>' + dot(10, 10)),
 ]),
 ("Tab strip", [
  ("close", '<path d="M5 5l10 10M15 5L5 15"/>'),
  ("new-tab", '<path d="M10 4v12M4 10h12"/>'),
  ("audio-on", '<path d="M3 11V9a1 1 0 0 1 1-1h1l3-3v10l-3-3H4a1 1 0 0 1-1-1z"/><path d="M15 7a5 5 0 0 1 0 6"/>' + dot(12, 10)),
  ("audio-muted", '<path d="M3 11V9a1 1 0 0 1 1-1h1l3-3v10l-3-3H4a1 1 0 0 1-1-1z"/><path d="M12 8l4 4M16 8l-4 4"/>'),
  ("pin", '<path d="M8 3h4v5l3 3v2H5v-2l3-3z"/><path d="M10 13v3"/>' + dot(10, 16)),
  ("sleeping", '<path d="M10 3a5 5 0 0 0 7 7 7 7 0 1 1-7-7z"/>' + dot(14.5, 5.5)),
  ("group", '<path d="M5 4h3a2 2 0 0 1 2 2h5a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/>' + dot(10, 11)),
 ]),
 ("Address bar", [
  ("lock", '<rect x="4" y="9" width="12" height="8" rx="3"/><path d="M7 9V7a3 3 0 0 1 6 0v2"/>' + dot(10, 13)),
  ("lock-open", '<rect x="4" y="9" width="12" height="8" rx="3"/><path d="M7 9V7a3 3 0 0 1 5.8-1"/>' + dot(10, 13)),
  ("search", '<circle cx="9" cy="9" r="6"/><path d="M14 14l3 3"/>' + dot(9, 9)),
  ("page-info", '<circle cx="7" cy="6" r="2"/><path d="M3 6h2M9 6h8M3 14h8"/>' + dot(15, 14)),
  ("share", '<path d="M10 10V3M6.5 6.5L10 3l3.5 3.5"/><path d="M7 9H6a2 2 0 0 0-2 2v4a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2v-4a2 2 0 0 0-2-2h-1"/>' + dot(10, 14)),
  ("translate", '<path d="M3 6h8M5 9l4 4M4 14l5-5 2-3"/><path d="M11 17l3-6 3 6M12 15h4"/>' + dot(7, 3)),
  ("reader", '<path d="M10 17c-1.5-1.5-4-2-7-2V4c3 0 5.5.5 7 2z"/><path d="M10 17c1.5-1.5 4-2 7-2V4c-3 0-5.5.5-7 2z"/>' + dot(6.5, 9.5)),
 ]),
 ("Menus and panels", [
  ("settings", '<path d="%s"/>' % GEAR_D + dot(10, 10)),
  ("history", '<circle cx="10" cy="10" r="7"/><path d="M10 6v4l3 2"/>' + dot(10, 10)),
  ("bookmarks", '<path d="M3 17V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v12l-5-3.5z"/><path d="M17 7v8"/>' + dot(8, 8)),
  ("downloads-tray", '<path d="M5.2 4h9.6a1 1 0 0 1 .95.7L17 11v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4l1.25-6.3A1 1 0 0 1 5.2 4z"/><path d="M3 11h4l1 2h4l1-2h4"/>' + dot(10, 7.5)),
  ("print", '<path d="M6 7V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v3"/><path d="M7 14H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2h-2"/><path d="M7 14v3h6v-3"/>' + dot(14, 10)),
  ("find", '<path d="M3 4h10M3 8h4"/><circle cx="12" cy="12" r="4"/><path d="M15 15l2 2"/>' + dot(4, 12)),
  ("incognito", '<path d="M4 17V9a6 6 0 0 1 12 0v8l-2-2-2 2-2-2-2 2-2-2z"/>' + dot(7.5, 9.5) + dot(12.5, 9.5)),
  ("new-window", '<rect x="3" y="4" width="14" height="12" rx="3"/><path d="M10 8v4M8 10h4"/>'),
  ("fullscreen", '<path d="M3 7V5a2 2 0 0 1 2-2h2M13 3h2a2 2 0 0 1 2 2v2M17 13v2a2 2 0 0 1-2 2h-2M7 17H5a2 2 0 0 1-2-2v-2"/>' + dot(10, 10)),
  ("tools", '<path d="M7 6V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1"/><rect x="3" y="6" width="14" height="11" rx="3"/><path d="M3 11h3M14 11h3"/>' + dot(10, 11)),
  ("help", '<circle cx="10" cy="10" r="7"/><path d="M8 8a2 2 0 1 1 2 2v1"/>' + dot(10, 14)),
  ("profile", '<circle cx="10" cy="7" r="3"/><path d="M4 17c0-3.3 2.7-6 6-6s6 2.7 6 6"/>'),
  ("vertical-tabs", '<rect x="3" y="3" width="14" height="14" rx="3"/><path d="M9 3v14M6 11v3"/>' + dot(6, 7)),
  ("horizontal-tabs", '<rect x="3" y="3" width="14" height="14" rx="3"/><path d="M3 9h14M10 6h4"/>' + dot(6, 6)),
  ("warning", '<path d="%s"/><path d="M10 8v3"/>' % WARN_D + dot(10, 14)),
  ("check", '<path d="M4 10l4 4 8-8"/>'),
  ("info", '<circle cx="10" cy="10" r="7"/><path d="M10 10v4"/>' + dot(10, 6.5)),
 ]),
 ("More", [
  ("chevron-right", '<path d="M8 5l5 5-5 5"/>'),
  ("chevron-left", '<path d="M12 5l-5 5 5 5"/>'),
  ("chevron-up", '<path d="M5 12l5-5 5 5"/>'),
  ("chevron-down", '<path d="M5 8l5 5 5-5"/>'),
  ("key", '<circle cx="6.5" cy="13.5" r="3.5"/><path d="M9 11l8-8M14 6l2.5 2.5"/>'),
  ("trash", '<path d="M3 6h14M8 6V4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v2"/><path d="M5 6l.8 9.5a2 2 0 0 0 2 1.5h4.4a2 2 0 0 0 2-1.5L15 6"/>' + dot(10, 11.5)),
  ("cast", '<path d="M3 6a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-1"/><path d="M4 12a4 4 0 0 1 4 4M4 9a7 7 0 0 1 7 7"/>' + dot(4, 16)),
  ("save", '<path d="M5 3h8l4 4v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M7 3v4h5V3M7 17v-4h6v4"/>'),
  ("exit", '<path d="M8 3H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3"/><path d="M9 10h8M13.5 6.5L17 10l-3.5 3.5"/>'),
  ("tab-groups", '<rect x="4" y="4" width="4" height="4" rx="1"/><rect x="12" y="4" width="4" height="4" rx="1"/><rect x="4" y="12" width="4" height="4" rx="1"/><rect x="12" y="12" width="4" height="4" rx="1"/>'),
  ("plus", '<path d="M10 5v10M5 10h10"/>'),
  ("minus", '<path d="M5 10h10"/>'),
  ("copy", '<rect x="7" y="7" width="10" height="10" rx="3"/><path d="M13 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/>' + dot(12, 12)),
  ("link", '<path d="M10 12.1a3.5 3.5 0 0 0 5.28.38l2.1-2.1a3.5 3.5 0 0 0-4.95-4.95L11.2 6.6"/><path d="M12.8 10.7a3.5 3.5 0 0 0-5.28-.38l-2.1 2.1a3.5 3.5 0 0 0 4.95 4.95l1.2-1.2"/>'),
 ]),
]

SYMBOL_ATTRS = 'viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'

def all_icons():
    return [(nm, mk) for _, items in CATS for nm, mk in items]

def symbols(indent=""):
    return "\n".join('%s<symbol id="b-%s" %s>%s</symbol>' % (indent, nm, SYMBOL_ATTRS, mk) for nm, mk in all_icons())
