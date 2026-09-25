# Building it yourself

These are the real steps used to build this project, generalized from a
Windows checkout. Nothing here is a promise it builds cleanly on your
machine; Chromium builds are large and sensitive to disk space, path
length, and toolchain versions. Expect to troubleshoot.

## What you need

- Windows 10/11, x64. (The project has only been built on Windows so far.)
- **Visual Studio 2022**, with "Desktop development with C++" and the
  MFC/ATL components.
- **Windows 11 SDK**, plus the SDK's "Debugging Tools for Windows" feature
  (a separate standalone install, not in the main VS Installer component
  list).
- **Python 3.11+** (a real python.org install, not the Microsoft Store
  alias), with long paths enabled.
- **Git**, **7-Zip**, and **ninja** on PATH.
- A Rust toolchain, for the `boring-core/rust` static library.
- 100 GB+ free on an SSD. Keep the checkout path short and near a drive
  root (for example `E:\ung`) to avoid Windows path-length issues.
- Exclude the checkout from real-time antivirus scanning, or the build
  will be dramatically slower.

## Step 1: build ungoogled-chromium on its own

This project does not use `depot_tools` directly; it builds on top of
[ungoogled-chromium-windows](https://github.com/ungoogled-software/ungoogled-chromium-windows),
which has its own build script that fetches Chromium source and applies
the de-Google patch set for you.

From a "Developer Command Prompt for VS 2022":

```
git clone --recurse-submodules https://github.com/ungoogled-software/ungoogled-chromium-windows.git ung
cd ung
git checkout --recurse-submodules 153.0.8010.52-1.1
python3 build.py
```

This clones Chromium source, applies ungoogled-chromium's patches, and
compiles. It takes hours on the first run. Confirm it worked by running
the resulting `chrome.exe` under `build\src\out\Default\`.

On a second or later run against the same checkout, use `python3 build.py --ci`
to skip the reclone/repatch step and resume the build; a plain `build.py`
reclones and repatches from scratch every time.

## Step 2: apply this project's patch layer

With a built ungoogled-chromium tree in hand, clone this repository
somewhere separate, then run:

```
python boring-core/tools/get_winsparkle.py
python boring-core/tools/apply.py --patch-set 153 --src <path-to-ungoogled-chromium-checkout>\build\src
```

This does three things:

1. Copies `boring-core/components/boring/*` and related file overlays into
   the Chromium tree.
2. Applies every patch listed in `boring-core/patches/series`, in order,
   against that tree.
3. Builds the Rust static library under `boring-core/rust`
   (`boring_adblock`) and places it where the C++ side expects it.

To undo everything the layer changed in the Chromium tree:

```
python boring-core/tools/apply.py --restore
```

## Step 3: build the browser

From the same Developer Command Prompt, with `DEPOT_TOOLS_WIN_TOOLCHAIN=0`
set (required for a hand-run ninja build; `build.py` sets this for you but
a direct `ninja` invocation does not):

```
set DEPOT_TOOLS_WIN_TOOLCHAIN=0
cd <ungoogled-chromium-checkout>\build\src
ninja -C out\Default chrome chromedriver mini_installer
```

This rebuilds only what changed since the last ungoogled-chromium build,
so it is much faster than a from-scratch build once one has succeeded.

## Step 4: check it

```
python boring-core/tools/smoke_all.py
```

This drives the built browser through its own debugging protocol
(WebDriver/CDP) to exercise the patched-in features (Protection page,
privacy defaults, summary panel, reader mode, and so on) and reports
pass/fail. It does not replace manually using the browser.

## Notes on what this does not cover

- This does not produce a signed installer. Packaging exists
  (`boring-core/tools` has packaging and appcast helpers) but signing
  needs a certificate this project does not have yet.
  See [LIMITATIONS.md](LIMITATIONS.md).
- Widevine/DRM is not part of this build. See LIMITATIONS.md.
- If you hit a build failure, the most common causes on Windows are stale
  MIDL-generated typelib placeholders, a missing SDK debugging-tools
  feature, or a Defender exclusion not being set. None of these are
  specific to this project; they are ungoogled-chromium/Chromium-on-Windows
  build quirks.
