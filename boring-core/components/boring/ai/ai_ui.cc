// Copyright 2026 boring. BSD style license.

#include "components/boring/ai/ai_ui.h"

#include <memory>
#include <string>

#include "base/functional/bind.h"
#include "base/memory/ref_counted_memory.h"
#include "base/values.h"
#include "components/boring/ai/ai_prefs.h"
#include "components/prefs/pref_service.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/url_data_source.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_data_source.h"
#include "content/public/browser/web_ui_message_handler.h"
#include "content/public/common/url_constants.h"

namespace boring {
namespace ai {

namespace {

constexpr char kPage[] = R"PAGE(<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>AI settings</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 15px/1.6 system-ui, sans-serif; margin: 0;
         padding: 2.5em 1.5em; display: flex; justify-content: center; }
  .page { width: 40em; max-width: 100%; }
  h1 { font-size: 1.6em; margin: 0 0 0.2em; }
  .lede { color: #5f6368; margin-top: 0; }
  fieldset { border: 1px solid rgba(128,128,128,0.35);
             border-radius: 10px; margin: 1.5em 0; padding: 1.2em 1.4em; }
  legend { font-weight: 600; padding: 0 0.4em; }
  label.row { display: block; margin: 0.6em 0; }
  input[type=text], input[type=password], select {
    box-sizing: border-box; border: 1px solid rgba(128,128,128,0.5);
    border-radius: 8px; font: inherit; margin-top: 0.3em;
    padding: 0.55em 0.7em; width: 100%; }
  .radio { align-items: flex-start; display: flex; gap: 0.6em;
           margin: 0.7em 0; }
  .radio input { margin-top: 0.35em; }
  .radio .what { font-weight: 600; }
  .radio .why { color: #5f6368; font-size: 0.9em; }
  button { background: #1a73e8; border: none; border-radius: 8px;
           color: #fff; cursor: pointer; font: inherit;
           padding: 0.65em 1.4em; }
  button:hover { background: #1765c9; }
  .note { background: rgba(128,128,128,0.12); border-radius: 10px;
          margin-top: 1.5em; padding: 1em 1.2em; }
  .saved { color: #188038; margin-inline-start: 1em; }
  .hidden { display: none; }
</style>
</head>
<body>
<div class="page">
  <h1>AI settings</h1>
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
      <input type="password" id="api-key" placeholder="paste your key here">
    </label>
    <p class="why">The key is kept on this device only. It is never sent
    to us and never synced to your other devices.</p>
  </fieldset>

  <fieldset>
    <legend>Model</legend>
    <label class="row">Model name
      <input type="text" id="model" placeholder="for example llama3.2">
    </label>
  </fieldset>

  <button id="save">Save</button><span id="saved" class="saved hidden">Saved</span>

  <div class="note" id="dest-note"></div>
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
  var p = currentProvider();
  el('local-box').classList.toggle('hidden', p !== 'ollama');
  el('key-box').classList.toggle('hidden', p === 'off' || p === 'ollama');
  var note = el('dest-note');
  if (p === 'off') {
    note.textContent = 'AI features are off. Nothing is sent anywhere.';
  } else if (p === 'ollama') {
    note.textContent = 'When you ask for a summary, the page text goes to ' +
        'Ollama on your own computer. It does not leave this machine.';
  } else {
    var names = {gemini: 'Google Gemini', openai: 'OpenAI',
                 openrouter: 'OpenRouter', groq: 'Groq'};
    note.textContent = 'When you ask for a summary, the page text is sent ' +
        'to ' + names[p] + '. You will be shown this before it is sent.';
  }
}

function load(settings) {
  var id = 'p-' + (settings.provider || 'off');
  if (el(id)) { el(id).checked = true; } else { el('p-off').checked = true; }
  el('ollama-url').value = settings.ollamaUrl || '';
  el('api-key').value = settings.apiKey || '';
  el('model').value = settings.model || '';
  refresh();
}

document.addEventListener('change', function(e) {
  if (e.target.name === 'provider') { refresh(); }
});

el('save').addEventListener('click', function() {
  chrome.send('saveSettings', [{
    provider: currentProvider(),
    ollamaUrl: el('ollama-url').value,
    apiKey: el('api-key').value,
    model: el('model').value
  }]);
  el('saved').classList.remove('hidden');
  setTimeout(function() { el('saved').classList.add('hidden'); }, 2000);
});

window.loadSettings = load;
chrome.send('getSettings');
)SCRIPT";

// Reads and writes the AI settings for the page.
class AiMessageHandler : public content::WebUIMessageHandler {
 public:
  AiMessageHandler() = default;
  ~AiMessageHandler() override = default;

  void RegisterMessages() override {
    web_ui()->RegisterMessageCallback(
        "getSettings",
        base::BindRepeating(&AiMessageHandler::HandleGet,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "saveSettings",
        base::BindRepeating(&AiMessageHandler::HandleSave,
                            base::Unretained(this)));
  }

 private:
  PrefService* GetPrefs() {
    return user_prefs::UserPrefs::Get(
        web_ui()->GetWebContents()->GetBrowserContext());
  }

  void HandleGet(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    base::DictValue settings;
    if (prefs) {
      settings.Set("provider", prefs->GetString(prefs::kProvider));
      settings.Set("model", prefs->GetString(prefs::kModel));
      settings.Set("ollamaUrl", prefs->GetString(prefs::kOllamaUrl));
      settings.Set("apiKey", prefs->GetString(prefs::kApiKey));
    }
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("loadSettings", settings);
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
    if (const std::string* key = in.FindString("apiKey")) {
      prefs->SetString(prefs::kApiKey, *key);
    }
    if (const std::string* model = in.FindString("model")) {
      prefs->SetString(prefs::kModel, *model);
    }
  }
};

bool ShouldHandle(const std::string& path) {
  return true;
}

void Handle(const std::string& path,
            content::WebUIDataSource::GotDataCallback callback) {
  // The script is served as its own file. Serving it inline would break
  // the page's security rules, which we are not going to weaken.
  std::string body = path == "ai.js" ? std::string(kScript)
                                     : std::string(kPage);
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
