// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/scam_navigation_throttle.h"

#include <memory>
#include <string>
#include <utility>

#include "base/command_line.h"
#include "components/boring/scam/scam_blocking_page.h"
#include "components/boring/scam/scam_service.h"
#include "components/security_interstitials/content/security_interstitial_tab_helper.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents.h"
#include "net/base/net_errors.h"

namespace boring {

namespace {
constexpr char kDisableSwitch[] = "disable-boring-scam-protection";
}

// static
void ScamNavigationThrottle::MaybeCreateAndAdd(
    content::NavigationThrottleRegistry& registry) {
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(kDisableSwitch)) {
    return;
  }
  content::NavigationHandle& handle = registry.GetNavigationHandle();
  if (!handle.IsInOutermostMainFrame()) {
    return;
  }
  ScamService::GetInstance()->EnsureLoading();
  registry.AddThrottle(std::make_unique<ScamNavigationThrottle>(registry));
}

ScamNavigationThrottle::ScamNavigationThrottle(
    content::NavigationThrottleRegistry& registry)
    : content::NavigationThrottle(registry) {}

ScamNavigationThrottle::~ScamNavigationThrottle() = default;

content::NavigationThrottle::ThrottleCheckResult
ScamNavigationThrottle::WillStartRequest() {
  return Check();
}

content::NavigationThrottle::ThrottleCheckResult
ScamNavigationThrottle::WillRedirectRequest() {
  return Check();
}

const char* ScamNavigationThrottle::GetNameForLogging() {
  return "BoringScamNavigationThrottle";
}

content::NavigationThrottle::ThrottleCheckResult
ScamNavigationThrottle::Check() {
  content::NavigationHandle* handle = navigation_handle();
  if (!handle->IsInOutermostMainFrame()) {
    return content::NavigationThrottle::PROCEED;
  }
  const GURL& url = handle->GetURL();
  if (!ScamService::GetInstance()->ShouldBlock(url)) {
    return content::NavigationThrottle::PROCEED;
  }

  std::unique_ptr<ScamBlockingPage> page =
      ScamBlockingPage::Create(handle->GetWebContents(), url);
  std::string html = page->GetHTMLContents();
  security_interstitials::SecurityInterstitialTabHelper::AssociateBlockingPage(
      handle, std::move(page));
  return content::NavigationThrottle::ThrottleCheckResult(
      CANCEL, net::ERR_BLOCKED_BY_CLIENT, std::move(html));
}

}  // namespace boring
