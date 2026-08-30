// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_POPUNDER_TAB_UNDER_THROTTLE_H_
#define COMPONENTS_BORING_POPUNDER_TAB_UNDER_THROTTLE_H_

#include "content/public/browser/navigation_throttle.h"
#include "content/public/browser/navigation_throttle_registry.h"

namespace boring {

// Blocks the classic pop-under trick: the page opens a popup on your
// click, then the original tab, now in the background, quietly sends
// itself to an ad or scam page. Chromium tracks this pattern but no
// longer blocks it; we do.
class TabUnderThrottle : public content::NavigationThrottle {
 public:
  static void MaybeCreateAndAdd(content::NavigationThrottleRegistry& registry);

  explicit TabUnderThrottle(content::NavigationThrottleRegistry& registry);
  ~TabUnderThrottle() override;

  // content::NavigationThrottle:
  ThrottleCheckResult WillStartRequest() override;
  ThrottleCheckResult WillRedirectRequest() override;
  const char* GetNameForLogging() override;

 private:
  ThrottleCheckResult Check();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_POPUNDER_TAB_UNDER_THROTTLE_H_
