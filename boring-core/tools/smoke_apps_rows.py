#!/usr/bin/env python3
"""Check "What the browser connects to", part "Apps you added", on the
Protection page.

  - A fresh profile has no add-ons: the page says "No apps added." and how
    to add one, the bundled store is not listed as an app, and the AI
    assistant row reads Off with its switch off and unusable.
  - Test add-ons with host permissions, nativeMessaging, and no host
    permissions all get rows with the expected permissions and controls.
  - The switch on a row disables and enables the add-on, matched against
    chrome://extensions (chrome.developerPrivate), not just the row.
  - Saving the local Ollama provider on chrome://boring-ai makes the AI row
    read "Ollama on this computer"; its switch sets the provider back to Off.
  - The Remove button asks through Chromium's own uninstall dialog, a native
    window. Headless that question cannot be answered, so only "pressing
    Remove alone takes nothing away" is checked. With BORING_ALLOW_HEADFUL=1
    (a dedicated test session, see drive.py) a real window is used and the
    answers are given through UI Automation on our own window: Cancel keeps
    the add-on and its row, Remove takes both away and leaves the other
    add-on alone. No mouse or key input is sent anywhere.

An inert add-on with Bitwarden's public key exercises password manager
grouping and the built-in save password preference without running Bitwarden.
"""

import json
import os
import shutil
import sys
import tempfile
import time

from drive import Browser, headful_allowed

URL = "chrome://boring-protection"
TMP = os.environ.get("TMP", r"E:\tmp")
HOST_NAME = "Boring Test Hosts"
NATIVE_NAME = "Boring Test Native"
PLAIN_NAME = "Boring Test Plain"
PASSWORD_NAME = "Boring Test Password Manager"
# Public key from the Bitwarden Chrome Web Store CRX3, used only to give
# the inert test manifest its real ID. No extension code is included.
BITWARDEN_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAmqKbvreshyXRuN2gikeR1idqR6"
    "KL0Di89JZcMyD4bjJRZVmQO7aznSGSALIHzSAUGYocUYBNDOP5QAhImxXyQ1qG8+goXs9"
    "3v9GzrNJETdVuCEhqBggC4/DFabryJZDiKvZ2Jl0DM7MsWdoybZPwrj70V3aJ/nVNOMkf"
    "868scNTMliwitCqqjT5baTANsG0DkZWQExD4lSXzSZHH9MEO8q0iZ7RRlNuGRBAkZgNV8F"
    "wZRsPKm/rwQ9dy3VpgLcmLp5GiMt+kAEncqKAkuRYnhVXXBsKqIyYTMjHSLkLnpfFySyO"
    "PLBdS617i/PGNiP/MT6Xy6z//v5NozUgaAZ4gJQIDAQAB"
)


def write_extension(root, name, extra):
    """A tiny unpacked Manifest V3 add-on. `extra` is merged into the manifest."""
    os.makedirs(root, exist_ok=True)
    manifest = {"manifest_version": 3, "name": name, "version": "1.0"}
    manifest.update(extra)
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    return root


def test_extensions(work):
    hosts = write_extension(
        os.path.join(work, "hosts"),
        HOST_NAME,
        {"host_permissions": ["http://apps-target.localhost/*"]},
    )
    native = write_extension(
        os.path.join(work, "native"), NATIVE_NAME, {"permissions": ["nativeMessaging"]}
    )
    plain = write_extension(os.path.join(work, "plain"), PLAIN_NAME, {})
    password = write_extension(
        os.path.join(work, "password"),
        PASSWORD_NAME,
        {"key": BITWARDEN_KEY, "permissions": ["nativeMessaging"]},
    )
    return hosts, native, plain, password


KEEP_NAME = "Boring Test Keep"
GONE_NAME = "Boring Test Goes Away"


