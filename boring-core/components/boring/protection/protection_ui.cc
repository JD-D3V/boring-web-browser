// Copyright 2026 boring. BSD style license.

#include "components/boring/protection/protection_ui.h"

#include <memory>
#include <string>

#include "base/functional/bind.h"
#include "base/memory/ref_counted_memory.h"
#include "base/values.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/scam/scam_service.h"
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
<title>Protection</title>
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
    --warn: light-dark(#9e3e24, #ffb69c);
    --warn-soft: light-dark(#fbebe4, #412f28);
  }
  * { box-sizing: border-box; }
  body { font: 15px/1.6 system-ui, sans-serif; margin: 0;
         background: var(--surface); color: var(--ink);
         padding: 3em 1.5em; display: flex; justify-content: center; }
  .page { width: 40em; max-width: 100%; }
  h1 { font-size: 1.6em; margin: 0 0 0.2em; }
  .lede, .why { color: var(--muted); }
  .lede { margin-top: 0; }
  .why { display: block; font-size: 0.9em; margin: 0.2em 0 0; }
  section { border: 1px solid var(--line); background: var(--paper);
            border-radius: 10px; margin: 1.5em 0; padding: 1.2em 1.4em; }
  h2 { font-size: 1.05em; margin: 0 0 0.6em; }
  .row { display: flex; gap: 1em; align-items: flex-start;
         justify-content: space-between; padding: 0.7em 0; }
  .row + .row { border-top: 1px solid var(--line); }
  .row strong { display: block; }
  .state { flex: none; border-radius: 999px; font-size: 0.85em;
           font-weight: 600; padding: 0.15em 0.8em;
           background: var(--soft); color: var(--accent); }
  .state.off { background: var(--warn-soft); color: var(--warn); }
  .state.wait { background: transparent; color: var(--muted);
                border: 1px solid var(--line); }
  .problem { color: var(--warn); }
  input[type=checkbox] { accent-color: var(--accent); width: 1.3em;
                         height: 1.3em; margin: 0.2em 0 0; flex: none; }
  label.row { cursor: pointer; }
  button { background: var(--accent); border: none; border-radius: 8px;
           color: var(--surface); cursor: pointer; font: inherit;
           padding: 0.65em 1.4em; }
  button:hover { filter: brightness(0.94); }
  button.no { background: transparent; border: 1px solid var(--field);
              color: inherit; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
  #confirm-off { background: var(--warn-soft); border-radius: 8px;
                 margin-top: 0.6em; padding: 1em 1.2em; }
  #confirm-off p { margin: 0 0 0.8em; }
  .buttons { display: flex; flex-wrap: wrap; gap: 0.8em; }
  .note { color: var(--muted); font-size: 0.9em; }
  a { color: var(--accent); text-underline-offset: 3px; }
  .hidden { display: none; }
  .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden;
             clip-path: inset(50%); white-space: nowrap; }
  @media (forced-colors: active) {
    button, .state { border: 1px solid ButtonText; }
  }
