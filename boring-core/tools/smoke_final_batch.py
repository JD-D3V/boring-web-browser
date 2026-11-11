#!/usr/bin/env python3
"""Check the last product batch before Release 3 (ledger 105) in the build.

  - Settings in a guest session does not show the Protection, Reading and
    Page summaries links; a normal window does.
  - The Protection page in an incognito window and in a guest session: the
    Secure DNS and browser update switches cannot be used there, Secure
    DNS says "Change this in a normal window.", and a setConnection message
    sent by hand changes nothing on disk. In a normal window the Secure DNS
    switch can be used.
  - The new tab page survives engine button numbers far outside the int
    range.

The folder copy rules, the download guard's script types and the list
signature are checked by smoke_folder_copy.py, smoke_scam_guards.py and
smoke_lists.py.

Usage: python smoke_final_batch.py
Needs BORING_OUT, as the other smoke tests do.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from drive import Browser
from smoke_local import wait_for

CORE = Path(__file__).resolve().parents[1]
CONNECTIONS = json.loads(
    (CORE / "components/boring/protection/connections.json").read_text(encoding="utf-8")
)["connections"]
PROTECTION = "chrome://boring-protection"
NORMAL_WINDOW = "Change this in a normal window."

# The three links, found through the settings shadow roots: true when shown.
MENU_LINKS = r"""
var out = {};
function walk(root) {
  root.querySelectorAll('*').forEach(function(el) {
    if (el.shadowRoot) walk(el.shadowRoot);
    if (el.tagName === 'A' && ['protection', 'reading', 'summaries'].indexOf(el.id) >= 0 &&
        el.closest && el.getAttribute('role') === 'menuitem') {
      out[el.id] = !el.hidden && el.getBoundingClientRect().height > 0;
    }
  });
}
walk(document);
return out;
"""

READ_ROWS = """
  var out = {};
  document.querySelectorAll('#connections-own .setting-row').forEach(function(r) {
    var id = r.id.replace('conn-row-', '');
    var sw = document.getElementById('conn-' + id);
    var detail = document.getElementById('conn-detail-' + id);
    out[id] = {on: sw.checked, disabled: sw.disabled,
               detail: detail ? detail.textContent : ''};
  });
  return out;
"""


def dig(tree, dotted):
    for part in dotted.split("."):
        if not isinstance(tree, dict) or part not in tree:
            return None
        tree = tree[part]
    return tree


def main():
    failures = []

    def check(name, ok, detail=""):
        print(("PASS: " if ok else "FAIL: ") + name + (f" ({detail})" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    tmp = os.environ.get("TMP") or None
    n_rows = len(CONNECTIONS)
    dns = next(c for c in CONNECTIONS if c["id"] == "secure_dns")

    def menu_links(b):
        b.get("chrome://settings")
        wait_for(b, "document.readyState === 'complete'", 10000)
        time.sleep(2.5)
        return b.run(MENU_LINKS)

    def rows(b):
        b.get(PROTECTION)
        wait_for(
            b,
            f"document.querySelectorAll('#connections-own .setting-row').length === {n_rows}",
            20000,
        )
        time.sleep(1.5)
        return b.run(READ_ROWS)

    # --- normal window -----------------------------------------------------
    with tempfile.TemporaryDirectory(prefix="final-batch-", dir=tmp) as profile:
        with Browser(user_data_dir=profile) as b:
            links = menu_links(b)
            check("normal window: the three Settings links show",
                  links == {"protection": True, "reading": True, "summaries": True}, str(links))
            r = rows(b)
            check("normal window: the Secure DNS switch can be used",
                  not r.get("secure_dns", {}).get("disabled", True), str(r.get("secure_dns")))
            check("normal window: no off-the-record wording",
                  all(row["detail"] != NORMAL_WINDOW for row in r.values()), str(r))

            # --- new tab, numbers out of the int range ----------------------
            b.get("chrome://newtab")
            wait_for(b, "document.readyState === 'complete'", 10000)
            b.run("chrome.send('showEngineMenu', [1e300, -1e300, 1e20, -5e19]); return 1")
            time.sleep(1.5)
            b.run("document.body.click(); return 1")
            b.get("chrome://version")
            check("new tab: the browser is still there after huge engine button numbers",
                  wait_for(b, "document.body.innerText.length > 0", 10000))

    # --- incognito and guest -----------------------------------------------
    for label, args in (("incognito", ["--incognito"]), ("guest", ["--guest"])):
        with tempfile.TemporaryDirectory(prefix="final-batch-", dir=tmp) as profile:
            with Browser(user_data_dir=profile, args=args) as b:
                if label == "guest":
                    links = menu_links(b)
                    check("guest: the three Settings links are hidden",
                          links == {"protection": False, "reading": False, "summaries": False},
                          str(links))
                r = rows(b)
                d = r.get("secure_dns", {})
                u = r.get("browser_updates", {})
                check(f"{label}: Secure DNS switch cannot be used", d.get("disabled") is True, str(d))
                check(f"{label}: Secure DNS says {NORMAL_WINDOW!r}",
                      d.get("detail") == NORMAL_WINDOW, str(d))
                check(f"{label}: browser update switch cannot be used",
                      u.get("disabled") is True, str(u))
                check(f"{label}: Secure DNS reads on", d.get("on") is True, str(d))
                b.run("chrome.send('setConnection', ['secure_dns', false]); return 1")
                time.sleep(1.5)
                r = rows(b)
                check(f"{label}: a forged message leaves Secure DNS on",
                      r.get("secure_dns", {}).get("on") is True, str(r.get("secure_dns")))
            # The browser is closed, so Local State is complete.
            try:
                local_state = json.loads((Path(profile) / "Local State").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                local_state = {}
            got = dig(local_state, dns["switch"]["pref"])
            check(f"{label}: Local State does not hold Secure DNS off",
                  got != dns["switch"]["off"], repr(got))

    print("smoke_final_batch:", "FAIL" if failures else "PASS")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
