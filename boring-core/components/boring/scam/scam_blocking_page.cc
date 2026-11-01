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

ScamBlockingPage::ScamBlockingPage(
    content::WebContents* web_contents,
    const GURL& request_url,
    bool no_bypass,
    std::unique_ptr<
        security_interstitials::SecurityInterstitialControllerClient>
        controller)
    : security_interstitials::SecurityInterstitialPage(web_contents,
                                                       request_url,
                                                       std::move(controller)),
      no_bypass_(no_bypass) {}

ScamBlockingPage::~ScamBlockingPage() = default;

std::string ScamBlockingPage::GetHTMLContents() {
  WarningText text;
  text.title = "Warning: this site looks dangerous";
  text.eyebrow = "Site blocked";
  text.heading = "This site looks dangerous.";
  text.what =
      "The address is on a list of known scam or phishing sites. It may try "
      "to steal your passwords, payment details, or money.";
  text.address = std::string(request_url().host());
  text.main_button = "Go back to safety";
  text.why =
      "Its address matched the local blocklist. Lists can make mistakes.";
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
