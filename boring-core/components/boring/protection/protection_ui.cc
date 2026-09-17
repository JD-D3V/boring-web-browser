// Copyright 2026 boring. BSD style license.

#include "components/boring/protection/protection_ui.h"

#include <algorithm>
#include <memory>
#include <string>

#include "base/functional/bind.h"
#include "base/memory/ref_counted_memory.h"
#include "base/time/time.h"
#include "base/values.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/lists/list_updater.h"
#include "components/boring/scam/scam_service.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition.h"
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
  .why { color: var(--muted); display: block; font-size: 0.9em;
         margin: 0.2em 0 0; }
  section { border: 1px solid var(--line); background: var(--paper);
            border-radius: 10px; margin: 1.5em 0; padding: 1.2em 1.4em; }
  .row { display: flex; gap: 1em; align-items: flex-start;
         justify-content: space-between; padding: 0.7em 0; }
  .row + .row, .why + .row, #confirm-off + .row {
    border-top: 1px solid var(--line); }
  .row + .why { margin: -0.5em 0 0.7em; }
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

  <section>
    <div class="row">
      <strong>Scam sites</strong>
      <span class="state wait" id="scam-state">Starting</span>
    </div>
    <p class="why problem hidden" id="scam-why"></p>
    <div class="row">
      <strong>Ads and trackers</strong>
      <span class="state wait" id="ads-state">Starting</span>
    </div>
    <p class="why problem hidden" id="ads-why"></p>
    <div class="row">
      <strong>Blocking lists</strong>
      <span class="state wait" id="lists-state">Starting</span>
    </div>
    <p class="why" id="lists-age"></p>
    <label class="row" for="list-updates">
      <span><strong>Keep them up to date</strong>
        <span class="why">Checks for newer lists about once a week. No
        account, no cookie, nothing about you or the pages you
        visit.</span></span>
      <input type="checkbox" id="list-updates">
    </label>
  </section>

  <section>
    <label class="row" for="senior">
      <span><strong>Senior Safe Mode</strong>
        <span class="why" id="senior-why">No way past scam warnings.
        Sponsored results hidden.</span></span>
      <input type="checkbox" id="senior">
    </label>
    <div id="confirm-off" class="hidden" role="alertdialog"
        aria-labelledby="confirm-text">
      <p id="confirm-text">Nobody from a bank or tech company will ever ask
      you to turn this off. If someone is asking, hang up.</p>
      <div class="buttons">
        <button id="keep-on">Keep it on</button>
        <button class="no" id="turn-off">Turn it off</button>
      </div>
    </div>
    <label class="row" for="hide-ads">
      <strong>Hide sponsored search results</strong>
      <input type="checkbox" id="hide-ads">
    </label>
  </section>
  <div id="status" class="sr-only" role="status"></div>
</div>
<script src="protection.js"></script>
</body>
</html>
)PAGE";

constexpr char kScript[] = R"SCRIPT(
function el(id) { return document.getElementById(id); }

// A failure is shown as a failure, with the reason.
function showState(name, state, problem) {
  var badge = el(name + '-state');
  var why = el(name + '-why');
  badge.className = 'state' + (state === 'ready' ? '' :
                               state === 'failed' ? ' off' : ' wait');
  badge.textContent = state === 'ready' ? 'On' :
                      state === 'failed' ? 'Off' : 'Starting';
  why.classList.toggle('hidden', state !== 'failed');
  if (state === 'failed') {
    var reason = problem || 'unknown problem';
    why.textContent = reason.charAt(0).toUpperCase() + reason.slice(1) + '.';
  }
}

// Lists that stop being replaced stop recognising the scams people
// are being sent to now, so old lists are shown as a problem rather
// than as a detail.
function showLists(days, updating) {
  var badge = el('lists-state');
  var age = el('lists-age');
  var old = days < 0 || days > 14;
  badge.className = 'state' + (old ? ' off' : '');
  badge.textContent = days < 0 ? 'Unknown' : old ? 'Old' : 'Current';
  age.classList.toggle('problem', old);
  if (days < 0) {
    age.textContent = 'Cannot tell how old the lists are.';
  } else if (days < 1) {
    age.textContent = 'Updated today.';
  } else if (days === 1) {
    age.textContent = 'Updated yesterday.';
  } else {
    age.textContent = 'Updated ' + days + ' days ago.';
  }
  if (old && !updating) {
    age.textContent += ' Updates are turned off.';
  }
  el('list-updates').checked = updating;
}

