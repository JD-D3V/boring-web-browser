// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/scam_blocking_page.h"

#include <utility>

#include "base/strings/escape.h"
#include "base/strings/strcat.h"
#include "base/strings/string_number_conversions.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/scam/scam_controller_client.h"
#include "components/security_interstitials/core/controller_client.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/web_contents.h"

namespace boring {

namespace {

// The page is written directly here, in plain language, with big text.
// It stays calm on purpose, and shares its colours with the AI and
// protection pages.
constexpr char kPageTop[] = R"HTML(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Warning: this site looks dangerous</title>
<style>
  :root { color-scheme: light dark;
    --surface: light-dark(#faf9f6, #1c2422);
    --paper: light-dark(#ffffff, #252e2b);
    --ink: light-dark(#242e2d, #e8ede7);
    --muted: light-dark(#5d6966, #adb9b2);
    --line: light-dark(#d8ddd7, #414e47);
    --accent: light-dark(#176b5b, #92d4bb);
    --warning: light-dark(#9e3e24, #ffb69c);
    --warning-soft: light-dark(#fbebe4, #412f28);
  }
  * { box-sizing: border-box; }
  body { background: var(--surface); color: var(--ink);
         font: 14px/1.6 "Segoe UI", system-ui, sans-serif;
         margin: 0; display: flex; min-height: 100vh; align-items: center;
         justify-content: center; }
  .warning-page { max-width: 640px; width: 100%; margin: 65px auto;
                  padding: 0 30px 35px; }
  .warning-symbol { display: grid; place-items: center; font-size: 24px;
                    color: var(--warning); background: var(--warning-soft);
                    width: 52px; height: 52px; border-radius: 15px;
                    margin-bottom: 26px; }
  .eyebrow { text-transform: uppercase; letter-spacing: 0.16em;
             font-size: 10px; font-weight: 650; color: var(--warning);
             margin-bottom: 10px; }
  h1 { font-size: 38px; letter-spacing: -0.045em; font-weight: 550;
       line-height: 1.1; margin: 0 0 0.4em; }
  p { color: var(--muted); font-size: 14px; line-height: 1.65;
      margin: 0 0 1em; }
  .host { font-size: 14px; padding: 14px 18px; border: 1px solid var(--line);
          border-radius: 8px; background: var(--paper); color: var(--ink);
          font-weight: 600; overflow-wrap: anywhere; margin: 0 0 1.2em; }
  .actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }
  .primary { min-height: 40px; padding: 10px 18px; border-radius: 7px;
             font-weight: 600; font-size: 13px; border: none;
             cursor: pointer; font-family: inherit;
             background: var(--accent); color: var(--surface); }
  .primary:hover { filter: brightness(0.92); }
  .text-button { background: none; border: none; color: var(--accent);
                 font-weight: 600; padding: 8px 0; text-align: left;
                 font-size: 13px; cursor: pointer; font-family: inherit; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  details { margin-top: 28px; font-size: 12px; color: var(--muted); }
  summary { cursor: pointer; }
  .panel-note { font-size: 12px; color: var(--muted); margin-top: 28px; }
  @media (max-width: 480px) { .warning-page { padding: 0 22px 22px; } }
  @media (forced-colors: active) {
    button { border: 1px solid ButtonText; }
    .primary { background: Highlight; color: HighlightText; }
  }
</style>
</head>
<body>
<div class="warning-page">
<div class="warning-symbol" aria-hidden="true">!</div>
<div class="eyebrow">Site blocked</div>
<h1>This site looks dangerous.</h1>
)HTML";

constexpr char kPageBottom[] = R"HTML(
<div class="actions">
<button class="primary" onclick="goBack()">Go back to safety</button>
</div>
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
)HTML";

constexpr char kContinueLink[] =
    "<details><summary>Why was this blocked?</summary>"
    "<p>Its address matched the local blocklist. Lists can make "
    "mistakes.</p>"
    "<button type=\"button\" class=\"text-button\" "
    "onclick=\"return proceedAnyway()\">Continue anyway</button></details>";

constexpr char kSeniorNote[] =
    "<p class=\"panel-note\">Senior Safe Mode is on. This site cannot be "
    "opened from this warning.</p>";

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
      std::make_unique<ScamControllerClient>(web_contents, request_url, prefs));
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
      {"<p>The address is on a list of known scam or phishing sites. It "
       "may try to steal your passwords, payment details, or money.</p>"
       "<div class=\"host\">",
       host, "</div>"});
  std::string bottom(kPageBottom);
  std::string marker = "%CONTINUE%";
  std::string link = senior_safe_mode_ ? kSeniorNote : kContinueLink;
  size_t marker_pos = bottom.find(marker);
  if (marker_pos != std::string::npos) {
    bottom.replace(marker_pos, marker.size(), link);
  }
  return base::StrCat({kPageTop, body, bottom});
}

void ScamBlockingPage::OnInterstitialClosing() {}

void ScamBlockingPage::CommandReceived(const std::string& command) {
  int command_id = 0;
  if (!base::StringToInt(command, &command_id)) {
    return;
  }
  if (command_id == security_interstitials::CMD_PROCEED && !senior_safe_mode_) {
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
