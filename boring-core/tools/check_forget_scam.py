#!/usr/bin/env python3
"""Forget this site also takes back a "Continue anyway" (ledger 129, S14), in a
real window.

Same local setup as smoke_scam.py (a temporary scam list, a local name mapped
to 127.0.0.1) and the same way of pressing the shield panel as
smoke_forget.py (UI Automation on our own window; no mouse or keys sent to
the desktop):

  1. the listed site shows the scam warning
  2. Continue anyway opens it, and a second visit in the same session opens it
     without the warning (the click-through is remembered for the session)
  3. Forget this site (shield panel, row, question, Forget)
  4. the tab reloads, and the scam warning is back

Usage: python check_forget_scam.py
"""

import ctypes
import tempfile
import time

from capture_native import frame_window
from drive import CHROME, Browser
from smoke_forget import QUESTION, names_of, press, safe
from smoke_local import HTML, Pages, list_folder, wait_for
from smoke_scam import (
    CONTINUE,
    LISTED,
    SAFE_PAGE,
    SCAM_LIST,
    args_for,
    open_url,
    wait_until_list_is_loaded,
)
from smoke_site_panel import find_panel, poll, press_shield

WARNING = "This site may be a scam"


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    failures = []

    def check(name, ok, detail=""):
        print(
            f"{'PASS' if ok else 'FAIL'}: {name}" + (f" ({detail})" if detail else "")
        )
        if not ok:
            failures.append(name)

    def warned(b):
        return bool(
            safe(
                lambda: b.run(
                    f"return !!document.body && document.body.innerText.includes({WARNING!r})"
                )
            )
        )

    pages = Pages({"/": (SAFE_PAGE, HTML)})
    try:
        with (
            list_folder({"scamlist.txt": SCAM_LIST}) as lists,
            tempfile.TemporaryDirectory(prefix="forget-scam-") as profile,
            Browser(
                user_data_dir=profile,
                args=args_for(
                    lists,
                    pages,
                    ["--boring-shield-panel-test", "--disable-background-mode"],
                ),
                headful=True,
            ) as b,
        ):
            frame = frame_window(CHROME, under=b.proc.pid)
            check("the scam list is loaded", wait_until_list_is_loaded(b))
            site = f"http://{LISTED}:{pages.port}/"

            open_url(b, site)
            time.sleep(1)
            check("the listed site shows the scam warning", warned(b))
            b.run(f"({CONTINUE}).click()")
            check(
                "Continue anyway opens the site",
                wait_for(b, "!!document.getElementById('ok')", 10000),
                b.current_url(),
            )
            open_url(b, site)
            check(
                "a second visit in the session opens without the warning",
                wait_for(b, "!!document.getElementById('ok')", 10000) and not warned(b),
            )

            try:
                press_shield(frame)
            except Exception as e:
                print(f"  could not press the shield: {e!r}")
            hwnd, names = find_panel(b, frame)
            check("the shield opens its panel", bool(hwnd))
            check("the panel has a Forget this site row", "Forget this site" in names)
            if hwnd:
                press(hwnd, "Forget this site")
                poll(lambda: QUESTION in names_of(hwnd), timeout=5)
                check("pressing the row asks first", QUESTION in names_of(hwnd))
                press(hwnd, "Forget")
            back = poll(lambda: warned(b), timeout=20)
            check("after Forget this site the scam warning is back", bool(back))
            check(
                "and the site itself is not open",
                not safe(lambda: b.run("return !!document.getElementById('ok')")),
            )
    finally:
        pages.close()
    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "all passed"))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
