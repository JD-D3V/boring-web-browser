// Copyright 2026 boring. BSD style license.

#include "components/boring/guards/clipboard_guard.h"

#include <string_view>

#include "base/command_line.h"
#include "base/functional/callback_helpers.h"
#include "base/json/string_escape.h"
#include "base/logging.h"
#include "base/strings/utf_string_conversions.h"
#include "components/boring/guards/guard_infobar.h"
#include "components/boring/guards/guards_policy.h"
#include "components/boring/guards/shell_command.h"
#include "components/boring/scam/takeover/takeover_tab_helper.h"
#include "content/public/browser/web_contents.h"
#include "ui/display/types/display_constants.h"
#include "url/gurl.h"

namespace boring {
namespace guards {

namespace {

// Nothing longer is a one-line command (shell_command.cc has the same
// limit); looking at a whole copied article would only be slow.
constexpr size_t kMaxChars = 64 * 1024;

// Test hook, like --boring-guards-test-answer: copies from pages are logged
// and dropped instead of written, so a smoke test never touches the
// person's real clipboard. Does nothing unless the switch is given.
constexpr char kTestClipboardSwitch[] = "boring-guards-test-clipboard";

constexpr char16_t kNotice[] =
    u"This page tried to copy a command. Real sites do not ask you to "
    u"paste commands into Windows.";
constexpr char16_t kStrongNotice[] =
    u"This page tried to copy a command, and it looks like a scam. Do not "
    u"paste it. Close the tab.";

// What goes on the clipboard in its place. If it is pasted into the Run
// box, Windows says it cannot find it, and nothing runs.
constexpr char16_t kReplacement[] =
    u"Blocked: this page tried to copy a command.";

bool LooksLikeCommand(const std::u16string& text) {
  return !text.empty() && text.size() <= kMaxChars &&
         LooksLikeShellCommand(base::UTF16ToUTF8(text));
}

}  // namespace

std::optional<std::u16string> CheckClipboardCopy(
    const content::ClipboardEndpoint& source,
    const ui::ClipboardMetadata& metadata,
    const content::ClipboardPasteData& data) {
  content::WebContents* web_contents = source.web_contents();
  if (!web_contents || !IsEnabled(web_contents->GetBrowserContext()) ||
      !web_contents->GetLastCommittedURL().SchemeIsHTTPOrHTTPS()) {
    return std::nullopt;
  }
  if (!LooksLikeCommand(data.text) && !LooksLikeCommand(data.html)) {
    return std::nullopt;
  }

  const bool fullscreen = web_contents->IsFullscreen();
  const bool strong =
      fullscreen || TakeoverTabHelper::LooksLikeScam(web_contents);
  if (fullscreen) {
    // The bar is part of the browser window, which a fullscreen page
    // covers. The block on going back in is let go when this leaves
    // scope: this is a one-time exit.
    std::optional<base::ScopedClosureRunner> drop =
        web_contents->ForSecurityDropFullscreen(display::kInvalidDisplayId);
  }
  GuardInfoBarDelegate::Show(web_contents,
                             {.message = strong ? kStrongNotice : kNotice},
                             GuardInfoBarDelegate::Answered());
  return std::u16string(kReplacement);
}

bool SwallowClipboardCopyForTest(const content::ClipboardEndpoint& source,
                                 const ui::ClipboardMetadata& metadata,
                                 const content::ClipboardPasteData& data) {
  if (!base::CommandLine::ForCurrentProcess()->HasSwitch(
          kTestClipboardSwitch)) {
    return false;
  }
  // What would have gone on the clipboard, as a JSON string so a command
  // that runs over several lines stays on one log line.
  std::optional<std::u16string> replacement =
      CheckClipboardCopy(source, metadata, data);
  LOG(INFO) << "boring-guards: clipboard: "
            << base::GetQuotedJSONString(base::UTF16ToUTF8(
                   replacement ? *replacement : data.text));
  return true;
}

}  // namespace guards
}  // namespace boring
