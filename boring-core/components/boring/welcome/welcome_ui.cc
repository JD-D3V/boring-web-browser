// Copyright 2026 boring. BSD style license.

#include "components/boring/welcome/welcome_ui.h"

#include <memory>
#include <string>

#include "base/functional/bind.h"
#include "base/memory/ref_counted_memory.h"
#include "base/values.h"
#include "components/boring/core/boring_prefs.h"
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
<title>Welcome</title>
<style>
  :root { color-scheme: light dark;
    --surface: light-dark(#faf9f6, #1c2422);
    --paper: light-dark(#ffffff, #252e2b);
    --ink: light-dark(#242e2d, #e8ede7);
    --muted: light-dark(#5d6966, #adb9b2);
    --line: light-dark(#d8ddd7, #414e47);
    --field: light-dark(#7d8783, #83908a);
    --accent: light-dark(#176b5b, #92d4bb);
    --soft: light-dark(#e5f1eb, #273f35);
  }
  * { box-sizing: border-box; }
  body { font: 16px/1.6 system-ui, sans-serif; margin: 0;
         background: var(--surface); color: var(--ink);
         padding: 4em 1.5em; display: flex; justify-content: center; }
  .page { width: 38em; max-width: 100%; }
  h1 { font-size: 2em; line-height: 1.2; margin: 0 0 0.3em; }
  .lede { color: var(--muted); font-size: 1.1em; margin: 0 0 2em; }
  section { background: var(--paper); border: 1px solid var(--line);
            border-radius: 12px; padding: 1.3em 1.5em; margin: 0 0 1.2em; }
  h2 { font-size: 1.1em; margin: 0 0 0.6em; }
  ul { list-style: none; margin: 0; padding: 0; }
  li { padding: 0.35em 0 0.35em 1.8em; position: relative; }
  li::before { content: ""; position: absolute; left: 0.2em; top: 0.85em;
               width: 0.8em; height: 0.45em; border: solid var(--accent);
               border-width: 0 0 2.5px 2.5px; transform: rotate(-45deg); }
  .why { color: var(--muted); margin: 0 0 1em; }
  button { background: var(--accent); border: none; border-radius: 8px;
           color: var(--surface); cursor: pointer; font: inherit;
           padding: 0.7em 1.5em; }
  button:hover { filter: brightness(0.94); }
  button.no { background: transparent; border: 1px solid var(--field);
              color: inherit; }
  .done { color: var(--accent); font-weight: 600; margin: 0; }
  a { color: var(--accent); text-underline-offset: 3px; }
  .links { display: grid; gap: 0.4em; }
  .start { margin-top: 2em; display: flex; justify-content: flex-end; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
  .hidden { display: none; }
  @media (forced-colors: active) {
    button, section { border: 1px solid ButtonText; }
  }
</style>
</head>
<body>
<main class="page">
  <h1>Welcome. You are set up.</h1>
  <p class="lede">There is nothing to sign in to and nothing to agree to.
  The browser is already protecting you.</p>

  <section aria-labelledby="on-heading">
    <h2 id="on-heading">Already on</h2>
    <ul>
      <li>Known scam and phishing sites are stopped before they open.</li>
      <li>Ads and trackers are blocked.</li>
      <li>Searches in the address bar go to DuckDuckGo, which does not
      track you.</li>
      <li>The pages you visit are checked on this computer. They are not
      sent anywhere to be checked.</li>
    </ul>
  </section>

  <section aria-labelledby="senior-heading">
    <h2 id="senior-heading">Setting this up for someone else?</h2>
    <p class="why">Senior Safe Mode removes the way past scam warnings and
    hides paid search results, so a wrong click cannot lead somewhere
    dangerous.</p>
    <div id="senior-off">
      <button id="senior-on">Turn on Senior Safe Mode</button>
    </div>
    <p id="senior-done" class="done hidden" tabindex="-1">Senior Safe Mode is
    on. You can change it any time from Protection in the menu.</p>
  </section>

  <section aria-labelledby="more-heading">
    <h2 id="more-heading">If you want to</h2>
    <div class="links">
      <a href="chrome://settings/importData">Bring over bookmarks and
      passwords from another browser</a>
      <a href="chrome://settings/defaultBrowser">Make this your default
      browser</a>
      <a href="chrome://settings/search">Choose a different search
      engine</a>
    </div>
  </section>

  <div class="start">
    <button id="start">Start browsing</button>
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

window.loadWelcome = function(state) {
  var wasOff = !el('senior-off').classList.contains('hidden');
  show(state.senior);
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
    base::DictValue out;
    out.Set("senior", IsSeniorSafeMode(GetPrefs()));
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("loadWelcome", out);
  }

  void HandleTurnOn(const base::ListValue& args) {
    if (PrefService* prefs = GetPrefs()) {
      prefs->SetBoolean(prefs::kSeniorSafeMode, true);
    }
    HandleGet(args);
  }
};

bool ShouldHandle(const std::string& path) {
  return path.empty() || path == "welcome.js";
}

void Handle(const std::string& path,
            content::WebUIDataSource::GotDataCallback callback) {
  std::string body =
      path == "welcome.js" ? std::string(kScript) : std::string(kPage);
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
