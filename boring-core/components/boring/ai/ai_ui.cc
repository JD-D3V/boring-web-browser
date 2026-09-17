// Copyright 2026 boring. BSD style license.

#include "components/boring/ai/ai_ui.h"

#include <memory>
#include <string>

#include "base/functional/bind.h"
#include "base/functional/callback_helpers.h"
#include "base/memory/ref_counted_memory.h"
#include "base/values.h"
#include "components/boring/ai/ai_prefs.h"
#include "components/boring/ai/ai_summary_service.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition.h"
#include "content/public/browser/url_data_source.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_data_source.h"
#include "content/public/browser/web_ui_message_handler.h"
#include "content/public/common/url_constants.h"

namespace boring {
namespace ai {

namespace {

constexpr char kPage[] = R"PAGE(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AI settings</title>
<style>
  :root { color-scheme: light dark;
    --surface: light-dark(#faf9f6, #1c2422);
    --paper: light-dark(#ffffff, #252e2b);
    --ink: light-dark(#242e2d, #e8ede7);
    --muted: light-dark(#5d6966, #adb9b2);
    --line: light-dark(#d8ddd7, #414e47);
    /* Edges of things you can type in or press. Dark enough to find
       against the white panel, which --line is not. */
    --field: light-dark(#7d8783, #83908a);
    --accent: light-dark(#176b5b, #92d4bb);
    --soft: light-dark(#e5f1eb, #273f35);
  }
  * { box-sizing: border-box; }
  body { font: 15px/1.6 system-ui, sans-serif; margin: 0;
         background: var(--surface); color: var(--ink);
         padding: 3em 1.5em; display: flex; justify-content: center; }
  .page { width: 40em; max-width: 100%; }
  h1 { font-size: 1.6em; margin: 0 0 0.2em; }
  .lede { color: var(--muted); margin-top: 0; }
  fieldset { border: 1px solid var(--line); background: var(--paper);
             border-radius: 10px; margin: 1.5em 0; padding: 1.2em 1.4em; }
  legend { font-weight: 600; padding: 0 0.4em; }
  label.row { display: block; margin: 0.6em 0; }
  input[type=text], input[type=password], select {
    border: 1px solid var(--field);
    background: var(--paper); color: var(--ink);
    border-radius: 8px; font: inherit; margin-top: 0.3em;
    padding: 0.55em 0.7em; width: 100%; }
  .radio { align-items: flex-start; display: flex; gap: 0.6em;
           margin: 0.7em 0; }
  .radio input { margin-top: 0.35em; }
  .radio .what { font-weight: 600; }
  .radio .why { color: var(--muted); font-size: 0.9em; }
  button { background: var(--accent); border: none; border-radius: 8px;
           color: var(--surface); cursor: pointer; font: inherit;
           padding: 0.65em 1.4em; }
  button:hover { filter: brightness(0.94); }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
  input[type=radio] { accent-color: var(--accent); }
  .note { background: var(--soft); border-radius: 10px;
          margin-top: 1.5em; padding: 1em 1.2em; }
  .saved { color: var(--accent); margin-inline-start: 1em; }
  .bad { color: light-dark(#9e3e24, #ffb69c); }
  button.no { background: transparent; border: 1px solid var(--field);
              color: inherit; }
  .hidden { display: none; }
  .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden;
             clip-path: inset(50%); white-space: nowrap; }
  #ask { border: 1px solid var(--line); background: var(--paper);
         border-radius: 12px;
         margin-bottom: 2em; padding: 1.2em 1.4em; }
  #ask h2 { font-size: 1.15em; margin: 0 0 0.4em; }
  #ask .page-name { font-weight: 600; word-break: break-all; }
  #ask .going { background: var(--soft); border-radius: 8px;
                margin: 0.9em 0; padding: 0.8em 1em; }
  #ask .buttons { display: flex; flex-wrap: wrap; gap: 0.8em; margin-top: 1em; }
  #summary { white-space: pre-wrap; overflow-wrap: anywhere; }
  #summary-settings { margin-bottom: 1.5em; }
  @media (forced-colors: active) {
    button { border: 1px solid ButtonText; }
  }
</style>
</head>
<body>
<div class="page">
  <div id="ask" class="hidden"></div>
  <!-- Says what the summary is doing. Kept apart from #ask, which is
       rebuilt on every change and would repeat itself if it spoke. -->
  <div id="summary-status" class="sr-only" role="status"></div>
  <button class="no hidden" id="summary-settings" aria-expanded="false"
      aria-controls="settings-panel">Show summary settings</button>
  <section id="settings-panel">
  <h1 id="settings-heading" tabindex="-1">AI settings</h1>
  <p class="lede">The browser never reads your pages on its own. Nothing
  is sent anywhere until you ask for it, and you are told where it is
  going first.</p>

  <fieldset>
    <legend>Which service answers</legend>
    <div class="radio">
      <input type="radio" name="provider" id="p-off" value="off">
      <label for="p-off"><span class="what">Off</span><br>
        <span class="why">No AI features at all. This is the default.</span>
      </label>
    </div>
    <div class="radio">
      <input type="radio" name="provider" id="p-ollama" value="ollama">
      <label for="p-ollama"><span class="what">On your own computer, with Ollama</span><br>
        <span class="why">Free and private. Nothing leaves this machine.
        You install Ollama yourself.</span>
      </label>
    </div>
    <div class="radio">
      <input type="radio" name="provider" id="p-gemini" value="gemini">
      <label for="p-gemini"><span class="what">Google Gemini, with your key</span><br>
        <span class="why">Pages you ask about are sent to Google.</span>
      </label>
    </div>
    <div class="radio">
      <input type="radio" name="provider" id="p-openai" value="openai">
      <label for="p-openai"><span class="what">OpenAI, with your key</span><br>
        <span class="why">Pages you ask about are sent to OpenAI.</span>
      </label>
    </div>
    <div class="radio">
      <input type="radio" name="provider" id="p-openrouter" value="openrouter">
      <label for="p-openrouter"><span class="what">OpenRouter, with your key</span><br>
        <span class="why">Pages you ask about are sent to OpenRouter.</span>
      </label>
    </div>
    <div class="radio">
      <input type="radio" name="provider" id="p-groq" value="groq">
      <label for="p-groq"><span class="what">Groq, with your key</span><br>
        <span class="why">Pages you ask about are sent to Groq.</span>
      </label>
    </div>
  </fieldset>

  <fieldset id="local-box">
    <legend>Your own computer</legend>
    <label class="row">Where Ollama is listening
      <input type="text" id="ollama-url" placeholder="http://localhost:11434">
    </label>
  </fieldset>

  <fieldset id="key-box">
    <legend>Your key</legend>
    <label class="row">Key
      <input type="password" id="api-key" placeholder="paste your key here"
          aria-describedby="key-bad">
    </label>
    <p class="why">The key is encrypted and kept on this device only. It
    is never sent to us, never synced to your other devices, and never
    shown again once saved.</p>
    <p id="key-bad" class="bad hidden">That key does not look right, so it
    was not saved. Keys are printable characters with no spaces or line
    breaks.</p>
    <button class="no" id="forget-key">Forget the saved key</button>
  </fieldset>

  <fieldset>
    <legend>Model</legend>
    <label class="row">Model name
      <input type="text" id="model" placeholder="for example llama3.2">
    </label>
  </fieldset>

  <button id="save">Save</button><span id="saved" class="saved"
      role="status"></span>

  <div class="note" id="dest-note"></div>
  </section>
</div>
<script src="ai.js"></script>
</body>
</html>
)PAGE";

constexpr char kScript[] = R"SCRIPT(
function el(id) { return document.getElementById(id); }

function currentProvider() {
  var picked = document.querySelector('input[name=provider]:checked');
  return picked ? picked.value : 'off';
}

function refresh() {
  var provider = currentProvider();
  el('local-box').classList.toggle('hidden', provider !== 'ollama');
  el('key-box').classList.toggle('hidden',
                               provider === 'off' || provider === 'ollama');
  var note = el('dest-note');
  if (provider === 'off') {
    note.textContent = 'AI features are off. Nothing is sent anywhere.';
  } else if (provider === 'ollama') {
    note.textContent = 'When you ask for a summary, the page text goes to ' +
        'Ollama on your own computer. It does not leave this machine.';
  } else {
    var names = {gemini: 'Google Gemini', openai: 'OpenAI',
                 openrouter: 'OpenRouter', groq: 'Groq'};
    note.textContent = 'When you ask for a summary, the page text is sent ' +
        'to ' + names[provider] + '. You will be shown this before it is sent.';
  }
}

// What the last button press asked for, so the reply can say how it went.
// Saying "Saved" before the browser answers would contradict a rejected key.
var pendingNotice = null;
var noticeTimer = null;

function showNotice(text) {
  el('saved').textContent = text;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(function() { el('saved').textContent = ''; }, 4000);
}

function load(settings) {
  if (pendingNotice === 'save') {
    showNotice(settings.keyRejected
        ? 'Other settings saved. The key was not.' : 'Saved');
  } else if (pendingNotice === 'forget') {
    showNotice('The saved key is gone');
  }
  pendingNotice = null;
  var id = 'p-' + (settings.provider || 'off');
  if (el(id)) { el(id).checked = true; } else { el('p-off').checked = true; }
  el('ollama-url').value = settings.ollamaUrl || '';
  el('model').value = settings.model || '';
  // The key never comes back from the browser. All we are told is
  // whether one is stored, so the box starts empty either way.
  var key = el('api-key');
  key.value = '';
  key.placeholder = settings.hasApiKey
      ? 'a key is saved. Type here only to replace it'
      : 'paste your key here';
  el('forget-key').classList.toggle('hidden', !settings.hasApiKey);
  el('key-bad').classList.toggle('hidden', !settings.keyRejected);
  key.setAttribute('aria-invalid', String(!!settings.keyRejected));
  refresh();
}

document.addEventListener('change', function(e) {
  if (e.target.name === 'provider') { refresh(); }
});

el('save').addEventListener('click', function() {
  var settings = {
    provider: currentProvider(),
    ollamaUrl: el('ollama-url').value,
    model: el('model').value
  };
  // Only send a key when one was actually typed, so saving the other
  // settings does not wipe the key already stored.
  if (el('api-key').value) { settings.apiKey = el('api-key').value; }
  pendingNotice = 'save';
  chrome.send('saveSettings', [settings]);
});

el('forget-key').addEventListener('click', function() {
  pendingNotice = 'forget';
  chrome.send('clearApiKey');
  // The button hides itself once the key is gone, so hand focus to the
  // box the key came from rather than dropping it on the page.
  el('api-key').focus();
});

// The summary side of the page. Asking for a summary only puts the page
// aside. Nothing is sent until the person reads where it is going and
// says send.
var PROVIDER_NAMES = {ollama: 'Ollama on your own computer',
                      gemini: 'Google Gemini', openai: 'OpenAI',
                      openrouter: 'OpenRouter', groq: 'Groq'};

// WebUI requires TrustedHTML. Build nodes directly instead of weakening
// that policy or treating page titles, model output, or errors as markup.
function summaryNode(tag, text, className) {
  var node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}

var summaryState = 'nothing';
// The state last drawn. While an answer is on its way the page asks
// every second, and redrawing the same thing each time would throw away
// keyboard focus.
var lastDrawn = null;
el('summary-settings').addEventListener('click', function() {
  var hidden = el('settings-panel').classList.toggle('hidden');
  this.setAttribute('aria-expanded', String(!hidden));
  this.textContent = hidden ? 'Show summary settings' : 'Hide summary settings';
});

function showSummaryState(s) {
  var drawn = JSON.stringify(s || {state: 'nothing'});
  if (drawn === lastDrawn) {
    return;
  }
  lastDrawn = drawn;
  var box = el('ask');
  var previous = summaryState;
  if (!s || s.state === 'nothing') {
    box.classList.add('hidden');
    box.replaceChildren();
    el('summary-settings').classList.add('hidden');
    el('settings-panel').classList.remove('hidden');
    summaryState = 'nothing';
    if (previous !== 'nothing') {
      el('summary-status').textContent = 'Summary closed.';
      el('settings-heading').focus();
    }
    return;
  }
  if (previous === 'nothing') {
    el('settings-panel').classList.add('hidden');
    el('summary-settings').setAttribute('aria-expanded', 'false');
    el('summary-settings').textContent = 'Show summary settings';
  }
  summaryState = s.state;
  el('summary-settings').classList.remove('hidden');
  box.classList.remove('hidden');
  box.replaceChildren();
  // The browser tells us where this would really go. Ollama pointed at
  // another machine is named as such rather than called local.
  var name = s.destination || PROVIDER_NAMES[s.provider] ||
             'the service you picked';
  var heading = summaryNode('h2', '');
  heading.id = 'summary-heading';
  heading.tabIndex = -1;
  box.append(heading, summaryNode('div', s.title || s.url || '', 'page-name'));
  function addButton(label, id, secondary, action) {
    var buttons = box.querySelector('.buttons');
    if (!buttons) {
      buttons = summaryNode('div', '', 'buttons');
      box.append(buttons);
    }
    var button = summaryNode('button', label, secondary ? 'no' : '');
    button.type = 'button';
    button.id = id;
    button.addEventListener('click', action);
    buttons.append(button);
  }

  if (s.state === 'waiting') {
    var where = s.local
        ? 'This stays on your computer. Nothing goes over the internet.'
        : 'The text of this page will be sent to ' + name +
          ', over the internet.';
    heading.textContent = 'Summarise this page?';
    box.append(summaryNode('div', where + ' About ' +
        (s.textLength || 0).toLocaleString('en') +
        ' characters of page text would be sent. Nothing has been sent ' +
        'yet.', 'going'));
    addButton('Send and summarise', 'do-send', false, function() {
      chrome.send('sendSummary');
      chrome.send('getSummaryState');
    });
    addButton('No thanks', 'do-cancel', true, function() {
      chrome.send('forgetSummary');
    });
  } else if (s.state === 'working') {
    heading.textContent = 'Working';
    box.append(summaryNode('p', 'Sent to ' + name + '. Waiting for the answer.'));
  } else if (s.state === 'done') {
    heading.textContent = 'Summary';
    var result = summaryNode('div', s.summary || '');
    result.id = 'summary';
    box.append(result);
    addButton('Close', 'do-cancel', true, function() {
      chrome.send('forgetSummary');
    });
  } else if (s.state === 'failed') {
    heading.textContent = 'That did not work';
    box.append(summaryNode('p', s.error || 'The service could not be reached.'));
    addButton('Close', 'do-cancel', true, function() {
      chrome.send('forgetSummary');
    });
  }

  // Only a change of state is news. A new title on the same state is
  // redrawn without being announced or taking focus.
  if (s.state !== previous) {
    var said = {
      waiting: 'Summarise this page? Nothing has been sent yet.',
      working: 'Sent to ' + name + '. Waiting for the answer.',
      done: 'The summary is ready.',
      failed: 'The summary did not work.'
    };
    el('summary-status').textContent = said[s.state] || '';
    heading.focus();
  }
}

// Ask for the state once a second, but only while an answer is on its
// way. An idle settings page has no reason to keep talking.
var pollTimer = null;
function keepUpToDate(state) {
  var busy = state === 'working';
  if (busy && !pollTimer) {
    pollTimer = setInterval(function() {
      chrome.send('getSummaryState');
    }, 1000);
  } else if (!busy && pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

window.loadSettings = load;
window.loadSummaryState = function(s) {
  showSummaryState(s);
  keepUpToDate(s ? s.state : 'nothing');
};
chrome.send('getSettings');
chrome.send('getSummaryState');
)SCRIPT";

// Reads and writes the AI settings for the page.
class AiMessageHandler : public content::WebUIMessageHandler {
 public:
  AiMessageHandler() = default;
  ~AiMessageHandler() override = default;

  void RegisterMessages() override {
    web_ui()->RegisterMessageCallback(
        "getSettings", base::BindRepeating(&AiMessageHandler::HandleGet,
                                           base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "saveSettings", base::BindRepeating(&AiMessageHandler::HandleSave,
                                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "clearApiKey", base::BindRepeating(&AiMessageHandler::HandleClearApiKey,
                                           base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "getSummaryState",
        base::BindRepeating(&AiMessageHandler::HandleSummaryState,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "sendSummary", base::BindRepeating(&AiMessageHandler::HandleSendSummary,
                                           base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "forgetSummary",
        base::BindRepeating(&AiMessageHandler::HandleForgetSummary,
                            base::Unretained(this)));
  }

 private:
  PrefService* GetPrefs() {
    return user_prefs::UserPrefs::Get(
        web_ui()->GetWebContents()->GetBrowserContext());
  }

  // The summary service belongs to this profile, so an incognito window
  // gets its own and never sees what an ordinary window put aside.
  AiSummaryService* GetService() {
    return AiSummaryService::GetForBrowserContext(
        web_ui()->GetWebContents()->GetBrowserContext());
  }

  void SendSettings(bool key_rejected) {
    PrefService* prefs = GetPrefs();
    base::DictValue settings;
    if (prefs) {
      settings.Set("provider", prefs->GetString(prefs::kProvider));
      settings.Set("model", prefs->GetString(prefs::kModel));
      settings.Set("ollamaUrl", prefs->GetString(prefs::kOllamaUrl));
      // The key itself is never sent back to the page. The page only
      // needs to know whether one is stored, so that is all it gets.
      settings.Set("hasApiKey", HasApiKey(prefs));
      settings.Set("keyRejected", key_rejected);
    }
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("loadSettings", settings);
  }

  void HandleGet(const base::ListValue& args) {
    SendSettings(/*key_rejected=*/false);
  }

  void HandleSave(const base::ListValue& args) {
    if (args.empty() || !args[0].is_dict()) {
      return;
    }
    PrefService* prefs = GetPrefs();
    if (!prefs) {
      return;
    }
    const base::DictValue& in = args[0].GetDict();
    const std::string* provider = in.FindString("provider");
    if (provider) {
      prefs->SetString(prefs::kProvider, *provider);
    }
    if (const std::string* url = in.FindString("ollamaUrl")) {
      prefs->SetString(prefs::kOllamaUrl, *url);
    }
    if (const std::string* model = in.FindString("model")) {
      prefs->SetString(prefs::kModel, *model);
    }
    // The key arrives only when the person typed a new one, so saving
    // the other settings never wipes a key that is already stored.
    bool key_rejected = false;
    if (const std::string* key = in.FindString("apiKey")) {
      if (!key->empty()) {
        key_rejected = !SetApiKey(prefs, *key);
      }
    }
    SendSettings(key_rejected);
  }

  void HandleClearApiKey(const base::ListValue& args) {
    if (PrefService* prefs = GetPrefs()) {
      SetApiKey(prefs, std::string());
    }
    SendSettings(/*key_rejected=*/false);
  }

  void HandleSummaryState(const base::ListValue& args) {
    AllowJavascript();
    AiSummaryService* service = GetService();
    PrefService* prefs = GetPrefs();
    if (!service) {
      return;
    }

    base::DictValue out;
    switch (service->state()) {
      case AiSummaryService::State::kNothing:
        out.Set("state", "nothing");
        break;
      case AiSummaryService::State::kWaiting:
        out.Set("state", "waiting");
        break;
      case AiSummaryService::State::kWorking:
        out.Set("state", "working");
        break;
      case AiSummaryService::State::kDone:
        out.Set("state", "done");
        break;
      case AiSummaryService::State::kFailed:
        out.Set("state", "failed");
        break;
    }
    out.Set("title", service->title());
    out.Set("url", service->url());
    out.Set("summary", service->summary());
    out.Set("error", service->error());
    out.Set("textLength", static_cast<int>(service->text_length()));
    out.Set("provider",
            prefs ? prefs->GetString(prefs::kProvider) : std::string("off"));
    // Worked out in C++ so the confirm screen cannot claim a request
    // stays on this machine when the address points somewhere else.
    out.Set("local", prefs && prefs->GetString(prefs::kProvider) == "ollama" &&
                         OllamaStaysOnThisMachine(prefs));
    out.Set("destination", DestinationForDisplay(prefs));
    web_ui()->CallJavascriptFunctionUnsafe("loadSummaryState", out);
  }

  void HandleSendSummary(const base::ListValue& args) {
    content::BrowserContext* context =
        web_ui()->GetWebContents()->GetBrowserContext();
    AiSummaryService* service = GetService();
    if (!service) {
      return;
    }
    // The prefs and the network stack both come from this same profile,
    // so an incognito summary can never go out under the ordinary
    // profile's key.
    service->Send(GetPrefs(),
                  context->GetDefaultStoragePartition()
                      ->GetURLLoaderFactoryForBrowserProcess(),
                  base::DoNothing());
  }

  void HandleForgetSummary(const base::ListValue& args) {
    if (AiSummaryService* service = GetService()) {
      service->Forget();
    }
    // Idle pages do not poll, so cancellation must update the visible UI.
    HandleSummaryState(args);
  }
};

bool ShouldHandle(const std::string& path) {
  // Only the page itself and its script. Anything else is not ours.
  return path.empty() || path == "ai.js";
}

void Handle(const std::string& path,
            content::WebUIDataSource::GotDataCallback callback) {
  // The script is served as its own file. Serving it inline would break
  // the page's security rules, which we are not going to weaken.
  std::string body =
      path == "ai.js" ? std::string(kScript) : std::string(kPage);
  std::move(callback).Run(
      base::MakeRefCounted<base::RefCountedString>(std::move(body)));
}

}  // namespace

BoringAiUI::BoringAiUI(content::WebUI* web_ui)
    : content::WebUIController(web_ui) {
  content::WebUIDataSource* source = content::WebUIDataSource::CreateAndAdd(
      web_ui->GetWebContents()->GetBrowserContext(), kBoringAiHost);
  source->SetRequestFilter(base::BindRepeating(&ShouldHandle),
                           base::BindRepeating(&Handle));
  web_ui->AddMessageHandler(std::make_unique<AiMessageHandler>());
}

BoringAiUI::~BoringAiUI() = default;

BoringAiUIConfig::BoringAiUIConfig()
    : content::DefaultWebUIConfig<BoringAiUI>(content::kChromeUIScheme,
                                              kBoringAiHost) {}

}  // namespace ai
}  // namespace boring