</style>
</head>
<body>
<div class="page">
  <h1>Protection</h1>
  <p class="lede">What the browser is doing to keep you safe, right now.
  Everything here happens on this computer.</p>

  <section aria-labelledby="now-heading">
    <h2 id="now-heading">Working right now</h2>
    <div class="row">
      <div><strong>Scam and phishing sites</strong>
        <p class="why" id="scam-why"></p></div>
      <span class="state wait" id="scam-state">Checking</span>
    </div>
    <div class="row">
      <div><strong>Ads and trackers</strong>
        <p class="why" id="ads-why"></p></div>
      <span class="state wait" id="ads-state">Checking</span>
    </div>
    <p class="note">Lists catch known threats. They cannot spot every
    unsafe site, so an unfamiliar site still deserves care.</p>
  </section>

  <section aria-labelledby="senior-heading">
    <h2 id="senior-heading">Senior Safe Mode</h2>
    <label class="row" for="senior">
      <span><strong>Turn on Senior Safe Mode</strong>
        <span class="why" id="senior-why">Scam warnings lose their
        "continue anyway" link, so there is no way past one by accident.
        Sponsored search results are hidden too.</span></span>
      <input type="checkbox" id="senior">
    </label>
    <div id="confirm-off" class="hidden" role="alertdialog"
        aria-labelledby="confirm-heading" aria-describedby="confirm-text">
      <p><strong id="confirm-heading">Before you turn this off</strong></p>
      <p id="confirm-text">No bank, computer company or government office
      will ever ask you to change this. If someone is asking you to right
      now, on the phone or on screen, stop and hang up.</p>
      <div class="buttons">
        <button id="keep-on">Keep it on</button>
        <button class="no" id="turn-off">Turn it off</button>
      </div>
    </div>
  </section>

  <section aria-labelledby="search-heading">
    <h2 id="search-heading">Search results</h2>
    <label class="row" for="hide-ads">
      <span><strong>Hide sponsored results</strong>
        <span class="why" id="hide-why">Paid placements on Google and Bing
        are removed instead of labelled. Sponsored does not always mean
        unsafe, and this does not remove every scam link.</span></span>
      <input type="checkbox" id="hide-ads">
    </label>
  </section>

  <p class="note">Page summaries are off unless you turn them on in
  <a href="chrome://boring-ai">AI settings</a>.</p>
  <div id="status" class="sr-only" role="status"></div>
</div>
<script src="protection.js"></script>
</body>
</html>
)PAGE";

constexpr char kScript[] = R"SCRIPT(
function el(id) { return document.getElementById(id); }

var WORDS = {
  scam: {
    ready: 'Sites on the list of known scams are stopped before they open.',
    off: 'Known scam sites are not being blocked.'
  },
  ads: {
    ready: 'Known advertising and tracking requests are blocked.',
    off: 'Ads and trackers are not being blocked.'
  }
};

// Shows one protection as it really is. A failure is never softened into
// something that looks like it is working.
function showState(name, state, problem) {
  var badge = el(name + '-state');
  var why = el(name + '-why');
  badge.className = 'state' + (state === 'ready' ? '' :
                               state === 'failed' ? ' off' : ' wait');
  if (state === 'ready') {
    badge.textContent = 'On';
    why.className = 'why';
    why.textContent = WORDS[name].ready;
  } else if (state === 'failed') {
    badge.textContent = 'Not working';
    why.className = 'why problem';
    why.textContent = WORDS[name].off + ' The reason: ' +
        (problem || 'unknown') + '. A browser update should fix this.';
  } else {
    badge.textContent = 'Starting';
    why.className = 'why';
    why.textContent = 'Getting ready. This takes a few seconds.';
  }
}

var pollTimer = null;

