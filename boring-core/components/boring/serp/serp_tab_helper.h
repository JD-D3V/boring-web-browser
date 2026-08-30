// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SERP_SERP_TAB_HELPER_H_
#define COMPONENTS_BORING_SERP_SERP_TAB_HELPER_H_

#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/web_contents_user_data.h"

namespace boring {

// Marks the sponsored blocks on Google and Bing search result pages
// with a clear label, or hides them when the user asked for that (or
// Senior Safe Mode is on). Runs a small script in an isolated world on
// search pages only.
class SerpTabHelper : public content::WebContentsObserver,
                      public content::WebContentsUserData<SerpTabHelper> {
 public:
  ~SerpTabHelper() override;

  // content::WebContentsObserver:
  void DocumentOnLoadCompletedInPrimaryMainFrame() override;

 private:
  friend class content::WebContentsUserData<SerpTabHelper>;

  explicit SerpTabHelper(content::WebContents* web_contents);

  WEB_CONTENTS_USER_DATA_KEY_DECL();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SERP_SERP_TAB_HELPER_H_
