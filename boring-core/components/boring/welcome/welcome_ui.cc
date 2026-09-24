// Copyright 2026 boring. BSD style license.

#include "components/boring/welcome/welcome_ui.h"

#include <memory>
#include <optional>
#include <string>

#include "base/functional/bind.h"
#include "base/memory/ref_counted_memory.h"
#include "base/memory/weak_ptr.h"
#include "base/task/thread_pool.h"
#include "base/values.h"
#include "components/boring/branding/brand_mark.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/importer/chromium_profiles.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_data_source.h"
#include "content/public/browser/web_ui_message_handler.h"
#include "content/public/common/url_constants.h"

namespace boring {

namespace {

constexpr char kPage[] = R"PAGE(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Welcome to Boring Browser</title>
<link rel="icon" type="image/svg+xml" href="brand.svg">
<style>
  :root { color-scheme: light dark;
    --surface: light-dark(#faf9f6, #1c2422);
    --paper: light-dark(#ffffff, #252e2b);
    --ink: light-dark(#242e2d, #e8ede7);
    --muted: light-dark(#5d6966, #adb9b2);
    --line: light-dark(#d8ddd7, #414e47);
    --accent: light-dark(#176b5b, #92d4bb);
    --soft: light-dark(#e5f1eb, #273f35);
  }
  * { box-sizing: border-box; }
  body { font: 14px/1.6 "Segoe UI", system-ui, sans-serif; margin: 0;
         background: var(--surface); color: var(--ink);
         padding: 4em 1.5em; display: flex; justify-content: center; }
  .page { width: 40em; max-width: 100%; }
  .brand { display: block; width: 44px; height: 44px; margin: 0 0 24px; }
  h1 { font-size: 2.3em; letter-spacing: -0.045em; font-weight: 550;
       line-height: 1.1; margin: 0 0 1em; }
  .panel { background: var(--paper); border: 1px solid var(--line);
           border-radius: 12px; padding: 1.3em 1.5em; margin: 0 0 1.2em; }
  .row { display: flex; align-items: center; justify-content: space-between;
         gap: 1em; }
  .primary, .secondary { min-height: 40px; padding: 10px 18px;
                          border-radius: 7px; font-weight: 600;
                          font-size: 13px; border: none; cursor: pointer;
                          font-family: inherit; }
  .primary { background: var(--accent); color: var(--surface); }
  .primary:hover { filter: brightness(0.92); }
  .secondary { border: 1px solid var(--line); background: var(--paper);
               color: var(--ink); }
  .secondary:hover { background: var(--soft); }
  .done { color: var(--accent); font-weight: 600; font-size: 13px;
          margin: 0; }
  a { color: var(--accent); font-weight: 600; font-size: 13px;
      text-underline-offset: 3px; }
  .links { display: grid; gap: 0.7em; }
  .links button { justify-self: start; }
  .start { margin-top: 1.5em; display: flex; justify-content: flex-end; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .hidden { display: none; }
  @media (forced-colors: active) {
    button, .panel { border: 1px solid ButtonText; }
    .primary { background: Highlight; color: HighlightText; }
  }
</style>
</head>
<body>
<main class="page">
  <img class="brand" src="brand.svg" width="44" height="44" alt=""
      aria-hidden="true">
  <h1>Welcome to Boring Browser</h1>

  <div class="panel links">
    <button class="secondary hidden" id="import-chromium">Import from Chrome
    or Edge</button>
    <a id="import-other" href="chrome://settings/importData">Import bookmarks
    and passwords</a>
    <a href="chrome://settings/defaultBrowser">Make Boring Browser your
    default browser</a>
  </div>

  <div class="panel">
    <div id="senior-off" class="row">
      <strong>Senior Safe Mode</strong>
      <button class="secondary" id="senior-on">Turn on</button>
    </div>
    <p id="senior-done" class="done hidden" tabindex="-1">Senior Safe Mode
    is on.</p>
  </div>

  <div class="start">
    <button class="primary" id="start">Start browsing</button>
  </div>
</main>
<script src="welcome.js"></script>
</body>
</html>
)PAGE";

constexpr char kScript[] = R"SCRIPT(
function el(id) { return document.getElementById(id); }

function show(senior) {
  el('senior-off').classList.toggle('hidden', senior);
  el('senior-done').classList.toggle('hidden', !senior);
}

el('senior-on').addEventListener('click', function() {
  chrome.send('turnOnSeniorSafeMode');
});

el('start').addEventListener('click', function() {
  location.href = 'chrome://newtab';
});

el('import-chromium').addEventListener('click', function() {
  location.href = 'chrome://settings/importData';
});

window.loadWelcome = function(state) {
  var wasOff = !el('senior-off').classList.contains('hidden');
  show(state.senior);
  // Chrome or Edge is on this computer: offer it by name, in place of
  // the general link, which opens the same dialog.
  el('import-chromium').classList.toggle('hidden', !state.chromium);
  el('import-other').classList.toggle('hidden', state.chromium);
  // The button that had focus is gone, so say what happened in its place.
  if (state.senior && wasOff && document.activeElement === document.body) {
    el('senior-done').focus();
  }
};
chrome.send('getWelcome');
)SCRIPT";

class WelcomeMessageHandler : public content::WebUIMessageHandler {
 public:
  WelcomeMessageHandler() = default;
  ~WelcomeMessageHandler() override = default;

  void RegisterMessages() override {
    web_ui()->RegisterMessageCallback(
        "getWelcome", base::BindRepeating(&WelcomeMessageHandler::HandleGet,
                                          base::Unretained(this)));
    // Only ever turns Senior Safe Mode on. Turning it off lives on the
    // Protection page, behind its warning.
    web_ui()->RegisterMessageCallback(
        "turnOnSeniorSafeMode",
        base::BindRepeating(&WelcomeMessageHandler::HandleTurnOn,
                            base::Unretained(this)));
  }

 private:
  PrefService* GetPrefs() {
    return user_prefs::UserPrefs::Get(
        web_ui()->GetWebContents()->GetBrowserContext());
  }

  void HandleGet(const base::ListValue& args) {
    AllowJavascript();
    Send();
    if (chromium_.has_value() || detecting_) {
      return;
    }
    // Looking for Chrome and Edge reads the disk, so it happens off the
    // UI thread and the page hears again when it is done.
    detecting_ = true;
    base::ThreadPool::PostTaskAndReplyWithResult(
        FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_VISIBLE},
        base::BindOnce(&HasChromiumProfiles),
        base::BindOnce(&WelcomeMessageHandler::OnDetected,
                       weak_factory_.GetWeakPtr()));
  }

  void OnDetected(bool found) {
    detecting_ = false;
    chromium_ = found;
    if (IsJavascriptAllowed()) {
      Send();
    }
  }

  void Send() {
    base::DictValue out;
    out.Set("senior", IsSeniorSafeMode(GetPrefs()));
    out.Set("chromium", chromium_.value_or(false));
    web_ui()->CallJavascriptFunctionUnsafe("loadWelcome", out);
  }

  void OnJavascriptDisallowed() override {
    weak_factory_.InvalidateWeakPtrs();
    detecting_ = false;
  }

  void HandleTurnOn(const base::ListValue& args) {
    if (PrefService* prefs = GetPrefs()) {
      prefs->SetBoolean(prefs::kSeniorSafeMode, true);
    }
    HandleGet(args);
  }

  // Whether a Chrome or Edge profile was found, once it is known.
  std::optional<bool> chromium_;
  bool detecting_ = false;
  base::WeakPtrFactory<WelcomeMessageHandler> weak_factory_{this};
};

bool ShouldHandle(const std::string& path) {
  return path.empty() || path == "welcome.js" || path == "brand.svg";
}

void Handle(const std::string& path,
            content::WebUIDataSource::GotDataCallback callback) {
  // brand.svg is the tab icon and the mark above the heading. Its type
  // comes from the .svg ending (WebUIDataSourceImpl::GetMimeType).
  std::string body;
  if (path == "welcome.js") {
    body = kScript;
  } else if (path == "brand.svg") {
    body = branding::kBrandTileSvg;
  } else {
    body = kPage;
  }
  std::move(callback).Run(
      base::MakeRefCounted<base::RefCountedString>(std::move(body)));
}

}  // namespace

BoringWelcomeUI::BoringWelcomeUI(content::WebUI* web_ui)
    : content::WebUIController(web_ui) {
  content::WebUIDataSource* source = content::WebUIDataSource::CreateAndAdd(
      web_ui->GetWebContents()->GetBrowserContext(), kBoringWelcomeHost);
  source->SetRequestFilter(base::BindRepeating(&ShouldHandle),
                           base::BindRepeating(&Handle));
  web_ui->AddMessageHandler(std::make_unique<WelcomeMessageHandler>());
}

BoringWelcomeUI::~BoringWelcomeUI() = default;

BoringWelcomeUIConfig::BoringWelcomeUIConfig()
    : content::DefaultWebUIConfig<BoringWelcomeUI>(content::kChromeUIScheme,
                                                   kBoringWelcomeHost) {}

}  // namespace boring
