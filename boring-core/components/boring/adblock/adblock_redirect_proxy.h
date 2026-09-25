// Copyright 2026 boring. BSD style license.

#ifndef COMPONENTS_BORING_ADBLOCK_ADBLOCK_REDIRECT_PROXY_H_
#define COMPONENTS_BORING_ADBLOCK_ADBLOCK_REDIRECT_PROXY_H_

#include <string>

#include "base/memory/scoped_refptr.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/adblock/blocking_off_sites.h"
#include "content/public/browser/content_browser_client.h"
#include "mojo/public/cpp/bindings/pending_receiver.h"
#include "mojo/public/cpp/bindings/pending_remote.h"
#include "mojo/public/cpp/bindings/remote.h"
#include "services/network/public/cpp/self_deleting_url_loader_factory.h"
#include "services/network/public/mojom/url_loader.mojom.h"
#include "services/network/public/mojom/url_loader_factory.mojom.h"
#include "url/gurl.h"

namespace content {
class BrowserContext;
}

namespace net {
class IsolationInfo;
}

namespace network {
class URLLoaderFactoryBuilder;
struct ResourceRequest;
}  // namespace network

namespace boring {

// Sits in front of the network for a renderer's page and worker
// requests, and answers a request a $redirect rule matches with the
// rule's stub (uBO's noop.js and friends) itself, so the server is
// never contacted. Everything else goes straight on to the real
// factory after one engine lookup.
//
// This is the only place the stub can be served. A URLLoaderThrottle
// may not turn an http(s) request into a data: URL, and can only swap
// a body in after the response has arrived from the server. So the
// throttles let a request with a stub through, and this answers it.
//
// Runs on its own background sequence, never the UI thread.
class AdblockRedirectProxy : public network::SelfDeletingURLLoaderFactory {
 public:
  AdblockRedirectProxy(
      mojo::PendingReceiver<network::mojom::URLLoaderFactory> receiver,
      mojo::PendingRemote<network::mojom::URLLoaderFactory> target,
      scoped_refptr<BlockingOffSites> off_sites,
      scoped_refptr<ProfileLists> lists,
      const GURL& top_frame_url,
      base::SelfDeletingPassKey pass_key);

  AdblockRedirectProxy(const AdblockRedirectProxy&) = delete;
  AdblockRedirectProxy& operator=(const AdblockRedirectProxy&) = delete;

  // Puts a proxy in front of `factory_builder` when `type` is a factory
  // a renderer loads page or worker subresources with. UI thread.
  static void MaybeProxy(
      content::BrowserContext* browser_context,
      int render_process_id,
      content::ContentBrowserClient::URLLoaderFactoryType type,
      const net::IsolationInfo& isolation_info,
      network::URLLoaderFactoryBuilder& factory_builder);

  // True once this render process's subresource factories are behind a
  // proxy. Until then a request with a stub must be blocked by the
  // renderer's throttle instead, or it would reach the real server.
  // Any thread.
  static bool CoversProcess(int render_process_id);

  // network::mojom::URLLoaderFactory:
  void CreateLoaderAndStart(
      mojo::PendingReceiver<network::mojom::URLLoader> loader,
      int32_t request_id,
      uint32_t options,
      const network::ResourceRequest& request,
      mojo::PendingRemote<network::mojom::URLLoaderClient> client,
      const net::MutableNetworkTrafficAnnotationTag& traffic_annotation)
      override;

 private:
  ~AdblockRedirectProxy() override;

  // Answers `request` with the stub in `data_url`, or fails it as
  // blocked when the stub cannot be served.
  static void ServeStub(
      const network::ResourceRequest& request,
      const std::string& data_url,
      mojo::PendingRemote<network::mojom::URLLoaderClient> client);

  void OnTargetDisconnected();

  mojo::Remote<network::mojom::URLLoaderFactory> target_;
  const scoped_refptr<BlockingOffSites> off_sites_;
  const scoped_refptr<ProfileLists> lists_;
  // The page in the tab, from the factory's isolation info. Empty for
  // factories that have none, where each request's first party site
  // stands in.
  const GURL top_frame_url_;
};

}  // namespace boring

#endif  // COMPONENTS_BORING_ADBLOCK_ADBLOCK_REDIRECT_PROXY_H_
