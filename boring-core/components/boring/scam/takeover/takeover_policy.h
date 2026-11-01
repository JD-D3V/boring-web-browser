// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_TAKEOVER_TAKEOVER_POLICY_H_
#define COMPONENTS_BORING_SCAM_TAKEOVER_TAKEOVER_POLICY_H_

namespace content {
class WebContents;
}

namespace boring {

// True when "Stop screen takeovers" is on for the profile of
// `web_contents` (boring.protection.stop_takeovers, on by default). True
// with no contents or no prefs: the safe answer is the protected one.
bool IsStopTakeoversEnabled(content::WebContents* web_contents);

// Whether a plain Esc leaves fullscreen even when the page has locked
// the keyboard. Chromium makes the person hold Esc for 1.5 seconds then,
// which a scared person does not know, and scam pages rely on it.
bool ShouldEscAlwaysExit(content::WebContents* web_contents);

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_TAKEOVER_TAKEOVER_POLICY_H_
