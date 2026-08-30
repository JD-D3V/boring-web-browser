// Copyright 2026 boring. BSD style license.

#include "components/boring/serp/serp_tab_helper.h"

#include <string>

#include "base/strings/strcat.h"
#include "base/strings/utf_string_conversions.h"
#include "components/boring/core/boring_prefs.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/render_frame_host.h"
#include "content/public/browser/web_contents.h"
#include "net/base/registry_controlled_domains/registry_controlled_domain.h"
#include "url/gurl.h"

namespace boring {

namespace {

// Isolated world for our script, away from the page's own scripts.
constexpr int32_t kBoringWorldId = 8888;

// The selectors cover the ad blocks Google and Bing use today. The
// script watches for new results because both sites update the page in
// place.
constexpr char kScript[] = R"((function() {
  if (window.__boringSerp) return;
  window.__boringSerp = true;
  document.documentElement.dataset.boringSerp = '1';
  var hide = %HIDE%;
  var sels = ['#tads', '#bottomads', 'div[data-text-ad]',
              '.b_ad', '.b_adTop', '.b_adBottom', 'li.b_ad',
              '.b_adLastChild'];
  function apply() {
    sels.forEach(function(s) {
      document.querySelectorAll(s).forEach(function(el) {
        if (hide) { el.style.display = 'none'; return; }
        if (el.dataset.boringLabeled) return;
        el.dataset.boringLabeled = '1';
        el.style.outline = '3px solid #c5221f';
        el.style.borderRadius = '8px';
        var tag = document.createElement('div');
        tag.textContent = 'Sponsored result (paid advertisement)';
        tag.style.cssText = 'background:#c5221f;color:#fff;' +
            'font:bold 13px system-ui;padding:4px 10px;' +
            'border-radius:6px 6px 0 0;';
        el.prepend(tag);
      });
    });
  }
  apply();
  new MutationObserver(apply).observe(
      document.documentElement, {subtree: true, childList: true});
})();)";

bool IsSearchResultsPage(const GURL& url) {
  if (!url.SchemeIsHTTPOrHTTPS()) {
    return false;
  }
  std::string domain =
      net::registry_controlled_domains::GetDomainAndRegistry(
          url, net::registry_controlled_domains::EXCLUDE_PRIVATE_REGISTRIES);
  bool google = domain.rfind("google.", 0) == 0;
  bool bing = domain == "bing.com";
  if (!google && !bing) {
    return false;
  }
  return url.path() == "/search";
}

}  // namespace

SerpTabHelper::SerpTabHelper(content::WebContents* web_contents)
    : content::WebContentsObserver(web_contents),
      content::WebContentsUserData<SerpTabHelper>(*web_contents) {}

SerpTabHelper::~SerpTabHelper() = default;

void SerpTabHelper::DocumentOnLoadCompletedInPrimaryMainFrame() {
  content::WebContents* contents = web_contents();
  if (!IsSearchResultsPage(contents->GetLastCommittedURL())) {
    return;
  }
  PrefService* pref_service =
      user_prefs::UserPrefs::Get(contents->GetBrowserContext());
  bool hide =
      IsSeniorSafeMode(pref_service) ||
      (pref_service &&
       pref_service->GetBoolean(prefs::kHideSponsoredResults));
  std::string script(kScript);
  std::string marker = "%HIDE%";
  size_t pos = script.find(marker);
  if (pos != std::string::npos) {
    script.replace(pos, marker.size(), hide ? "true" : "false");
  }
  contents->GetPrimaryMainFrame()->ExecuteJavaScriptInIsolatedWorld(
      base::UTF8ToUTF16(script), base::NullCallback(), kBoringWorldId);
}

WEB_CONTENTS_USER_DATA_KEY_IMPL(SerpTabHelper);

}  // namespace boring
