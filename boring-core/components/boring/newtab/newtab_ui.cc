// Copyright 2026 boring. BSD style license.

#include "components/boring/newtab/newtab_ui.h"

#include <memory>
#include <optional>
#include <string>
#include <vector>

#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/memory/ref_counted_memory.h"
#include "base/memory/weak_ptr.h"
#include "base/strings/string_util.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/cancelable_task_tracker.h"
#include "base/time/time.h"
#include "base/values.h"
#include "components/boring/accounts/accounts_store.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/branding/brand_mark.h"
#include "components/boring/core/boring_capabilities.h"
#include "components/boring/newtab/search_engine_menu.h"
#include "components/boring/scam/scam_service.h"
#include "components/pref_registry/pref_registry_syncable.h"
#include "components/prefs/pref_change_registrar.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/page_navigator.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_data_source.h"
#include "content/public/browser/web_ui_message_handler.h"
#include "content/public/common/referrer.h"
#include "content/public/common/url_constants.h"
#include "ui/base/page_transition_types.h"
#include "ui/base/window_open_disposition.h"
#include "url/gurl.h"

namespace boring {

namespace {

// Enough to be useful, few enough that the page stays calm.
constexpr size_t kMaxShortcuts = 8;
constexpr size_t kMaxTitleLength = 40;
// "Pick up where you left off" shows this many pages, as drawn.
constexpr size_t kMaxRecentPages = 3;
constexpr size_t kMaxRecentTitleLength = 200;

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
<link rel="stylesheet" href="chrome://theme/colors.css?sets=ui,chrome">
<style>
  /* The colours are the window's own (chrome://theme/colors.css), so the
     page follows the Look and the accent the person chose. The TOKENS
     rows of the compiled design, light and dark, are the fallbacks. */
  :root { color-scheme: light dark;
    --page: var(--color-new-tab-page-background, light-dark(#f8f7f4, #151514));
    --surface: var(--color-toolbar, light-dark(#ffffff, #1c1c1a));
    --field: var(--color-location-bar-background, light-dark(#f4f3ef, #121211));
    --hover: light-dark(#ebe9e4, #333330);
    --line: var(--color-toolbar-separator, light-dark(#e2dfd9, #2d2d2a));
    --edge: var(--color-boring-edge, light-dark(#8a867d, #77756d));
    --ink: var(--color-toolbar-text, light-dark(#1f1e1c, #ecebe7));
    --ink2: var(--color-toolbar-button-icon-inactive, light-dark(#5d5a54, #a9a79f));
    --ok: light-dark(#1a7f55, #4cc38a);
    --bad: light-dark(#a3271c, #ff9a8f);
    --bad-tint: light-dark(#fbe6e3, #3b1c1a);
    --solid: light-dark(#1a1c22, #e8e9ed);
    --solid-ink: light-dark(#ffffff, #14151a);
    --accent: var(--color-sys-primary, light-dark(#4f46e5, #9b98ff));
  }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: flex; flex-direction: column;
         align-items: center; background: var(--page); color: var(--ink);
         font: 13px/1.4 system-ui, "Segoe UI", sans-serif; }
  /* Always wins over any author display rule, no matter its specificity,
     so a form given the hidden attribute is always actually hidden. */
  [hidden] { display: none !important; }
  button { font: inherit; color: inherit; border: 0; background: none;
           padding: 0; cursor: pointer; text-align: start; }
  /* The account chips (Accounts, below). */
  .top { align-self: stretch; height: 56px; flex: none; display: flex;
         align-items: center; justify-content: flex-end; gap: 6px;
         padding: 0 20px; }
  /* boring: Accounts. A chip per account, as drawn (PageNewTab), then Add
     account. The circle colours are set from the script. */
  .chip { height: 34px; display: flex; align-items: center; gap: 9px;
          padding: 0 12px 0 5px; border-radius: 17px; min-width: 0;
          background: var(--surface); box-shadow: inset 0 0 0 1px var(--line);
          color: var(--ink); text-decoration: none; white-space: nowrap;
          transition: background-color 150ms ease-out,
                      transform 120ms ease-out; }
  .chip:active { transform: scale(0.98); }
  @media (hover: hover) { .chip:hover { background: var(--hover); } }
  .chip-mark { width: 24px; height: 24px; flex: none; display: grid;
               place-items: center; border-radius: 12px; font-size: 12px;
               font-weight: 600; color: var(--solid-ink); }
  .chip .name { font-weight: 500; max-width: 160px; overflow: hidden;
                text-overflow: ellipsis; }
  .chip .provider { color: var(--ink2); }
  .chip.add { gap: 6px; padding: 0 12px; background: transparent;
              color: var(--ink2); box-shadow: inset 0 0 0 1px var(--edge); }
  @media (prefers-reduced-motion: reduce) {
    .chip { transition: none; }
    .chip:active { transform: none; }
  }
  @media (forced-colors: active) {
    .chip { border: 1px solid ButtonText; }
    .chip-mark { border: 1px solid CanvasText; }
  }
  /* boring: end Accounts. */
  .home { width: 640px; max-width: calc(100% - 40px); margin-top: 44px;
          display: flex; flex-direction: column; gap: 32px; }
  section { display: flex; flex-direction: column; gap: 12px; }
  .head { display: flex; align-items: center; justify-content: space-between; }
  .label { margin: 0; font-size: 12.5px; font-weight: 500; color: var(--ink2); }
  .edit { font-size: 12.5px; color: var(--ink2); border-radius: 5px; }
  @media (hover: hover) { .edit:hover { color: var(--ink); } }
  .shortcuts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
               gap: 10px; margin: 0; padding: 0; list-style: none; }
  .shortcuts li { position: relative; min-width: 0; }
  /* Tiles arrive once per page load, a few ms apart. */
  @keyframes tile-in { from { opacity: 0; transform: translateY(6px); } }
  @keyframes tile-fade { from { opacity: 0; } }
  .shortcuts.appear li { animation: tile-in 220ms ease-out both;
        animation-delay: calc(var(--i, 0) * 30ms); }
  .shortcut { width: 100%; height: 52px; display: flex; align-items: center;
              gap: 12px; padding: 0 12px; border-radius: 9px;
              text-decoration: none; color: var(--ink);
              background: var(--surface); box-shadow: inset 0 0 0 1px var(--edge);
              transition: background-color 150ms ease-out,
                          transform 120ms ease-out; }
  .shortcut:active { transform: scale(0.98); }
  @media (hover: hover) { .shortcut:hover { background: var(--hover); } }
  .shortcut-mark { width: 28px; height: 28px; flex: none; display: grid;
                   place-items: center; border-radius: 7px;
                   background: var(--field); color: var(--ink);
                   font-size: 13px; font-weight: 600; }
  .shortcut .name { min-width: 0; overflow: hidden; text-overflow: ellipsis;
                    white-space: nowrap; font-weight: 500; }
  .shortcut.add { color: var(--ink2); background: transparent;
                  box-shadow: inset 0 0 0 1px var(--edge); }
  /* Remove and Add a site show while editing; Add a site also shows when
     there is nothing pinned, so the grid is never an empty box. */
  .pinned:not(.editing) .remove,
  .pinned:not(.editing):not(.empty) .shortcut.add { display: none; }
  .remove { position: absolute; top: -8px; right: -8px; width: 24px;
            height: 24px; border-radius: 12px; display: grid;
            place-items: center; line-height: 1; color: var(--ink2);
            background: var(--surface); box-shadow: 0 0 0 1px var(--line);
            transition: transform 120ms ease-out; }
  .remove:active { transform: scale(0.92); }
  @media (hover: hover) { .remove:hover { color: var(--ink); } }
  .editor { display: grid; gap: 10px; padding: 16px 18px;
            border-radius: 10px; background: var(--surface);
            box-shadow: 0 0 0 1px var(--line); }
  .editor label { display: grid; gap: 4px; font-size: 13px; color: var(--ink2); }
  .editor input { height: 34px; padding: 0 10px; border: 0;
                  border-radius: 7px; background: var(--field);
                  color: var(--ink); font: inherit;
                  box-shadow: inset 0 0 0 1px var(--edge); }
  .buttons { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  .primary, .secondary { height: 32px; padding: 0 14px; border-radius: 7px;
                         font-weight: 500;
                         transition: transform 120ms ease-out; }
  .primary { background: var(--solid); color: var(--solid-ink); }
  .secondary { box-shadow: inset 0 0 0 1px var(--edge); }
  .primary:active, .secondary:active { transform: scale(0.98); }
  .text-link { color: var(--ink); text-decoration: underline;
               text-underline-offset: 3px; }
  .bad { color: var(--bad); margin: 0; font-size: 13px; }
  .recent-list { margin: 0; padding: 0; list-style: none; border-radius: 10px;
                 background: var(--surface); box-shadow: 0 0 0 1px var(--line); }
  .recent-list li + li { box-shadow: inset 0 1px 0 var(--line); }
  .recent-row { height: 42px; display: flex; align-items: center; gap: 12px;
                padding: 0 14px; text-decoration: none; color: var(--ink);
                border-radius: 10px; }
  @media (hover: hover) { .recent-row:hover { background: var(--hover); } }
  .recent-row svg { flex: none; }
  .recent-row .title { flex: 1; min-width: 0; overflow: hidden;
                       text-overflow: ellipsis; white-space: nowrap; }
  /* The host is never hidden or cut: the page's own title gives way first. */
  .recent-row .site { flex: none; color: var(--ink2); white-space: nowrap; }
  .recent-row .when { width: 70px; flex: none; text-align: end;
                      font-size: 12px; color: var(--ink2); }
  .spacer { flex: 1; }
  .protection { margin: 32px 0 22px; display: flex; align-items: center;
                gap: 8px; font-size: 12.5px; color: var(--ink2); }
  .protection svg { flex: none; color: var(--ok); }
  .protection.off { padding: 8px 14px; border-radius: 9px;
                    color: var(--bad); background: var(--bad-tint); }
  .protection.off svg { color: var(--bad); }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  @media (max-width: 560px) {
    .shortcuts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @media (prefers-reduced-motion: reduce) {
    .shortcut, .remove, .primary, .secondary { transition: none; }
    .shortcut:active, .remove:active, .primary:active,
    .secondary:active { transform: none; }
    .shortcuts.appear li { animation: tile-fade 150ms ease-out both;
          animation-delay: 0ms; }
  }
  @media (forced-colors: active) {
    .shortcut, .remove, .editor input, .recent-list, button {
      border: 1px solid ButtonText;
    }
    .protection svg { color: CanvasText; }
  }
</style>
</head>
<body>
<div class="top" id="accounts"></div>
<main class="home">
  <section class="pinned" id="pinned" aria-labelledby="pinned-label">
    <div class="head">
      <h2 class="label" id="pinned-label">Pinned sites</h2>
      <button class="edit" id="edit" type="button" aria-pressed="false">Edit</button>
    </div>
    <ul class="shortcuts" id="shortcuts" aria-labelledby="pinned-label"></ul>
    <form class="editor" id="add-form" hidden>
      <label>Name <input id="add-title" maxlength="40" autocomplete="off"></label>
      <label>Address <input id="add-url" autocomplete="off"
             placeholder="example.com" spellcheck="false"></label>
      <p id="add-bad" class="bad" hidden role="alert">Not a web address.</p>
      <div class="buttons">
        <button class="primary" type="submit">Add</button>
        <button class="secondary" type="button" id="add-cancel">Cancel</button>
      </div>
    </form>
  </section>
  <section id="recent" aria-labelledby="recent-label" hidden>
    <h2 class="label" id="recent-label">Pick up where you left off</h2>
    <ul class="recent-list" id="recent-list" aria-labelledby="recent-label"></ul>
  </section>
</main>
<div class="spacer"></div>
<p class="protection" id="protection" hidden role="status">
  <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
       stroke="currentColor" stroke-width="2" stroke-linejoin="round"
       aria-hidden="true"><path d="M12 3l7.5 2.8v5.7c0 4.3-3 7.7-7.5 9-4.5-1.3-7.5-4.7-7.5-9V5.8z"></path></svg>
  <span id="protection-text"></span>
</p>
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

// A 2px line icon, as the design draws them.
function glyph(d, size) {
  var ns = 'http://www.w3.org/2000/svg';
  var svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  var path = document.createElementNS(ns, 'path');
  path.setAttribute('d', d);
  svg.append(path);
  return svg;
}

var shortcutCount = 0;
var tilesShown = false;

function showShortcuts(list) {
  var ul = el('shortcuts');
  ul.replaceChildren();
  shortcutCount = list.length;
  // Only the first time: a tile added or removed later should not make
  // the whole grid arrive again.
  ul.classList.toggle('appear', !tilesShown);
  tilesShown = true;
  el('pinned').classList.toggle('empty', list.length === 0);
  list.forEach(function(item, index) {
    var li = node('li');
    li.style.setProperty('--i', index);
    var a = node('a', 'shortcut');
    a.href = item.url;
    var name = item.title || item.host;
    a.append(node('span', 'shortcut-mark', (name || '?').charAt(0).toUpperCase()),
             node('span', 'name', name));
    a.setAttribute('aria-label', name);
    var remove = node('button', 'remove', '×');
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
    li.style.setProperty('--i', list.length);
    var add = node('button', 'shortcut add');
    add.type = 'button';
    add.id = 'add-open';
    add.append(node('span', 'shortcut-mark', '+'),
               node('span', 'name', 'Add a site'));
    add.addEventListener('click', openForm);
    li.append(add);
    ul.append(li);
  }
}

// Edit shows the remove buttons and Add a site; Done hides them again.
function setEditing(on) {
  el('pinned').classList.toggle('editing', on);
  el('edit').textContent = on ? 'Done' : 'Edit';
  el('edit').setAttribute('aria-pressed', on ? 'true' : 'false');
  if (!on) closeForm();
}
el('edit').addEventListener('click', function() {
  setEditing(!el('pinned').classList.contains('editing'));
});

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

// Today, Yesterday, a weekday within the week, a date before that.
function whenText(ms) {
  var then = new Date(ms);
  var day = new Date(ms);
  day.setHours(0, 0, 0, 0);
  var today = new Date();
  today.setHours(0, 0, 0, 0);
  var days = Math.round((today - day) / 86400000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return then.toLocaleDateString(undefined, {weekday: 'long'});
  return then.toLocaleDateString(undefined, {day: 'numeric', month: 'short'});
}

var PAGE_ICON = 'M6.5 3.5h7.5l4 4V20.5h-11.5zM14 3.5v4h4M9.5 12h5M9.5 15.5h5';

// The last few pages from history. Titles come from the sites, so they
// only ever go in as text.
window.loadRecent = function(list) {
  var ul = el('recent-list');
  ul.replaceChildren();
  list.forEach(function(item) {
    var li = node('li');
    var a = node('a', 'recent-row');
    a.href = item.url;
    a.append(glyph(PAGE_ICON, 15),
             node('span', 'title', item.title || item.host),
             node('span', 'site', item.host),
             node('span', 'when', whenText(item.when)));
    li.append(a);
    ul.append(li);
  });
  el('recent').hidden = list.length === 0;
};

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
  var details = node('a', 'text-link', 'Details');
  details.href = 'chrome://settings/protection';
  if (failed) {
    box.hidden = false;
    box.classList.add('off');
    text.append('Protection needs attention. ', details);
  } else if (ready) {
    box.hidden = false;
    box.classList.remove('off');
    text.append('Protection is on. ', details);
  } else {
    box.hidden = true;
    setTimeout(function() { chrome.send('getProtection'); }, 2000);
  }
}

// boring: Accounts. Chips for the accounts the person keeps (Settings,
// Accounts), in their order. Names are the person's own text, so they only
// ever go in as text. A chip asks the browser to open that account's mail
// in this tab by id; the address never reaches the page. null means this
// window shows none (Incognito, guest).
var ACCOUNT_COLOURS = [
  'var(--accent)',
  'var(--color-tab-group-tab-strip-frame-active-cyan, light-dark(#0f6f66, #6fcfc4))',
  'var(--color-tab-group-tab-strip-frame-active-blue, light-dark(#2f5fb3, #8ab4f8))',
  'var(--color-tab-group-tab-strip-frame-active-red, light-dark(#b3261e, #f28b82))',
  'var(--color-tab-group-tab-strip-frame-active-yellow, light-dark(#835c00, #f2c35b))',
  'var(--color-tab-group-tab-strip-frame-active-green, light-dark(#1e7a3c, #7fcf96))',
  'var(--color-tab-group-tab-strip-frame-active-pink, light-dark(#ad2f69, #f48fb9))',
  'var(--color-tab-group-tab-strip-frame-active-purple, light-dark(#6b45b8, #c3a6f5))',
  'var(--color-tab-group-tab-strip-frame-active-orange, light-dark(#9c4700, #f5a35c))'
];
var PLUS_ICON = 'M12 5v14M5 12h14';
window.loadAccounts = function(list) {
  var row = el('accounts');
  row.replaceChildren();
  if (!list) return;
  list.forEach(function(item, index) {
    var chip = node('button', 'chip');
    chip.type = 'button';
    var mark = node('span', 'chip-mark', item.initial);
    mark.setAttribute('aria-hidden', 'true');
    var colour = index === 0 ? 0 : 1 + (index - 1) % (ACCOUNT_COLOURS.length - 1);
    mark.style.background = ACCOUNT_COLOURS[colour];
    if (colour === 0) {
      mark.style.color = 'var(--color-sys-on-primary, var(--solid-ink))';
    }
    chip.append(mark, node('span', 'name', item.name),
                node('span', 'provider', item.provider));
    chip.setAttribute('aria-label', item.name + ', ' + item.provider + ' mail');
    chip.addEventListener('click', function() {
      chrome.send('openAccount', [item.id]);
    });
    row.append(chip);
  });
  var add = node('a', 'chip add');
  add.href = 'chrome://settings/accounts';
  var plus = glyph(PLUS_ICON, 14);
  plus.setAttribute('stroke-width', '1.7');
  add.append(plus, 'Add account');
  row.append(add);
};
// boring: end Accounts.

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
// Test only, see kSearchMenuTestSwitch.
window.searchMenuTestResult = function(result) {
  window.lastSearchMenuTest = result;
};
chrome.send('getAccounts');
chrome.send('getShortcuts');
chrome.send('getRecent');
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
        "getRecent",
        base::BindRepeating(&NewTabMessageHandler::HandleGetRecent,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "getProtection",
        base::BindRepeating(&NewTabMessageHandler::HandleGetProtection,
                            base::Unretained(this)));
    // boring: Accounts.
    web_ui()->RegisterMessageCallback(
        "getAccounts",
        base::BindRepeating(&NewTabMessageHandler::HandleGetAccounts,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "openAccount",
        base::BindRepeating(&NewTabMessageHandler::HandleOpenAccount,
                            base::Unretained(this)));
    // Forget this session, or any other history deletion, empties the rows
    // of a page that is already open, not only of the next one.
    history_watch_ = WatchHistoryDeletions(
        web_ui()->GetWebContents(),
        base::BindRepeating(&NewTabMessageHandler::OnHistoryDeleted,
                            weak_factory_.GetWeakPtr()));
    // Test only: nothing a page can ask for without the switch. Kept with
    // the search box gone, since it also drives the address bar's engine
    // menu (smoke_search_menu.py).
    if (base::CommandLine::ForCurrentProcess()->HasSwitch(
            kSearchMenuTestSwitch)) {
      web_ui()->RegisterMessageCallback(
          "searchMenuTest",
          base::BindRepeating(&NewTabMessageHandler::HandleSearchMenuTest,
                              base::Unretained(this)));
    }
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

  // "Pick up where you left off": the last few web pages in history.
  void HandleGetRecent(const base::ListValue& args) {
    tracker_.TryCancelAll();
    GetRecentPagesForPage(
        web_ui()->GetWebContents(), kMaxRecentPages, &tracker_,
        base::BindOnce(&NewTabMessageHandler::OnRecentPages,
                       weak_factory_.GetWeakPtr()));
  }

  void OnRecentPages(std::vector<RecentPage> pages) {
    base::ListValue list;
    for (const RecentPage& page : pages) {
      // Checked again here: only a web address becomes a link.
      if (!page.url.SchemeIsHTTPOrHTTPS()) {
        continue;
      }
      std::string title = base::UTF16ToUTF8(page.title);
      // Cut on a character boundary, never inside one: a half character
      // is not UTF-8, and base::Value refuses it.
      if (title.size() > kMaxRecentTitleLength) {
        title.resize(
            base::TruncateUTF8ToByteSize(title, kMaxRecentTitleLength).size());
      }
      base::DictValue item;
      item.Set("title", title);
      item.Set("url", page.url.spec());
      item.Set("host", page.url.host());
      item.Set("when", page.when.InMillisecondsFSinceUnixEpoch());
      list.Append(std::move(item));
    }
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("loadRecent", list);
  }

  void OnHistoryDeleted() {
    if (IsJavascriptAllowed()) {
      HandleGetRecent(base::ListValue());
    }
  }

  void HandleSearchMenuTest(const base::ListValue& args) {
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe(
        "searchMenuTestResult",
        RunSearchEngineMenuTestCommand(web_ui()->GetWebContents(), args));
  }

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

  // boring: Accounts. The chips: id, initial, name and provider for each
  // account the person keeps, never an address. None in Incognito or guest
  // windows (both are off the record), where nobody is signed in.
  bool ShowsAccounts() {
    return !web_ui()->GetWebContents()->GetBrowserContext()->IsOffTheRecord();
  }

  void SendAccounts() {
    base::Value list;
    if (PrefService* prefs = GetPrefs(); prefs && ShowsAccounts()) {
      base::ListValue chips;
      for (const accounts::Account& account : accounts::GetAccounts(*prefs)) {
        base::DictValue chip;
        chip.Set("id", account.id);
        chip.Set("initial", accounts::Initial(account));
        chip.Set("name", account.name);
        chip.Set("provider", accounts::ProviderName(account));
        chips.Append(std::move(chip));
      }
      list = base::Value(std::move(chips));
    }
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("loadAccounts", list);
  }

  void OnAccountsChanged() {
    if (IsJavascriptAllowed()) {
      SendAccounts();
    }
  }

  void HandleGetAccounts(const base::ListValue& args) {
    // Chips follow the list as it changes in the panel or in Settings.
    if (!accounts_registrar_.prefs() && GetPrefs()) {
      accounts_registrar_.Init(GetPrefs());
      accounts_registrar_.Add(
          accounts::kAccountsPref,
          base::BindRepeating(&NewTabMessageHandler::SendAccounts,
                              base::Unretained(this)));
    }
    SendAccounts();
  }

  // [id]. Opens that account's mail in this tab. The page names an account;
  // the address comes from the store, checked again as it is read.
  void HandleOpenAccount(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (!prefs || !ShowsAccounts() || args.size() != 1 || !args[0].is_string()) {
      return;
    }
    std::optional<accounts::Account> account =
        accounts::FindAccount(*prefs, args[0].GetString());
    if (!account || !account->links.mail.is_valid()) {
      return;
    }
    web_ui()->GetWebContents()->OpenURL(
        content::OpenURLParams(account->links.mail, content::Referrer(),
                               WindowOpenDisposition::CURRENT_TAB,
                               ui::PAGE_TRANSITION_AUTO_BOOKMARK,
                               /*is_renderer_initiated=*/false),
        /*navigation_handle_callback=*/{});
  }

  PrefChangeRegistrar accounts_registrar_;
  // boring: end Accounts.

  // Cancels a history query still running when the page goes away.
  base::CancelableTaskTracker tracker_;
  std::unique_ptr<HistoryDeletionWatch> history_watch_;
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
