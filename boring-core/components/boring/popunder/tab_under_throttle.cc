// Copyright 2026 boring. BSD style license.

#include "components/boring/popunder/tab_under_throttle.h"

#include <memory>

#include "base/command_line.h"
#include "base/logging.h"
#include "components/blocked_content/popup_opener_tab_helper.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents.h"
#include "net/base/net_errors.h"
#include "url/gurl.h"
#include "url/origin.h"

namespace boring {

namespace {
constexpr char kDisableSwitch[] = "disable-boring-popunder-blocking";
}

// static
void TabUnderThrottle::MaybeCreateAndAdd(
    content::NavigationThrottleRegistry& registry) {
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(kDisableSwitch)) {
    return;
  }
  if (!registry.GetNavigationHandle().IsInOutermostMainFrame()) {
    return;
  }
  registry.AddThrottle(std::make_unique<TabUnderThrottle>(registry));
}

TabUnderThrottle::TabUnderThrottle(
    content::NavigationThrottleRegistry& registry)
    : content::NavigationThrottle(registry) {}

TabUnderThrottle::~TabUnderThrottle() = default;

content::NavigationThrottle::ThrottleCheckResult
TabUnderThrottle::WillStartRequest() {
  return Check();
}

content::NavigationThrottle::ThrottleCheckResult
TabUnderThrottle::WillRedirectRequest() {
  return Check();
}

const char* TabUnderThrottle::GetNameForLogging() {
  return "BoringTabUnderThrottle";
}

content::NavigationThrottle::ThrottleCheckResult TabUnderThrottle::Check() {
  content::NavigationHandle* handle = navigation_handle();
  if (!handle->IsInOutermostMainFrame() || !handle->IsRendererInitiated() ||
      handle->HasUserGesture()) {
    return content::NavigationThrottle::PROCEED;
  }
  content::WebContents* contents = handle->GetWebContents();
  if (contents->GetVisibility() != content::Visibility::HIDDEN) {
    return content::NavigationThrottle::PROCEED;
  }
  auto* popup_opener =
      blocked_content::PopupOpenerTabHelper::FromWebContents(contents);
  if (!popup_opener ||
      !popup_opener->has_opened_popup_since_last_user_gesture()) {
    return content::NavigationThrottle::PROCEED;
  }
  // Same site navigations are fine; the trick needs a different site.
  const GURL& current = contents->GetLastCommittedURL();
  const GURL& target = handle->GetURL();
  if (current.is_valid() &&
      url::Origin::Create(current).IsSameOriginWith(target)) {
    return content::NavigationThrottle::PROCEED;
  }
  VLOG(1) << "boring: blocked tab under navigation to " << target;
  return content::NavigationThrottle::ThrottleCheckResult(
      CANCEL, net::ERR_BLOCKED_BY_CLIENT);
}

}  // namespace boring
