#!/usr/bin/env python3
"""Give the browser its own name and Windows identity.

Rewrites Chromium's product name in the English strings, the BRANDING
file and the Windows install constants. Every run starts from the
pristine copy of each file, so running it twice changes nothing, and
apply.py --restore puts the originals back.

Credit to the Chromium authors is left as it is.

Usage: python rebrand.py [--src E:\\ung\\build\\src]
"""

import argparse
import os
import re

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = r"E:\ung\build\src"
# One store per source tree. See pristine.py for why this is not a
# single shared folder any more.
import pristine  # noqa: E402

NAME = "Boring Browser"
# Used where Windows wants no spaces: the install folder, registry ids,
# ProgIDs and the URL scheme.
ID = "BoringBrowser"

STRING_FILES = [
    "chrome/app/chromium_strings.grd",
    "chrome/app/settings_chromium_strings.grdp",
    "components/components_chromium_strings.grd",
]

# "Chromium" is two different things in these files. It is the name of
# the product, which becomes ours, and it is the name of the upstream
# project, which is not ours to rename. Renaming the project is what
# turned the About page into "made possible by the Boring Browser open
# source project", which reads as though we wrote Chromium and drops the
# credit the page exists to give.
#
# These are the uses held back from the rename:
#   - "The Chromium Authors", the copyright holder on the About page.
#   - "Chromium project", in message descriptions.
#   - the text of the link that points at chromium.org, which sits
#     between the BEGIN_LINK_CHROMIUM and END_LINK_CHROMIUM markers.
# Google's own google_chrome_strings.grd does the same thing: the
# product there is Chrome and the project it credits is still Chromium.
PROJECT_REFERENCE = re.compile(
    r"Chromium(?= Authors\b)"
    r"|Chromium(?= project\b)"
    r'|(?<=</ph>)Chromium(?=<ph name="END_LINK_CHROMIUM">)'
)

PRODUCT_WORD = re.compile(r"\bChromium\b")

# Held out of the rename for the length of one substitution. A NUL never
# appears in these files, so it cannot collide with their contents.
HOLD = re.compile("\x00(\\d+)\x00")

# Named separately from the count check so that a future edit which
# happens to keep the count but move the credit somewhere useless still
# fails. These are the two sentences the About page is built from.
REQUIRED_IN_TREE = [
    # "... is made possible by the [Chromium] open source project ...",
    # where the brackets are the link to chromium.org.
    (
        "components/components_chromium_strings.grd",
        '</ph>Chromium<ph name="END_LINK_CHROMIUM">',
    ),
    # The copyright holder shown on chrome://version.
    ("chrome/app/chromium_strings.grd", "The Chromium Authors"),
]

