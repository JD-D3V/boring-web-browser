#!/usr/bin/env python3
"""Check that connections.json lists every connection the browser makes
on its own, and keep the copy of it that the Protection page compiles in.

components/boring/protection/connections.json is the one list. The
Protection page draws its "On its own" rows from it, and net_audit.py
reads it to name what it sees. This check runs on every push (no browser,
a second) and fails when:

  - an entry is missing a field, or its pref does not exist,
  - an entry names a net_audit scenario that does not exist,
  - connections_data.h (the compiled-in copy) differs from the JSON,
  - a source file that fetches from the network is not claimed by an
    entry, or a claimed file names a host the entry does not list,
  - net_audit.py itself names a host that is not in the file.

Usage:
  python check_connections.py            check, exit 1 on any problem
  python check_connections.py --write    rewrite connections_data.h
"""

import ast
import json
import re
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
JSON_REL = "components/boring/protection/connections.json"
HEADER_REL = "components/boring/protection/connections_data.h"

# Code that starts a request to the network. A file with one of these is a
# background connection unless it is listed below as started by a click.
FETCH_MARKERS = (
    "SimpleURLLoader",
    "set_appcast_url",
    "kDnsOverHttpsTemplates",
    "dns-query",
)

# Fetches the person starts, one at a time, by pressing a button: the AI
# summary calls the provider they chose with their own key. They are listed
# in part 2 of the section ("Apps you added"), not here.
STARTED_BY_A_CLICK = {
    "components/boring/ai/ai_summary_service.cc",
    "components/boring/ai/ai_summary_service.h",
}

# Folders that are not ours or never run in the browser.
SKIP_PARTS = ("chromium-web-store", "third_party", ".pristine")

KINDS = {"local_state", "profile", "updater", "extension"}

URL_HOST = re.compile(r"[\"'](?:https?|wss?)://([A-Za-z0-9.-]+)")
BARE_HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|io|org|dev)")

# The control scenario deliberately loads a host that is not ours.
AUDIT_OWN_HOSTS = {"example.com"}


def _is_comment(line):
    text = line.lstrip("+ \t")
    return text.startswith("//") or text.startswith("*") or text.startswith("#")


def load(core):
    return json.loads((core / JSON_REL).read_text(encoding="utf-8"))["connections"]


def header_text(core):
    raw = (core / JSON_REL).read_text(encoding="utf-8")
    json.loads(raw)  # fail loudly on bad JSON
    return (
        "// Copyright 2026 boring. BSD style license.\n"
        "\n"
        "// A copy of connections.json for the Protection page to read. Written\n"
        "// by tools/check_connections.py --write, which CI runs in check mode, so\n"
        "// the two cannot drift. Do not edit by hand. (Not listed in BUILD.gn on\n"
        "// purpose: it is only included, and a BUILD.gn change would force a\n"
        "// full regenerate of the build files.)\n"
        "\n"
        "#ifndef COMPONENTS_BORING_PROTECTION_CONNECTIONS_DATA_H_\n"
        "#define COMPONENTS_BORING_PROTECTION_CONNECTIONS_DATA_H_\n"
        "\n"
        "namespace boring {\n"
        "\n"
        'inline constexpr char kConnectionsJson[] = R"json(' + raw.rstrip("\n") + ')json";\n'
        "\n"
        "}  // namespace boring\n"
        "\n"
        "#endif  // COMPONENTS_BORING_PROTECTION_CONNECTIONS_DATA_H_\n"
    )


