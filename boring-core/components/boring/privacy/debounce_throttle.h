// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PRIVACY_DEBOUNCE_THROTTLE_H_
#define COMPONENTS_BORING_PRIVACY_DEBOUNCE_THROTTLE_H_

#include "content/public/browser/navigation_throttle.h"
#include "content/public/browser/navigation_throttle_registry.h"
#include "url/gurl.h"

namespace boring {

// Skips tracking redirects and AMP cache pages: when a page address is
// one of the known redirectors (see debounce.h) the navigation is
// stopped and started again at the address it was going to reach, so
// the redirector is never asked and never learns who clicked.
//
// Looked at twice, as the navigation starts and again at each server
// redirect, because some redirectors are only reached that way. Only the
// page itself, never a frame, and never a form post, a reload or a step
// back or forward. Off with prefs::kSkipRedirects.
class DebounceThrottle : public content::NavigationThrottle {
 public:
  static void MaybeCreateAndAdd(content::NavigationThrottleRegistry& registry);

  explicit DebounceThrottle(content::NavigationThrottleRegistry& registry);
  ~DebounceThrottle() override;

  // content::NavigationThrottle:
  ThrottleCheckResult WillStartRequest() override;
  ThrottleCheckResult WillRedirectRequest() override;
  const char* GetNameForLogging() override;

 private:
  ThrottleCheckResult Check();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_PRIVACY_DEBOUNCE_THROTTLE_H_
