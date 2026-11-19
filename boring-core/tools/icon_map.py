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
ICONS_SVG = os.path.join(REPO, "design", "v7", "icons-dotted", "icons.svg")
DEFAULT_TREE = r"E:\ung-154\build\src"
SEARCH_ROOTS = ("chrome", "components", "ui")
REFERENCE_SIZE_DIP = 48
SKIP_DIRS = {"out", "third_party", "node_modules", "test", "tests"}

# Our id -> icon base names (file name without .icon). A name that starts
# with "boring_" is ours alone, with no Chromium file to replace: it lands
# in chrome/app/vector_icons and compiled-icons.patch lists it in BUILD.gn.
#
# The c- ids are the compiled UI's set (2026-11-19): the master window's
# I table, 24 grid, 2 px line, full ink. Each has an icon of ours named
# after it, so new UI can draw any glyph the screens show, and takes over
# the Chromium icons for the same idea. The b- ids are the older set; they
# stay only where the compiled screens draw no glyph of their own (stop,
# home, star, pin, audio, share, help and the like). Our b- ids with no
# entry here (split-view, sleeping, vertical and horizontal tabs, zoom,
# lock-open, reader, profile) have no Chromium counterpart worth
# replacing. The warning icons stay Chromium's: they are filled, which
# says "danger" more strongly than our outline, and a scam-safe browser
# keeps the stronger cue.
ICON_MAP = {
    "c-back": [
        "boring_back",
        "arrow_back",
        "arrow_back_old",
        "arrow_back_chrome_refresh_old",
        "back_arrow_old",
        "back_arrow_chrome_refresh_old",
        "back_arrow_touch_old",
    ],
    "c-fwd": [
        "boring_fwd",
        "arrow_forward",
        "arrow_forward_old",
        "forward_arrow_old",
        "forward_arrow_chrome_refresh_old",
        "forward_arrow_touch_old",
    ],
    "c-reload": [
        "boring_reload",
        "autorenew",
        "autorenew_old",
        "reload_chrome_refresh_old",
        "reload_touch_old",
    ],
    "b-stop": ["navigate_stop_chrome_refresh_old", "navigate_stop_touch_old"],
    "b-home": ["navigate_home_chrome_refresh_old", "navigate_home_touch_old", "home"],
    "b-star": ["star", "star_old", "star_chrome_refresh_old"],
    "b-star-filled": ["star_filled", "star_active_chrome_refresh_old"],
    "c-down": [
        "boring_down",
        "download_toolbar_button_chrome_refresh_old",
        "download_toolbar_button_old",
        "download_toolbar_button_touch_old",
        "download_menu_old",
    ],
    "c-ext": ["boring_ext", "extension_chrome_refresh_old", "extension_old"],
    "c-dots": ["boring_menu"],
    # Protected, with the tick: the toolbar button's on state.
    "c-shield": ["boring_protection_on"],
    # The plain shield: the Protection button in its other states, and the
    # menu's Protection row, which draws vector_icons::kShieldIcon.
    "c-shield-plain": ["boring_protection", "shield"],
    "c-close": [
        "boring_close",
        "close_tab_chrome_refresh_old",
        "close_chrome_refresh_old",
        "close",
    ],
    "c-plus": [
        "boring_plus",
        "new_tab_refresh_old",
        "add_old",
        "zoom_plus_menu_refresh_old",
        "zoom_plus_chrome_refresh_old",
        "add_chrome_refresh_old",
    ],
    "b-group": ["tab_group_old"],
    "c-lock": [
        "boring_lock",
        "lock",
        "lock_old",
        "https_valid_old",
        "secure_page_info_chrome_refresh_old",
    ],
    "c-find": [
        "boring_find",
        "search",
        "search_chrome_refresh_old",
        "search_menu_old",
        "find_in_page",
    ],
    "b-page-info": ["tune"],
    "b-share": [
        "share",
        "share_chrome_refresh_old",
        "share_win_chrome_refresh_old",
        "share_windows",
    ],
    "c-lang": ["boring_lang", "translate", "translate_old", "g_translate"],
    # Settings is the sliders everywhere the screens show it.
    "c-sliders": ["boring_sliders", "settings", "settings_menu_old"],
    "c-clock": ["boring_clock", "history", "history_old"],
    "c-mark": [
        "boring_mark",
        "bookmarks_side_panel_refresh_old",
        "bookmarks_side_panel_old",
        "bookmarks_lists_menu_old",
    ],
    "c-print": ["boring_print", "print", "print_menu_old"],
    # The ghost, wherever Chromium draws Incognito: the avatar button of an
    # Incognito window, the menu, its profile menu, downloads, the omnibox.
    "c-priv": [
        "boring_priv",
        "incognito_refresh_menu_old",
        "incognito",
        "incognito_old",
        "incognito_circle_filled",
        "incognito_cr2023_old",
    ],
    "c-win": ["boring_win", "new_window", "new_window_old"],
    "b-fullscreen": ["fullscreen", "fullscreen_old", "fullscreen_refresh_old"],
    "c-tools": ["boring_tools", "more_tools_menu_old"],
    "b-help": ["help_menu_old"],
    "b-check": ["check"],
    "c-info": ["boring_info", "info", "http_chrome_refresh_old", "info_refresh_old"],
    "b-audio-on": ["volume_up", "volume_up_old", "volume_up_chrome_refresh_old"],
    "b-audio-muted": ["volume_off", "volume_off_chrome_refresh_old"],
    "b-pin": ["pin_old"],
    "c-zoom": ["boring_zoom", "zoom_in", "zoom_in_old"],
    "b-profile": ["account_circle_chrome_refresh_old", "account_circle"],
    "c-key": ["boring_key", "password_manager_old", "password_manager"],
    "c-trash": ["boring_trash", "trash_can_refresh_old", "trash_can_old"],
    "b-cast": ["cast_chrome_refresh_old", "cast"],
    "c-save": ["boring_save", "file_save_chrome_refresh_old", "file_save_old", "file_save"],
    "c-exit": ["boring_exit", "exit_menu_old", "exit_to_app"],
    "b-tab-groups": ["saved_tab_group_bar_everything_old"],
    "b-minus": [
        "zoom_minus_menu_refresh_old",
        "zoom_minus_chrome_refresh_old",
        "zoom_minus_old",
        "remove_old",
    ],
    "b-copy": ["copy_menu_old", "copy_old", "content_copy"],
    "c-link": ["boring_link", "link_chrome_refresh_old", "link"],
    "c-chevron-right": [
        "boring_chevron_right",
        "submenu_arrow_chrome_refresh_old",
        "chevron_right_chrome_refresh_old",
        "chevron_right_old",
        "chevron_right",
        "keyboard_arrow_right",
        "keyboard_arrow_right_flippable",
    ],
    "b-chevron-left": ["keyboard_arrow_left"],
    "b-chevron-down": [
        "keyboard_arrow_down_chrome_refresh_old",
        "keyboard_arrow_down_old",
        "keyboard_arrow_down",
    ],
    "b-chevron-up": [
        "keyboard_arrow_up_chrome_refresh_old",
        "keyboard_arrow_up_old",
        "keyboard_arrow_up",
    ],
    "c-code": ["boring_code", "developer_tools_old", "code"],
    # Glyphs of the compiled screens with nothing of Chromium's to replace:
    # Forget, the Shelf and its rows, the Passport's facts, the Bar's
    # actions, the accounts' links and the stand-ins for site icons.
    "c-erase": ["boring_erase"],
    "c-shelf": ["boring_shelf"],
    "c-tab": ["boring_tab"],
    "c-folder": ["boring_folder"],
    "c-doc": ["boring_doc"],
    "c-eye": ["boring_eye"],
    "c-cal": ["boring_cal"],
    "c-twin": ["boring_twin"],
    "c-card": ["boring_card"],
    "c-moon": ["boring_moon"],
    "c-mail": ["boring_mail"],
    "c-pin": ["boring_pin"],
    "c-bed": ["boring_bed"],
    "c-cloud": ["boring_cloud"],
    "c-news": ["boring_news"],
    "c-bank": ["boring_bank"],
    "c-book": ["boring_book"],
    "c-fork": ["boring_fork"],
    "c-box": ["boring_box"],
    "c-train": ["boring_train"],
    "c-qr": ["boring_qr"],
    "c-look": ["boring_look"],
    "c-account": ["boring_account"],
    "c-shield-alert": ["boring_shield_alert"],
}

