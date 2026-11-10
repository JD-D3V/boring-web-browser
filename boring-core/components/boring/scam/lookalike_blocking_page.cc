// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/lookalike_blocking_page.h"

#include <memory>
#include <set>
#include <utility>

#include "base/memory/raw_ptr.h"
#include "base/strings/string_number_conversions.h"
#include "base/supports_user_data.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/scam/warning_page.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "components/security_interstitials/content/security_interstitial_controller_client.h"
#include "components/security_interstitials/content/settings_page_helper.h"
#include "components/security_interstitials/core/controller_client.h"
#include "components/security_interstitials/core/metrics_helper.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/page_navigator.h"
#include "content/public/browser/web_contents.h"
#include "content/public/common/referrer.h"
#include "ui/base/page_transition_types.h"
#include "ui/base/window_open_disposition.h"

namespace boring {

namespace {

// Domains this profile chose to continue to, kept on the browser context
// so they die with the profile and never reach another one.
constexpr char kAllowedDomainsKey[] = "boring_lookalike_allowed_domains";

class AllowedDomains : public base::SupportsUserData::Data {
 public:
  std::set<std::string> domains;
};

AllowedDomains* GetAllowedDomains(content::BrowserContext* context,
                                  bool create) {
  if (!context) {
    return nullptr;
  }
  auto* allowed =
      static_cast<AllowedDomains*>(context->GetUserData(kAllowedDomainsKey));
  if (!allowed && create) {
    auto owned = std::make_unique<AllowedDomains>();
    allowed = owned.get();
    context->SetUserData(kAllowedDomainsKey, std::move(owned));
  }
  return allowed;
}

// The prefs that remember a "Continue anyway" for this profile, or null in a
// private window, which only remembers for the window's own session.
PrefService* RememberingPrefs(content::BrowserContext* context) {
  if (!context || context->IsOffTheRecord()) {
    return nullptr;
  }
  return user_prefs::UserPrefs::Get(context);
}

std::unique_ptr<security_interstitials::MetricsHelper> MakeMetricsHelper(
    const GURL& url) {
  security_interstitials::MetricsHelper::ReportDetails details;
  details.metric_prefix = "boring_lookalike";
  return std::make_unique<security_interstitials::MetricsHelper>(url, details,
                                                                 nullptr);
}

// Handles the two choices on the look-alike warning page.
class LookalikeControllerClient
    : public security_interstitials::SecurityInterstitialControllerClient {
 public:
  LookalikeControllerClient(content::WebContents* web_contents,
                            const GURL& request_url,
                            const GURL& safe_url,
                            const std::string& domain,
                            PrefService* prefs)
      : security_interstitials::SecurityInterstitialControllerClient(
            web_contents,
            MakeMetricsHelper(request_url),
            prefs,
            "en-US",
            GURL("chrome://newtab/"),
            /*settings_page_helper=*/nullptr),
        safe_url_(safe_url),
        domain_(domain),
        context_(web_contents->GetBrowserContext()) {}

  // The real site, in place of the copy, so Back does not return to it.
  // With no real site to name, leave the way the scam warning does.
  void GoBack() override {
    if (!safe_url_.is_valid()) {
      GoBackAfterNavigationCommitted();
      return;
    }
    content::OpenURLParams params(safe_url_, content::Referrer(),
                                  WindowOpenDisposition::CURRENT_TAB,
                                  ui::PAGE_TRANSITION_LINK,
                                  /*is_renderer_initiated=*/false);
    params.should_replace_current_entry = true;
    web_contents()->OpenURL(params, /*navigation_handle_callback=*/{});
  }

  void Proceed() override {
    AllowLookalike(context_, domain_);
    Reload();
  }

 private:
  const GURL safe_url_;
  const std::string domain_;
  raw_ptr<content::BrowserContext> context_;
};

}  // namespace

void AllowLookalike(content::BrowserContext* context,
                    const std::string& domain) {
  if (AllowedDomains* allowed = GetAllowedDomains(context, /*create=*/true)) {
    allowed->domains.insert(domain);
  }
  // Remembered across runs in this profile's own prefs, never in a private
  // window.
  if (PrefService* prefs = RememberingPrefs(context)) {
    {
      ScopedListPrefUpdate update(prefs, prefs::kLookalikeAllowedSites);
      if (!update->contains(domain)) {
        update->Append(domain);
      }
    }
    // Written now, so closing the browser right after does not lose it.
    prefs->CommitPendingWrite();
  }
}

void ForgetLookalike(content::BrowserContext* context,
                     const std::string& domain) {
  if (AllowedDomains* allowed = GetAllowedDomains(context, /*create=*/false)) {
    allowed->domains.erase(domain);
  }
  if (PrefService* prefs = RememberingPrefs(context)) {
    ScopedListPrefUpdate update(prefs, prefs::kLookalikeAllowedSites);
    update->EraseValue(base::Value(domain));
    prefs->CommitPendingWrite();
  }
}

bool IsLookalikeAllowed(content::BrowserContext* context,
                        const std::string& domain) {
  // "No way past scam warnings" wins over anything remembered.
  PrefService* all_prefs = context ? user_prefs::UserPrefs::Get(context)
                                   : nullptr;
  if (all_prefs && all_prefs->GetBoolean(prefs::kNoScamBypass)) {
    return false;
  }
  const AllowedDomains* allowed = GetAllowedDomains(context, /*create=*/false);
  if (allowed && allowed->domains.count(domain)) {
    return true;
  }
  PrefService* prefs = RememberingPrefs(context);
  return prefs &&
         prefs->GetList(prefs::kLookalikeAllowedSites).contains(domain);
}

// static
const security_interstitials::SecurityInterstitialPage::TypeID
    LookalikeBlockingPage::kTypeForTesting =
        &LookalikeBlockingPage::kTypeForTesting;

// static
std::unique_ptr<LookalikeBlockingPage> LookalikeBlockingPage::Create(
    content::WebContents* web_contents,
    const GURL& request_url,
    const GURL& safe_url,
    const std::string& domain) {
  PrefService* prefs =
      user_prefs::UserPrefs::Get(web_contents->GetBrowserContext());
  const bool no_bypass = prefs && prefs->GetBoolean(prefs::kNoScamBypass);
  return std::make_unique<LookalikeBlockingPage>(
      web_contents, request_url, safe_url, no_bypass,
      std::make_unique<LookalikeControllerClient>(web_contents, request_url,
                                                  safe_url, domain, prefs));
}

LookalikeBlockingPage::LookalikeBlockingPage(
    content::WebContents* web_contents,
    const GURL& request_url,
    const GURL& safe_url,
    bool no_bypass,
    std::unique_ptr<
        security_interstitials::SecurityInterstitialControllerClient>
        controller)
    : security_interstitials::SecurityInterstitialPage(web_contents,
                                                       request_url,
                                                       std::move(controller)),
      safe_url_(safe_url),
      no_bypass_(no_bypass) {}

LookalikeBlockingPage::~LookalikeBlockingPage() = default;

std::string LookalikeBlockingPage::GetHTMLContents() {
  WarningText text;
  text.title = "Address looks like another site";
  text.eyebrow = "Look-alike address";
  text.address = std::string(request_url().host());
  text.no_bypass =
      "No way past scam warnings is on. This site cannot be opened from "
      "this warning.";
  if (safe_url_.is_valid()) {
    const std::string real(safe_url_.host());
    text.heading = "This is not " + real + ".";
    text.what = "This site's name looks like " + real +
                ", but it is a different site. Scammers copy names like this "
                "to get logins and payments.";
    text.main_button = "Go to " + real;
    text.why = "Its name is built to look like " + real +
               ". If you know this site, you can continue.";
  } else {
    text.heading = "This address may be copying another site.";
    text.what =
        "This site's name mixes letters from other alphabets so that it can "
        "pass for another site.";
    text.main_button = "Go back to safety";
    text.why =
        "Real sites rarely mix letters this way. If you know this site, "
        "you can continue.";
  }
  return BuildWarningPage(web_contents(), text, !no_bypass_);
}

void LookalikeBlockingPage::OnInterstitialClosing() {}

void LookalikeBlockingPage::CommandReceived(const std::string& command) {
  int command_id = 0;
  if (!base::StringToInt(command, &command_id)) {
    return;
  }
  if (command_id == security_interstitials::CMD_PROCEED && !no_bypass_) {
    controller()->Proceed();
    return;
  }
  if (command_id == security_interstitials::CMD_DONT_PROCEED) {
    controller()->GoBack();
  }
}

security_interstitials::SecurityInterstitialPage::TypeID
LookalikeBlockingPage::GetTypeForTesting() {
  return kTypeForTesting;
}

void LookalikeBlockingPage::PopulateInterstitialStrings(
    base::DictValue& load_time_data) {}

}  // namespace boring
