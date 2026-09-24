// Copyright 2026 boring. BSD style license.

#include "components/boring/privacy/tracking_param_throttle.h"

#include <algorithm>
#include <memory>
#include <optional>
#include <vector>

#include "base/functional/bind.h"
#include "base/task/sequenced_task_runner.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/privacy/tracking_params.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/page_navigator.h"
#include "content/public/browser/reload_type.h"
#include "content/public/browser/web_contents.h"
#include "url/gurl.h"
#include "url/origin.h"

namespace boring {

namespace {

bool IsOn(content::NavigationHandle& handle) {
  const PrefService* prefs =
      user_prefs::UserPrefs::Get(handle.GetWebContents()->GetBrowserContext());
  return prefs && prefs->GetBoolean(prefs::kStripTrackingParams);
}

// Starts the same navigation again at the clean address. Posted, because
// a throttle may not start a navigation from inside another one.
void Renavigate(base::WeakPtr<content::WebContents> web_contents,
                content::OpenURLParams params) {
  if (web_contents) {
    web_contents->OpenURL(params, /*navigation_handle_callback=*/{});
  }
}

}  // namespace

// static
void TrackingParamThrottle::MaybeCreateAndAdd(
    content::NavigationThrottleRegistry& registry) {
  content::NavigationHandle& handle = registry.GetNavigationHandle();
  // Only the page itself. Frames and subresources inside a page are the
  // page's own business, and rewriting them breaks more than it saves.
  if (!handle.IsInPrimaryMainFrame() ||
      !handle.GetURL().SchemeIsHTTPOrHTTPS()) {
    return;
  }
  // Back, forward, a restored tab and a reload go to a page already
  // visited, so its address was already sent. Starting them again would
  // also turn a step back into a new entry, and Back would never get
  // past it.
  if (handle.IsHistory() ||
      handle.GetReloadType() != content::ReloadType::NONE) {
    return;
  }
  registry.AddThrottle(std::make_unique<TrackingParamThrottle>(registry));
}

TrackingParamThrottle::TrackingParamThrottle(
    content::NavigationThrottleRegistry& registry)
    : content::NavigationThrottle(registry) {}

TrackingParamThrottle::~TrackingParamThrottle() = default;

content::NavigationThrottle::ThrottleCheckResult
TrackingParamThrottle::WillStartRequest() {
  const std::optional<url::Origin>& initiator =
      navigation_handle()->GetInitiatorOrigin();
  return Check(initiator ? initiator->GetURL() : GURL());
}

content::NavigationThrottle::ThrottleCheckResult
TrackingParamThrottle::WillRedirectRequest() {
  const std::vector<GURL>& chain = navigation_handle()->GetRedirectChain();
  return Check(chain.size() >= 2 ? chain[chain.size() - 2] : GURL());
}

content::NavigationThrottle::ThrottleCheckResult TrackingParamThrottle::Check(
    const GURL& from) {
  content::NavigationHandle& handle = *navigation_handle();
  const GURL& url = handle.GetURL();
  // A form post carries its own data; leave it as sent.
  if (handle.IsPost() || !IsOn(handle)) {
    return PROCEED;
  }
  if (from.is_valid() && from.SchemeIsHTTPOrHTTPS() && IsSameSite(from, url)) {
    return PROCEED;
  }
  std::optional<GURL> clean = StripTrackingParams(url);
  if (!clean) {
    return PROCEED;
  }
  // A site that redirects the clean address back to one with the
  // parameter would otherwise go round forever, each time as a new
  // navigation with a fresh redirect limit. Let that one through.
  if (std::ranges::contains(handle.GetRedirectChain(), *clean)) {
    return PROCEED;
  }
  // Everything but the address stays as it was: who started it, the
  // referrer, the user gesture. A link from another site must still
  // look like one to the server, or it would get cookies and headers
  // meant only for addresses a person typed.
  content::OpenURLParams params =
      content::OpenURLParams::FromNavigationHandle(&handle);
  params.url = *clean;
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(&Renavigate, handle.GetWebContents()->GetWeakPtr(),
                     std::move(params)));
  return CANCEL_AND_IGNORE;
}

const char* TrackingParamThrottle::GetNameForLogging() {
  return "BoringTrackingParamThrottle";
}

}  // namespace boring
