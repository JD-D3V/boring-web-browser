// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/renderer/adblock_renderer_throttle.h"

#include <utility>

#include "base/functional/bind.h"
#include "net/base/net_errors.h"
#include "net/url_request/redirect_info.h"
#include "services/network/public/cpp/resource_request.h"
#include "url/gurl.h"
#include "url/origin.h"

namespace boring {

namespace {

const char* TypeFor(network::mojom::RequestDestination destination,
                    const GURL& url) {
  // Reuse the browser side mapping. It only reads enum values, so it is
  // safe in the renderer too.
  using network::mojom::RequestDestination;
  switch (destination) {
    case RequestDestination::kScript:
    case RequestDestination::kWorker:
    case RequestDestination::kSharedWorker:
    case RequestDestination::kServiceWorker:
      return "script";
    case RequestDestination::kImage:
      return "image";
    case RequestDestination::kStyle:
    case RequestDestination::kXslt:
      return "stylesheet";
    case RequestDestination::kFont:
      return "font";
    case RequestDestination::kAudio:
    case RequestDestination::kVideo:
    case RequestDestination::kTrack:
      return "media";
    case RequestDestination::kReport:
      return "ping";
    case RequestDestination::kEmpty:
      return url.SchemeIsWSOrWSS() ? "websocket" : "xmlhttprequest";
    case RequestDestination::kJson:
      return "xmlhttprequest";
    default:
      return "other";
  }
}

}  // namespace

AdblockRendererThrottle::AdblockRendererThrottle(
    mojo::PendingRemote<mojom::AdblockChecker> checker)
    : pending_checker_(std::move(checker)) {}

AdblockRendererThrottle::~AdblockRendererThrottle() = default;

void AdblockRendererThrottle::DetachFromCurrentSequence() {
  // The throttle is about to move to another thread. Hand over an
  // unbound pipe again so it can bind there.
  if (checker_.is_bound()) {
    mojo::PendingRemote<mojom::AdblockChecker> fresh;
    checker_->Clone(fresh.InitWithNewPipeAndPassReceiver());
    checker_.reset();
    pending_checker_ = std::move(fresh);
  }
}

void AdblockRendererThrottle::BindIfNeeded() {
  if (!checker_.is_bound() && pending_checker_.is_valid()) {
    checker_.Bind(std::move(pending_checker_));
    checker_.set_disconnect_handler(base::BindOnce(
        &AdblockRendererThrottle::OnDisconnect, weak_factory_.GetWeakPtr()));
  }
}

void AdblockRendererThrottle::WillStartRequest(
    network::ResourceRequest* request,
    bool* defer) {
  // Frame requests go through the browser side throttle instead.
  if (request->destination == network::mojom::RequestDestination::kDocument ||
      request->destination == network::mojom::RequestDestination::kIframe ||
      request->destination == network::mojom::RequestDestination::kFrame ||
      request->destination ==
          network::mojom::RequestDestination::kFencedframe) {
    return;
  }
  if (!request->url.SchemeIsHTTPOrHTTPS() && !request->url.SchemeIsWSOrWSS()) {
    return;
  }
  BindIfNeeded();
  if (!checker_.is_bound()) {
    return;
  }
  initiator_ = request->request_initiator.has_value()
                   ? request->request_initiator->GetURL()
                   : GURL();
  request_type_ = TypeFor(request->destination, request->url);
  *defer = true;
  waiting_ = true;
  checker_->Check(request->url, initiator_, request_type_,
                  base::BindOnce(&AdblockRendererThrottle::OnResult,
                                 weak_factory_.GetWeakPtr()));
}

void AdblockRendererThrottle::WillRedirectRequest(
    net::RedirectInfo* redirect_info,
    const network::mojom::URLResponseHead& response_head,
    bool* defer,
    network::HttpRequestHeadersUpdateParams* headers_update_params) {
  if (request_type_.empty()) {
    return;
  }
  BindIfNeeded();
  if (!checker_.is_bound()) {
    return;
  }
  *defer = true;
  waiting_ = true;
  checker_->Check(redirect_info->new_url, initiator_, request_type_,
                  base::BindOnce(&AdblockRendererThrottle::OnResult,
                                 weak_factory_.GetWeakPtr()));
}

void AdblockRendererThrottle::OnResult(bool block) {
  if (!waiting_) {
    return;
  }
  waiting_ = false;
  if (block) {
    delegate_->CancelWithError(net::ERR_BLOCKED_BY_CLIENT, "boring-adblock");
    return;
  }
  delegate_->Resume();
}

void AdblockRendererThrottle::OnDisconnect() {
  // Never leave a request hanging if the browser end goes away.
  checker_.reset();
  if (waiting_) {
    waiting_ = false;
    delegate_->Resume();
  }
}

}  // namespace boring
