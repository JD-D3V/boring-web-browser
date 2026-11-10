// Copyright 2026 boring. BSD style license.

#include "components/boring/scam/takeover/takeover_ui.h"

#include <memory>
#include <string>

#include "base/functional/bind.h"
#include "base/memory/ref_counted_memory.h"
#include "base/values.h"
#include "components/boring/scam/takeover/takeover_tab_helper.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_data_source.h"
#include "content/public/browser/web_ui_message_handler.h"
#include "content/public/common/url_constants.h"

namespace boring {

namespace {

// Calm on purpose, big text, one button. Shares its colours with the
// scam warning page.
constexpr char kPage[] = R"PAGE(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Your computer is fine</title>
<style>
  :root { color-scheme: light dark;
    --surface: light-dark(#faf9f6, #1c2422);
    --paper: light-dark(#ffffff, #252e2b);
    --ink: light-dark(#242e2d, #e8ede7);
    --muted: light-dark(#5d6966, #adb9b2);
    --line: light-dark(#d8ddd7, #414e47);
    --accent: light-dark(#4f46e5, #9d9aff);
  }
  * { box-sizing: border-box; }
  body { background: var(--surface); color: var(--ink);
         font: 16px/1.6 "Segoe UI", system-ui, sans-serif; margin: 0;
         display: flex; min-height: 100vh; align-items: center;
         justify-content: center; }
  main { max-width: 640px; width: 100%; padding: 30px; }
  h1 { font-size: 40px; letter-spacing: -0.04em; font-weight: 550;
       line-height: 1.1; margin: 0 0 0.5em; }
  p { color: var(--muted); font-size: 18px; margin: 0 0 1em; }
  p.strong { color: var(--ink); font-weight: 600; }
  .site { font-size: 14px; padding: 12px 16px; border: 1px solid var(--line);
          border-radius: 8px; background: var(--paper); color: var(--ink);
          overflow-wrap: anywhere; margin: 0 0 1.5em; }
  button { display: block; width: 100%; min-height: 72px; padding: 16px 24px;
           border: none; border-radius: 12px; cursor: pointer;
           font: inherit; font-size: 24px; font-weight: 650;
           background: var(--accent);
           color: light-dark(#ffffff, #1b1a4a);
           transition: transform 150ms ease-out; }
  button:active { transform: scale(0.98); }
  :focus-visible { outline: 3px solid var(--ink); outline-offset: 3px; }
  @media (prefers-reduced-motion: reduce) {
    button { transition: none; } button:active { transform: none; } }
  @media (forced-colors: active) {
    button { border: 2px solid ButtonText; } }
</style>
</head>
<body>
<main>
<h1>Your computer is fine.</h1>
<p>The page you were on was trying to scare you. It is a scam. Nothing was
installed and nothing is broken.</p>
<p class="strong">Do not call any phone number it showed you.</p>
<div class="site" id="site" hidden></div>
<button type="button" id="close" autofocus>Close this tab</button>
</main>
<script src="takeover.js"></script>
</body>
</html>
)PAGE";

constexpr char kScript[] = R"SCRIPT(
var site = new URLSearchParams(location.search).get('site');
// Shown only when it is a host name or an address, so a typed-in address
// cannot put its own words under the heading.
var isHost = /^[a-z0-9.-]+$|^\[[0-9a-f:.]+\]$/i;
if (site && site.length <= 253 && isHost.test(site)) {
  var el = document.getElementById('site');
  el.textContent = 'The page was on ' + site;
  el.hidden = false;
}
document.getElementById('close').addEventListener('click', function() {
  chrome.send('closeTab');
});
)SCRIPT";

class TakeoverMessageHandler : public content::WebUIMessageHandler {
 public:
  TakeoverMessageHandler() = default;
  ~TakeoverMessageHandler() override = default;

  void RegisterMessages() override {
    web_ui()->RegisterMessageCallback(
        "closeTab", base::BindRepeating(&TakeoverMessageHandler::HandleClose,
                                        base::Unretained(this)));
  }

 private:
  // The page is ours and has no leave-page prompt, so this closes the
  // tab at once.
  void HandleClose(const base::ListValue& args) {
    web_ui()->GetWebContents()->Close();
  }
};

// The data source hands the filter the path with its query still on, and
// the tab helper opens chrome://boring-takeover/?site=..., so cut it off.
std::string PathOnly(const std::string& path) {
  return path.substr(0, path.find_first_of("?#"));
}

bool ShouldHandle(const std::string& path) {
  std::string only = PathOnly(path);
  return only.empty() || only == "takeover.js";
}

void Handle(const std::string& path,
            content::WebUIDataSource::GotDataCallback callback) {
  std::string body = PathOnly(path) == "takeover.js" ? kScript : kPage;
  std::move(callback).Run(
      base::MakeRefCounted<base::RefCountedString>(std::move(body)));
}

}  // namespace

BoringTakeoverUI::BoringTakeoverUI(content::WebUI* web_ui)
    : content::WebUIController(web_ui) {
  content::WebUIDataSource* source = content::WebUIDataSource::CreateAndAdd(
      web_ui->GetWebContents()->GetBrowserContext(), kBoringTakeoverHost);
  source->SetRequestFilter(base::BindRepeating(&ShouldHandle),
                           base::BindRepeating(&Handle));
  web_ui->AddMessageHandler(std::make_unique<TakeoverMessageHandler>());
}

BoringTakeoverUI::~BoringTakeoverUI() = default;

BoringTakeoverUIConfig::BoringTakeoverUIConfig()
    : content::DefaultWebUIConfig<BoringTakeoverUI>(content::kChromeUIScheme,
                                                    kBoringTakeoverHost) {}

}  // namespace boring
