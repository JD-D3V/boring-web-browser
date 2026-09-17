// Copyright 2026 boring. BSD style license.

#include "components/boring/newtab/newtab_ui.h"

#include <memory>
#include <string>

#include "base/functional/bind.h"
#include "base/memory/ref_counted_memory.h"
#include "base/strings/string_util.h"
#include "base/values.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/scam/scam_service.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_data_source.h"
#include "content/public/browser/web_ui_message_handler.h"
#include "content/public/common/url_constants.h"
#include "url/gurl.h"

namespace boring {

namespace {

// Enough to be useful, few enough that the page stays calm.
constexpr size_t kMaxShortcuts = 8;
constexpr size_t kMaxTitleLength = 40;

constexpr char kPage[] = R"PAGE(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>New Tab</title>
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
  html, body { height: 100%; }
  body { font: 15px/1.6 system-ui, sans-serif; margin: 0;
         background: var(--surface); color: var(--ink);
         display: flex; flex-direction: column; align-items: center;
         justify-content: center; padding: 2em 1.5em; }
  .page { width: 44em; max-width: 100%; }
  .hint { color: var(--muted); text-align: center; margin: 0 0 2em; }
  #shortcuts { display: grid; gap: 0.8em; list-style: none; margin: 0;
               padding: 0; grid-template-columns: repeat(auto-fill,
               minmax(9.5em, 1fr)); }
  #shortcuts li { position: relative; }
  #shortcuts a { display: flex; flex-direction: column; align-items: center;
                 gap: 0.5em; padding: 1em 0.6em 0.8em; border-radius: 10px;
                 color: inherit; text-decoration: none;
                 background: var(--paper); border: 1px solid var(--line); }
  #shortcuts a:hover { border-color: var(--field); }
  .mark { width: 2.4em; height: 2.4em; border-radius: 8px; display: grid;
          place-items: center; font-weight: 600; background: var(--soft);
          color: var(--accent); }
  .name { max-width: 100%; overflow: hidden; text-overflow: ellipsis;
          white-space: nowrap; font-size: 0.9em; }
  .remove { position: absolute; top: 0.3em; right: 0.3em; width: 1.8em;
            height: 1.8em; border-radius: 6px; border: none; padding: 0;
            background: transparent; color: var(--muted); cursor: pointer;
            font: inherit; line-height: 1; opacity: 0; }
  li:hover .remove, .remove:focus-visible { opacity: 1; }
  .add { display: flex; flex-direction: column; align-items: center;
         justify-content: center; gap: 0.5em; width: 100%; min-height: 100%;
         padding: 1em 0.6em 0.8em; border-radius: 10px; cursor: pointer;
         border: 1px dashed var(--field); background: transparent;
         color: var(--muted); font: inherit; }
  form { display: grid; gap: 0.6em; background: var(--paper);
         border: 1px solid var(--line); border-radius: 10px;
         padding: 1em 1.2em; margin-top: 1em; }
  label { display: grid; gap: 0.2em; font-size: 0.9em; }
  input { border: 1px solid var(--field); background: var(--paper);
          color: var(--ink); border-radius: 8px; font: inherit;
          padding: 0.5em 0.7em; }
  .buttons { display: flex; gap: 0.6em; flex-wrap: wrap; }
  button.primary { background: var(--accent); color: var(--surface);
                   border: none; border-radius: 8px; padding: 0.55em 1.2em;
                   font: inherit; cursor: pointer; }
  button.secondary { background: transparent; color: inherit;
                     border: 1px solid var(--field); border-radius: 8px;
                     padding: 0.55em 1.2em; font: inherit; cursor: pointer; }
  .bad { color: var(--warn); margin: 0; font-size: 0.9em; }
  #protection { margin-top: 2.5em; text-align: center; font-size: 0.9em;
                color: var(--muted); }
  #protection a { color: inherit; text-underline-offset: 3px; }
  #protection.off { color: var(--warn); background: var(--warn-soft);
                    border-radius: 8px; padding: 0.6em 1em; }
  .dot { display: inline-block; width: 0.55em; height: 0.55em;
         border-radius: 50%; background: var(--accent);
         margin-inline-end: 0.5em; vertical-align: 0.05em; }
  .off .dot { background: var(--warn); }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  .hidden { display: none; }
  @media (forced-colors: active) {
    #shortcuts a, .add, button { border: 1px solid ButtonText; }
  }
