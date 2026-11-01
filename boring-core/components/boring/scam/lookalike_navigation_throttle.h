// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_LOOKALIKE_NAVIGATION_THROTTLE_H_
#define COMPONENTS_BORING_SCAM_LOOKALIKE_NAVIGATION_THROTTLE_H_

#include "content/public/browser/navigation_throttle.h"
#include "content/public/browser/navigation_throttle_registry.h"

namespace boring {

// Stops a page whose name is dressed up as another site's, before any
// request goes to it, and shows the look-alike warning instead.
//
// Chromium has the same idea (chrome/browser/lookalikes), but it sits
// idle here: it does nothing until a "safety tips" file arrives from
// Google's component updater, which this browser never contacts, and it
// looks only after the site has answered. This one asks Chromium's own
// matching code (components/lookalikes) for the cases it warns about with
// a full page, and adds lookalike_brands.h for plain-letter copies such as
// paypa1.com, which Chromium only counts. Nothing is looked up online.
//
// Switched by "Warn about scam tricks" (boring.protection.warn_scam_tricks).
class LookalikeNavigationThrottle : public content::NavigationThrottle {
 public:
  static void MaybeCreateAndAdd(content::NavigationThrottleRegistry& registry);

  explicit LookalikeNavigationThrottle(
      content::NavigationThrottleRegistry& registry);
  ~LookalikeNavigationThrottle() override;

  // content::NavigationThrottle:
  ThrottleCheckResult WillStartRequest() override;
  ThrottleCheckResult WillRedirectRequest() override;
  const char* GetNameForLogging() override;

 private:
  ThrottleCheckResult Check();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_LOOKALIKE_NAVIGATION_THROTTLE_H_
