// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/adblock_redirect_proxy.h"

#include <algorithm>
#include <optional>
#include <set>
#include <string>
#include <utility>

#include "base/byte_size.h"
#include "base/containers/span.h"
#include "base/functional/bind.h"
#include "base/memory/self_deleting.h"
#include "base/no_destructor.h"
#include "base/synchronization/lock.h"
#include "base/task/sequenced_task_runner.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "content/public/browser/browser_context.h"
#include "mojo/public/cpp/system/data_pipe.h"
#include "net/base/data_url.h"
#include "net/base/isolation_info.h"
#include "net/base/net_errors.h"
#include "net/http/http_response_headers.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/url_loader_completion_status.h"
#include "services/network/public/cpp/url_loader_factory_builder.h"
#include "services/network/public/mojom/fetch_api.mojom-shared.h"
#include "services/network/public/mojom/url_response_head.mojom.h"
#include "url/origin.h"

namespace boring {

namespace {

// uBO's largest stubs are a few tens of KB. Anything far bigger is not
// one of them, and is blocked instead of pushed through a pipe.
constexpr size_t kMaxStubBytes = 4 * 1024 * 1024;

// All proxies share one sequence: each request costs one engine lookup
// there, and nothing on the UI thread waits for it.
scoped_refptr<base::SequencedTaskRunner> ProxyTaskRunner() {
  static base::NoDestructor<scoped_refptr<base::SequencedTaskRunner>> runner(
      base::ThreadPool::CreateSequencedTaskRunner(
          {base::TaskPriority::USER_BLOCKING}));
  return *runner;
}

// Render processes whose subresource factories have a proxy. Ids are
// never reused within a run, so nothing is ever taken out; the set
// grows by one small int per renderer.
class CoveredProcesses {
 public:
  void Add(int id) {
    base::AutoLock lock(lock_);
    ids_.insert(id);
  }
  bool Contains(int id) const {
    base::AutoLock lock(lock_);
    return ids_.contains(id);
  }

