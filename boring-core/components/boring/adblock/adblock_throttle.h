// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_ADBLOCK_THROTTLE_H_
#define COMPONENTS_BORING_ADBLOCK_ADBLOCK_THROTTLE_H_

#include <memory>
#include <string>
#include <vector>

#include "net/http/http_request_headers.h"
#include "third_party/blink/public/common/loader/url_loader_throttle.h"
#include "url/gurl.h"

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
  void WillRedirectRequest(
      net::RedirectInfo* redirect_info,
      const network::mojom::URLResponseHead& response_head,
      bool* defer,
      network::HttpRequestHeadersUpdateParams* headers_update_params) override;

 private:
  // Remembered from WillStartRequest for redirect checks.
  GURL initiator_;
  std::string request_type_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_ADBLOCK_THROTTLE_H_
