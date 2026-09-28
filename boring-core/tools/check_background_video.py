#!/usr/bin/env python3
"""Check that a hidden tab stops decoding video while its audio plays on.

Chromium turns off the video track of a playing video whose tab is
hidden (background video track optimization), so a tab left playing
music costs no video decoding. This checks our build still does that
and that none of our code (ad blocking, scriptlets, cosmetic filtering)
keeps the video decoding.

Driven by WebDriver only, window off screen, audio output muted with
--mute-audio (the page still counts the video as audible, the speakers
just stay silent). Inside the video's page a logger records once a
second: whether the page is visible, frames decoded so far
(getVideoPlaybackQuality), the playback position and whether it paused.
Then a second tab is opened and shown, hiding the first, and
chrome://media-internals is read from it.

Needs the internet (YouTube by default). Usage:
  python check_background_video.py [URL] [--blocking-off]
"""

import json
import sys
import time

from drive import Browser

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
URL = ARGS[0] if ARGS else "https://www.youtube.com/watch?v=aqz-KE-bpKQ"
VISIBLE_SECONDS = 15
HIDDEN_SECONDS = 60
SETTLE_SECONDS = 12

LOGGER = """
window.__bgLog = [];
setInterval(function() {
  var v = document.querySelector('video');
  if (!v) return;
  var q = v.getVideoPlaybackQuality ? v.getVideoPlaybackQuality() : {};
  window.__bgLog.push({t: Date.now(), vis: document.visibilityState,
    frames: q.totalVideoFrames || 0, time: v.currentTime, paused: v.paused,
    muted: v.muted});
}, 1000);
return !!document.querySelector('video');
"""


def rate(samples, key):
    if len(samples) < 2:
        return None
    dt = (samples[-1]["t"] - samples[0]["t"]) / 1000
    return (samples[-1][key] - samples[0][key]) / dt if dt else None


def main():
    extra = ["--disable-boring-adblock"] if "--blocking-off" in sys.argv else []
    with Browser(
        args=["--mute-audio", "--autoplay-policy=no-user-gesture-required"] + extra
    ) as b:
        b.get(URL)
        time.sleep(8)
        # Start playback if the page did not; a click from script, not the OS.
        b.run("var v=document.querySelector('video'); if (v && v.paused) v.play();")
        if not b.run(LOGGER):
            print("FAIL: no video element on the page")
            return 1
        video_handle = b._req("GET", f"/session/{b.sid}/window")["value"]
        time.sleep(VISIBLE_SECONDS)

        new = b._req("POST", f"/session/{b.sid}/window/new", {"type": "tab"})["value"]
        b._req("POST", f"/session/{b.sid}/window", {"handle": new["handle"]})
        b.get("chrome://media-internals")
        time.sleep(HIDDEN_SECONDS)
        internals = b.run("return document.body.innerText")

        b._req("POST", f"/session/{b.sid}/window", {"handle": video_handle})
        log = b.run("return window.__bgLog")

    visible = [s for s in log if s["vis"] == "visible"]
    hidden_all = [s for s in log if s["vis"] == "hidden"]
    # Chromium waits about ten seconds after a tab is hidden before it
    # turns the video track off, so the settled period starts after that.
    # It ends at the first reset or pause: pages swap media (an ad, the
    # next video) and that is the page's doing, reported separately.
    hidden = []
    for s in hidden_all[SETTLE_SECONDS:]:
        if hidden and (s["time"] < hidden[-1]["time"] or s["paused"]):
            break
        hidden.append(s)
    reset = len(hidden) < len(hidden_all[SETTLE_SECONDS:])
    fps_visible = rate(visible, "frames")
    fps_hidden = rate(hidden, "frames")
    play_hidden = rate(hidden, "time")
    paused_hidden = any(s["paused"] for s in hidden)
    print(
        json.dumps(
            {
                "samples_visible": len(visible),
                "samples_hidden": len(hidden),
                "decoded_fps_visible": fps_visible,
                "decoded_fps_hidden": fps_hidden,
                "playback_speed_hidden": play_hidden,
                "paused_while_hidden": paused_hidden,
                "page_reset_or_paused_later": reset,
            },
            indent=1,
        )
    )
    lines = [
        ln
        for ln in internals.splitlines()
        if any(k in ln.lower() for k in ("background", "track", "suspend", "hidden"))
    ]
    print("media-internals lines mentioning background/track/suspend/hidden:")
    for ln in lines[:20]:
        print("  " + ln.strip()[:160])

    ok = (
        fps_visible
        and fps_visible > 5
        and fps_hidden is not None
        and fps_hidden < 1
        and play_hidden
        and play_hidden > 0.8
        and not paused_hidden
    )
    print(
        "PASS: hidden tab stops decoding video, playback continues"
        if ok
        else "FAIL: see numbers above"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
