"""The one place the browser's name and publisher are written down.

JD has not chosen the final name, so "Boring Browser" is a placeholder.
rebrand.py reads it for the installer, the shortcuts, the uninstall
entry and the file properties of every binary, and rename_release.py
reads it for the file names people download. Changing the name later is
one edit here.

Read by: rebrand.py, rename_release.py, branded_string_check.py and
check_package.py.

Not generated from here, so look for them when the name changes:
  - patches/package-boring-files.patch, apply.py and check_package.py
    spell out LICENSE-<ID>.txt (tests/test_installer_strings.py fails if
    they stop matching ID).
  - the strings in the browser's own pages (components/boring/welcome,
    protection, update), the README, the download site and the winget
    manifests.

Left spelled out in rebrand.py on purpose: the ProgID prefixes
(BoringHTM, BoringPDF) and the boringbrowser URL scheme. Nobody sees
them, and changing them drops the default browser choice of anyone who
updates.
"""

NAME = "Boring Browser"

# Who Windows says publishes the browser: the Publisher column of
# Installed apps, the uninstall entry, and "Company" in the properties
# of chrome.exe, chrome.dll, setup.exe and the installer. Windows shows
# it on the line under the app's name, so the product name here would
# only repeat itself; the person who publishes it says something. It
# was "The Chromium Authors", which read as though Google's Chromium
# team shipped this build. They are still credited as the copyright
# holder, which is what that text is for.
PUBLISHER = "JD"

# Used where Windows wants no spaces: the install folder, registry ids,
# ProgIDs, the URL scheme and the names of the files people download.
ID = NAME.replace(" ", "")