</style>
</head>
<body>
<main class="page">
  <h1 class="hidden">New tab</h1>
  <p class="hint">Type in the address bar to search or go to a site.</p>
  <ul id="shortcuts" aria-label="Shortcuts"></ul>
  <form id="add-form" class="hidden">
    <label>Name <input id="add-title" maxlength="40" autocomplete="off"></label>
    <label>Address <input id="add-url" autocomplete="off"
        placeholder="example.com"></label>
    <p id="add-bad" class="bad hidden" role="alert">That address does not
    look right. Try something like example.com.</p>
    <div class="buttons">
      <button class="primary" type="submit">Add shortcut</button>
      <button class="secondary" type="button" id="add-cancel">Cancel</button>
    </div>
  </form>
  <p id="protection" role="status"><span class="dot" aria-hidden="true"></span
  ><span id="protection-text">Checking protection</span></p>
</main>
<script src="newtab.js"></script>
</body>
</html>
)PAGE";

constexpr char kScript[] = R"SCRIPT(
function el(id) { return document.getElementById(id); }

function node(tag, className, text) {
  var n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
}

var shortcutCount = 0;

function showShortcuts(list) {
  var ul = el('shortcuts');
  ul.replaceChildren();
  shortcutCount = list.length;
  list.forEach(function(item, index) {
    var li = node('li');
    var a = node('a');
    a.href = item.url;
    var name = item.title || item.host;
    a.append(node('span', 'mark', (name || '?').charAt(0).toUpperCase()),
             node('span', 'name', name));
    a.setAttribute('aria-label', name);
    var remove = node('button', 'remove', '\u00d7');
    remove.type = 'button';
    remove.setAttribute('aria-label', 'Remove ' + name);
    remove.addEventListener('click', function() {
      chrome.send('removeShortcut', [index]);
    });
    li.append(a, remove);
    ul.append(li);
  });
  if (list.length < 8) {
    var li = node('li');
    var add = node('button', 'add');
    add.type = 'button';
    add.id = 'add-open';
    add.append(node('span', 'mark', '+'), node('span', 'name', 'Add shortcut'));
    add.addEventListener('click', openForm);
    li.append(add);
    ul.append(li);
  }
}

function openForm() {
  el('add-form').classList.remove('hidden');
  el('add-bad').classList.add('hidden');
  el('add-title').focus();
}

function closeForm() {
  el('add-form').classList.add('hidden');
  el('add-title').value = '';
  el('add-url').value = '';
  var open = el('add-open');
  if (open) open.focus();
}

el('add-form').addEventListener('submit', function(e) {
  e.preventDefault();
  chrome.send('addShortcut', [el('add-title').value, el('add-url').value]);
});
el('add-cancel').addEventListener('click', closeForm);

function showProtection(p) {
  var box = el('protection');
  var text = el('protection-text');
  text.replaceChildren();
  var link = node('a', '', '');
  link.href = 'chrome://boring-protection';
  if (p.scam === 'failed' || p.ads === 'failed') {
    box.className = 'off';
    text.append('Protection needs attention. ');
    link.textContent = 'See what is wrong';
  } else if (p.scam === 'ready' && p.ads === 'ready') {
    box.className = '';
    text.append('Scam and ad protection is on. ');
    link.textContent = 'Details';
  } else {
    box.className = '';
    text.append('Protection is starting. ');
    link.textContent = 'Details';
    setTimeout(function() { chrome.send('getProtection'); }, 2000);
  }
  text.append(link);
}

window.loadShortcuts = function(list, added, rejected) {
  showShortcuts(list);
  if (rejected) {
    el('add-bad').classList.remove('hidden');
    el('add-url').focus();
  } else if (added) {
    closeForm();
  }
};
window.loadProtection = showProtection;
chrome.send('getShortcuts');
chrome.send('getProtection');
)SCRIPT";

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

// Turns what a person typed into a web address, or an empty GURL when it
// is not one. Only http and https: a shortcut must never run script or
// open a local file.
GURL ShortcutUrl(const std::string& typed) {
  std::string text(base::TrimWhitespaceASCII(typed, base::TRIM_ALL));
  if (text.empty()) {
    return GURL();
  }
  GURL url(text);
  if (!url.is_valid() || !url.has_scheme() || !url.has_host()) {
    url = GURL("https://" + text);
  }
  if (!url.is_valid() || !url.SchemeIsHTTPOrHTTPS() || !url.has_host() ||
      url.host().find('.') == std::string::npos) {
    return GURL();
  }
  return url;
}

class NewTabMessageHandler : public content::WebUIMessageHandler {
 public:
  NewTabMessageHandler() = default;
  ~NewTabMessageHandler() override = default;

