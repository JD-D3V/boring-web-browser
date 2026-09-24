// Copyright 2026 boring. BSD style license.

#include "components/boring/newtab/newtab_ui.h"

#include <memory>
#include <string>

#include "base/functional/bind.h"
#include "base/memory/ref_counted_memory.h"
#include "base/memory/weak_ptr.h"
#include "base/strings/string_util.h"
#include "base/task/sequenced_task_runner.h"
#include "base/time/time.h"
#include "base/values.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/branding/brand_mark.h"
#include "components/boring/core/boring_capabilities.h"
#include "components/boring/scam/scam_service.h"
#include "components/boring/search/search_engines.h"
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

// The two shortcuts a fresh profile starts with. They are written once,
// the first time this page loads on a profile that has never had a
// shortcut list, see kNewTabDefaultsSeededPref below. "Reading" points at
// our own settings page; "Wikipedia" is a plain, useful web address.
constexpr char kNewTabDefaultsSeededPref[] = "boring.newtab.defaults_seeded";
constexpr char kDefaultReadingTitle[] = "Reading";
constexpr char kDefaultReadingUrl[] = "chrome://settings/reading";
constexpr char kDefaultWikipediaTitle[] = "Wikipedia";
constexpr char kDefaultWikipediaUrl[] = "https://www.wikipedia.org/";

