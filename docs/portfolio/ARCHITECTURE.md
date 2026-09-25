# Architecture, five-minute version

## The base decision

This project does not write a rendering engine. It builds on
[ungoogled-chromium](https://github.com/ungoogled-software/ungoogled-chromium),
which is itself a patch set over stock Chromium that strips Google's
services, telemetry and background calls. Chromium's Blink engine, V8, the
sandbox and site isolation are all upstream and untouched.

Release 1 base: **Chromium 153.0.8010.52** (ungoogled-chromium tag
`153.0.8010.52-1.1`). See [LIMITATIONS.md](LIMITATIONS.md).

## The layers

```
Chromium / Blink (upstream, pinned, untouched)
        |
ungoogled-chromium (de-Google patch set, upstream)
        |
boring-core (this project's thin patch layer)
        |
the built browser
```

`boring-core` is deliberately small: as of this writing, 37 patch files
under `boring-core/patches/`, applied in order by
`boring-core/tools/apply.py`, plus a set of new files copied into the tree
(`boring-core/components/boring/*` and related overlays). Keeping the
patch set small matters for one practical reason: Chromium ships security
fixes on its own schedule, and a smaller delta is faster to re-merge onto
a new upstream version.

## What the patch layer adds

- **New WebUI surfaces**, under `chrome://boring-*` and wired into
  settings: a Protection page, a first-run welcome screen, a new tab page
  with a search engine picker, an on-click summary panel, and reader mode.
  A scam warning page exists in code but is not used in release 1.
- **Engine-level ad and tracker blocking**, via a small Rust static
  library (`boring-core/rust/`, crate name `boring_adblock`) that wraps
  the third-party `adblock` crate and is called from C++ through an FFI
  boundary (`boring-core/components/boring/adblock/adblock_ffi.cc`).
- **Privacy defaults**, in `privacy-defaults.patch`: HTTPS-first
  (balanced), Quad9 secure DNS (which refuses known malware and phishing
  domains), and ungoogled-chromium's fingerprint noise on canvas, text and
  element sizes. WebRTC is kept to proxied routes, which ungoogled already
  does.
- **Tracking parameter removal**, a navigation throttle in
  `components/boring/privacy` that strips known tracking parameters from
  cross-site navigations. The list is adapted from Brave (MPL-2.0).
- **An updater**, WinSparkle driven from `components/boring/update`. It
  reads a fixed feed and requires an EdDSA signature before any installer
  runs. It checks once a day, and only in installed copies.
- **Per-site blocking off**, from the toolbar shield. Ad, tracker and
  tab-under blocking skip the listed sites; Chromium's pop-up blocker is
  left alone. The Protection page lists them.
- **Chrome Web Store installs**, via `extension-install-defaults.patch`
  (every install prompts) and a bundled, pinned copy of
  [chromium-web-store](https://github.com/NeverDecaf/chromium-web-store)
  (MIT) with its self-update address removed, set up by
  `components/boring/webstore`. ungoogled-chromium turns off Chromium's
  own store updates, so the helper is what keeps store extensions current.
- **Spellcheck fallback**, an en-US Hunspell dictionary (SCOWL licence)
  shipped beside the browser. Windows' own checker still goes first.
- **Import from Chrome and Edge**, `components/boring/importer`: bookmarks,
  history and added search engines, one entry per profile. Never
  passwords or cookies.
- **List refresh**, `components/boring/lists/list_updater.*`, which would
  fetch newer blocking lists and verify a signed manifest first. Off in
  release 1, because the list signing key does not exist yet.
- **UI shape changes**: toolbar, tab shape, omnibox shape, settings page
  layout, all applied as patches against Chromium's own UI code rather
  than a bolted-on overlay.
- **Branding**: the name, icon and colour scheme, applied through
  `branding-resources.patch` and `boring-core/tools/rebrand.py`.

## What it deliberately does not touch

- The sandbox and site isolation are never disabled. This is treated as a
  hard rule, not a preference.
- Widevine/DRM is not re-enabled in shipped builds (see LIMITATIONS.md).
- No custom cryptography. List signing uses ECDSA P-256; update signing
  uses WinSparkle's EdDSA (Ed25519).

## Tooling

`boring-core/tools/` holds the mechanics that make the patch layer
maintainable rather than a one-time hack:

- `apply.py` / `apply.py --restore`, applies or reverts the whole layer
  against a Chromium checkout.
- `make_patch.py`, `rebase_check.py`, for regenerating and validating
  patches against a new upstream tag.
- `smoke_*.py`, a set of scripts that drive the built browser (via its own
  debugging protocol, never synthetic OS input) to check each feature
  still works after a rebase.
- `get_filterlists.py`, `get_scamlist.py`, `publish_lists.py`,
  `make_appcast.py`, the list and update pipeline.

## Why this shape

The goal is to take Chromium's own security work (engine, sandboxing,
patch cadence) essentially for free, add a specific and narrow set of
things Chromium/ungoogled-chromium do not do (blocking and privacy
defaults on from the start, a Senior Safe Mode, on-click summaries, and
later scam blocking once a list may be redistributed), and keep the patch surface small enough that one person can
actually keep it current. It is not an attempt to out-build Chromium.