# Strings Chromium uses in every build but only defines for the Google
# branded one. The code reads them through chrome/grit/branded_strings.h
# without a branding guard, so a Chromium branded build does not compile
# until the message exists in chromium_strings.grd as well.
#
# These are upstream oversights, not ours. Each one is added here with
# the bug it comes from, written the way upstream writes it, with the
# product name left as "Chromium" so the rename below handles it like
# every other string. Added only when it is genuinely missing, so this
# list can outlive the fix without doing anything.
MISSING_BRANDED_MESSAGES = [
    # There was a fourth entry here, for
    # IDS_OMNIBOX_EVERYWHERE_STATUS_ICON_MENU_TOGGLE. It was removed
    # because the diagnosis behind it was wrong, and a wrong entry here
    # is worse than no entry: it invents a string over the top of a tree
    # that is broken some other way, instead of letting the build say so.
    #
    # That string is in upstream's chromium_strings.grd, at line 3170 of
    # 153.0.8010.47. The build failed on it because rebrand.py was
    # reading a pristine store of Chromium 151 files and writing 151's
    # string file over the 153 tree, so the build was compiling 151
    # strings. Chromium added that message in 152. The fix was
    # pristine.py, one store per tree, not a string added here.
    #
    # Chromium 153.0.8010.47, found by branded_string_check.py before the
    # build reached them. chrome/browser/win/installer_downloader/ reads
    # all three, and that file has no #if in it at all. The feature
    # offers to save an installer to OneDrive before a Windows 11
    # upgrade; it is upstream's, we only need it to compile, and the
    # product name is written as Chromium so the rename reaches it.
    #
    # Marked not translateable on purpose, unlike upstream. A string we
    # add has no entry in any .xtb, and asking the translation machinery
    # for one we invented is a second problem to debug.
    (
        "IDS_INSTALLER_DOWNLOADER_DISCLAIMER",
        "Installer downloader infobar message prompting users upgrading "
        "to Windows 11 to download the installer to OneDrive.",
        "Upgrading to Windows 11 soon? Download the Chromium Installer "
        "to OneDrive so you’re ready from day one.",
    ),
    (
        "IDS_INSTALLER_DOWNLOADER_BUTTON_LABEL",
        "Button label for the installer downloader infobar.",
        "Download Chromium Installer",
    ),
    (
        "IDS_INSTALLER_DOWNLOADER_LINK",
        "Text for the link in the installer downloader infobar.",
        "Learn more about installing Chromium",
    ),
]

MESSAGES_CLOSE = "    </messages>"

BRANDING = {
    "PRODUCT_FULLNAME": NAME,
    "PRODUCT_SHORTNAME": NAME,
    "PRODUCT_INSTALLER_FULLNAME": NAME + " Installer",
    "PRODUCT_INSTALLER_SHORTNAME": NAME + " Installer",
}

INSTALL_MODES = [
    # The install and profile folder. No space: Windows cannot load the
    # browser's side-by-side assembly from a folder name with one.
    ('kProductPathName[] = L"Chromium";', f'kProductPathName[] = L"{ID}";'),
    ('.base_app_name = L"Chromium",', f'.base_app_name = L"{NAME}",'),
    ('.base_app_id = L"Chromium",', f'.base_app_id = L"{ID}",'),
    (
        '.browser_prog_id_prefix = L"ChromiumHTM",',
        '.browser_prog_id_prefix = L"BoringHTM",',
    ),
    ('L"Chromium HTML Document",', f'L"{NAME} HTML Document",'),
    (
        '.direct_launch_url_scheme = "chromium",',
        '.direct_launch_url_scheme = "boringbrowser",',
    ),
    ('.pdf_prog_id_prefix = L"ChromiumPDF",', '.pdf_prog_id_prefix = L"BoringPDF",'),
    ('L"Chromium PDF Document",', f'L"{NAME} PDF Document",'),
    # Our own ids, so an installed Chromium and this browser never
    # overwrite each other's registration.
    (
        'L"{7D2B3E1D-D096-4594-9D8F-A6667F12E0AC}"',
        'L"{5B0E9C2A-6F3D-4A71-9C88-2E4B7D1A6C35}"',
    ),
]


def pristine_text(src, rel):
    """The original file, saved the first time we touch it.

    Rebranding works from the original rather than from the file in the
    tree, so running it twice cannot rename an already renamed string.
    That makes the store the input to this tool, and an original from
    the wrong Chromium version silently produces the wrong output.
    """
    return pristine.text(src, rel)


def write_if_changed(src, rel, text):
    path = os.path.join(src, rel)
    with open(path, encoding="utf-8", newline="") as f:
        if f.read() == text:
            return
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    print("rebrand", rel)


def rename_product(text):
    """Renames the product, leaving references to the project alone."""
    kept = []

    def hold(match):
        kept.append(match.group(0))
        return f"\x00{len(kept) - 1}\x00"

    held = PROJECT_REFERENCE.sub(hold, text)
    renamed = PRODUCT_WORD.sub(NAME, held)
    return HOLD.sub(lambda m: kept[int(m.group(1))], renamed)


