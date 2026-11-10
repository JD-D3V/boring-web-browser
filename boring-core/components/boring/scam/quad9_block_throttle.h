// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_SCAM_QUAD9_BLOCK_THROTTLE_H_
#define COMPONENTS_BORING_SCAM_QUAD9_BLOCK_THROTTLE_H_

#include <memory>

#include "content/public/browser/navigation_throttle.h"
#include "content/public/browser/navigation_throttle_registry.h"

namespace boring {

class Quad9BlockChecker;

// Quad9, the secure DNS server, will not look up a name on its threat list,
// and the browser sees that as "site not found", the same as a typo. When
// the page in the main window cannot be found and Quad9 is the secure DNS
// server, this asks Quad9 once more and, if it says the site is blocked,
// shows the scam warning in place of the not found page.
//
// It does not need the scam list, so it is added whether or not the list
// is there. Anything it cannot tell leaves the not found page as it was.
class Quad9BlockThrottle : public content::NavigationThrottle {
 public:
  static void MaybeCreateAndAdd(content::NavigationThrottleRegistry& registry);

  explicit Quad9BlockThrottle(content::NavigationThrottleRegistry& registry);
  ~Quad9BlockThrottle() override;

  // content::NavigationThrottle:
  ThrottleCheckResult WillFailRequest() override;
  const char* GetNameForLogging() override;

 private:
  void OnChecked(bool blocked);

  std::unique_ptr<Quad9BlockChecker> checker_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_SCAM_QUAD9_BLOCK_THROTTLE_H_