constexpr char kPage[] = R"PAGE(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>New Tab</title>
<link rel="icon" type="image/svg+xml" href="brand.svg">
<style>
  :root { color-scheme: light dark;
    --surface: light-dark(#faf9f6, #1c2422);
    --paper: light-dark(#ffffff, #252e2b);
    --ink: light-dark(#242e2d, #e8ede7);
    --muted: light-dark(#5d6966, #adb9b2);
    --line: light-dark(#d8ddd7, #414e47);
    /* Field edges: 3:1 or more against the page in both themes. */
    --field: light-dark(#7d8985, #8b9891);
    --accent: light-dark(#176b5b, #92d4bb);
    --soft: light-dark(#e5f1eb, #273f35);
    --warn: light-dark(#9e3e24, #ffb69c);
    --warn-soft: light-dark(#fbebe4, #412f28);
  }
  * { box-sizing: border-box; }
  body { font: 15px/1.6 system-ui, sans-serif; margin: 0;
         background: var(--surface); color: var(--ink); }
  /* Always wins over any author display rule, no matter its specificity,
     so a form given the hidden attribute is always actually hidden. */
  [hidden] { display: none !important; }
  .home { max-width: 640px; margin: 0 auto; padding: 70px 24px 56px;
          text-align: center; }
  .home-brand { display: block; width: 44px; height: 44px;
                margin: 0 auto 24px; }
  .home h1 { font: 550 52px/1.08 system-ui, sans-serif;
       letter-spacing: -0.045em; color: var(--ink); margin: 12px 0 18px; }
  .intro { font-size: 15px; color: var(--muted); margin: 0 0 32px; }
  .search-form { position: relative; display: flex; align-items: center;
            gap: 10px;
            background: var(--paper); border: 1px solid var(--field);
            border-radius: 12px; padding: 5px 8px 5px 16px; margin: 0;
            box-shadow: 0 3px 12px #00000003; text-align: start; }
  .search-form:has(#q:focus-visible) { outline: 2px solid var(--accent);
            outline-offset: 3px; }
  .search-form .icon { flex: none; color: var(--muted); }
  .search-form .engine { width: auto; min-width: 36px; gap: 4px;
        display: flex; align-items: center; padding: 0 6px;
        color: var(--muted); }
  .engine-mark { width: 22px; height: 22px; border-radius: 6px;
        border: 1px solid var(--field); background: var(--paper);
        color: var(--ink); font: 600 12px/20px Georgia, serif;
        text-align: center; }
  .engines { position: absolute; top: calc(100% + 6px); left: 0;
        z-index: 2; min-width: 220px; margin: 0; padding: 6px;
        list-style: none; background: var(--paper);
        border: 1px solid var(--field); border-radius: 12px;
        box-shadow: 0 8px 24px #0000001a; }
  .engines[hidden] { display: none; }
  .search-form .engines button { width: 100%; height: auto; min-height: 36px;
        display: flex; align-items: center; gap: 10px; padding: 6px 10px;
        border-radius: 8px; text-align: start; font: inherit; }
  .search-form .engines button[aria-selected="true"] { font-weight: 600; }
  .search-form .engines button:disabled { cursor: default; color: var(--muted); }
  .engines .note { font-size: 12px; color: var(--muted);
        padding: 6px 10px 2px; }
  .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden;
        clip-path: inset(50%); white-space: nowrap; }
  .search-form input { flex: 1; min-width: 0; height: 36px;
       line-height: 36px; border: none; background: transparent;
       color: var(--ink); font: inherit; padding: 0; }
  .search-form input:focus-visible { outline: none; }
  .search-form input::placeholder { color: var(--muted); }
  .search-form button { flex: none; width: 36px; height: 36px; border: none;
        border-radius: 8px; background: transparent; color: var(--ink);
        display: grid; place-items: center; padding: 0; cursor: pointer; }
  .search-form button:hover { background: var(--soft); }
  .search-form button svg { display: block; }
  .shortcuts { display: flex; flex-wrap: wrap; justify-content: center;
               gap: 32px; margin: 30px 0 0; padding: 0; list-style: none; }
  .shortcuts li { position: relative; }
  .shortcut { display: flex; flex-direction: column;
                        align-items: center; gap: 10px; width: 72px;
                        color: inherit; text-decoration: none;
                        background: transparent; border: none;
                        padding: 9px; font: inherit; cursor: pointer; }
  .shortcut-mark { width: 42px; height: 42px; border-radius: 11px;
          display: grid; place-items: center; background: var(--paper);
          border: 1px solid var(--line); font: 21px/1 Georgia, serif;
          color: var(--ink); }
  .shortcut .name { max-width: 72px; overflow: hidden;
          text-overflow: ellipsis; white-space: nowrap; font-size: 12px;
          text-align: center; }
  .remove { position: absolute; top: 3px; right: -6px; width: 20px;
            height: 20px; border-radius: 8px; border: none; padding: 0;
            background: var(--paper); color: var(--muted);
            cursor: pointer; font: inherit; line-height: 1; opacity: 0;
            transition: opacity 120ms ease; }
  .shortcuts li:hover .remove, .remove:focus-visible { opacity: 1; }
  .editor { display: grid; gap: 10px; background: var(--paper);
              border: 1px solid var(--line); border-radius: 10px;
              padding: 16px 18px; margin-top: 24px; text-align: start; }
  .editor label { display: grid; gap: 4px; font-size: 13px;
                     color: var(--muted); }
  .editor input { border: 1px solid var(--field);
                     background: var(--surface); color: var(--ink);
                     border-radius: 8px; font: inherit;
                     padding: 8px 10px; }
  .buttons { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  button.primary { background: var(--accent); color: var(--surface);
                   border: none; border-radius: 9px; padding: 9px 16px;
                   font: inherit; cursor: pointer; }
  button.secondary { background: transparent; color: inherit;
                      border: 1px solid var(--line); border-radius: 9px;
                      padding: 9px 16px; font: inherit; cursor: pointer; }
  .text-button { background: none; border: none; padding: 0; margin: 0;
                 color: var(--accent); font: inherit; font-weight: 600;
                 font-size: 13px; cursor: pointer; text-decoration: none; }
  .bad { color: var(--warn); margin: 0; font-size: 13px; }
  .home-bottom { display: flex; gap: 9px; align-items: center;
                 justify-content: center; margin: 58px 0 0;
                 font-size: 12px; color: var(--muted); }
  .home-bottom.off { color: var(--warn); background: var(--warn-soft);
                    border-radius: 10px; padding: 10px 16px;
                    width: fit-content; max-width: 100%;
                    margin-inline: auto; }
  .status-dot { flex: none; width: 7px; height: 7px; border-radius: 50%;
         background: var(--accent); }
  .home-bottom.off .status-dot { background: var(--warn); }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  @media (max-width: 800px) {
    .home { padding-top: 48px; }
  }
  @media (max-width: 500px) {
    .home { padding-inline: 20px; }
    .home h1 { font-size: 40px; }
    .shortcuts { gap: 16px; }
    .home-bottom { flex-wrap: wrap; }
  }
  @media (prefers-reduced-motion: reduce) {
    .remove { transition: none; }
  }
  @media (forced-colors: active) {
    .shortcut, .shortcut-mark, .search-form, .editor input, button {
      border: 1px solid ButtonText;
    }
    .search-form:has(#q:focus-visible) { outline-color: Highlight; }
    .status-dot { background: CanvasText; forced-color-adjust: none; }
  }
</style>
</head>
<body>
<main class="home">
  <img class="home-brand" src="brand.svg" width="44" height="44" alt=""
      aria-hidden="true">
  <h1>Just a Browser.</h1>
  <p class="intro">Find what you came for.</p>
  <form class="search-form" id="search" role="search">
    <button id="engine" class="engine" type="button"
        aria-haspopup="listbox" aria-expanded="false"
        aria-controls="engines" aria-label="Choose a search engine">
      <span class="engine-mark" id="engine-mark" aria-hidden="true">?</span>
      <svg aria-hidden="true" focusable="false" width="10" height="10"
          viewBox="0 0 10 10">
        <polyline points="2,3.5 5,6.5 8,3.5" fill="none"
            stroke="currentColor" stroke-width="1.5"
            stroke-linecap="round"/>
      </svg>
    </button>
    <ul class="engines" id="engines" role="listbox"
        aria-label="Search engines" hidden></ul>
    <p class="sr-only" id="engine-status" role="status"></p>
    <input id="q" type="search" autocomplete="off" spellcheck="false"
        aria-label="Search the web">
    <button id="go" type="submit" aria-label="Search">
      <svg aria-hidden="true" focusable="false" width="16" height="16"
          viewBox="0 0 20 20">
        <line x1="4" y1="10" x2="15" y2="10" stroke="currentColor"
            stroke-width="1.8" stroke-linecap="round"/>
        <polyline points="10,5 15,10 10,15" fill="none"
            stroke="currentColor" stroke-width="1.8"
            stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
  </form>
  <ul class="shortcuts" id="shortcuts" aria-label="Shortcuts"></ul>
  <form class="editor" id="add-form" hidden>
    <label>Name <input id="add-title" maxlength="40" autocomplete="off"></label>
    <label>Address <input id="add-url" autocomplete="off"
        placeholder="example.com"></label>
    <p id="add-bad" class="bad" hidden role="alert">Not a web address.</p>
    <div class="buttons">
      <button class="primary" type="submit">Add</button>
      <button class="secondary" type="button" id="add-cancel">Cancel</button>
      <a class="text-button" href="chrome://settings/appearance">More appearance settings</a>
    </div>
  </form>
  <p class="home-bottom" id="protection" hidden role="status">
    <span class="status-dot" aria-hidden="true"></span>
    <span id="protection-text"></span>
  </p>
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
    var a = node('a', 'shortcut');
    a.href = item.url;
    var name = item.title || item.host;
    a.append(node('span', 'shortcut-mark', (name || '?').charAt(0).toUpperCase()),
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
    var add = node('button', 'shortcut');
    add.type = 'button';
    add.id = 'add-open';
    add.setAttribute('aria-label', 'Customize shortcuts');
    add.append(node('span', 'shortcut-mark', '\uff0b'),
               node('span', 'name', 'Customize'));
    add.addEventListener('click', openForm);
    li.append(add);
    ul.append(li);
  }
}

function openForm() {
  el('add-form').hidden = false;
  el('add-bad').hidden = true;
  el('add-title').focus();
}

function closeForm() {
  el('add-form').hidden = true;
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

// Only claims a state the browser can actually back up: real status from
// the scam and ad-blocking services, never a guess, and never nothing
// while there is something true to say.
function showProtection(p) {
  var box = el('protection');
  var text = el('protection-text');
  // 'off' is a state this browser can back up as much as 'ready' is:
  // it means no scam list ships, which is true and not a fault.
  var scamOk = p.scam === 'ready' || p.scam === 'off';
  var ready = scamOk && p.ads === 'ready';
  var failed = p.scam === 'failed' || p.ads === 'failed';
  text.replaceChildren();
  if (failed) {
    box.hidden = false;
    box.classList.add('off');
    var details = node('a', 'text-button', 'View →');
    details.href = 'chrome://settings/protection';
    text.append('Protection needs attention. ', details);
  } else if (ready) {
    box.hidden = false;
    box.classList.remove('off');
    var view = node('a', 'text-button', 'View →');
    view.href = 'chrome://settings/protection';
    text.append('Protection is on. You\u2019re in control. ', view);
  } else {
    box.hidden = true;
    setTimeout(function() { chrome.send('getProtection'); }, 2000);
  }
}

var searchUrl = '';
// Set while a choice is on its way, so the answer is read out once.
var choosing = false;

el('search').addEventListener('submit', function(e) {
  e.preventDefault();
  var typed = el('q').value.trim();
  if (!typed || !searchUrl) return;
  location.href = searchUrl.replace('%s', encodeURIComponent(typed));
});

var engineList = el('engines');
var engineButton = el('engine');

function closeEngines(focusButton) {
  engineList.hidden = true;
  engineButton.setAttribute('aria-expanded', 'false');
  if (focusButton) engineButton.focus();
}

function openEngines() {
  engineList.hidden = false;
  engineButton.setAttribute('aria-expanded', 'true');
  var current = engineList.querySelector('[aria-selected="true"]') ||
      engineList.querySelector('button:not(:disabled)');
  if (current) current.focus();
}

engineButton.addEventListener('click', function() {
  if (engineList.hidden) {
    openEngines();
  } else {
    closeEngines(true);
  }
});

engineButton.addEventListener('keydown', function(e) {
  if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && engineList.hidden) {
    e.preventDefault();
    openEngines();
  }
});

// Arrow keys, Home and End move between the engines that can be chosen.
// A disabled one cannot take focus, so it is skipped rather than left
// to stop the arrows there.
engineList.addEventListener('keydown', function(e) {
  var items = Array.from(engineList.querySelectorAll('button:not(:disabled)'));
  var at = items.indexOf(document.activeElement);
  var next = -1;
  if (e.key === 'Escape') {
    e.preventDefault();
    closeEngines(true);
    return;
  }
  if (!items.length) return;
  if (e.key === 'ArrowDown') {
    next = (at + 1) % items.length;
  } else if (e.key === 'ArrowUp') {
    next = (at - 1 + items.length) % items.length;
  } else if (e.key === 'Home') {
    next = 0;
  } else if (e.key === 'End') {
    next = items.length - 1;
  }
  if (next >= 0) {
    e.preventDefault();
    items[next].focus();
  }
});

// Tab, or a click somewhere else, closes the list, so it is never left
// open behind the focus.
engineList.addEventListener('focusout', function(e) {
  if (!engineList.hidden && !engineList.contains(e.relatedTarget) &&
      e.relatedTarget !== engineButton) {
    closeEngines(false);
  }
});

document.addEventListener('click', function(e) {
  if (!engineList.hidden && !el('search').contains(e.target)) {
    closeEngines(false);
  }
});

function showEngines(engines, canChange) {
  engineList.textContent = '';
  engines.forEach(function(engine) {
    var item = document.createElement('li');
    item.setAttribute('role', 'none');
    var pick = document.createElement('button');
    pick.type = 'button';
    pick.tabIndex = -1;
    pick.setAttribute('role', 'option');
    pick.setAttribute('aria-selected', engine.isDefault ? 'true' : 'false');
    var mark = document.createElement('span');
    mark.className = 'engine-mark';
    mark.setAttribute('aria-hidden', 'true');
    mark.textContent = (engine.name || '?').charAt(0).toUpperCase();
    pick.append(mark, engine.name);
    pick.disabled = !engine.isDefault && (!canChange || !engine.canBeDefault);
    pick.addEventListener('click', function() {
      closeEngines(true);
      if (!engine.isDefault) {
        choosing = true;
        chrome.send('setSearchEngine', [engine.id]);
      }
    });
    item.append(pick);
    engineList.append(item);
  });
  engineList.removeAttribute('aria-describedby');
  if (!canChange) {
    var note = document.createElement('li');
    note.className = 'note';
    note.id = 'engines-note';
    note.setAttribute('role', 'none');
    note.textContent = 'Change the search engine in a normal window.';
    engineList.append(note);
    engineList.setAttribute('aria-describedby', 'engines-note');
  }
  // With search off, even one engine is worth offering.
  engineButton.hidden = engines.length < (searchUrl ? 2 : 1);
}

window.loadSearch = function(engine) {
  if (choosing) {
    choosing = false;
    el('engine-status').textContent =
        'Search engine: ' + (engine.name || 'none');
  }
  searchUrl = engine.url || '';
  var engines = engine.engines || [];
  // No engine to search with, for example after "No Search" in
  // settings: say so, and keep the list so one can be chosen here.
  el('q').disabled = !searchUrl;
  el('q').placeholder = searchUrl ? 'Search ' + (engine.name || 'the web') :
                                    'Search is off. Choose an engine.';
  el('engine-mark').textContent =
      searchUrl ? (engine.name || '?').charAt(0).toUpperCase() : '?';
  engineButton.setAttribute('aria-label', searchUrl ?
      'Search engine: ' + (engine.name || 'none') + '. Choose another' :
      'Choose a search engine');
  showEngines(engines, engine.canChange);
  el('search').hidden = !searchUrl && !engines.length;
};

window.loadShortcuts = function(list, added, rejected) {
  showShortcuts(list);
  if (rejected) {
    el('add-bad').hidden = false;
    el('add-url').focus();
  } else if (added) {
    closeForm();
  }
};
window.loadProtection = showProtection;
chrome.send('getShortcuts');
chrome.send('getSearch');
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

// A shortcut address a person could never type into the add form above
// (that only ever accepts http/https), but that our own code is willing
// to seed as a default: one of our own settings pages.
bool IsAllowedInternalShortcut(const GURL& url) {
  return url.is_valid() && url.SchemeIs(content::kChromeUIScheme) &&
         url.host() == "settings" && url.path() == "/reading";
}

// Where the address bar sends a search. The prefs hold a template with
// {searchTerms} in it, and are only written once someone picks an
// engine, so until then it is the one we ship with. The first is not
// always written; the mirrored copy is, whenever the default changes.
constexpr const char* kSearchEnginePrefs[] = {
    "default_search_provider_data.template_url_data",
    "default_search_provider_data.mirrored_template_url_data",
};
constexpr char kDefaultSearchName[] = "DuckDuckGo";
constexpr char kDefaultSearchUrl[] = "https://duckduckgo.com/?q=%s";

// Turns a search engine's template into a plain url with one %s where the
// typed words go. Returns nothing if it is not a web address we can use.
std::string SearchUrlFromTemplate(const std::string& engine_url) {
  const std::string terms = "{searchTerms}";
  size_t at = engine_url.find(terms);
  if (at == std::string::npos) {
    return std::string();
  }
  std::string url = engine_url;
  url.replace(at, terms.size(), "%s");
  // Drop the other {...} parts, which stand for things like the client id
  // and are optional.
  while ((at = url.find('{')) != std::string::npos) {
    size_t end = url.find('}', at);
    if (end == std::string::npos) {
      return std::string();
    }
    url.erase(at, end - at + 1);
  }
  GURL parsed(url);
  return parsed.is_valid() && parsed.SchemeIsHTTPOrHTTPS() ? url
                                                           : std::string();
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
        "setSearchEngine",
        base::BindRepeating(&NewTabMessageHandler::HandleSetSearchEngine,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "getSearch", base::BindRepeating(&NewTabMessageHandler::HandleGetSearch,
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
        // by hand. A default we seeded ourselves (see
        // EnsureDefaultShortcuts) can point at one of our own settings
        // pages; anything else has to be a plain http(s) address.
        GURL parsed = url ? ShortcutUrl(*url) : GURL();
        if (!parsed.is_valid() && url) {
          GURL internal(*url);
          if (IsAllowedInternalShortcut(internal)) {
            parsed = internal;
          }
        }
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
    EnsureDefaultShortcuts(GetPrefs());
    SendShortcuts(/*added=*/false, /*rejected=*/false);
  }

  // Writes the two default shortcuts the very first time this page loads
  // on a profile, and never again. Once boring.newtab.defaults_seeded is
  // set, a person's own edits, including removing everything, are never
  // quietly put back.
  void EnsureDefaultShortcuts(PrefService* prefs) {
    if (!prefs || prefs->GetBoolean(kNewTabDefaultsSeededPref)) {
      return;
    }
    {
      ScopedListPrefUpdate update(prefs, kNewTabShortcutsPref);
      if (update->empty()) {
        base::DictValue reading;
        reading.Set("title", kDefaultReadingTitle);
        reading.Set("url", kDefaultReadingUrl);
        update->Append(std::move(reading));
        base::DictValue wiki;
        wiki.Set("title", kDefaultWikipediaTitle);
        wiki.Set("url", kDefaultWikipediaUrl);
        update->Append(std::move(wiki));
      }
    }
    prefs->SetBoolean(kNewTabDefaultsSeededPref, true);
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

  // Makes the chosen engine the browser's default, then shows it. The
  // address bar follows, because this is the same default it reads.
  void HandleSetSearchEngine(const base::ListValue& args) {
    if (!args.empty() && args[0].is_string()) {
      SetDefaultSearchEngine(web_ui()->GetWebContents()->GetBrowserContext(),
                             args[0].GetString());
    }
    HandleGetSearch(args);
  }

  void HandleGetSearch(const base::ListValue& args) {
    content::BrowserContext* context =
        web_ui()->GetWebContents()->GetBrowserContext();
    base::ListValue engines;
    std::string name;
    std::string url;
    for (const SearchEngine& engine : GetSearchEngines(context)) {
      base::DictValue item;
      item.Set("id", engine.id);
      item.Set("name", engine.name);
      item.Set("isDefault", engine.is_default);
      item.Set("canBeDefault", engine.can_be_default);
      engines.Append(std::move(item));
      if (engine.is_default) {
        name = engine.name;
        url = SearchUrlFromTemplate(engine.url);
      }
    }
    // Whenever there is a list, it is shown, even with no engine to
    // search with as the default ("No Search" in settings, which the
    // list leaves out): the page then says search is off and offers
    // the list, rather than showing nothing.
    if (!engines.empty()) {
      base::DictValue out;
      out.Set("name", name);
      out.Set("url", url);
      out.Set("engines", std::move(engines));
      out.Set("canChange", !context->IsOffTheRecord());
      AllowJavascript();
      web_ui()->CallJavascriptFunctionUnsafe("loadSearch", out);
      return;
    }

    // The engine list is not loaded yet: fall back to the pref, and ask
    // again shortly for the list. Once someone has chosen, the choice
    // stands, even one that turns search off; only a profile that never
    // chose gets the engine we ship with.
    name = kDefaultSearchName;
    url = kDefaultSearchUrl;
    if (PrefService* prefs = GetPrefs()) {
      for (const char* pref : kSearchEnginePrefs) {
        const base::DictValue& engine = prefs->GetDict(pref);
        if (const std::string* engine_url = engine.FindString("url")) {
          url = SearchUrlFromTemplate(*engine_url);
          const std::string* short_name = engine.FindString("short_name");
          name = short_name ? *short_name : std::string();
          break;
        }
      }
    }
    base::DictValue out;
    out.Set("name", name);
    out.Set("url", url);
    out.Set("engines", base::ListValue());
    out.Set("canChange", false);
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("loadSearch", out);
    if (search_retries_ < kMaxSearchRetries) {
      ++search_retries_;
      base::SequencedTaskRunner::GetCurrentDefault()->PostDelayedTask(
          FROM_HERE,
          base::BindOnce(&NewTabMessageHandler::RetryGetSearch,
                         weak_factory_.GetWeakPtr()),
          base::Seconds(1));
    }
  }

  void RetryGetSearch() { HandleGetSearch(base::ListValue()); }

  void HandleGetProtection(const base::ListValue& args) {
    ScamService* scam = ScamService::GetInstance();
    AdblockService* ads = AdblockService::GetInstance();
    if (kScamBlockingAvailable) {
      scam->EnsureLoading();
    }
    ads->EnsureLoading();
    base::DictValue out;
    out.Set("scam",
            kScamBlockingAvailable ? StatusName(scam->status()) : "off");
    out.Set("ads", StatusName(ads->status()));
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("loadProtection", out);
  }

  // A few more tries for the engine list if it was not loaded yet.
  static constexpr int kMaxSearchRetries = 5;
  int search_retries_ = 0;
  base::WeakPtrFactory<NewTabMessageHandler> weak_factory_{this};
};

bool ShouldHandle(const std::string& path) {
  return path.empty() || path == "newtab.js" || path == "brand.svg";
}

void Handle(const std::string& path,
            content::WebUIDataSource::GotDataCallback callback) {
  // brand.svg is the tab icon and the mark above the heading. Its type
  // comes from the .svg ending (WebUIDataSourceImpl::GetMimeType).
  std::string body;
  if (path == "newtab.js") {
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

void RegisterNewTabPrefs(user_prefs::PrefRegistrySyncable* registry) {
  registry->RegisterListPref(kNewTabShortcutsPref);
  registry->RegisterBooleanPref(kNewTabDefaultsSeededPref, false);
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