def check_attribution(rel, before, after):
    """Refuses to write a file that lost a credit to the project.

    Cheap to run and it fails at the point the mistake is made, rather
    than on an About page nobody reads until a build is out.
    """
    want = len(PROJECT_REFERENCE.findall(before))
    got = len(PROJECT_REFERENCE.findall(after))
    if want != got:
        raise SystemExit(
            f"rebrand: {rel} would keep {got} of {want} references to the "
            "Chromium project; renaming those drops the upstream credit"
        )


def add_missing_messages(rel, text):
    """Puts back branded strings upstream only defined for Chrome.

    Done before the rename, so the added text goes through exactly the
    same substitution as everything around it and the product name is
    still written down in one place.
    """
    if rel != "chrome/app/chromium_strings.grd":
        return text
    ending = "\r\n" if "\r\n" in text else "\n"
    additions = []
    for name, desc, body in MISSING_BRANDED_MESSAGES:
        if f'name="{name}"' in text:
            continue  # Upstream fixed it, or this is an older Chromium.
        additions.append(
            ending.join(
                [
                    f'      <message name="{name}" desc="{desc}" '
                    'translateable="false">',
                    f"        {body}",
                    "      </message>",
                    "",
                ]
            )
        )
    if not additions:
        return text
    if text.count(MESSAGES_CLOSE) != 1:
        raise SystemExit(
            f"rebrand: cannot find one {MESSAGES_CLOSE.strip()!r} in {rel}, "
            "so there is nowhere safe to add the missing messages"
        )
    for name, _desc, _body in MISSING_BRANDED_MESSAGES:
        print("rebrand: adding missing branded string", name)
    return text.replace(MESSAGES_CLOSE, "".join(additions) + MESSAGES_CLOSE)


def rebrand(src):
    for rel in STRING_FILES:
        before = pristine_text(src, rel)
        after = rename_product(add_missing_messages(rel, before))
        check_attribution(rel, before, after)
        write_if_changed(src, rel, after)

    rel = "chrome/app/theme/chromium/BRANDING"
    lines = []
    for line in pristine_text(src, rel).splitlines(keepends=True):
        key = line.split("=", 1)[0]
        if key in BRANDING:
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            line = f"{key}={BRANDING[key]}{ending}"
        lines.append(line)
    write_if_changed(src, rel, "".join(lines))

    rel = "chrome/install_static/chromium_install_modes.h"
    text = pristine_text(src, rel)
    for old, new in INSTALL_MODES:
        if text.count(old) != 1:
            raise SystemExit(f"rebrand: expected one {old!r} in {rel}")
        text = text.replace(old, new)
    write_if_changed(src, rel, text)


def check_tree(src):
    """Reads back the files in the build tree and checks the credits.

    This is the check a release job can run without building anything.
    """
    problems = []
    for rel in STRING_FILES:
        before = pristine_text(src, rel)
        with open(os.path.join(src, rel), encoding="utf-8", newline="") as f:
            after = f.read()
        want = len(PROJECT_REFERENCE.findall(before))
        got = len(PROJECT_REFERENCE.findall(after))
        if want != got:
            problems.append(f"{rel}: {got} of {want} project references left")
    for phrase in REQUIRED_IN_TREE:
        rel, text = phrase
        with open(os.path.join(src, rel), encoding="utf-8", newline="") as f:
            if text not in f.read():
                problems.append(f"{rel}: missing {text!r}")
    if problems:
        for line in problems:
            print("rebrand --check:", line)
        raise SystemExit(1)
    print("rebrand --check: upstream credits intact")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument(
        "--check",
        action="store_true",
        help="check the tree's credits to the Chromium project, change nothing",
    )
    args = ap.parse_args()
    if args.check:
        check_tree(args.src)
    else:
        rebrand(args.src)


if __name__ == "__main__":
    main()