def write_removal_addons(work):
    """Two add-ons for the Remove check. The second has a page that
    removes the add-on, with no question asked (showConfirmDialog false)."""
    keep = write_extension(os.path.join(work, "keep"), KEEP_NAME, {})
    gone = write_extension(os.path.join(work, "gone"), GONE_NAME, {})
    with open(os.path.join(gone, "bye.html"), "w", encoding="utf-8") as f:
        f.write('<!doctype html><title>bye</title><script src="bye.js"></script>')
    with open(os.path.join(gone, "bye.js"), "w", encoding="utf-8") as f:
        f.write("chrome.management.uninstallSelf({showConfirmDialog: false});")
    return keep, gone


def remove_by_itself(b, row):
    """Opens the add-on's removal page in another tab and comes back, with
    the Protection page still open in the first."""
    window = f"/session/{b.sid}/window"
    protection = b._req("GET", window)["value"]
    other = b._req("POST", window + "/new", {"type": "tab"})["value"]["handle"]
    extension_id = row["id"].removeprefix("app-").removesuffix("-row")
    try:
        b._req("POST", window, {"handle": other})
        b.get(f"chrome-extension://{extension_id}/bye.html")
        time.sleep(2)
    finally:
        try:
            b._req("DELETE", window)
        except RuntimeError:
            pass  # the tab went with the add-on
        b._req("POST", window, {"handle": protection})