# Icons that are ours alone: no Chromium file to replace.
OURS = tuple(n for names in ICON_MAP.values() for n in names if n.startswith("boring_"))
OURS_SUFFIXES = tuple(n + ".icon" for n in OURS)
# The canvas our own icons declare: the toolbar's icon size, as the menu
# and Protection icons always had. Callers name the size they draw.
OURS_CANVAS = 20


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
    return {
        re.search(r'id="([^"]+)"', m.group(0)).group(1): m.group(0)
        for m in re.finditer(r"<symbol\b.*?</symbol>", text, re.S)
    }


def flips_in_rtl(tree_root, rel):
    """Whether Chromium's own icon flips itself in right-to-left languages.

    Menu chevrons do; button arrows do not, because the button mirrors its
    whole canvas. A replacement copies whichever its original does, so it
    never ends up flipped twice or not at all.
    """
    if rel.endswith(OURS_SUFFIXES):
        return False
    return "FLIPS_IN_RTL" in pristine.text(tree_root, rel)


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
            if name in OURS:
                # Ours already, not in the Chromium tree.
                rels = [(f"chrome/app/vector_icons/{name}.icon", OURS_CANVAS)]
            else:
                rels = [
                    (rel, original_canvas(tree_root, rel))
                    for rel in resolved.get(name, [])
                ]
            for rel, canvas in rels:
                flips = flips_in_rtl(tree_root, rel)
                text = svg_to_icon.convert_symbol(symbols[sid], name, canvas, flips)
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
    "CANVAS_DIMENSIONS": 1,
    "STROKE": 1,
    "MOVE_TO": 2,
    "LINE_TO": 2,
    "H_LINE_TO": 1,
    "V_LINE_TO": 1,
    "CUBIC_TO": 6,
    "ARC_TO": 7,
    "CIRCLE": 3,
    "ROUND_RECT": 5,
    "CLOSE": 0,
    "NEW_PATH": 0,
    "FLIPS_IN_RTL": 0,
    "FILL_RULE_NONZERO": 0,
    "CAP_SQUARE": 0,
}


