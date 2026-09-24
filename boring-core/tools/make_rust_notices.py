#!/usr/bin/env python3
"""Write the notice file for the Rust crates we link into the browser.

Chromium generates `about_credits.html` from its own `third_party`
directories. The blocking engine is a separate Rust build, so not one of
its crates appears there: checked, `NOTICES.html` contains the string
"adblock" zero times. Shipping a binary that links `adblock` without
naming it and its licence is a straightforward licence failure.

This reads `Cargo.lock`, finds each crate in the local registry cache,
takes the licence from its `Cargo.toml` and the licence text from the
file beside it, and writes one html file naming every crate, its exact
version, its licence and where its source is.

`adblock` is MPL-2.0. MPL-2.0 section 3.2 wants the source form of the
covered files made available to whoever gets the binary, which a notice
alone does not do. We do not modify the crate, so the honest and usual
answer is to point at the exact upstream version, which is what the
`source` column does. Whether that is enough is JD's call to confirm,
and the file says so rather than implying the question is settled.

    python make_rust_notices.py --out NOTICES-rust.html

Nothing here contacts the network.
"""

import argparse
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.dirname(HERE)
LOCK = os.path.join(CORE, "rust", "Cargo.lock")

# Licence text lives in one of these, next to the crate's Cargo.toml.
LICENCE_NAMES = (
    "LICENSE", "LICENSE.txt", "LICENSE.md",
    "LICENCE", "LICENCE.txt",
    "LICENSE-MIT", "LICENSE-APACHE", "LICENSE-APACHE-2.0",
    "COPYING", "COPYRIGHT", "NOTICE",
)

# A licence that obliges us to do more than name it.
RECIPROCAL = ("MPL", "GPL", "LGPL", "EPL", "CDDL", "AGPL")


def registry_dirs():
    home = os.path.expanduser("~")
    root = os.path.join(home, ".cargo", "registry", "src")
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, d) for d in os.listdir(root)]


def read_lock(path):
    """Every [[package]] in Cargo.lock, as (name, version)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    out = []
    for block in text.split("[[package]]")[1:]:
        name = re.search(r'^name\s*=\s*"([^"]+)"', block, re.M)
        version = re.search(r'^version\s*=\s*"([^"]+)"', block, re.M)
        if name and version:
            out.append((name.group(1), version.group(1)))
    return sorted(set(out))


def crate_dir(name, version):
    for reg in registry_dirs():
        d = os.path.join(reg, f"{name}-{version}")
        if os.path.isdir(d):
            return d
    return None


def licence_of(path):
    """The licence expression from a crate's Cargo.toml."""
    toml = os.path.join(path, "Cargo.toml")
    if not os.path.isfile(toml):
        return ""
    with open(toml, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = re.match(r'^license\s*=\s*"([^"]+)"', line.strip())
            if m:
                return m.group(1)
            m = re.match(r"^license-file\s*=\s*\"([^\"]+)\"", line.strip())
            if m:
                return "see " + m.group(1)
    return ""


def licence_texts(path):
    """Every licence file in the crate, as (filename, text)."""
    found = []
    if not path:
        return found
    for entry in sorted(os.listdir(path)):
        base = entry.split(".")[0].upper()
        if entry.upper() in (n.upper() for n in LICENCE_NAMES) or base in (
            "LICENSE", "LICENCE", "COPYING", "NOTICE"
        ):
            full = os.path.join(path, entry)
            if os.path.isfile(full):
                with open(full, encoding="utf-8", errors="replace") as fh:
                    found.append((entry, fh.read()))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--lock", default=LOCK)
    ap.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="exit non-zero if a crate has no licence text on this machine",
    )
    args = ap.parse_args()

    crates = read_lock(args.lock)
    if not crates:
        print(f"no packages found in {args.lock}", file=sys.stderr)
        return 2

    # Our own crates are not third party and are not in the registry.
    # They are this project's code, under whatever licence this project
    # ends up with, which is not decided yet. Say that rather than
    # printing "not stated" as though a crate had forgotten to.
    OURS = ("adblock_ffi", "boring_adblock")

    rows = []
    missing = []
    for name, version in crates:
        if name in OURS:
            rows.append((name, version, "this project, licence not yet chosen", []))
            continue
        path = crate_dir(name, version)
        lic = licence_of(path) if path else ""
        texts = licence_texts(path)
        if not texts:
            missing.append(f"{name} {version}")
        rows.append((name, version, lic, texts))

    reciprocal = [
        (n, v, l) for n, v, l, _ in rows
        if any(tag in (l or "").upper() for tag in RECIPROCAL)
    ]

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Rust component notices</title>",
        "<style>body{font:14px/1.6 system-ui,sans-serif;margin:2em auto;"
        "max-width:56em;padding:0 1em}"
        "table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #ccc;padding:6px 8px;text-align:left;"
        "vertical-align:top;font-size:13px}"
        "pre{white-space:pre-wrap;background:#f6f6f4;padding:1em;"
        "border-radius:6px;font-size:12px}"
        "h2{margin-top:2em;border-top:1px solid #ddd;padding-top:1em}"
        "</style></head><body>",
        "<h1>Rust component notices</h1>",
        "<p>The ad and tracker blocking engine in this browser is built "
        "as a separate Rust library. Its crates are not part of "
        "Chromium's own third party set, so they are not listed in "
        "<code>NOTICES.html</code> or at <code>chrome://credits</code>. "
        "They are listed here instead.</p>",
    ]

    if reciprocal:
        parts.append(
            "<p><strong>Source availability.</strong> The following are "
            "under licences that ask for more than attribution. None of "
            "them is modified here; each is the unmodified published "
            "version named below, available from crates.io at that exact "
            "version. Whether that satisfies the obligation for a given "
            "release is a decision for the release owner, not a "
            "question this file settles.</p><ul>"
        )
        for n, v, l in reciprocal:
            parts.append(
                f"<li><code>{html.escape(n)} {html.escape(v)}</code>, "
                f"{html.escape(l)}, "
                f"https://crates.io/crates/{html.escape(n)}/{html.escape(v)}"
                "</li>"
            )
        parts.append("</ul>")

    parts.append("<h2>Crates</h2><table><tr><th>Crate</th><th>Version</th>"
                 "<th>Licence</th><th>Source</th></tr>")
    for name, version, lic, _ in rows:
        src = f"https://crates.io/crates/{name}/{version}"
        parts.append(
            f"<tr><td>{html.escape(name)}</td>"
            f"<td>{html.escape(version)}</td>"
            f"<td>{html.escape(lic or 'not stated in Cargo.toml')}</td>"
            f"<td>{html.escape(src)}</td></tr>"
        )
    parts.append("</table>")

    parts.append("<h2>Licence texts</h2>")
    for name, version, _lic, texts in rows:
        for fname, text in texts:
            parts.append(
                f"<h3>{html.escape(name)} {html.escape(version)}, "
                f"{html.escape(fname)}</h3>"
            )
            parts.append(f"<pre>{html.escape(text)}</pre>")

    parts.append("</body></html>")

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(parts))

    print(f"wrote {args.out}: {len(rows)} crates, "
          f"{len(reciprocal)} needing more than attribution")
    if missing:
        print(f"no licence text found on this machine for {len(missing)}: "
              + ", ".join(missing[:8]) + ("..." if len(missing) > 8 else ""),
              file=sys.stderr)
        if args.fail_on_missing:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