def scenario_names(core):
    tree = ast.parse((core / "tools/net_audit.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "SCENARIOS" for t in node.targets
        ):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    return set()


def audit_host_literals(core):
    """Host-shaped strings in net_audit.py, so a host cannot hide there."""
    tree = ast.parse((core / "tools/net_audit.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if BARE_HOST.fullmatch(value) and "/" not in value:
                found.add(value)
            for host in URL_HOST.findall('"' + value):
                found.add(host)
    return found


def source_files(core):
    """Every file that could start a request: our code, the files we
    drop into Chromium, and the lines our patches add to it."""
    for base in ("components/boring", "chromium_src", "patches"):
        root = core / base
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in (".cc", ".h", ".mm", ".patch"):
                continue
            rel = path.relative_to(core).as_posix()
            if any(part in rel for part in SKIP_PARTS) or rel.endswith("_test.cc"):
                continue
            yield rel, path


def code_lines(path):
    """The lines that run: comments out, and for a patch only added lines."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if path.suffix == ".patch":
        lines = [ln for ln in lines if ln.startswith("+") and not ln.startswith("+++")]
    return [ln for ln in lines if not _is_comment(ln)]


def check(core=CORE):
    core = Path(core)
    errors = []
    try:
        entries = load(core)
    except (OSError, ValueError, KeyError) as e:
        return [f"cannot read {JSON_REL}: {e}"]

    scenarios = scenario_names(core)
    prefs_h = (core / "components/boring/core/boring_prefs.h").read_text(
        encoding="utf-8"
    )
    ids = set()
    listed_hosts = set()
    claimed = {}
    for entry in entries:
        name = entry.get("id", "?")
        for field in ("id", "label", "hosts", "why", "switch", "scenario", "code"):
            if field not in entry:
                errors.append(f"{name}: missing '{field}'")
        if name in ids:
            errors.append(f"{name}: duplicate id")
        ids.add(name)
        hosts = entry.get("hosts") or []
        if not hosts:
            errors.append(f"{name}: no hosts")
        listed_hosts.update(hosts)
        if entry.get("scenario") not in scenarios:
            errors.append(f"{name}: no net_audit scenario '{entry.get('scenario')}'")
        switch = entry.get("switch") or {}
        kind = switch.get("kind")
        if kind not in KINDS:
            errors.append(f"{name}: unknown switch kind '{kind}'")
        elif kind == "profile" and f'"{switch.get("pref")}"' not in prefs_h:
            errors.append(f"{name}: pref '{switch.get('pref')}' is not registered")
        elif kind == "local_state" and not switch.get("pref"):
            errors.append(f"{name}: no pref")
        elif kind == "extension" and not switch.get("extension_id"):
            errors.append(f"{name}: no extension_id")
        for rel in entry.get("code", []):
            claimed[rel] = entry

    if "all-off" not in scenarios:
        errors.append("net_audit.py has no 'all-off' scenario")

    header = core / HEADER_REL
    if not header.exists() or header.read_text(encoding="utf-8") != header_text(core):
        errors.append(
            f"{HEADER_REL} is out of date: run "
            "python boring-core/tools/check_connections.py --write"
        )

    for rel, path in source_files(core):
        lines = code_lines(path)
        text = "\n".join(lines)
        fetches = any(marker in text for marker in FETCH_MARKERS)
        owner = claimed.get(rel)
        if fetches and not owner and rel not in STARTED_BY_A_CLICK:
            errors.append(
                f"{rel}: fetches from the network but no entry in connections.json "
                "lists it under 'code'"
            )
        if owner:
            allowed = set(owner.get("hosts", []))
            for host in URL_HOST.findall(text):
                if host not in allowed and host not in ("localhost", "127.0.0.1"):
                    errors.append(
                        f"{rel}: names host {host}, which '{owner['id']}' does not list"
                    )
    for rel in claimed:
        if not (core / rel).exists():
            errors.append(f"{rel}: listed under 'code' but does not exist")

    for host in sorted(audit_host_literals(core) - listed_hosts - AUDIT_OWN_HOSTS):
        errors.append(f"tools/net_audit.py names host {host}, which is not in the file")
    return errors


def main():
    if "--write" in sys.argv:
        (CORE / HEADER_REL).write_text(header_text(CORE), encoding="utf-8", newline="\n")
        print("wrote", HEADER_REL)
        return 0
    errors = check()
    for line in errors:
        print("FAIL:", line)
    if not errors:
        print("connections.json: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
