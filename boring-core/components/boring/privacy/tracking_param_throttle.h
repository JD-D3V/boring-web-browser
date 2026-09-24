// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_PRIVACY_TRACKING_PARAM_THROTTLE_H_
#define COMPONENTS_BORING_PRIVACY_TRACKING_PARAM_THROTTLE_H_

#include "content/public/browser/navigation_throttle.h"
#include "content/public/browser/navigation_throttle_registry.h"
#include "url/gurl.h"

namespace boring {

// Takes known tracking parameters out of a page address before the
// request leaves the browser, when one site sends a person to another:
// a link, a redirect, or an address typed or pasted in. A site linking
// to itself is left alone, the way Brave does it, because there the
// parameter tells the site nothing it does not already know.
//
// The navigation is stopped and started again at the clean address, so
// the server never sees the identifier. Off with a switch on the
// Protection page.
class TrackingParamThrottle : public content::NavigationThrottle {
 public:
  static void MaybeCreateAndAdd(content::NavigationThrottleRegistry& registry);

  explicit TrackingParamThrottle(content::NavigationThrottleRegistry& registry);
  ~TrackingParamThrottle() override;

  // content::NavigationThrottle:
  ThrottleCheckResult WillStartRequest() override;
  ThrottleCheckResult WillRedirectRequest() override;
  const char* GetNameForLogging() override;

 private:
  ThrottleCheckResult Check(const GURL& from);
};

}  // namespace boring

#endif  // COMPONENTS_BORING_PRIVACY_TRACKING_PARAM_THROTTLE_H_
