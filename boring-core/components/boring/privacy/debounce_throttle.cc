// Copyright 2026 boring. BSD style license.

#include "components/boring/privacy/debounce_throttle.h"

#include <algorithm>
#include <memory>
#include <optional>
#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "base/task/sequenced_task_runner.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/privacy/debounce.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/navigation_handle.h"
#include "content/public/browser/page_navigator.h"
#include "content/public/browser/reload_type.h"
#include "content/public/browser/web_contents.h"
#include "url/gurl.h"

namespace boring {

namespace {

bool IsOn(content::NavigationHandle& handle) {
  const PrefService* prefs =
      user_prefs::UserPrefs::Get(handle.GetWebContents()->GetBrowserContext());
  return prefs && prefs->GetBoolean(prefs::kSkipRedirects);
}

// Starts the same navigation again at the address it was going to reach.
// Posted, because a throttle may not start a navigation from inside
// another one.
void Renavigate(base::WeakPtr<content::WebContents> web_contents,
                content::OpenURLParams params) {
  if (web_contents) {
    web_contents->OpenURL(params, /*navigation_handle_callback=*/{});
  }
}

}  // namespace

// static
void DebounceThrottle::MaybeCreateAndAdd(
    content::NavigationThrottleRegistry& registry) {
  content::NavigationHandle& handle = registry.GetNavigationHandle();
  // Only the page itself. A frame or subresource is the page's own
  // business, and rewriting those breaks more than it saves.
  if (!handle.IsInPrimaryMainFrame() ||
      !handle.GetURL().SchemeIsHTTPOrHTTPS()) {
    return;
  }
  // Back, forward, a restored tab and a reload go to a page already
  // visited. Starting them again would also turn a step back into a new
  // entry, and Back would never get past it.
  if (handle.IsHistory() ||
      handle.GetReloadType() != content::ReloadType::NONE) {
    return;
  }
  if (!IsOn(handle)) {
    return;
  }
  registry.AddThrottle(std::make_unique<DebounceThrottle>(registry));
}

DebounceThrottle::DebounceThrottle(content::NavigationThrottleRegistry& registry)
    : content::NavigationThrottle(registry) {}

DebounceThrottle::~DebounceThrottle() = default;

content::NavigationThrottle::ThrottleCheckResult
DebounceThrottle::WillStartRequest() {
  return Check();
}

content::NavigationThrottle::ThrottleCheckResult
DebounceThrottle::WillRedirectRequest() {
  return Check();
}

content::NavigationThrottle::ThrottleCheckResult DebounceThrottle::Check() {
  content::NavigationHandle& handle = *navigation_handle();
  // A form post carries its own data; leave it as sent.
  if (handle.IsPost()) {
    return PROCEED;
  }
  std::optional<GURL> target = Debounce(handle.GetURL());
  if (!target) {
    return PROCEED;
  }
  // A site that sends the real address straight back to the redirector
  // would otherwise go round forever, each time as a new navigation with
  // a fresh redirect limit. Let that one through.
  if (std::ranges::contains(handle.GetRedirectChain(), *target)) {
    return PROCEED;
  }
  // Everything but the address stays as it was: who started it, the
  // referrer, the user gesture. The new address goes through every other
  // check as the navigation it now is, scam protection included.
  content::OpenURLParams params =
      content::OpenURLParams::FromNavigationHandle(&handle);
  params.url = *target;
  base::SequencedTaskRunner::GetCurrentDefault()->PostTask(
      FROM_HERE,
      base::BindOnce(&Renavigate, handle.GetWebContents()->GetWeakPtr(),
                     std::move(params)));
  return CANCEL_AND_IGNORE;
}

const char* DebounceThrottle::GetNameForLogging() {
  return "BoringDebounceThrottle";
}

}  // namespace boring