  void RegisterMessages() override {
    web_ui()->RegisterMessageCallback(
        "getShortcuts",
        base::BindRepeating(&NewTabMessageHandler::HandleGetShortcuts,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "addShortcut",
        base::BindRepeating(&NewTabMessageHandler::HandleAddShortcut,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "removeShortcut",
        base::BindRepeating(&NewTabMessageHandler::HandleRemoveShortcut,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "getProtection",
        base::BindRepeating(&NewTabMessageHandler::HandleGetProtection,
                            base::Unretained(this)));
  }

 private:
  PrefService* GetPrefs() {
    return user_prefs::UserPrefs::Get(
        web_ui()->GetWebContents()->GetBrowserContext());
  }

  void SendShortcuts(bool added, bool rejected) {
    base::ListValue list;
    if (PrefService* prefs = GetPrefs()) {
      for (const base::Value& item : prefs->GetList(kNewTabShortcutsPref)) {
        if (!item.is_dict()) {
          continue;
        }
        const std::string* title = item.GetDict().FindString("title");
        const std::string* url = item.GetDict().FindString("url");
        // Checked again on the way out, in case the profile was edited
        // by hand.
        GURL parsed = url ? ShortcutUrl(*url) : GURL();
        if (!parsed.is_valid()) {
          continue;
        }
        base::DictValue out;
        out.Set("title", title ? *title : std::string());
        out.Set("url", parsed.spec());
        out.Set("host", parsed.host());
        list.Append(std::move(out));
      }
    }
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe(
        "loadShortcuts", list, base::Value(added), base::Value(rejected));
  }

  void HandleGetShortcuts(const base::ListValue& args) {
    SendShortcuts(/*added=*/false, /*rejected=*/false);
  }

  void HandleAddShortcut(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (!prefs || args.size() < 2 || !args[0].is_string() ||
        !args[1].is_string()) {
      return;
    }
    GURL url = ShortcutUrl(args[1].GetString());
    if (!url.is_valid()) {
      SendShortcuts(/*added=*/false, /*rejected=*/true);
      return;
    }
    std::string title(
        base::TrimWhitespaceASCII(args[0].GetString(), base::TRIM_ALL));
    if (title.size() > kMaxTitleLength) {
      title.resize(kMaxTitleLength);
    }
    {
      ScopedListPrefUpdate update(prefs, kNewTabShortcutsPref);
      if (update->size() >= kMaxShortcuts) {
        SendShortcuts(/*added=*/false, /*rejected=*/false);
        return;
      }
      base::DictValue item;
      item.Set("title", title);
      item.Set("url", url.spec());
      update->Append(std::move(item));
    }
    SendShortcuts(/*added=*/true, /*rejected=*/false);
  }

  void HandleRemoveShortcut(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_int()) {
      int index = args[0].GetInt();
      ScopedListPrefUpdate update(prefs, kNewTabShortcutsPref);
      if (index >= 0 && static_cast<size_t>(index) < update->size()) {
        update->erase(update->begin() + index);
      }
    }
    SendShortcuts(/*added=*/false, /*rejected=*/false);
  }

  void HandleGetProtection(const base::ListValue& args) {
    ScamService* scam = ScamService::GetInstance();
    AdblockService* ads = AdblockService::GetInstance();
    scam->EnsureLoading();
    ads->EnsureLoading();
    base::DictValue out;
    out.Set("scam", StatusName(scam->status()));
    out.Set("ads", StatusName(ads->status()));
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("loadProtection", out);
  }
};

bool ShouldHandle(const std::string& path) {
  return path.empty() || path == "newtab.js";
}

void Handle(const std::string& path,
            content::WebUIDataSource::GotDataCallback callback) {
  std::string body =
      path == "newtab.js" ? std::string(kScript) : std::string(kPage);
  std::move(callback).Run(
      base::MakeRefCounted<base::RefCountedString>(std::move(body)));
}

}  // namespace

void RegisterNewTabPrefs(user_prefs::PrefRegistrySyncable* registry) {
  registry->RegisterListPref(kNewTabShortcutsPref);
}

BoringNewTabUI::BoringNewTabUI(content::WebUI* web_ui)
    : content::WebUIController(web_ui) {
  content::WebUIDataSource* source = content::WebUIDataSource::CreateAndAdd(
      web_ui->GetWebContents()->GetBrowserContext(), kBoringNewTabHost);
  source->SetRequestFilter(base::BindRepeating(&ShouldHandle),
                           base::BindRepeating(&Handle));
  web_ui->AddMessageHandler(std::make_unique<NewTabMessageHandler>());
}

BoringNewTabUI::~BoringNewTabUI() = default;

BoringNewTabUIConfig::BoringNewTabUIConfig()
    : content::DefaultWebUIConfig<BoringNewTabUI>(content::kChromeUIScheme,
                                                  kBoringNewTabHost) {}

}  // namespace boring
