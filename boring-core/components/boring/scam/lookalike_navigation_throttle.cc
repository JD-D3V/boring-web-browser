// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/lookalike_navigation_throttle.h"

#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "components/boring/guards/guards_policy.h"
#include "components/boring/scam/lookalike_blocking_page.h"
#include "components/boring/scam/lookalike_brands.h"
#include "components/lookalikes/core/lookalike_url_util.h"
#include "components/security_interstitials/content/security_interstitial_tab_helper.h"
#include "components/url_formatter/url_formatter.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/web_contents.h"
#include "net/base/net_errors.h"
#include "net/base/registry_controlled_domains/registry_controlled_domain.h"
#include "net/base/url_util.h"

namespace boring {

namespace {

// A site whose name copies another's, and the site it copies.
struct Lookalike {
  // The copy's eTLD+1: what "Continue anyway" lets through.
  std::string domain;
  // The real site, or empty when the name copies no one site.
  GURL safe_url;
};

// https, the default port and no path: where the real site is.
GURL RealSite(const std::string& domain) {
  return GURL("https://" + domain + "/");
}

std::optional<Lookalike> FindLookalike(const GURL& url) {
  if (!url.SchemeIsHTTPOrHTTPS()) {
    return std::nullopt;
  }
  // The same early outs Chromium's service has: nothing to say about
  // addresses that are not on the public web, or on a government ending.
  const std::string host = url.GetHost();
  if (net::HostStringIsLocalhost(host) || net::IsHostnameNonUnique(host)) {
    return std::nullopt;
  }
  const std::string public_domain = lookalikes::GetETLDPlusOne(host);
  if (public_domain.empty() || lookalikes::IsSafeTLD(host)) {
    return std::nullopt;
  }
  // The name a person can register, counting free hosting platforms such as
  // github.io and pages.dev as registries: "paypa1-login.github.io" is its
  // own name, not a page of github.io.
  std::string domain = net::registry_controlled_domains::GetDomainAndRegistry(
      host, net::registry_controlled_domains::INCLUDE_PRIVATE_REGISTRIES);
  if (domain.empty()) {
    domain = public_domain;
  }
  // One of the 10,000 most visited sites, or under one: it is the real
  // thing, whatever it looks like.
  if (url_formatter::IsDomainAndRegistryATopDomain(domain)) {
    return std::nullopt;
  }

  // Chromium's own checks. No engaged sites (what this profile visits
  // most) and no safety tips file: nothing here depends on either. Of what
  // they find, a full page warning is what Chromium itself shows for a
  // letter-for-letter copy of a top 500 site written in other alphabets,
  // a site that embeds a top site's name ("paypal.com.example.net"), and a
  // name that fails the spoof checks. The rest it only counts, or shows a
  // hint for, and we do not warn on those.
  const lookalikes::DomainInfo info = lookalikes::GetDomainInfo(url);
  std::string matched;
  lookalikes::LookalikeUrlMatchType type =
      lookalikes::LookalikeUrlMatchType::kNone;
  if (lookalikes::GetMatchingDomain(
          info, /*engaged_sites=*/{},
          base::BindRepeating([](const std::string&) { return false; }),
          /*config_proto=*/nullptr, &matched, &type)) {
    if (type == lookalikes::LookalikeUrlMatchType::kSkeletonMatchTop500 ||
        type == lookalikes::LookalikeUrlMatchType::kTargetEmbedding) {
      return Lookalike{domain, RealSite(lookalikes::GetETLDPlusOne(matched))};
    }
  } else if (lookalikes::ShouldBlockBySpoofCheckResult(info)) {
    return Lookalike{domain, GURL()};
  }

  // Plain-letter copies such as paypa1.com, which Chromium does not warn
  // about. See lookalike_brands.h.
  const std::string brand = FindLookalikeBrand(domain);
  if (!brand.empty()) {
    return Lookalike{domain, RealSite(brand)};
  }
  return std::nullopt;
}

}  // namespace

// static
void LookalikeNavigationThrottle::MaybeCreateAndAdd(
    content::NavigationThrottleRegistry& registry) {
  if (!registry.GetNavigationHandle().IsInOutermostMainFrame()) {
    return;
  }
  registry.AddThrottle(std::make_unique<LookalikeNavigationThrottle>(registry));
}

LookalikeNavigationThrottle::LookalikeNavigationThrottle(
    content::NavigationThrottleRegistry& registry)
    : content::NavigationThrottle(registry) {}

LookalikeNavigationThrottle::~LookalikeNavigationThrottle() = default;

content::NavigationThrottle::ThrottleCheckResult
LookalikeNavigationThrottle::WillStartRequest() {
  return Check();
}

content::NavigationThrottle::ThrottleCheckResult
LookalikeNavigationThrottle::WillRedirectRequest() {
  return Check();
}

const char* LookalikeNavigationThrottle::GetNameForLogging() {
  return "BoringLookalikeNavigationThrottle";
}

content::NavigationThrottle::ThrottleCheckResult
LookalikeNavigationThrottle::Check() {
  content::NavigationHandle* handle = navigation_handle();
  content::WebContents* contents = handle->GetWebContents();
  content::BrowserContext* context =
      contents ? contents->GetBrowserContext() : nullptr;
  if (!contents || !guards::IsEnabled(context)) {
    return content::NavigationThrottle::PROCEED;
  }
  const GURL& url = handle->GetURL();
  std::optional<Lookalike> found = FindLookalike(url);
  if (!found || IsLookalikeAllowed(context, found->domain)) {
    return content::NavigationThrottle::PROCEED;
  }
  // A page being loaded ahead of time has no one to show a warning to.
  if (handle->IsInPrerenderedMainFrame()) {
    return content::NavigationThrottle::CANCEL;
  }

  std::unique_ptr<LookalikeBlockingPage> page = LookalikeBlockingPage::Create(
      contents, url, found->safe_url, found->domain);
  std::string html = page->GetHTMLContents();
  security_interstitials::SecurityInterstitialTabHelper::AssociateBlockingPage(
      handle, std::move(page));
  return content::NavigationThrottle::ThrottleCheckResult(
      CANCEL, net::ERR_BLOCKED_BY_CLIENT, std::move(html));
}

}  // namespace boring
