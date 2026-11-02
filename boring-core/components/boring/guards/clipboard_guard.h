// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_GUARDS_CLIPBOARD_GUARD_H_
#define COMPONENTS_BORING_GUARDS_CLIPBOARD_GUARD_H_

#include <optional>
#include <string>

#include "content/public/browser/clipboard_types.h"
#include "ui/base/clipboard/clipboard_metadata.h"

namespace boring {
namespace guards {

// The ClickFix guard. Called from
// ChromeContentBrowserClient::IsClipboardCopyAllowedByPolicy(), which
// every write to the clipboard from a page goes through, before Chromium
// writes it.
//
// When the page is putting a command on the clipboard for the person to
// paste into Windows (see shell_command.h), this returns the line to
// write instead, which is plain text that does nothing if it is pasted,
// and puts a quiet warning bar on the tab. A page that is fullscreen is
// taken out of fullscreen first, so the bar can be seen. The wording is
// stronger when the page is fullscreen or the tab has tripped the
// takeover detector.
//
// Returns nothing, and does nothing, for everything else: ordinary text,
// pages that are not on the web, and a profile with "Warn about scam
// tricks" off.
std::optional<std::u16string> CheckClipboardCopy(
    const content::ClipboardEndpoint& source,
    const ui::ClipboardMetadata& metadata,
    const content::ClipboardPasteData& data);

// Test only. With --boring-guards-test-clipboard, runs the guard, logs the
// text that would have been written ("boring-guards: clipboard: " and a
// JSON string) and returns true, and the caller drops the copy. Without
// the switch it returns false and does nothing.
bool SwallowClipboardCopyForTest(const content::ClipboardEndpoint& source,
                                 const ui::ClipboardMetadata& metadata,
                                 const content::ClipboardPasteData& data);

}  // namespace guards
}  // namespace boring

#endif  // COMPONENTS_BORING_GUARDS_CLIPBOARD_GUARD_H_
