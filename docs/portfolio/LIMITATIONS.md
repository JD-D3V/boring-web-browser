# Limitations, plainly

What release 1 does not do, or has not proven yet.

## What was tested

Release 1 is built on Chromium 153.0.8010.52. The release files passed
the full automated suite on the build PC (smoke tests, sandbox, package
check, network audit). They were then installed on a clean Windows 11
24H2 in Windows Sandbox: first run, browsing, settings kept across a
restart, ad blocking, the offline update test and uninstall.

That clean install found a real bug: the ad block engine needed the
Visual C++ runtime, so on a PC without it blocking was silently off.
It was fixed and re-tested before release.

## Updates are new

Installed copies check once a day for a new release, using WinSparkle and
a fixed feed at `https://jd-d3v.github.io/boring-web-browser/appcast.xml`. A new release
installs only after you agree, and only with a valid EdDSA signature from
our key. A copy run from the zip does not update. In a Sandbox test with a
throwaway key, the prompt, download and signature check worked, and
tampered or wrongly signed installers were refused. But a test release on
the same Chromium version did not replace the installed files, so updating
from one real release to the next is not proven yet. If it fails, an
out-of-date Chromium gets less safe every week, so check the release page
yourself.

## Unsigned

There is no code-signing certificate. SmartScreen will warn when you run
the installer. Do not turn SmartScreen or Defender off. Signing is planned
after release 1. A signature identifies the publisher; it does not prove
the software is safe.

## No scam warning page

Scam and phishing blocking needs a list we are allowed to pass on. The
feeds we tried (URLhaus, OpenPhish) allow access but not redistribution
inside an installer, so no scam list ships. The warning page code is in the
tree but has nothing to act on.

What release 1 does instead: secure DNS through Quad9, which refuses to
look up known malware and phishing domains. There is no warning page. The
site just does not open. New or unreported sites get through, and changing
secure DNS away from Quad9 removes this protection.

## No Widevine

Widevine needs a licence from Google. Netflix and other DRM video will not
play.

## Blocking lists do not update

The ad and tracker lists are fixed at build time. List updates need a
separate list signing key that does not exist yet, so the browser keeps the lists it
shipped with. A newer release brings newer lists. EasyList and EasyPrivacy
are used under their own licence terms.

## Extensions, spelling and import are new

- Chrome Web Store extensions update only through the built-in store
  helper, not through Chromium. Remove the helper and they stop getting
  updates. The helper itself changes only with a browser update.
- The helper asks Google's extension update service about your store
  extensions every 5 hours. The privacy page lists what it sends.
- Spellcheck uses Windows' checker first. On a PC that has English
  spelling data, the bundled English (US) dictionary cannot be shown to
  load, because Windows does the work.
- Import reads Chrome and Edge from their usual folders on this computer.
  It never takes passwords or cookies.

None of these has been tested on a built release yet.

## Not in release 1

- Sync. `sync-server/` is a separate Go server. The browser does not use it.
- Tor windows.

## Privacy is measured, not promised

ungoogled-chromium removes Google's background calls, and this project adds
no telemetry. The browser still contacts some services on its own, such as
Quad9 for DNS. Each release lists what a network audit saw on that build.
That audit covers the paths it exercised, not every code path.

Page summaries are off until you pick a provider. A remote provider
receives the page text.

## One maintainer

No support promise, no fixed update schedule.
