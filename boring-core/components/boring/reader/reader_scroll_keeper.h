// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_READER_READER_SCROLL_KEEPER_H_
#define COMPONENTS_BORING_READER_READER_SCROLL_KEEPER_H_

#include <cstdint>

#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/web_contents_user_data.h"

namespace base {
class Value;
}  // namespace base

namespace content {
class WebContents;
}  // namespace content

namespace boring {

// A small script that reads, from the page a person is looking at, which
// paragraph they have reached. Run it in the live page before asking for
// reader view. It returns a dictionary of hash, chars and progress, or
// null when it cannot tell.
extern const char kReaderAnchorScript[];

// Opens reader view where the reader already was, rather than back at
// the top of the article.
//
// The two pages have different markup, so there is no shared scroll
// position to carry over. What does survive is the text: the paragraph
// someone is reading says the same thing in both. So we remember a hash
// of that paragraph, and once the distilled page is up we find the
// paragraph that matches and scroll to it.
class ReaderScrollKeeper
    : public content::WebContentsObserver,
      public content::WebContentsUserData<ReaderScrollKeeper> {
 public:
  ~ReaderScrollKeeper() override;

  ReaderScrollKeeper(const ReaderScrollKeeper&) = delete;
  ReaderScrollKeeper& operator=(const ReaderScrollKeeper&) = delete;

  // Takes the result of kReaderAnchorScript and remembers it for the next
  // distilled page in this tab. A null or unreadable result is ignored,
  // which simply leaves reader view opening at the top as before.
  static void Remember(content::WebContents* web_contents,
                       const base::Value& anchor);

  // content::WebContentsObserver:
  void DocumentOnLoadCompletedInPrimaryMainFrame() override;

 private:
  friend class content::WebContentsUserData<ReaderScrollKeeper>;

  explicit ReaderScrollKeeper(content::WebContents* web_contents);

  // Set when a place has been remembered and the reader page has not yet
  // loaded. Cleared once used, or once the tab goes somewhere else.
  bool has_remembered_place_ = false;
  int32_t paragraph_hash_ = 0;
  int paragraph_length_ = 0;
  double progress_into_paragraph_ = 0;

  WEB_CONTENTS_USER_DATA_KEY_DECL();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_READER_READER_SCROLL_KEEPER_H_