def check_syntax(text, where="icon"):
    """Raise ValueError on an unknown command or the wrong argument count."""
    body = " ".join(
        ln
        for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("//")
    )
    tokens = [t.strip() for t in body.split(",")]
    if tokens and tokens[-1] == "":
        tokens.pop()
    i = 0
    seen_canvas = False
    while i < len(tokens):
        name = tokens[i]
        if name not in ARITY:
            raise ValueError(f"{where}: unknown command {name!r}")
        n = ARITY[name]
        args = tokens[i + 1 : i + 1 + n]
        if len(args) < n or any(a in ARITY or a == "" for a in args):
            raise ValueError(f"{where}: {name} needs {n} numbers")
        for a in args:
            float(a.rstrip("f"))
        seen_canvas |= name == "CANVAS_DIMENSIONS"
        i += 1 + n
    if not seen_canvas:
        raise ValueError(f"{where}: no CANVAS_DIMENSIONS")


def validate(paths, tree_root):
    """Check every file's syntax, then run Chromium's own aggregator.

    Raises if any file is malformed. Nothing in the tree is touched.
    """
    for p in paths:
        with open(p, encoding="utf-8") as f:
            check_syntax(f.read(), os.path.basename(p))
    aggregator = os.path.join(
        tree_root, "components", "vector_icons", "aggregate_vector_icons.py"
    )
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
            [
                sys.executable,
                aggregator,
                "--working_directory=" + work,
                "--file_list=" + listing,
                "--output_cc=" + os.path.join(work, "out.cc"),
                "--output_h=" + os.path.join(work, "out.h"),
            ],
            capture_output=True,
            text=True,
            cwd=work,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "icon aggregator failed:\n" + result.stderr + result.stdout
            )


if __name__ == "__main__":
    tree = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TREE
    out = os.path.join(CORE, "chromium_src")
    for p in generate(tree, out):
        print(os.path.relpath(p, REPO))