var pollTimer = null;

function load(s) {
  showState('scam', s.scam, s.scamProblem);
  showState('ads', s.ads, s.adsProblem);
  showLists(s.listDays, s.listUpdates);

  var senior = el('senior');
  senior.checked = s.senior;
  senior.disabled = s.seniorForced;
  if (s.seniorForced) {
    el('senior-why').textContent = 'Set for this computer.';
  }
  var hide = el('hide-ads');
  hide.checked = s.hideSponsored || s.senior;
  hide.disabled = s.senior;

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
    say('Senior Safe Mode on.');
    return;
  }
  // Turning it off is the one change a scammer asks for, so ask first.
  e.target.checked = true;
  el('confirm-off').classList.remove('hidden');
  el('keep-on').focus();
});

el('keep-on').addEventListener('click', function() {
  el('confirm-off').classList.add('hidden');
  el('senior').focus();
});

el('turn-off').addEventListener('click', function() {
  el('confirm-off').classList.add('hidden');
  chrome.send('setSeniorSafeMode', [false]);
  el('senior').focus();
  say('Senior Safe Mode off.');
});

el('hide-ads').addEventListener('change', function(e) {
  chrome.send('setHideSponsored', [e.target.checked]);
});

el('list-updates').addEventListener('change', function(e) {
  chrome.send('setListUpdates', [e.target.checked]);
  say(e.target.checked ? 'Lists will be kept up to date.'
                       : 'Lists will not be updated.');
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
    web_ui()->RegisterMessageCallback(
        "setListUpdates",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetListUpdates,
                            base::Unretained(this)));
  }

 private:
  PrefService* GetPrefs() {
    return user_prefs::UserPrefs::Get(
        web_ui()->GetWebContents()->GetBrowserContext());
  }

  // How many days old the older of the two lists is, or -1 when that
  // cannot be told. This is the timestamp on the files actually in
  // use, not anything the browser wrote down about them, so the page
  // cannot claim the lists are fresher than they are.
  static int ListAgeInDays(const AdblockService* ads, const ScamService* scam) {
    const base::Time ads_at = ads->list_time();
    const base::Time scam_at = scam->list_time();
    if (ads_at.is_null() || scam_at.is_null()) {
      return -1;
    }
    const base::TimeDelta age = base::Time::Now() - std::min(ads_at, scam_at);
    return std::max(0, age.InDays());
  }

  void HandleGet(const base::ListValue& args) {
    // Opening this page is a good moment to make sure the lists are
    // loading, so the answer is about the lists and not about timing.
    ScamService* scam = ScamService::GetInstance();
    AdblockService* ads = AdblockService::GetInstance();
    scam->EnsureLoading();
    ads->EnsureLoading();

    PrefService* prefs = GetPrefs();

    // And a good moment to look for newer ones, unless this is an
    // incognito window, whose network session should not carry it.
    content::BrowserContext* context =
        web_ui()->GetWebContents()->GetBrowserContext();
    if (!context->IsOffTheRecord()) {
      ListUpdater::GetInstance()->MaybeCheck(
          prefs, context->GetDefaultStoragePartition()
                     ->GetURLLoaderFactoryForBrowserProcess());
    }
    base::DictValue out;
    out.Set("scam", StatusName(scam->status()));
    out.Set("scamProblem", scam->status_message());
    out.Set("ads", StatusName(ads->status()));
    out.Set("adsProblem", ads->status_message());
    out.Set("senior", IsSeniorSafeMode(prefs));
    out.Set("seniorForced", IsSeniorSafeModeForced());
    out.Set("hideSponsored",
            prefs && prefs->GetBoolean(prefs::kHideSponsoredResults));
    out.Set("listDays", ListAgeInDays(ads, scam));
    out.Set("listUpdates", ListUpdater::IsEnabled(prefs));
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

  void HandleSetListUpdates(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kListUpdates, args[0].GetBool());
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
