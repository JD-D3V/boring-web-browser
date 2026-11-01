// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_PHONE_PHONE_SCAM_TAB_HELPER_H_
#define COMPONENTS_BORING_SCAM_PHONE_PHONE_SCAM_TAB_HELPER_H_

#include "base/memory/weak_ptr.h"
#include "base/values.h"
#include "content/public/browser/web_contents_observer.h"
#include "content/public/browser/web_contents_user_data.h"

namespace content {
class NavigationHandle;
}

namespace boring {

// Looks at each page of one tab for the tech support scam pop-up: a
// scary warning that shows a phone number. When it finds one it puts a
// quiet bar on the tab and marks the tab as one that looked like a scam,
// the same signal the takeover detector sets, so the scam guards use their
// strong wording from then on.
//
// The page is read by phone_scam_detect.js in an isolated world, in this
// tab's own process. Nothing is sent anywhere. Covered by the "Warn about
// scam tricks" switch.
class PhoneScamTabHelper
    : public content::WebContentsObserver,
      public content::WebContentsUserData<PhoneScamTabHelper> {
 public:
  ~PhoneScamTabHelper() override;

  // content::WebContentsObserver:
  void DocumentOnLoadCompletedInPrimaryMainFrame() override;
  void DidFinishNavigation(content::NavigationHandle* handle) override;

 private:
  friend class content::WebContentsUserData<PhoneScamTabHelper>;

  explicit PhoneScamTabHelper(content::WebContents* web_contents);

  // `document` is which page this was asked about: a scan that comes back
  // after the tab has moved on is dropped.
  void Scan(int document);
  void OnScanned(int document, base::Value result);
  void Warn();

  int document_ = 0;
  // The bar has gone up for this document.
  bool warned_ = false;

  base::WeakPtrFactory<PhoneScamTabHelper> weak_factory_{this};
  WEB_CONTENTS_USER_DATA_KEY_DECL();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_PHONE_PHONE_SCAM_TAB_HELPER_H_
