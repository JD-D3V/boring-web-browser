// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_ADBLOCK_THROTTLE_H_
#define COMPONENTS_BORING_ADBLOCK_ADBLOCK_THROTTLE_H_

#include <memory>

#include "third_party/blink/public/common/loader/url_loader_throttle.h"

namespace boring {

// Browser side throttle. Covers navigations (so iframes) and requests
// the browser itself makes. Page subresources are covered by the
// renderer side throttle instead.
class AdblockThrottle : public blink::URLLoaderThrottle {
 public:
  // Returns null when ad blocking is turned off.
  static std::unique_ptr<AdblockThrottle> MaybeCreate();

  AdblockThrottle();
  ~AdblockThrottle() override;

  // blink::URLLoaderThrottle:
  void WillStartRequest(network::ResourceRequest* request,
                        bool* defer) override;
  void WillRedirectRequest(net::RedirectInfo* redirect_info,
                           const network::mojom::URLResponseHead& response_head,
                           bool* defer,
                           std::vector<std::string>* to_be_removed_headers,
                           net::HttpRequestHeaders* modified_headers,
                           net::HttpRequestHeaders* modified_cors_headers)
      override;

 private:
  // Remembered from WillStartRequest for redirect checks.
  GURL initiator_;
  std::string request_type_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_ADBLOCK_THROTTLE_H_
