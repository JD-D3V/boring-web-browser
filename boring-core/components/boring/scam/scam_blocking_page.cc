// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/scam_blocking_page.h"

#include <utility>

#include "base/strings/escape.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/strcat.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/scam/scam_controller_client.h"
#include "components/security_interstitials/core/controller_client.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/web_contents.h"

namespace boring {

namespace {

// The page is written directly here, in plain language, with big text.
// A design pass comes later; this stays calm and readable on purpose.
constexpr char kPageTop[] = R"(<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Warning: this site looks dangerous</title>
<style>
  body { background: #fef7f7; color: #202124; font-family: system-ui, sans-serif;
         margin: 0; display: flex; min-height: 100vh; align-items: center;
         justify-content: center; }
  .card { max-width: 40em; padding: 2.5em; }
  h1 { font-size: 1.9em; margin: 0.5em 0; }
  p { font-size: 1.15em; line-height: 1.6; }
  .host { font-weight: bold; word-break: break-all; }
  .safe { display: inline-block; background: #1a73e8; color: #fff;
          border: none; border-radius: 8px; font-size: 1.2em;
          padding: 0.8em 1.6em; cursor: pointer; margin-top: 1em; }
  .safe:hover { background: #1765c9; }
  .continue { display: block; margin-top: 2.5em; font-size: 0.9em;
              color: #5f6368; }
  .continue a { color: #5f6368; }
  .icon { font-size: 3em; }
</style>
</head>
<body>
<div class="card">
<div class="icon">&#9888;&#65039;</div>
<h1>This site looks dangerous</h1>
)";

constexpr char kPageBottom[] = R"(
<button class="safe" onclick="goBack()">Go back to safety</button>
%CONTINUE%
</div>
<script>
function goBack() {
  if (window.certificateErrorPageController) {
    certificateErrorPageController.dontProceed();
  } else {
    history.back();
  }
}
function proceedAnyway() {
  if (window.certificateErrorPageController) {
    certificateErrorPageController.proceed();
  }
  return false;
}
</script>
</body>
</html>
)";

constexpr char kContinueLink[] =
    "<span class=\"continue\">If you are certain this site is safe, you can "
    "<a href=\"#\" onclick=\"return proceedAnyway()\">continue anyway</a>."
    "</span>";

}  // namespace

// static
const security_interstitials::SecurityInterstitialPage::TypeID
    ScamBlockingPage::kTypeForTesting = &ScamBlockingPage::kTypeForTesting;

// static
std::unique_ptr<ScamBlockingPage> ScamBlockingPage::Create(
    content::WebContents* web_contents,
    const GURL& request_url) {
  PrefService* prefs =
      user_prefs::UserPrefs::Get(web_contents->GetBrowserContext());
  bool senior = IsSeniorSafeMode(prefs);
  return std::make_unique<ScamBlockingPage>(
      web_contents, request_url, senior,
      std::make_unique<ScamControllerClient>(web_contents, request_url,
                                             prefs));
}

ScamBlockingPage::ScamBlockingPage(
    content::WebContents* web_contents,
    const GURL& request_url,
    bool senior_safe_mode,
    std::unique_ptr<
        security_interstitials::SecurityInterstitialControllerClient>
        controller)
    : security_interstitials::SecurityInterstitialPage(web_contents,
                                                       request_url,
                                                       std::move(controller)),
      senior_safe_mode_(senior_safe_mode) {}

ScamBlockingPage::~ScamBlockingPage() = default;

std::string ScamBlockingPage::GetHTMLContents() {
  std::string host = base::EscapeForHTML(request_url().host());
  std::string body = base::StrCat(
      {"<p>The site <span class=\"host\">", host,
       "</span> is on a list of known scam or phishing sites. Criminals "
       "build sites like this to steal passwords, card numbers, or "
       "money.</p><p>It is safest to leave now.</p>"});
  std::string bottom(kPageBottom);
  std::string marker = "%CONTINUE%";
  std::string link = senior_safe_mode_ ? "" : kContinueLink;
  size_t pos = bottom.find(marker);
  if (pos != std::string::npos) {
    bottom.replace(pos, marker.size(), link);
  }
  return base::StrCat({kPageTop, body, bottom});
}

void ScamBlockingPage::OnInterstitialClosing() {}

void ScamBlockingPage::CommandReceived(const std::string& command) {
  int cmd = 0;
  if (!base::StringToInt(command, &cmd)) {
    return;
  }
  if (cmd == security_interstitials::CMD_PROCEED && !senior_safe_mode_) {
    controller()->Proceed();
    return;
  }
  if (cmd == security_interstitials::CMD_DONT_PROCEED) {
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