function load(s) {
  showState('scam', s.scam, s.scamProblem);
  showState('ads', s.ads, s.adsProblem);

  var senior = el('senior');
  senior.checked = s.senior;
  senior.disabled = s.seniorForced;
  if (s.seniorForced) {
    el('senior-why').textContent = 'Turned on for this computer by whoever ' +
        'set it up, so it cannot be turned off here.';
  }
  var hide = el('hide-ads');
  hide.checked = s.hideSponsored || s.senior;
  hide.disabled = s.senior;
  if (s.senior) {
    el('hide-why').textContent = 'Always hidden while Senior Safe Mode is on.';
  }

  // Keep asking only while something is still starting up.
  var starting = s.scam === 'loading' || s.ads === 'loading';
  if (starting && !pollTimer) {
    pollTimer = setInterval(function() {
      chrome.send('getProtection');
    }, 2000);
  } else if (!starting && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function say(text) {
  el('status').textContent = text;
}

el('senior').addEventListener('change', function(e) {
  if (e.target.checked) {
    chrome.send('setSeniorSafeMode', [true]);
    say('Senior Safe Mode is on.');
    return;
  }
  // Turning it off is the one change a scammer asks for. Put it back
  // until the person has read why, then ask again.
  e.target.checked = true;
  el('confirm-off').classList.remove('hidden');
  el('keep-on').focus();
});

el('keep-on').addEventListener('click', function() {
  el('confirm-off').classList.add('hidden');
  el('senior').focus();
  say('Senior Safe Mode stays on.');
});

el('turn-off').addEventListener('click', function() {
  el('confirm-off').classList.add('hidden');
  chrome.send('setSeniorSafeMode', [false]);
  el('senior').focus();
  say('Senior Safe Mode is off.');
});

el('hide-ads').addEventListener('change', function(e) {
  chrome.send('setHideSponsored', [e.target.checked]);
  say(e.target.checked ? 'Sponsored results will be hidden.'
                       : 'Sponsored results will be labelled.');
});

window.loadProtection = load;
chrome.send('getProtection');
)SCRIPT";

// Both services describe themselves with the same three states.
template <typename Status>
const char* StatusName(Status status) {
  switch (status) {
    case Status::kReady:
      return "ready";
    case Status::kFailed:
      return "failed";
    case Status::kLoading:
      return "loading";
  }
  return "loading";
}

class ProtectionMessageHandler : public content::WebUIMessageHandler {
 public:
  ProtectionMessageHandler() = default;
  ~ProtectionMessageHandler() override = default;

  void RegisterMessages() override {
    web_ui()->RegisterMessageCallback(
        "getProtection",
        base::BindRepeating(&ProtectionMessageHandler::HandleGet,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setSeniorSafeMode",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetSenior,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setHideSponsored",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetHide,
                            base::Unretained(this)));
  }

 private:
  PrefService* GetPrefs() {
    return user_prefs::UserPrefs::Get(
        web_ui()->GetWebContents()->GetBrowserContext());
  }

  void HandleGet(const base::ListValue& args) {
    // Opening this page is a good moment to make sure the lists are
    // loading, so the answer is about the lists and not about timing.
    ScamService* scam = ScamService::GetInstance();
    AdblockService* ads = AdblockService::GetInstance();
    scam->EnsureLoading();
    ads->EnsureLoading();

    PrefService* prefs = GetPrefs();
    base::DictValue out;
    out.Set("scam", StatusName(scam->status()));
    out.Set("scamProblem", scam->status_message());
    out.Set("ads", StatusName(ads->status()));
    out.Set("adsProblem", ads->status_message());
    out.Set("senior", IsSeniorSafeMode(prefs));
    out.Set("seniorForced", IsSeniorSafeModeForced());
    out.Set("hideSponsored",
            prefs && prefs->GetBoolean(prefs::kHideSponsoredResults));
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("loadProtection", out);
  }

  void HandleSetSenior(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kSeniorSafeMode, args[0].GetBool());
    }
    HandleGet(args);
  }

  void HandleSetHide(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kHideSponsoredResults, args[0].GetBool());
    }
    HandleGet(args);
  }
};

bool ShouldHandle(const std::string& path) {
  return path.empty() || path == "protection.js";
}

void Handle(const std::string& path,
            content::WebUIDataSource::GotDataCallback callback) {
  // The script is its own file so the page's security rules can stay
  // strict about inline script.
  std::string body =
      path == "protection.js" ? std::string(kScript) : std::string(kPage);
  std::move(callback).Run(
      base::MakeRefCounted<base::RefCountedString>(std::move(body)));
}

}  // namespace

BoringProtectionUI::BoringProtectionUI(content::WebUI* web_ui)
    : content::WebUIController(web_ui) {
  content::WebUIDataSource* source = content::WebUIDataSource::CreateAndAdd(
      web_ui->GetWebContents()->GetBrowserContext(), kBoringProtectionHost);
  source->SetRequestFilter(base::BindRepeating(&ShouldHandle),
                           base::BindRepeating(&Handle));
  web_ui->AddMessageHandler(std::make_unique<ProtectionMessageHandler>());
}

BoringProtectionUI::~BoringProtectionUI() = default;

BoringProtectionUIConfig::BoringProtectionUIConfig()
    : content::DefaultWebUIConfig<BoringProtectionUI>(content::kChromeUIScheme,
                                                      kBoringProtectionHost) {}

}  // namespace boring
