# the boring web browser

Working name. A browser should be boring: dependable, private, no drama,
no crypto, no hype.

A private, fast, well made browser with a focus on keeping ordinary
people safe, especially from the scam ads and scam sites that catch older
and less technical users.

Three things it has to get right:

1. **Privacy.** Strong ad and tracker blocking, on by default, no
   configuration required. Nothing phones home. No crypto, no ad network,
   no partner deals.
2. **Safety.** Scam ads and scam sites get blocked and called out, with a
   single switch Senior Safe Mode that locks the whole thing down for
   someone who just wants to read the news and check their email.
3. **Polish and speed.** A clean, readable interface that feels native,
   video that plays properly, and memory use that doesn't get silly.

## How it's built

Desktop is a Chromium fork with a deliberately thin patch layer, kept in
`boring-core`, on top of ungoogled-chromium. The engine is left alone, so
security fixes from upstream can be taken quickly instead of turning into
a rescue operation every time.

`sync-server` is a small Go server that speaks the Chromium sync
protocol, so bookmarks and passwords sync without a Google account.

## Building

You need a working ungoogled-chromium checkout that has been built once,
plus Python 3 and a Rust toolchain.

```
python boring-core/tools/apply.py --src <path-to-chromium-src>
```

That copies `components/boring` and the file overlays into the tree,
applies the patches listed in `boring-core/patches/series`, and builds
the Rust static library. Then build `chrome` as usual with ninja.

Run `python boring-core/tools/apply.py --restore` to undo every change to
the Chromium files.

To check a finished build:

```
python boring-core/tools/smoke_all.py
```

## License

TBD.
