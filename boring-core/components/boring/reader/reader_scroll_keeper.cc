// Copyright 2026 boring. BSD style license.

#include "components/boring/reader/reader_scroll_keeper.h"

#include <optional>
#include <string>
#include <utility>

#include "base/functional/callback_helpers.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/utf_string_conversions.h"
#include "base/values.h"
#include "components/dom_distiller/core/url_constants.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "content/public/common/isolated_world_ids.h"
#include "url/gurl.h"

namespace boring {

namespace {

// The same isolated world the rest of our scripts use. See
// components/boring/serp/serp_tab_helper.cc for why the value is worked
// out this way rather than included from the chrome layer.
constexpr int32_t kBoringWorldId = content::ISOLATED_WORLD_ID_CONTENT_END + 3;

// Paragraphs shorter than this are skipped. Short lines repeat too often
// in an article ("Advertisement", a byline) to identify a place reliably.
constexpr int kShortestUsefulParagraph = 40;

// Leaves a little air above the paragraph so it does not sit jammed
// against the top edge.
constexpr int kBreathingRoomPx = 24;

// Finds the matching paragraph and scrolls to it. The article arrives a
// piece at a time, so if it is not there yet we keep looking for a few
// seconds rather than giving up on the first try.
constexpr char kScrollScript[] = R"((function() {
  var targetHash = %HASH%;
  var targetLength = %CHARS%;
  var progressIntoParagraph = %PROGRESS%;

  function normalized(text) {
    return (text || '').replace(/\s+/g, ' ').trim();
  }

  function hashOf(text) {
    var accumulated = 0;
    for (var i = 0; i < text.length; i++) {
      accumulated = ((accumulated << 5) - accumulated + text.charCodeAt(i)) | 0;
    }
    return accumulated;
  }

  function scrollToRememberedParagraph() {
    var paragraphs = document.querySelectorAll('p');
    for (var i = 0; i < paragraphs.length; i++) {
      var text = normalized(paragraphs[i].innerText);
      // Compare the cheap length first. Hashing every paragraph is waste.
      if (text.length !== targetLength) continue;
      if (hashOf(text) !== targetHash) continue;
      var rect = paragraphs[i].getBoundingClientRect();
      var targetY =
          window.scrollY + rect.top + (rect.height * progressIntoParagraph);
      window.scrollTo(0, Math.max(0, targetY - %ROOM%));
      return true;
    }
    return false;
  }

  if (scrollToRememberedParagraph()) return;
  var attempts = 0;
  var retryTimer = setInterval(function() {
    attempts++;
    if (scrollToRememberedParagraph() || attempts > 50) {
      clearInterval(retryTimer);
    }
  }, 100);
})())";

std::string Substitute(std::string text,
                       const std::string& marker,
                       const std::string& value) {
  const size_t marker_pos = text.find(marker);
  if (marker_pos != std::string::npos) {
    text.replace(marker_pos, marker.size(), value);
  }
  return text;
}

}  // namespace

// Walks the paragraphs to find the first one still on screen, and works
// out how far into it the reader has got.
const char kReaderAnchorScript[] = R"((function() {
  function normalized(text) {
    return (text || '').replace(/\s+/g, ' ').trim();
  }

  function hashOf(text) {
    var accumulated = 0;
    for (var i = 0; i < text.length; i++) {
      accumulated = ((accumulated << 5) - accumulated + text.charCodeAt(i)) | 0;
    }
    return accumulated;
  }

  var paragraphs = document.querySelectorAll('p');
  for (var i = 0; i < paragraphs.length; i++) {
    var rect = paragraphs[i].getBoundingClientRect();
    // Rects are measured from the viewport, so a bottom at or above zero
    // means this paragraph has already been scrolled past.
    if (rect.height <= 0) continue;
    if (rect.bottom <= 0) continue;
    var text = normalized(paragraphs[i].innerText);
    if (text.length < 40) continue;

    // How far into this paragraph the reader has got. Zero means its top
    // is still on screen.
    var progressIntoParagraph = 0;
    if (rect.top < 0) {
      progressIntoParagraph = Math.min(1, (-rect.top) / rect.height);
    }
    return {
      hash: hashOf(text),
      chars: text.length,
      progress: progressIntoParagraph
    };
  }
  return null;
})())";

ReaderScrollKeeper::ReaderScrollKeeper(content::WebContents* web_contents)
    : content::WebContentsObserver(web_contents),
      content::WebContentsUserData<ReaderScrollKeeper>(*web_contents) {}

ReaderScrollKeeper::~ReaderScrollKeeper() = default;

// static
void ReaderScrollKeeper::Remember(content::WebContents* web_contents,
                                  const base::Value& anchor) {
  if (!web_contents || !anchor.is_dict()) {
    return;  // Nothing to go on; reader view opens at the top as before.
  }
  const base::DictValue& anchor_fields = anchor.GetDict();
  const std::optional<int> paragraph_hash = anchor_fields.FindInt("hash");
  const std::optional<int> paragraph_length = anchor_fields.FindInt("chars");
  const std::optional<double> progress = anchor_fields.FindDouble("progress");
  if (!paragraph_hash || !paragraph_length ||
      *paragraph_length < kShortestUsefulParagraph) {
    return;
  }

  CreateForWebContents(web_contents);
  ReaderScrollKeeper* keeper = FromWebContents(web_contents);
  if (!keeper) {
    return;
  }
  keeper->paragraph_hash_ = static_cast<int32_t>(*paragraph_hash);
  keeper->paragraph_length_ = *paragraph_length;
  keeper->progress_into_paragraph_ = progress.value_or(0.0);
  keeper->has_remembered_place_ = true;
}

void ReaderScrollKeeper::DocumentOnLoadCompletedInPrimaryMainFrame() {
  if (!has_remembered_place_) {
    return;
  }
  content::WebContents* contents = web_contents();
  if (!contents) {
    return;
  }
  // Only ever act on the reader page. Any other navigation means the
  // person went somewhere else, and the remembered place is stale.
  if (!contents->GetLastCommittedURL().SchemeIs(
          dom_distiller::kDomDistillerScheme)) {
    has_remembered_place_ = false;
    return;
  }
  has_remembered_place_ = false;

  std::string script(kScrollScript);
  script = Substitute(std::move(script), "%HASH%",
                      base::NumberToString(paragraph_hash_));
  script = Substitute(std::move(script), "%CHARS%",
                      base::NumberToString(paragraph_length_));
  script = Substitute(std::move(script), "%PROGRESS%",
                      base::NumberToString(progress_into_paragraph_));
  script = Substitute(std::move(script), "%ROOM%",
                      base::NumberToString(kBreathingRoomPx));

  contents->GetPrimaryMainFrame()->ExecuteJavaScriptInIsolatedWorld(
      base::UTF8ToUTF16(script), base::NullCallback(), kBoringWorldId);
}

WEB_CONTENTS_USER_DATA_KEY_IMPL(ReaderScrollKeeper);

}  // namespace boring
