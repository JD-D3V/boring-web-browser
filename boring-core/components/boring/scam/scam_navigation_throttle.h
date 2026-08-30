// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_SCAM_NAVIGATION_THROTTLE_H_
#define COMPONENTS_BORING_SCAM_SCAM_NAVIGATION_THROTTLE_H_

#include "content/public/browser/navigation_throttle.h"
#include "content/public/browser/navigation_throttle_registry.h"

namespace boring {

// Checks every main frame navigation against the scam blocklist and
// shows the warning wall before a listed page can load.
class ScamNavigationThrottle : public content::NavigationThrottle {
 public:
  static void MaybeCreateAndAdd(content::NavigationThrottleRegistry& registry);

  explicit ScamNavigationThrottle(
      content::NavigationThrottleRegistry& registry);
  ~ScamNavigationThrottle() override;

  // content::NavigationThrottle:
  ThrottleCheckResult WillStartRequest() override;
  ThrottleCheckResult WillRedirectRequest() override;
  const char* GetNameForLogging() override;

 private:
  ThrottleCheckResult Check();
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_SCAM_NAVIGATION_THROTTLE_H_
