// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/quad9_block_checker.h"

#include <optional>
#include <string>
#include <utility>

#include "base/base64url.h"
#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/time/time.h"
#include "components/boring/scam/quad9_answer.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition.h"
#include "net/base/load_flags.h"
#include "net/base/url_util.h"
#include "net/traffic_annotation/network_traffic_annotation.h"
#include "net/url_request/referrer_policy.h"
#include "services/network/public/cpp/resource_request.h"
#include "services/network/public/cpp/shared_url_loader_factory.h"
#include "services/network/public/cpp/simple_url_loader.h"
#include "services/network/public/mojom/fetch_api.mojom.h"
#include "url/gurl.h"
#include "url/url_constants.h"

namespace boring {

namespace {

constexpr char kQuad9Endpoint[] = "https://dns.quad9.net/dns-query";

// Points the question at a server on this machine, which is how the smoke
// test answers it without a real threat list name. Honoured only for the
// literal loopback address 127.0.0.1 or [::1] (http or https) and ignored
// for anything else, so nothing can send the question to another host.
constexpr char kTestEndpointSwitch[] = "boring-test-quad9-endpoint";

// A DNS answer is a few hundred bytes. This is the most that is read.
constexpr size_t kMaxAnswerBytes = 4096;
constexpr base::TimeDelta kTimeout = base::Seconds(2);

GURL Endpoint() {
  const base::CommandLine* command_line = base::CommandLine::ForCurrentProcess();
  if (command_line->HasSwitch(kTestEndpointSwitch)) {
    GURL test(command_line->GetSwitchValueASCII(kTestEndpointSwitch));
    if (test.is_valid() &&
        (test.SchemeIs(url::kHttpScheme) || test.SchemeIs(url::kHttpsScheme)) &&
        (test.host() == "127.0.0.1" || test.host() == "[::1]") &&
        !test.has_username() && !test.has_password()) {
      return test;
    }
  }
  return GURL(kQuad9Endpoint);
}

std::unique_ptr<network::SimpleURLLoader> MakeLoader(const GURL& url) {
  net::NetworkTrafficAnnotationTag annotation =
      net::DefineNetworkTrafficAnnotation("boring_quad9_block_check", R"(
        semantics {
          sender: "boring scam warning"
          description:
            "When a site cannot be found and Quad9 is the secure DNS "
            "server, asks Quad9 once more for that name, to tell a site "
            "Quad9 blocked as dangerous from one that does not exist."
          trigger:
            "A page address that could not be found, in the main "
            "window only."
          data:
            "The same site name Quad9 was already asked for a moment "
            "earlier. No cookies, no identifier, no referrer."
          destination: OTHER
          destination_other: "Quad9, the secure DNS server in use."
        }
        policy {
          cookies_allowed: NO
          setting:
            "Only when Secure DNS is on and set to Quad9. Turned off "
            "with Secure DNS on the Protection page."
          policy_exception_justification: "Not implemented yet."
        })");

  auto request = std::make_unique<network::ResourceRequest>();
  request->url = url;
  request->method = "GET";
  request->credentials_mode = network::mojom::CredentialsMode::kOmit;
  request->referrer_policy = net::ReferrerPolicy::NO_REFERRER;
  request->load_flags = net::LOAD_DISABLE_CACHE;
  // The server answers the question itself. A redirect would hand the site
  // name to whichever host it names.
  request->redirect_mode = network::mojom::RedirectMode::kError;
  request->headers.SetHeader("Accept", "application/dns-message");
  auto loader = network::SimpleURLLoader::Create(std::move(request), annotation);
  loader->SetTimeoutDuration(kTimeout);
  return loader;
}

}  // namespace

Quad9BlockChecker::Quad9BlockChecker() = default;
Quad9BlockChecker::~Quad9BlockChecker() = default;

bool Quad9BlockChecker::Check(content::BrowserContext* context,
                              const std::string& host,
                              Callback callback) {
  const std::string query = BuildDnsQuery(host);
  if (!context || query.empty()) {
    return false;
  }
  host_ = host;
  callback_ = std::move(callback);
  std::string encoded;
  base::Base64UrlEncode(query, base::Base64UrlEncodePolicy::OMIT_PADDING,
                        &encoded);
  loader_ = MakeLoader(net::AppendQueryParameter(Endpoint(), "dns", encoded));
  loader_->DownloadToString(
      context->GetDefaultStoragePartition()
          ->GetURLLoaderFactoryForBrowserProcess()
          .get(),
      base::BindOnce(&Quad9BlockChecker::OnDownloaded, base::Unretained(this)),
      kMaxAnswerBytes);
  return true;
}

void Quad9BlockChecker::OnDownloaded(std::optional<std::string> body) {
  const bool blocked =
      body && ParseQuad9Answer(*body, host_) == Quad9Verdict::kBlocked;
  std::move(callback_).Run(blocked);
}

}  // namespace boring
