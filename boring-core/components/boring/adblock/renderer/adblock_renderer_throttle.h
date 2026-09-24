// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_RENDERER_ADBLOCK_RENDERER_THROTTLE_H_
#define COMPONENTS_BORING_ADBLOCK_RENDERER_ADBLOCK_RENDERER_THROTTLE_H_

#include <string>
#include <vector>

#include "base/memory/weak_ptr.h"
#include "components/boring/adblock/mojom/adblock.mojom.h"
#include "mojo/public/cpp/bindings/pending_remote.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "net/http/http_request_headers.h"
#include "third_party/blink/public/common/loader/url_loader_throttle.h"
#include "third_party/blink/public/common/tokens/tokens.h"
#include "url/gurl.h"

namespace boring {

// Renderer side throttle for page subresources (images, scripts, xhr
// and so on). Pauses the request, asks the browser over mojo, then
// resumes or cancels.
class AdblockRendererThrottle : public blink::URLLoaderThrottle {
 public:
  // `top_frame_url` is the page in the tab, or empty when not known
  // (see TopFrameUrlFor()).
  AdblockRendererThrottle(mojo::PendingRemote<mojom::AdblockChecker> checker,
                          const GURL& top_frame_url);
  ~AdblockRendererThrottle() override;

  // The page in the tab that holds this frame, even when the frame is a
  // third party one from another process. Main thread only, so only for
  // frame requests; workers are left to the request's first party site.
  static GURL TopFrameUrlFor(const blink::LocalFrameToken& frame_token);

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
  // The page in the tab, sent with each check so the browser can tell
  // whether blocking is off there.
  GURL top_frame_url_;
  // True while a request is paused waiting for the browser's answer.
  bool waiting_ = false;
  base::WeakPtrFactory<AdblockRendererThrottle> weak_factory_{this};
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_RENDERER_ADBLOCK_RENDERER_THROTTLE_H_
