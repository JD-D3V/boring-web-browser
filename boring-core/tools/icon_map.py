#!/usr/bin/env python3
"""Replace Chromium's vector icons with ours, by file name.

ICON_MAP says which of our icons (ids in design/v7/icons-full/icons.svg)
stands in for which Chromium icons. Chromium has several files per idea:
a rounded-icons name, an "_old" name, a touch name, and sometimes a copy
in more than one directory. Which one a button draws depends on a flag,
so every variant is replaced and the window looks the same either way.

Files land under boring-core/chromium_src/<same path as in Chromium>, the
way the existing three icon overrides do, and apply.py copies them in.

Usage:
  python icon_map.py [tree_root]    # regenerate chromium_src icons
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

import pristine
import svg_to_icon

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(CORE)
ICONS_SVG = os.path.join(REPO, "design", "v7", "icons-full", "icons.svg")
DEFAULT_TREE = r"E:\ung-154\build\src"
SEARCH_ROOTS = ("chrome", "components", "ui")
REFERENCE_SIZE_DIP = 48
SKIP_DIRS = {"out", "third_party", "node_modules", "test", "tests"}

# Our id -> Chromium icon base names (file name without .icon). Our ids
# with no entry here (protection, split-view, sleeping, vertical and
# horizontal tabs, zoom, lock-open, reader, profile) have no Chromium
# counterpart worth replacing; they stay in the set for new UI. The
# warning icons also stay Chromium's: they are filled, which says
# "danger" more strongly than our outline, and a scam-safe browser keeps
# the stronger cue.
ICON_MAP = {
    "b-back": ["arrow_back", "arrow_back_old", "arrow_back_chrome_refresh_old",
               "back_arrow_old", "back_arrow_chrome_refresh_old",
               "back_arrow_touch_old"],
    "b-forward": ["arrow_forward", "arrow_forward_old", "forward_arrow_old",
                  "forward_arrow_chrome_refresh_old", "forward_arrow_touch_old"],
    "b-reload": ["autorenew", "autorenew_old", "reload_chrome_refresh_old",
                 "reload_touch_old"],
    "b-stop": ["navigate_stop_chrome_refresh_old", "navigate_stop_touch_old"],
    "b-home": ["navigate_home_chrome_refresh_old", "navigate_home_touch_old",
               "home"],
    "b-star": ["star", "star_old", "star_chrome_refresh_old"],
    "b-star-filled": ["star_filled", "star_active_chrome_refresh_old"],
    "b-download": ["download_toolbar_button_chrome_refresh_old",
                   "download_toolbar_button_old",
                   "download_toolbar_button_touch_old"],
    "b-downloads-tray": ["download_menu_old"],
    "b-extensions": ["extension_chrome_refresh_old", "extension_old"],
    "b-menu": ["boring_menu"],
    "b-close": ["close_tab_chrome_refresh_old", "close_chrome_refresh_old",
                "close"],
    "b-new-tab": ["new_tab_refresh_old", "add_old"],
    "b-group": ["tab_group_old"],
    "b-lock": ["lock", "lock_old", "https_valid_old",
               "secure_page_info_chrome_refresh_old"],
    "b-search": ["search", "search_chrome_refresh_old"],
    "b-page-info": ["tune"],
    "b-share": ["share", "share_chrome_refresh_old",
                "share_win_chrome_refresh_old", "share_windows"],
    "b-translate": ["translate", "translate_old", "g_translate"],
    "b-settings": ["settings", "settings_menu_old"],
    "b-history": ["history", "history_old"],
    "b-bookmarks": ["bookmarks_side_panel_refresh_old",
                    "bookmarks_side_panel_old"],
    "b-print": ["print", "print_menu_old"],
    "b-find": ["find_in_page"],
    "b-incognito": ["incognito_refresh_menu_old"],
    "b-new-window": ["new_window", "new_window_old"],
    "b-fullscreen": ["fullscreen"],
    "b-tools": ["more_tools_menu_old"],
    "b-help": ["help_menu_old"],
    "b-check": ["check"],
    "b-info": ["info", "http_chrome_refresh_old"],
    "b-audio-on": ["volume_up", "volume_up_old", "volume_up_chrome_refresh_old"],
    "b-audio-muted": ["volume_off", "volume_off_chrome_refresh_old"],
    "b-pin": ["pin_old"],
}


def resolve(tree_root):
    """Every wanted base name -> the tree-relative paths of its .icon files.

    A name can exist in more than one directory (chrome/app and
    components both have arrow_back_old); all copies are returned, since
    each is a separate icon to C++.
    """
    wanted = {n for names in ICON_MAP.values() for n in names}
    found = {n: [] for n in wanted}
    # Files we already put in chromium_src are not Chromium's; the tree is.
    for root in SEARCH_ROOTS:
        for dirpath, dirs, files in os.walk(os.path.join(tree_root, root)):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                if f.endswith(".icon") and f[:-5] in wanted:
                    rel = os.path.relpath(os.path.join(dirpath, f), tree_root)
                    found[f[:-5]].append(rel.replace("\\", "/"))
    for paths in found.values():
        paths.sort()
    return found


def _symbols():
    import re
    with open(ICONS_SVG, encoding="utf-8") as f:
        text = f.read()
    return {re.search(r'id="([^"]+)"', m.group(0)).group(1): m.group(0)
            for m in re.finditer(r"<symbol\b.*?</symbol>", text, re.S)}


def original_canvas(tree_root, rel):
    """The canvas size of Chromium's own icon, from the pristine store.

    The tree holds our replacements once apply.py has run, so the
    original has to come from the store apply.py keeps. Callers that draw
    an icon without naming a size get its canvas size, so ours keeps it.
    """
    original = pristine.text(tree_root, rel)
    m = re.search(r"CANVAS_DIMENSIONS,\s*(\d+)", original)
    # An icon with no CANVAS_DIMENSIONS is drawn on Chromium's 48 grid.
    return int(m.group(1)) if m else REFERENCE_SIZE_DIP


def generate(tree_root, out_root):
    """Write the replacement icons under out_root; returns the paths."""
    resolved = resolve(tree_root)
    symbols = _symbols()
    written = []
    for sid, names in ICON_MAP.items():
        for name in names:
            if name == "boring_menu":
                # Ours already, not in the Chromium tree.
                rels = [("chrome/app/vector_icons/boring_menu.icon", None)]
            else:
                rels = [(rel, original_canvas(tree_root, rel))
                        for rel in resolved.get(name, [])]
            for rel, canvas in rels:
                text = svg_to_icon.convert_symbol(symbols[sid], name, canvas)
                dest = os.path.join(out_root, *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                written.append(dest)
    return written


# Arguments each command takes. The aggregator copies tokens into C++
# without looking at them, so a typo only fails hours later at compile
# time; this catches it first.
ARITY = {
    "CANVAS_DIMENSIONS": 1, "STROKE": 1, "MOVE_TO": 2, "LINE_TO": 2,
    "H_LINE_TO": 1, "V_LINE_TO": 1, "CUBIC_TO": 6, "ARC_TO": 7, "CIRCLE": 3,
    "ROUND_RECT": 5, "CLOSE": 0, "NEW_PATH": 0, "FLIPS_IN_RTL": 0,
    "FILL_RULE_NONZERO": 0, "CAP_SQUARE": 0,
}


def check_syntax(text, where="icon"):
    """Raise ValueError on an unknown command or the wrong argument count."""
    body = " ".join(ln for ln in text.splitlines()
                    if ln.strip() and not ln.lstrip().startswith("//"))
    tokens = [t.strip() for t in body.split(",")]
    if tokens and tokens[-1] == "":
        tokens.pop()
    i = 0
    seen_canvas = False
    while i < len(tokens):
        name = tokens[i]
        if name not in ARITY:
            raise ValueError("%s: unknown command %r" % (where, name))
        n = ARITY[name]
        args = tokens[i + 1:i + 1 + n]
        if len(args) < n or any(a in ARITY or a == "" for a in args):
            raise ValueError("%s: %s needs %d numbers" % (where, name, n))
        for a in args:
            float(a.rstrip("f"))
        seen_canvas |= name == "CANVAS_DIMENSIONS"
        i += 1 + n
    if not seen_canvas:
        raise ValueError("%s: no CANVAS_DIMENSIONS" % where)


def validate(paths, tree_root):
    """Check every file's syntax, then run Chromium's own aggregator.

    Raises if any file is malformed. Nothing in the tree is touched.
    """
    for p in paths:
        with open(p, encoding="utf-8") as f:
            check_syntax(f.read(), os.path.basename(p))
    aggregator = os.path.join(tree_root, "components", "vector_icons",
                              "aggregate_vector_icons.py")
    templates = os.path.join(tree_root, "chrome", "app", "vector_icons")
    with tempfile.TemporaryDirectory() as work:
        for t in ("vector_icons.cc.template", "vector_icons.h.template"):
            shutil.copy(os.path.join(templates, t), work)
        names = []
        for p in paths:
            name = os.path.basename(p)
            if name not in names:
                shutil.copy(p, os.path.join(work, name))
                names.append(name)
        listing = os.path.join(work, "files.txt")
        with open(listing, "w") as f:
            f.write("\n".join(names))
        result = subprocess.run(
            [sys.executable, aggregator, "--working_directory=" + work,
             "--file_list=" + listing,
             "--output_cc=" + os.path.join(work, "out.cc"),
             "--output_h=" + os.path.join(work, "out.h")],
            capture_output=True, text=True, cwd=work)
        if result.returncode != 0:
            raise RuntimeError("icon aggregator failed:\n" + result.stderr + result.stdout)


if __name__ == "__main__":
    tree = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TREE
    out = os.path.join(CORE, "chromium_src")
    for p in generate(tree, out):
        print(os.path.relpath(p, REPO))
