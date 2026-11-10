// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/quad9_block_throttle.h"

#include <memory>
#include <string>
#include <utility>

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "components/boring/privacy/privacy_state.h"
#include "components/boring/scam/quad9_block_checker.h"
#include "components/boring/scam/scam_blocking_page.h"
#include "components/security_interstitials/content/security_interstitial_tab_helper.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents.h"
#include "net/base/net_errors.h"
#include "url/gurl.h"

namespace boring {

namespace {
constexpr char kDisableSwitch[] = "disable-boring-scam-protection";
}  // namespace

// static
void Quad9BlockThrottle::MaybeCreateAndAdd(
    content::NavigationThrottleRegistry& registry) {
  if (base::CommandLine::ForCurrentProcess()->HasSwitch(kDisableSwitch)) {
    return;
  }
  // The warning page is an interstitial, which only the main window of a
  // tab may show.
  if (!registry.GetNavigationHandle().IsInPrimaryMainFrame()) {
    return;
  }
  registry.AddThrottle(std::make_unique<Quad9BlockThrottle>(registry));
}

Quad9BlockThrottle::Quad9BlockThrottle(
    content::NavigationThrottleRegistry& registry)
    : content::NavigationThrottle(registry) {}

Quad9BlockThrottle::~Quad9BlockThrottle() = default;

content::NavigationThrottle::ThrottleCheckResult
Quad9BlockThrottle::WillFailRequest() {
  content::NavigationHandle* handle = navigation_handle();
  // Only a name that could not be found. A real server that answered with
  // an error, a refused connection and the rest are not Quad9's doing.
  if (handle->GetNetErrorCode() != net::ERR_NAME_NOT_RESOLVED) {
    return content::NavigationThrottle::PROCEED;
  }
  content::WebContents* contents = handle->GetWebContents();
  content::BrowserContext* context =
      contents ? contents->GetBrowserContext() : nullptr;
  const GURL& url = handle->GetURL();
  if (!context || !url.SchemeIsHTTPOrHTTPS() || !url.has_host() ||
      !GetPrivacyState(context).dns_filters_threats) {
    return content::NavigationThrottle::PROCEED;
  }

  checker_ = std::make_unique<Quad9BlockChecker>();
  if (!checker_->Check(context, std::string(url.host()),
                       base::BindOnce(&Quad9BlockThrottle::OnChecked,
                                      base::Unretained(this)))) {
    return content::NavigationThrottle::PROCEED;
  }
  return content::NavigationThrottle::DEFER;
}

const char* Quad9BlockThrottle::GetNameForLogging() {
  return "BoringQuad9BlockThrottle";
}

void Quad9BlockThrottle::OnChecked(bool blocked) {
  content::NavigationHandle* handle = navigation_handle();
  content::WebContents* contents = handle->GetWebContents();
  if (!blocked || !contents) {
    Resume();
    return;
  }
  const GURL url = handle->GetURL();
  std::unique_ptr<ScamBlockingPage> page =
      ScamBlockingPage::CreateForQuad9Block(contents, url);
  std::string html = page->GetHTMLContents();
  security_interstitials::SecurityInterstitialTabHelper::AssociateBlockingPage(
      handle, std::move(page));
  // The error stays "name not resolved": a different error code here would
  // move the error page to another process, which the navigation checks
  // for and refuses (it is a CHECK). Only the page changes.
  CancelDeferredNavigation(content::NavigationThrottle::ThrottleCheckResult(
      CANCEL, net::ERR_NAME_NOT_RESOLVED, std::move(html)));
}

}  // namespace boring
