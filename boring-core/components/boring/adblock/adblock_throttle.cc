// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/adblock_throttle.h"

#include "components/boring/adblock/adblock_service.h"
#include "components/boring/adblock/blocking_off_sites.h"
#include "net/base/net_errors.h"
#include "net/url_request/redirect_info.h"
#include "services/network/public/cpp/resource_request.h"
#include "url/gurl.h"
#include "url/origin.h"

namespace boring {

// static
std::unique_ptr<AdblockThrottle> AdblockThrottle::MaybeCreate(
    const network::ResourceRequest& request,
    content::BrowserContext* browser_context) {
  if (AdblockService::IsDisabled()) {
    return nullptr;
  }
  // Blocking follows the page in the tab, not the frame or server a
  // request goes to, so an ad frame on a site the person turned
  // blocking off for loads, and the same frame elsewhere does not.
  if (browser_context && BlockingOffSites::ForContext(browser_context)
                             ->IsOff(TopFrameUrl(request))) {
    return nullptr;
  }
  AdblockService::GetInstance()->EnsureLoading();
  return std::make_unique<AdblockThrottle>();
}

// static
GURL AdblockThrottle::TopFrameUrl(const network::ResourceRequest& request) {
  if (request.trusted_params &&
      request.trusted_params->isolation_info.top_frame_origin()) {
    return request.trusted_params->isolation_info.top_frame_origin()->GetURL();
  }
  // Null in a third party frame, which then counts as no page at all
  // and stays blocked.
  if (!request.site_for_cookies.IsNull()) {
    return request.site_for_cookies.RepresentativeUrl();
  }
  return GURL();
}

AdblockThrottle::AdblockThrottle() = default;
AdblockThrottle::~AdblockThrottle() = default;

void AdblockThrottle::WillStartRequest(network::ResourceRequest* request,
                                       bool* defer) {
  initiator_ = request->request_initiator.has_value()
                   ? request->request_initiator->GetURL()
                   : GURL();
  request_type_ = AdblockService::RequestTypeFromDestination(
      request->destination, request->url);
  // Never block the page the user is going to. Blocking whole pages is
  // the scam protection's job, with a clear warning, not the ad
  // blocker's.
  if (request_type_ == "document") {
    return;
  }
  if (AdblockService::GetInstance()->ShouldBlock(request->url, initiator_,
                                                 request_type_)) {
    delegate_->CancelWithError(net::ERR_BLOCKED_BY_CLIENT, "boring-adblock");
  }
}

void AdblockThrottle::WillRedirectRequest(
    net::RedirectInfo* redirect_info,
    const network::mojom::URLResponseHead& response_head,
    bool* defer,
    network::HttpRequestHeadersUpdateParams* headers_update_params) {
  if (request_type_ == "document") {
    return;
  }
  if (AdblockService::GetInstance()->ShouldBlock(redirect_info->new_url,
                                                 initiator_, request_type_)) {
    delegate_->CancelWithError(net::ERR_BLOCKED_BY_CLIENT, "boring-adblock");
  }
}

}  // namespace boring
