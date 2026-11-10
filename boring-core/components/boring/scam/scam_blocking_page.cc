// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/scam_blocking_page.h"

#include <utility>

#include "base/strings/string_number_conversions.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/scam/scam_controller_client.h"
#include "components/boring/scam/warning_page.h"
#include "components/prefs/pref_service.h"
#include "components/security_interstitials/core/controller_client.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/web_contents.h"

namespace boring {

// static
const security_interstitials::SecurityInterstitialPage::TypeID
    ScamBlockingPage::kTypeForTesting = &ScamBlockingPage::kTypeForTesting;

// static
std::unique_ptr<ScamBlockingPage> ScamBlockingPage::Create(
    content::WebContents* web_contents,
    const GURL& request_url) {
  PrefService* prefs =
      user_prefs::UserPrefs::Get(web_contents->GetBrowserContext());
  const bool no_bypass = prefs && prefs->GetBoolean(prefs::kNoScamBypass);
  return std::make_unique<ScamBlockingPage>(
      web_contents, request_url, no_bypass,
      std::make_unique<ScamControllerClient>(web_contents, request_url, prefs));
}

// static
std::unique_ptr<ScamBlockingPage> ScamBlockingPage::CreateForQuad9Block(
    content::WebContents* web_contents,
    const GURL& request_url) {
  PrefService* prefs =
      user_prefs::UserPrefs::Get(web_contents->GetBrowserContext());
  // No way past it, whatever "No way past scam warnings" says: the site
  // was never looked up, so there is nothing to continue to.
  return std::make_unique<ScamBlockingPage>(
      web_contents, request_url, /*no_bypass=*/true,
      std::make_unique<ScamControllerClient>(web_contents, request_url, prefs),
      /*quad9_block=*/true);
}

ScamBlockingPage::ScamBlockingPage(
    content::WebContents* web_contents,
    const GURL& request_url,
    bool no_bypass,
    std::unique_ptr<
        security_interstitials::SecurityInterstitialControllerClient>
        controller,
    bool quad9_block)
    : security_interstitials::SecurityInterstitialPage(web_contents,
                                                       request_url,
                                                       std::move(controller)),
      no_bypass_(no_bypass),
      quad9_block_(quad9_block) {}

ScamBlockingPage::~ScamBlockingPage() = default;

std::string ScamBlockingPage::GetHTMLContents() {
  WarningText text;
  text.title = "Site blocked";
  text.eyebrow = "Site blocked";
  text.address = std::string(request_url().host());
  text.main_button = "Go back to safety";
  if (quad9_block_) {
    text.heading = "This site is on a list of dangerous sites.";
    text.what =
        "Quad9, the secure DNS service this browser uses, lists this site "
        "as dangerous. It was not opened.";
    text.no_bypass = "This site cannot be opened from this warning.";
    return BuildWarningPage(web_contents(), text, /*may_continue=*/false);
  }
  text.heading = "This site may be a scam.";
  text.what =
      "This address is on a list of known scam sites. Sites like it try to "
      "get your passwords or money.";
  text.why =
      "Its address matched the list on this computer. Lists can be wrong.";
  text.no_bypass =
      "No way past scam warnings is on. This site cannot be opened from "
      "this warning.";
  return BuildWarningPage(web_contents(), text, !no_bypass_);
}

void ScamBlockingPage::OnInterstitialClosing() {}

void ScamBlockingPage::CommandReceived(const std::string& command) {
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
ScamBlockingPage::GetTypeForTesting() {
  return kTypeForTesting;
}

void ScamBlockingPage::PopulateInterstitialStrings(
    base::DictValue& load_time_data) {}

}  // namespace boring