def wait_for(b, script, seconds=25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if b.run(script):
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


APPS_READY = "return !!document.querySelector('#connections-apps .setting-row')"

READ_APPS = """
  var out = {rows: [], heads: [], empty: null, ai: null, exportUrl: null};
  var box = document.getElementById('connections-apps');
  var group = '';
  Array.prototype.forEach.call(box.children, function(c) {
    if (c.tagName === 'H4') { group = c.textContent; out.heads.push(group); }
    if (!c.classList.contains('setting-row')) { return; }
    var sw = c.querySelector('input.switch');
    if (!sw) { return; }
    if (sw.id === 'stop-saving-passwords') { return; }
    var item = {id: c.id, group: group, text: c.innerText, on: sw.checked,
                disabled: sw.disabled, canRemove: !!c.querySelector('button')};
    if (c.id === 'ai-assistant-row') { out.ai = item; } else { out.rows.push(item); }
  });
  var e = document.getElementById('apps-empty');
  out.empty = e ? e.innerText : null;
  var exportLink = box.querySelector('a[href="chrome://password-manager/settings"]');
  out.exportUrl = exportLink ? exportLink.href : null;
  out.text = box.innerText;
  return out;
"""

EXT_STATE = """
  var done = arguments[arguments.length - 1];
  chrome.developerPrivate.getExtensionsInfo(
      {includeDisabled: true, includeTerminated: true}, function(list) {
    var out = {};
    list.forEach(function(e) { out[e.name] = e.state; });
    done(out);
  });
"""

SAVE_PREF = """
  var done = arguments[arguments.length - 1];
  chrome.settingsPrivate.getPref('credentials_enable_service',
                                 pref => done(pref.value));
"""

SET_HOST_ACCESS = """
  const [extensionId, grant, done] = arguments;
  const access = chrome.developerPrivate.HostAccess;
  chrome.developerPrivate.updateExtensionConfiguration({
    extensionId, hostAccess: grant ? access.ON_ALL_SITES : access.ON_CLICK
  }).then(() => done(null), error => done(String(error)));
"""


def read_apps(b):
    return b.run(READ_APPS)


def row_for(apps, name):
    for r in apps["rows"]:
        if name in r["text"]:
            return r
    return None


def extension_states(b):
    b.get("chrome://extensions")
    for _ in range(40):
        try:
            return b.run_async(EXT_STATE)
        except Exception:
            time.sleep(0.5)
    return {}


def check_live_host_access(b, host_row):
    """Change access in another tab while the Protection page stays open."""
    window = f"/session/{b.sid}/window"
    protection = b._req("GET", window)["value"]
    extensions = b._req("POST", window + "/new", {"type": "tab"})["value"]["handle"]
    extension_id = host_row["id"].removeprefix("app-").removesuffix("-row")
    try:
        for grant in (False, True):
            b._req("POST", window, {"handle": extensions})
            b.get("chrome://extensions")
            if not wait_for(b, "return !!chrome.developerPrivate?.updateExtensionConfiguration"):
                return "could not open Chromium's add-on controls"
            error = b.run_async(SET_HOST_ACCESS, [extension_id, grant])
            if error:
                return f"could not change site access: {error}"
            b._req("POST", window, {"handle": protection})
            if not wait_for(
                b,
                "return document.getElementById(%s).innerText.includes('apps-target.localhost') === %s"
                % (json.dumps(host_row["id"]), "true" if grant else "false"),
                8,
            ):
                return "site access text did not update in the open Protection page"
    finally:
        b._req("POST", window, {"handle": extensions})
        b._req("DELETE", window)
        b._req("POST", window, {"handle": protection})
    return None


def native_remove_answers(work, failures):
    """The Remove question answered both ways, in a real window.

    Chromium's uninstall dialog is a native window WebDriver cannot see, so
    it is found and pressed through UI Automation on windows of the browser
    this test started (the same helpers smoke_site_panel.py uses). Names of
    every control seen are printed, so a dialog worded differently on a new
    Chromium says what it said instead of just failing."""
    from capture_native import frame_window
    from drive import CHROME
    from smoke_site_panel import Window, browser_windows

    def find_dialog(b, frame, seconds):
        deadline = time.monotonic() + seconds
        seen = []
        while time.monotonic() < deadline:
            for hwnd in browser_windows(b.proc.pid):
                if hwnd == frame:
                    continue
                try:
                    with Window(hwnd) as w:
                        names = w.names()
                except OSError:
                    continue
                seen = names or seen
                if "Cancel" in names and "Remove" in names:
                    return hwnd, names
            time.sleep(0.3)
        return None, seen

    def press(hwnd, name):
        with Window(hwnd) as w:
            return w.press(lambda n: n == name)

    keep, gone = write_removal_addons(os.path.join(work, "native"))
    with Browser(
        user_data_dir=os.path.join(work, "native-profile"),
        args=["--load-extension=" + keep + "," + gone, "--window-size=1200,850"],
        headful=True,
    ) as b:
        b.get(URL)
        if not wait_for(
            b, "return document.querySelectorAll('#connections-apps .setting-row[id^=app-]').length === 2"
        ):
            failures.append("remove (real window): the two add-on rows did not appear")
            return
        frame = frame_window(CHROME, under=b.proc.pid)
        apps = read_apps(b)
        keep_row, gone_row = row_for(apps, KEEP_NAME), row_for(apps, GONE_NAME)
        if not keep_row or not gone_row:
            failures.append(f"remove (real window): rows missing: {apps['rows']!r}")
            return

        # Cancel: nothing is taken away.
        b.run("document.querySelector('#%s .app-remove').click(); return 1" % keep_row["id"])
        dialog, names = find_dialog(b, frame, 20)
        print("remove question (Cancel):", names)
        if not dialog:
            failures.append(f"remove (real window): no question with Remove and Cancel appeared; saw {names!r}")
            return
        print("pressed Cancel through", press(dialog, "Cancel"))
        gone_after = find_dialog(b, frame, 6)[0] is None
        if not gone_after:
            failures.append("remove (real window): the question stayed after Cancel")
        time.sleep(1)
        if not row_for(read_apps(b), KEEP_NAME):
            failures.append("remove (real window): Cancel took the row away")
        states = extension_states(b)
        print("after Cancel:", states)
        if states.get(KEEP_NAME) != "ENABLED":
            failures.append(f"remove (real window): Cancel changed the add-on: {states}")
        b.get(URL)
        wait_for(b, "return !!document.getElementById('ai-assistant-row')")
        if not row_for(read_apps(b), KEEP_NAME):
            failures.append("remove (real window): after Cancel and a reload the row is gone")

        # Remove: this add-on and its row go, the other stays.
        apps = read_apps(b)
        gone_row = row_for(apps, GONE_NAME)
        if not gone_row:
            failures.append("remove (real window): the row to remove is missing")
            return
        b.run("document.querySelector('#%s .app-remove').click(); return 1" % gone_row["id"])
        dialog, names = find_dialog(b, frame, 20)
        print("remove question (Remove):", names)
        if not dialog:
            failures.append(f"remove (real window): the second question did not appear; saw {names!r}")
            return
        print("pressed Remove through", press(dialog, "Remove"))
        if not wait_for(
            b, "return !document.getElementById(%s)" % json.dumps(gone_row["id"]), 20
        ):
            failures.append("remove (real window): the row did not go after Remove")
        states = extension_states(b)
        print("after Remove:", states)
        if GONE_NAME in states:
            failures.append(f"remove (real window): Remove left the add-on installed: {states}")
        if states.get(KEEP_NAME) != "ENABLED":
            failures.append(f"remove (real window): Remove touched the other add-on: {states}")
        b.get(URL)
        wait_for(b, "return !!document.getElementById('ai-assistant-row')")
        apps = read_apps(b)
        if row_for(apps, GONE_NAME) or not row_for(apps, KEEP_NAME):
            failures.append(f"remove (real window): after Remove and a reload the rows are wrong: {apps['rows']!r}")


def main():
    failures = []
    work = tempfile.mkdtemp(prefix="apps-rows-", dir=TMP)
    try:
        extensions = test_extensions(work)

        # 1. Fresh profile, no add-ons.
        with Browser(user_data_dir=os.path.join(work, "empty")) as b:
            b.get(URL)
            if not wait_for(b, "return !!document.getElementById('ai-assistant-row')"):
                failures.append("the Apps you added part never appeared")
            apps = read_apps(b)
            if not apps["empty"] or "No apps added." not in apps["empty"]:
                failures.append(f"empty state missing: {apps['empty']!r}")
            if apps["empty"] and "web store" not in apps["empty"]:
                failures.append("empty state does not say how to add one")
            if apps["rows"]:
                failures.append("rows with no add-ons: " + repr(apps["rows"]))
            if apps["exportUrl"] != "chrome://password-manager/settings":
                failures.append("built-in password manager is missing its export link")
            if not b.run("return document.getElementById('stop-saving-passwords-row')?.hidden"):
                failures.append("the save prompt switch should be hidden without a password add-on")
            ai = apps["ai"]
            if not ai or "Off" not in ai["text"] or ai["on"] or not ai["disabled"]:
                failures.append(f"AI row should read Off, switch off and unusable: {ai!r}")
            if ai and "Set up" not in ai["text"]:
                failures.append("AI row has no Set up link")
            for word in ("Any add-on can reach the internet", "AI"):
                if word not in apps["text"]:
                    failures.append(f"part is missing {word!r}")
            if "\u2014" in apps["text"]:
                failures.append("an em dash on the page")
            print("empty profile:", apps["empty"], "|", (ai or {}).get("text", "").replace("\n", " / "))

        # 2 and 3. Add-on switches matched against chrome://extensions.
        profile = os.path.join(work, "with")
        os.makedirs(os.path.join(profile, "Default"))
        with open(os.path.join(profile, "Default", "Preferences"), "w", encoding="utf-8") as f:
            json.dump({"credentials_enable_service": True}, f)
        with Browser(
            user_data_dir=profile, args=["--load-extension=" + ",".join(extensions)]
        ) as b:
            b.get(URL)
            if not wait_for(
                b, "return document.querySelectorAll('#connections-apps .setting-row[id^=app-]').length === 4"
            ):
                failures.append("add-on rows did not appear")
            apps = read_apps(b)
            print("rows:", [r["text"].replace("\n", " / ") for r in apps["rows"]])
            if apps["empty"]:
                failures.append("empty state showed with add-ons loaded")
            if "Other add-ons" not in apps["heads"]:
                failures.append(f"no Other add-ons heading: {apps['heads']}")
            host_row = row_for(apps, HOST_NAME)
            native_row = row_for(apps, NATIVE_NAME)
            if not host_row or "apps-target.localhost" not in host_row["text"]:
                failures.append(f"host row missing its Chromium permission text: {host_row!r}")
            if not native_row or "cooperating native applications" not in native_row["text"]:
                failures.append(f"native row missing its Chromium permission text: {native_row!r}")
            plain_row = row_for(apps, PLAIN_NAME)
            if not plain_row:
                failures.append("an add-on without host permissions did not get a row")
            if len(apps["rows"]) != 4:
                failures.append(f"expected 4 add-on rows, got {len(apps['rows'])}")
            for r in (host_row, native_row, plain_row):
                if r and (not r["on"] or r["disabled"] or r["group"] != "Other add-ons"):
                    failures.append(f"row should be on, usable, under Other add-ons: {r!r}")
                if r and not r["canRemove"]:
                    failures.append(f"add-on has no Remove button: {r!r}")
            if "Web Store" in " ".join(r["text"] for r in apps["rows"]):
                failures.append("the bundled store is listed as an app")

            password_row = row_for(apps, PASSWORD_NAME)
            if not password_row or password_row["group"] != "Password managers":
                failures.append(f"password manager did not get grouped: {password_row!r}")
            if b.run("return !document.getElementById('stop-saving-passwords-row')?.hidden "
                     "&& !!document.getElementById('stop-saving-passwords')"):
                if b.run("return document.getElementById('stop-saving-passwords').checked"):
                    failures.append("the save prompt switch did not read the seeded preference")
                b.run("document.getElementById('stop-saving-passwords').click(); return 1")
                b.get("chrome://settings")
                if not wait_for(b, "return !!chrome.settingsPrivate?.getPref"):
                    failures.append("could not read the built-in save password preference")
                elif b.run_async(SAVE_PREF) is not False:
                    failures.append("the browser's built-in save prompt is still on")
                b.get(URL)
                if not wait_for(
                    b, "return document.getElementById('stop-saving-passwords').checked"
                ):
                    failures.append("turning off the built-in save prompt did not persist")
            else:
                failures.append("an enabled password manager did not expose the save prompt switch")

            if host_row:
                live_error = check_live_host_access(b, host_row)
                if live_error:
                    failures.append(live_error)
                switch = "#" + host_row["id"].replace("-row", "")
                b.run(f"document.querySelector('{switch}').click(); return 1")
                if not wait_for(b, f"return !document.querySelector('{switch}').checked"):
                    failures.append("host switch did not read off after a click")
                states = extension_states(b)
                print("after off:", states)
                if states.get(HOST_NAME) != "DISABLED":
                    failures.append(f"switch off did not disable the add-on: {states}")
                if states.get(NATIVE_NAME) != "ENABLED":
                    failures.append(f"the other add-on changed: {states}")
                b.get(URL)
                wait_for(b, APPS_READY)
                again = row_for(read_apps(b), HOST_NAME)
                if not again or again["on"] or again["disabled"]:
                    failures.append(f"disabled add-on row after reload: {again!r}")
                b.run(f"document.querySelector('{switch}').click(); return 1")
                if not wait_for(b, f"return document.querySelector('{switch}').checked"):
                    failures.append("host switch did not read on after a second click")
                states = extension_states(b)
                print("after on:", states)
                if states.get(HOST_NAME) != "ENABLED":
                    failures.append(f"switch on did not enable the add-on: {states}")

            # 4. The AI row follows chrome://boring-ai.
            b.get("chrome://boring-ai")
            wait_for(b, "return !!document.getElementById('p-ollama')")
            b.run(
                "document.getElementById('p-ollama').click();"
                "document.getElementById('model').value = 'llama3.2';"
                "document.getElementById('save').click(); return 1"
            )
            time.sleep(1.5)
            b.get(URL)
            ok = wait_for(
                b, "var r = document.getElementById('ai-assistant-row');"
                "return !!r && r.innerText.indexOf('Ollama on this computer') >= 0"
            )
            ai = read_apps(b)["ai"]
            print("AI row after Ollama:", (ai or {}).get("text", "").replace("\n", " / "))
            if not ok or not ai or not ai["on"] or ai["disabled"] or "Change" not in ai["text"]:
                failures.append(f"AI row should read Ollama on this computer, on: {ai!r}")
            b.run("const input = document.getElementById('ai-assistant');"
                  "input.focus(); input.click(); return 1")
            ok = wait_for(
                b, "var r = document.getElementById('ai-assistant-row');"
                "return r.innerText.indexOf('Off') >= 0"
                " && !document.getElementById('ai-assistant').checked"
            )
            if not ok:
                failures.append("the AI switch did not set the assistant back to Off")
            elif not b.run(
                "return document.activeElement === "
                "document.querySelector('#ai-assistant-row a')"
            ):
                failures.append("turning AI off lost keyboard focus instead of moving it to Set up")
            b.get("chrome://boring-ai")
            wait_for(b, "return !!document.getElementById('p-off')")
            if not b.run("return document.getElementById('p-off').checked"):
                failures.append("chrome://boring-ai does not show Off after the switch")

        # 5. The Remove button (A3). It asks through Chromium's own
        # uninstall dialog, a native window that WebDriver cannot see and
        # that cannot be answered without input to a real window, so the
        # Cancel and Remove answers are not driven here. What is checked:
        # pressing Remove alone takes nothing away (as when the dialog is
        # cancelled), and a row goes at once when its add-on is removed
        # (the add-on removes itself, which asks nothing).
        keep, gone = write_removal_addons(work)
        with Browser(
            user_data_dir=os.path.join(work, "removal"),
            args=["--load-extension=" + keep + "," + gone],
        ) as b:
            b.get(URL)
            if not wait_for(
                b, "return document.querySelectorAll('#connections-apps .setting-row[id^=app-]').length === 2"
            ):
                failures.append("remove: the two add-on rows did not appear")
            else:
                apps = read_apps(b)
                keep_row = row_for(apps, KEEP_NAME)
                gone_row = row_for(apps, GONE_NAME)
                if not keep_row or not gone_row or not keep_row["canRemove"]:
                    failures.append(f"remove: rows or Remove buttons missing: {apps['rows']!r}")
                else:
                    b.run(
                        "document.querySelector('#%s .app-remove').click(); return 1"
                        % keep_row["id"]
                    )
                    time.sleep(3)
                    if not row_for(read_apps(b), KEEP_NAME):
                        failures.append("remove: the row went away on Remove, before any answer")
                    remove_by_itself(b, gone_row)
                    if not wait_for(
                        b,
                        "return !document.getElementById(%s)" % json.dumps(gone_row["id"]),
                        8,
                    ):
                        failures.append("remove: the row of a removed add-on did not go from the open page")
                    if not row_for(read_apps(b), KEEP_NAME):
                        failures.append("remove: another add-on's row went with it")
                    states = extension_states(b)
                    print("after remove:", states)
                    if states.get(KEEP_NAME) != "ENABLED":
                        failures.append(f"remove: pressing Remove alone changed the add-on: {states}")
                    if GONE_NAME in states:
                        failures.append(f"remove: the removed add-on is still installed: {states}")
                    b.get(URL)
                    wait_for(b, "return !!document.getElementById('ai-assistant-row')")
                    apps = read_apps(b)
                    if row_for(apps, GONE_NAME) or not row_for(apps, KEEP_NAME):
                        failures.append(f"remove: after reloading the page the rows are wrong: {apps['rows']!r}")

        # 6. The Cancel and Remove answers, in a real window only.
        if headful_allowed():
            native_remove_answers(work, failures)
        else:
            print("INFO the Cancel and Remove answers need a real window "
                  "(BORING_ALLOW_HEADFUL=1); not run")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("ok: apps you added rows, switches and AI row")
    return 0


if __name__ == "__main__":
    sys.exit(main())
