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
#include "third_party/skia/include/core/SkColor.h"
#include "ui/color/color_id.h"
#include "ui/color/color_provider.h"
#include "ui/gfx/color_utils.h"

namespace boring {

namespace {

// The page is written directly here, in plain language, with big text.
// It stays calm on purpose, and takes its colours from the window's own
// palette (see ColourVariables).
constexpr char kPageTop[] = R"HTML(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Warning: this site looks dangerous</title>
<style>
  %COLOURS%
  * { box-sizing: border-box; }
  body { background: var(--paper); color: var(--ink);
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
          border-radius: 8px; background: var(--chip); color: var(--ink);
          font-weight: 600; overflow-wrap: anywhere; margin: 0 0 1.2em; }
  .actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }
  .primary { min-height: 40px; padding: 10px 18px; border-radius: 7px;
             font-weight: 600; font-size: 13px; border: none;
             cursor: pointer; font-family: inherit;
             background: var(--accent); color: var(--on-accent); }
  .text-button { background: none; border: none; color: var(--accent);
                 font-weight: 600; padding: 8px 0; text-align: left;
                 font-size: 13px; cursor: pointer; font-family: inherit; }
  /* Press and hover: colour and a small scale only, so input never waits. */
  .primary, .text-button {
    transition: background-color 150ms ease-out, color 150ms ease-out,
                border-color 150ms ease-out, transform 150ms ease-out; }
  .primary:active { transform: scale(0.98); }
  .text-button:active { transform: scale(0.98); }
  @media (hover: hover) {
    .primary:hover { background: color-mix(in srgb, var(--accent) 86%, var(--ink)); }
    .text-button:hover { text-decoration: underline; text-underline-offset: 3px; }
  }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  details { margin-top: 28px; font-size: 12px; color: var(--muted); }
  summary { cursor: pointer; }
  .panel-note { font-size: 12px; color: var(--muted); margin-top: 28px; }
  @media (prefers-reduced-motion: reduce) {
    .primary, .text-button { transition: none; }
    .primary:active, .text-button:active { transform: none; }
  }
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

constexpr char kNoWayPastNote[] =
    "<p class=\"panel-note\">\"No way past scam warnings\" is on, so this "
    "site cannot be opened from here.</p>";

// The page is not a chrome:// page, so it cannot load the theme's
// colors.css the way the Protection page does. The colours are read from
// the tab's own colour provider when the page is built instead, which is
// the same palette the window is using: Cool, Beige or Green, light or
// dark. Dark is told from the page colour itself, not from a setting, so
// it cannot disagree with what the provider handed back.
std::string ColourVariables(content::WebContents* contents) {
  const ui::ColorProvider& colours = contents->GetColorProvider();
  const SkColor paper = colours.GetColor(ui::kColorDialogBackground);
  const bool dark = color_utils::IsDark(paper);
  const auto rgb = [&colours](ui::ColorId id) {
    return color_utils::SkColorToRgbString(colours.GetColor(id));
  };
  return base::StrCat(
      {":root { color-scheme: ", dark ? "dark" : "light", ";\n",
       "    --paper: rgb(", color_utils::SkColorToRgbString(paper), ");\n",
       "    --ink: rgb(", rgb(ui::kColorDialogForeground), ");\n",
       "    --muted: rgb(", rgb(ui::kColorLabelForegroundSecondary), ");\n",
       "    --line: rgb(", rgb(ui::kColorBubbleBorder), ");\n",
       "    --accent: rgb(", rgb(ui::kColorSysPrimary), ");\n",
       "    --on-accent: rgb(", rgb(ui::kColorSysOnPrimary), ");\n",
       "    --chip: color-mix(in srgb, var(--ink) 6%, var(--paper));\n",
       "    --warning: ", dark ? "#ffb69c" : "#9e3e24", ";\n",
       "    --warning-soft: ", dark ? "#412f28" : "#fbebe4", ";\n",
       "  }"});
}

void ReplaceFirst(std::string& text,
                  const std::string& marker,
                  const std::string& with) {
  const size_t pos = text.find(marker);
  if (pos != std::string::npos) {
    text.replace(pos, marker.size(), with);
  }
}

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
  // "No way past scam warnings" is, for now, what Senior Safe Mode
  // switches on. The switches branch maps it to its own pref; this is
  // the one line that changes.
  const bool no_way_past = IsSeniorSafeMode(prefs);
  return std::make_unique<ScamBlockingPage>(
      web_contents, request_url, no_way_past,
      std::make_unique<ScamControllerClient>(web_contents, request_url, prefs));
}

ScamBlockingPage::ScamBlockingPage(
    content::WebContents* web_contents,
    const GURL& request_url,
    bool no_way_past,
    std::unique_ptr<
        security_interstitials::SecurityInterstitialControllerClient>
        controller)
    : security_interstitials::SecurityInterstitialPage(web_contents,
                                                       request_url,
                                                       std::move(controller)),
      no_way_past_(no_way_past) {}

ScamBlockingPage::~ScamBlockingPage() = default;

std::string ScamBlockingPage::GetHTMLContents() {
  std::string host = base::EscapeForHTML(request_url().host());
  std::string body = base::StrCat(
      {"<p>The address is on a list of known scam or phishing sites. It "
       "may try to steal your passwords, payment details, or money.</p>"
       "<div class=\"host\">",
       host, "</div>"});
  std::string top(kPageTop);
  ReplaceFirst(top, "%COLOURS%", ColourVariables(web_contents()));
  std::string bottom(kPageBottom);
  ReplaceFirst(bottom, "%CONTINUE%",
               no_way_past_ ? kNoWayPastNote : kContinueLink);
  return base::StrCat({top, body, bottom});
}

void ScamBlockingPage::OnInterstitialClosing() {}

void ScamBlockingPage::CommandReceived(const std::string& command) {
  int command_id = 0;
  if (!base::StringToInt(command, &command_id)) {
    return;
  }
  if (command_id == security_interstitials::CMD_PROCEED && !no_way_past_) {
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
