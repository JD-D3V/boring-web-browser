// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_RENDERER_ADBLOCK_RENDERER_THROTTLE_H_
#define COMPONENTS_BORING_ADBLOCK_RENDERER_ADBLOCK_RENDERER_THROTTLE_H_

#include <string>
#include <vector>

#include "base/memory/weak_ptr.h"
#include "net/http/http_request_headers.h"
#include "url/gurl.h"
#include "components/boring/adblock/mojom/adblock.mojom.h"
#include "mojo/public/cpp/bindings/pending_remote.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "third_party/blink/public/common/loader/url_loader_throttle.h"

namespace boring {

// Renderer side throttle for page subresources (images, scripts, xhr
// and so on). Pauses the request, asks the browser over mojo, then
// resumes or cancels.
class AdblockRendererThrottle : public blink::URLLoaderThrottle {
 public:
  explicit AdblockRendererThrottle(
      mojo::PendingRemote<mojom::AdblockChecker> checker);
  ~AdblockRendererThrottle() override;

  // blink::URLLoaderThrottle:
  void DetachFromCurrentSequence() override;
  void WillStartRequest(network::ResourceRequest* request,
                        bool* defer) override;
  void WillRedirectRequest(
      net::RedirectInfo* redirect_info,
      const network::mojom::URLResponseHead& response_head,
      bool* defer,
      network::HttpRequestHeadersUpdateParams* headers_update_params) override;

 private:
  void BindIfNeeded();
  void OnResult(bool block);
  void OnDisconnect();

  mojo::PendingRemote<mojom::AdblockChecker> pending_checker_;
  mojo::Remote<mojom::AdblockChecker> checker_;
  GURL initiator_;
  std::string request_type_;
  // True while a request is paused waiting for the browser's answer.
  bool waiting_ = false;
  base::WeakPtrFactory<AdblockRendererThrottle> weak_factory_{this};
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_RENDERER_ADBLOCK_RENDERER_THROTTLE_H_
