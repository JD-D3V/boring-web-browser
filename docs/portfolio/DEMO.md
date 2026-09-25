# Demo recording plan

A short screen recording of the built browser, for people who would
rather not run an unsigned build themselves. This is a plan,
not a finished recording; nothing here has been recorded yet.

## Ground rules for recording

- Record on a clean or disposable profile, never the developer's real
  browsing profile, bookmarks, history, or saved passwords.
- No personal data, email addresses, real accounts, or API keys visible
  on screen at any point, including in the omnibox history dropdown,
  window title, or taskbar.
- No signing keys, tokens, GitHub credentials, or file paths that reveal
  the local machine's username or directory layout beyond what's already
  public in this repo.
- Capture the browser window itself, not the whole desktop, to avoid
  accidentally showing other open windows or notifications.
- Use test sites for anything that needs a real page (a blocked-site
  demo uses a Quad9 test domain, not a live malicious site).

## Target length

3 to 5 minutes total. Short scenes, no narration filler. A silent
recording with on-screen captions is acceptable if voiceover isn't
practical; captions should use the same plain, calm tone as the rest of
the project (no marketing language).

## Scenes

1. **Launch and new tab** (~15s). Cold start to the new tab page. Shows
   startup time and the actual new-tab UI (search box, shortcuts, the "B"
   mark, "Just a Browser." / "Find what you came for.").

2. **Ordinary browsing with protection on** (~30s). Navigate to a couple
   of ordinary sites. Shows the protection indicator in the toolbar
   staying green/on, nothing intrusive.

3. **Protection page** (~30s). Open it from the toolbar. Show the rows
   for ads and trackers, dangerous sites (Quad9), HTTPS-first, WebRTC,
   fingerprint noise and updates.

4. **A blocked dangerous site** (~20s). Open a Quad9 test domain, not a
   live malicious site, and show that it does not load. There is no
   warning page in release 1; say so on screen.

5. **Senior Safe Mode** (~20s). Turn it on from the welcome screen or the
   Protection page. Show sponsored results staying hidden, and the
   confirmation it asks for before turning off.

6. **Reader mode** (~20s). Open a normal article page, trigger reader
   mode from the toolbar, show the clean, decluttered result.

7. **AI summary, on click only** (~30s). Trigger a page summary manually.
   Show the honest label naming which model/provider is being used before
   the request goes out, and the result. Make clear this only ran because
   it was clicked, not automatically.

8. **Settings overview** (~20s). A quick scroll through the settings
   navigation, showing it's a normal, readable settings surface, not
   hiding anything unusual.

9. **Close** (~10s). A title card: release 1, Chromium 153.0.8010.52,
   unsigned, link to this repo.

## What must not be on screen

- Any real email, real bookmark, real saved password, or real browsing
  history.
- Any API key, token, or signing material, even blurred (re-record
  instead of blurring; blurring text can fail).
- Any window other than the browser itself.
- Any live scam or phishing URL. Use a designated test URL from the
  project's own test fixtures, not a real malicious site, even for
  demonstration.
- Anything that implies the browser is safe to use as a daily driver.
  Keep any caption/voiceover consistent with LIMITATIONS.md.
- **Your own IP address.** This is not hypothetical. A capture queued for
  the README turned out to be a Google "unusual traffic" interstitial,
  not the search page it was labelled as, and that page prints the
  visitor's IP address in the body text. It was caught by looking at the
  picture before shipping it. Bot checks, error pages and "about this
  page" panels all do this.
- The "controlled by automated test software" infobar. Capture with
  `capture_native.py`, which switches it off by default.

Look at every frame before it ships. A screenshot is not verified by the
filename somebody gave it: the one above was called `google-search.png`
and was not a search page at all.

## Where it would go

Once recorded, this would be linked from the README as the primary way to
see the browser working, alongside the static screenshots. It does not
replace them; some reviewers will want a still image over a video.
