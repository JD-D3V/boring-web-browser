// Copyright 2026 boring. BSD style license.

#include "components/boring/adblock/cname_uncloaker.h"

#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "base/functional/callback.h"
#include "base/task/bind_post_task.h"
#include "base/time/time.h"
#include "base/timer/timer.h"
#include "components/prefs/pref_service.h"
#include "content/public/browser/browser_task_traits.h"
#include "content/public/browser/browser_thread.h"
#include "content/public/browser/render_process_host.h"
#include "content/public/browser/storage_partition.h"
#include "mojo/public/cpp/bindings/receiver.h"
#include "net/base/address_list.h"
#include "net/base/network_anonymization_key.h"
#include "net/base/registry_controlled_domains/registry_controlled_domain.h"
#include "net/base/schemeful_site.h"
#include "net/dns/public/host_resolver_results.h"
#include "net/dns/public/resolve_error_info.h"
#include "services/network/public/cpp/resolve_host_client_base.h"
#include "services/network/public/mojom/host_resolver.mojom.h"
#include "services/network/public/mojom/network_context.mojom.h"
#include "url/gurl.h"
#include "url/scheme_host_port.h"

namespace boring {

namespace {

// chrome/common/pref_names.h kDnsOverHttpsMode, and the value it holds in
// secure mode (net::SecureDnsMode::kSecure). Named here because a
// component cannot include chrome/.
constexpr char kDnsOverHttpsModePref[] = "dns_over_https.mode";
constexpr char kSecureMode[] = "secure";

// The request waits for this answer, so a resolver that never answers
// must not hold it forever. The request's own lookup would wait too; this
// only stops the extra check from waiting longer than that.
constexpr base::TimeDelta kTimeout = base::Seconds(5);

PrefService* g_local_state = nullptr;

bool SecureDnsIsStrict() {
  return g_local_state &&
         g_local_state->GetString(kDnsOverHttpsModePref) == kSecureMode;
}

std::vector<std::string> ThirdPartyAliases(const std::string& host,
                                           const std::vector<std::string>& in) {
  std::vector<std::string> out;
  for (const std::string& alias : in) {
    if (alias.empty() || alias == host) {
      continue;
    }
    // www.example.com -> example.com is the site talking to itself, not
    // a cloak (uBO's cnameIgnore1stParty, on by default there too).
    if (net::registry_controlled_domains::SameDomainOrHost(
            GURL("https://" + host), GURL("https://" + alias),
            net::registry_controlled_domains::INCLUDE_PRIVATE_REGISTRIES)) {
      continue;
    }
    out.push_back(alias);
  }
  return out;
}

// One lookup, owned by itself: deleted when the answer arrives, the
// pipe breaks or the time runs out, whichever comes first.
class AliasLookup : public network::ResolveHostClientBase {
 public:
  AliasLookup(std::string host, CnameUncloaker::AliasesCallback callback)
      : host_(std::move(host)), callback_(std::move(callback)) {}

  void Start(network::mojom::NetworkContext* context,
             const url::SchemeHostPort& target,
             const net::NetworkAnonymizationKey& key) {
    auto params = network::mojom::ResolveHostParameters::New();
    params->include_canonical_name = true;
    // Answers from the cache are the point: the request itself resolves
    // the same name through the same cache.
    params->cache_usage =
        network::mojom::ResolveHostParameters::CacheUsage::ALLOWED;
    context->ResolveHost(
        network::mojom::HostResolverHost::NewSchemeHostPort(target), key,
        std::move(params), receiver_.BindNewPipeAndPassRemote());
    receiver_.set_disconnect_handler(
        base::BindOnce(&AliasLookup::Finish, base::Unretained(this),
                       std::vector<std::string>()));
    timer_.Start(FROM_HERE, kTimeout,
                 base::BindOnce(&AliasLookup::Finish, base::Unretained(this),
                                std::vector<std::string>()));
  }

  // network::ResolveHostClientBase:
  void OnComplete(
      int32_t result,
      const net::ResolveErrorInfo& resolve_error_info,
      const net::AddressList& resolved_addresses,
      const net::HostResolverEndpointResults& alternative_endpoints) override {
    Finish(result == net::OK
               ? ThirdPartyAliases(host_, resolved_addresses.dns_aliases())
               : std::vector<std::string>());
  }

 private:
  void Finish(std::vector<std::string> aliases) {
    std::move(callback_).Run(std::move(aliases));
    delete this;
  }

  const std::string host_;
  CnameUncloaker::AliasesCallback callback_;
  mojo::Receiver<network::mojom::ResolveHostClient> receiver_{this};
  base::OneShotTimer timer_;
};

void GetAliasesOnUI(int render_process_id,
                    GURL url,
                    GURL initiator,
                    GURL top_frame_url,
                    CnameUncloaker::AliasesCallback callback) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  content::RenderProcessHost* host =
      content::RenderProcessHost::FromID(render_process_id);
  if (!SecureDnsIsStrict() || !host || !host->GetStoragePartition()) {
    std::move(callback).Run({});
    return;
  }
  // Keyed like the request's own lookup, so the two share a cache entry
  // and the name goes to the resolver once, not twice.
  const net::SchemefulSite top_site(top_frame_url.is_valid() ? top_frame_url
                                                             : initiator);
  const net::SchemefulSite frame_site(initiator.is_valid() ? initiator : url);
  const net::NetworkAnonymizationKey key =
      net::NetworkAnonymizationKey::CreateFromFrameSite(top_site, frame_site);

  auto* lookup = new AliasLookup(std::string(url.host()), std::move(callback));
  lookup->Start(host->GetStoragePartition()->GetNetworkContext(),
                url::SchemeHostPort(url), key);
}

}  // namespace

// static
void CnameUncloaker::SetLocalState(PrefService* local_state) {
  DCHECK_CURRENTLY_ON(content::BrowserThread::UI);
  if (!g_local_state) {
    g_local_state = local_state;
  }
}

// static
void CnameUncloaker::GetAliases(int render_process_id,
                                const GURL& url,
                                const GURL& initiator,
                                const GURL& top_frame_url,
                                AliasesCallback callback) {
  if (!url.SchemeIsHTTPOrHTTPS() || url.HostIsIPAddress() ||
      url.host().empty()) {
    std::move(callback).Run({});
    return;
  }
  content::GetUIThreadTaskRunner({})->PostTask(
      FROM_HERE,
      base::BindOnce(&GetAliasesOnUI, render_process_id, url, initiator,
                     top_frame_url,
                     base::BindPostTaskToCurrentDefault(std::move(callback))));
}

}  // namespace boring