 private:
  mutable base::Lock lock_;
  std::set<int> ids_ GUARDED_BY(lock_);
};

CoveredProcesses& Covered() {
  static base::NoDestructor<CoveredProcesses> covered;
  return *covered;
}

void CreateOnProxySequence(
    mojo::PendingReceiver<network::mojom::URLLoaderFactory> receiver,
    mojo::PendingRemote<network::mojom::URLLoaderFactory> target,
    scoped_refptr<BlockingOffSites> off_sites,
    scoped_refptr<ProfileLists> lists,
    const GURL& top_frame_url) {
  base::MakeSelfDeleting<AdblockRedirectProxy>(
      std::move(receiver), std::move(target), std::move(off_sites),
      std::move(lists), top_frame_url);
}

}  // namespace

AdblockRedirectProxy::AdblockRedirectProxy(
    mojo::PendingReceiver<network::mojom::URLLoaderFactory> receiver,
    mojo::PendingRemote<network::mojom::URLLoaderFactory> target,
    scoped_refptr<BlockingOffSites> off_sites,
    scoped_refptr<ProfileLists> lists,
    const GURL& top_frame_url,
    base::SelfDeletingPassKey pass_key)
    : network::SelfDeletingURLLoaderFactory(std::move(receiver), pass_key),
      off_sites_(std::move(off_sites)),
      lists_(std::move(lists)),
      top_frame_url_(top_frame_url) {
  target_.Bind(std::move(target));
  target_.set_disconnect_handler(base::BindOnce(
      &AdblockRedirectProxy::OnTargetDisconnected, base::Unretained(this)));
}

AdblockRedirectProxy::~AdblockRedirectProxy() = default;

// static
void AdblockRedirectProxy::MaybeProxy(
    content::BrowserContext* browser_context,
    int render_process_id,
    content::ContentBrowserClient::URLLoaderFactoryType type,
    const net::IsolationInfo& isolation_info,
    network::URLLoaderFactoryBuilder& factory_builder) {
  using FactoryType = content::ContentBrowserClient::URLLoaderFactoryType;
  // The factories renderers fetch page and worker subresources with.
  // Navigations, downloads and the browser's own fetches are left to
  // the browser side throttle, which blocks outright.
  if (type != FactoryType::kDocumentSubResource &&
      type != FactoryType::kWorkerSubResource &&
      type != FactoryType::kServiceWorkerSubResource) {
    return;
  }
  if (!browser_context || AdblockService::IsDisabled()) {
    return;
  }
  GURL top_frame_url;
  if (isolation_info.top_frame_origin()) {
    top_frame_url = isolation_info.top_frame_origin()->GetURL();
  }
  auto [receiver, target] = factory_builder.Append();
  ProxyTaskRunner()->PostTask(
      FROM_HERE,
      base::BindOnce(&CreateOnProxySequence, std::move(receiver),
                     std::move(target),
                     BlockingOffSites::ForContext(browser_context),
                     ProfileLists::ForContext(browser_context), top_frame_url));
  Covered().Add(render_process_id);
}

// static
bool AdblockRedirectProxy::CoversProcess(int render_process_id) {
  return Covered().Contains(render_process_id);
}

void AdblockRedirectProxy::CreateLoaderAndStart(
    mojo::PendingReceiver<network::mojom::URLLoader> loader,
    int32_t request_id,
    uint32_t options,
    const network::ResourceRequest& request,
    mojo::PendingRemote<network::mojom::URLLoaderClient> client,
    const net::MutableNetworkTrafficAnnotationTag& traffic_annotation) {
  DCHECK_CALLED_ON_VALID_THREAD(thread_checker_);
  std::string stub;
  bool block = false;
  if (request.url.SchemeIsHTTPOrHTTPS()) {
    GURL top_frame_url = top_frame_url_;
    if (!top_frame_url.is_valid() && !request.site_for_cookies.IsNull()) {
      top_frame_url = request.site_for_cookies.RepresentativeUrl();
    }
    // The same type the renderer's throttle asked with, so both get the
    // same answer: it calls <embed> and <object> loads "other".
    using network::mojom::RequestDestination;
    const bool embed = request.destination == RequestDestination::kEmbed ||
                       request.destination == RequestDestination::kObject;
    const std::string request_type =
        embed ? "other"
              : AdblockService::RequestTypeFromDestination(request.destination,
                                                           request.url);
    // Frames are navigations, handled by the browser side throttle.
    if (request_type != "document" && request_type != "subdocument" &&
        !(off_sites_ && off_sites_->IsOff(top_frame_url))) {
      const GURL initiator = request.request_initiator.has_value()
                                 ? request.request_initiator->GetURL()
                                 : GURL();
      AdblockService::Decision decision = AdblockService::GetInstance()->Check(
          request.url, initiator, request_type,
          lists_ ? lists_->Get() : EnabledLists());
      block = decision.block;
      stub = std::move(decision.redirect);
    }
  }

  if (!block) {
    target_->CreateLoaderAndStart(std::move(loader), request_id, options,
                                  request, std::move(client),
                                  traffic_annotation);
    return;
  }
  // A plain block normally never gets here: the renderer's throttle
  // cancels it first. One that does (the lists changed in between) is
  // still blocked, never sent on.
  if (stub.empty()) {
    mojo::Remote<network::mojom::URLLoaderClient>(std::move(client))
        ->OnComplete(
            network::URLLoaderCompletionStatus(net::ERR_BLOCKED_BY_CLIENT));
    return;
  }
  ServeStub(request, stub, std::move(client));
}

// static
void AdblockRedirectProxy::ServeStub(
    const network::ResourceRequest& request,
    const std::string& data_url,
    mojo::PendingRemote<network::mojom::URLLoaderClient> client) {
  mojo::Remote<network::mojom::URLLoaderClient> client_remote(
      std::move(client));
  auto fail = [&client_remote] {
    client_remote->OnComplete(
        network::URLLoaderCompletionStatus(net::ERR_BLOCKED_BY_CLIENT));
  };

  auto head = network::mojom::URLResponseHead::New();
  std::string body;
  if (net::DataURL::BuildResponse(GURL(data_url), request.method,
                                  &head->mime_type, &head->charset, &body,
                                  &head->headers) != net::OK ||
      !head->headers || body.size() > kMaxStubBytes) {
    fail();
    return;
  }

  // This answer skips the network service, which is where CORS is
  // normally checked and the response type set, so both are done here
  // as the real server's reply would have come out:
  //   same origin           basic
  //   no-cors, other site   opaque, as for any third party script or
  //                         image; the page cannot read it
  //   cors, other site      cors, allowed for the requesting origin.
  //                         The stub is our own harmless file, so
  //                         allowing it hides nothing from the page
  //                         that a real ad server would have shown.
  //   same-origin mode,     a network error, as the real one would be
  //   other site
  using network::mojom::FetchResponseType;
  using network::mojom::RequestMode;
  const bool same_origin =
      request.request_initiator.has_value() &&
      request.request_initiator->IsSameOriginWith(request.url);
  if (same_origin) {
    head->response_type = FetchResponseType::kBasic;
  } else if (request.mode == RequestMode::kNoCors) {
    head->response_type = FetchResponseType::kOpaque;
  } else if ((request.mode == RequestMode::kCors ||
              request.mode == RequestMode::kCorsWithForcedPreflight) &&
             request.request_initiator.has_value()) {
    head->response_type = FetchResponseType::kCors;
    head->headers->SetHeader("Access-Control-Allow-Origin",
                             request.request_initiator->Serialize());
    if (request.credentials_mode == network::mojom::CredentialsMode::kInclude) {
      head->headers->SetHeader("Access-Control-Allow-Credentials", "true");
    }
  } else {
    fail();
    return;
  }
  head->content_length = static_cast<int64_t>(body.size());
  head->request_time = base::Time::Now();
  head->response_time = head->request_time;

  // Stubs are small, so the whole body fits in the pipe and is written
  // before the response is even sent.
  mojo::ScopedDataPipeProducerHandle producer;
  mojo::ScopedDataPipeConsumerHandle consumer;
  const uint32_t capacity =
      static_cast<uint32_t>(std::max<size_t>(body.size(), 1));
  if (mojo::CreateDataPipe(capacity, producer, consumer) != MOJO_RESULT_OK) {
    fail();
    return;
  }
  if (!body.empty() &&
      producer->WriteAllData(base::as_byte_span(body)) != MOJO_RESULT_OK) {
    fail();
    return;
  }
  producer.reset();

  client_remote->OnReceiveResponse(std::move(head), std::move(consumer),
                                   std::nullopt);
  network::URLLoaderCompletionStatus status(net::OK);
  status.encoded_data_length = base::ByteSize(body.size());
  status.encoded_body_length = base::ByteSize(body.size());
  status.decoded_body_length = base::ByteSize(body.size());
  client_remote->OnComplete(status);
}

void AdblockRedirectProxy::OnTargetDisconnected() {
  DisconnectReceiversAndDestroy();
}

}  // namespace boring
