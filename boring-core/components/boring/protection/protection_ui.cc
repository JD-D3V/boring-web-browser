// Copyright 2026 boring. BSD style license.

#include "components/boring/protection/protection_ui.h"

#include <algorithm>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "base/memory/ref_counted_memory.h"
#include "base/memory/weak_ptr.h"
#include "base/scoped_observation.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "base/values.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/adblock/blocking_off_sites.h"
#include "components/boring/adblock/custom_rules.h"
#include "components/boring/branding/brand_mark.h"
#include "components/boring/core/boring_capabilities.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/lists/list_paths.h"
#include "components/boring/lists/list_updater.h"
#include "components/boring/performance/never_sleep_sites.h"
#include "components/boring/privacy/privacy_state.h"
#include "components/boring/protection/memory_saver.h"
#include "components/boring/scam/scam_service.h"
#include "components/boring/update/browser_updater.h"
#include "components/prefs/pref_change_registrar.h"
#include "components/prefs/pref_service.h"
#include "components/prefs/scoped_user_pref_update.h"
#include "components/user_prefs/user_prefs.h"
#include "content/public/browser/browser_context.h"
#include "content/public/browser/storage_partition.h"
#include "content/public/browser/web_contents.h"
#include "content/public/browser/web_ui.h"
#include "content/public/browser/web_ui_data_source.h"
#include "content/public/browser/web_ui_message_handler.h"
#include "content/public/common/url_constants.h"
#include "extensions/browser/extension_registry.h"
#include "extensions/browser/extension_registry_observer.h"
#include "extensions/browser/unloaded_extension_reason.h"
#include "extensions/common/extension.h"
#include "url/gurl.h"

namespace boring {

namespace {

constexpr char kPage[] = R"PAGE(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Protection</title>
<link rel="icon" type="image/svg+xml" href="brand.svg">
<style>
  :root { color-scheme: light dark;
    --surface: light-dark(#faf9f6, #1c2422);
    --paper: light-dark(#ffffff, #252e2b);
    --ink: light-dark(#242e2d, #e8ede7);
    --muted: light-dark(#5d6966, #adb9b2);
    --line: light-dark(#d8ddd7, #414e47);
    /* Control edges: 3:1 or more against the page in both themes. */
    --field: light-dark(#7d8985, #8b9891);
    --accent: light-dark(#176b5b, #92d4bb);
    --soft: light-dark(#e5f1eb, #273f35);
    --warning: light-dark(#9e3e24, #ffb69c);
    --warning-soft: light-dark(#fbebe4, #412f28);
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  body { font: 14px/1.6 "Segoe UI", system-ui, sans-serif; margin: 0;
         background: var(--surface); color: var(--ink);
         padding: 3em 1.5em; display: flex; justify-content: center; }
  .page { width: 46em; max-width: 100%; }
  h1 { font-size: 2.3em; letter-spacing: -0.045em; font-weight: 550;
       line-height: 1.1; margin: 0 0 0.2em; }
  .muted { color: var(--muted); margin: 0 0 1.6em; }
  .state-row { padding: 16px 0; border-top: 1px solid var(--line); }
  .state-row:first-of-type { border-top: none; }
  .state-line { display: flex; justify-content: space-between;
                align-items: center; gap: 14px; }
  .state-line strong { font-weight: 600; font-size: 14px; }
  .state-value { color: var(--accent); font-size: 12px; font-weight: 600;
                 white-space: nowrap; }
  .state-value.warn { color: var(--warning); }
  .state-value.loading { color: var(--muted); }
  .state-row p { font-size: 12px; margin: 6px 0 0; color: var(--muted); }
  .setting-row { display: flex; gap: 20px; justify-content: space-between;
                 align-items: center; border-top: 1px solid var(--line);
                 padding: 18px 0; cursor: pointer; }
  .setting-row strong { font-size: 14px; font-weight: 600; display: block; }
  .setting-row p { font-size: 12px; margin: 5px 0 0; color: var(--muted);
                   max-width: 430px; }
  /* A 40x24 switch, drawn from the real checkbox so its checked,
     disabled and keyboard behaviour stay the browser's own. */
  .switch { appearance: none; position: relative; flex: none; margin: 0;
            width: 40px; height: 24px; border-radius: 16px;
            border: 1px solid var(--field); background: var(--field);
            cursor: pointer; }
  /* 180 ms, eased: the knob settles rather than snaps. */
  .switch { transition: background-color 180ms ease,
                        border-color 180ms ease; }
  .switch::before { content: ""; position: absolute; left: 3px; top: 3px;
                    width: 16px; height: 16px; border-radius: 50%;
                    background: var(--paper);
                    transition: transform 180ms cubic-bezier(0.2, 0, 0, 1),
                                background-color 180ms ease; }
  .switch:checked { background: var(--accent); border-color: var(--accent); }
  .switch:checked::before { transform: translateX(16px);
                            background: var(--surface); }
  .switch:disabled { opacity: 0.55; cursor: not-allowed; }
  .switch:focus-visible { outline-offset: 3px; }
  .information { padding: 16px 18px; background: var(--soft);
                 border-radius: 8px; color: var(--ink); font-size: 13px;
                 line-height: 1.6; margin-top: 16px; }
  .warning-note { background: var(--warning-soft); }
  .actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; }
  .primary, .secondary { min-height: 40px; padding: 10px 18px;
                          border-radius: 7px; font-weight: 600;
                          font-size: 13px; border: none; cursor: pointer;
                          font-family: inherit; }
  .primary { background: var(--accent); color: var(--surface); }
  .primary:hover { filter: brightness(0.92); }
  .secondary { border: 1px solid var(--line); background: var(--paper);
               color: var(--ink); }
  .secondary:hover { background: var(--soft); }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .hidden { display: none; }
  .text-button { color: var(--accent); }
  .site-list { list-style: none; margin: 10px 0 0; padding: 0; }
  .site-list li { display: flex; justify-content: space-between;
                  align-items: center; gap: 14px; padding: 6px 0;
                  font-size: 13px; }
  .site-list .secondary { min-height: 32px; padding: 6px 14px; }
  .regional { border: none; border-top: 1px solid var(--line);
              margin: 0; padding: 18px 0 10px; min-width: 0; }
  .regional legend { float: left; width: 100%; padding: 0;
                     font-size: 14px; font-weight: 600;
                     margin-bottom: 8px; }
  .regional > div { clear: both; }
  .check-row { display: flex; align-items: center; gap: 10px;
               padding: 6px 0; font-size: 13px; cursor: pointer; }
  /* Real checkboxes, sized up and drawn in the page's accent. */
  .check-row input { width: 18px; height: 18px; margin: 0; flex: none;
                     accent-color: var(--accent); cursor: pointer; }
  h2.section { font-size: 1.3em; font-weight: 550; letter-spacing: -0.02em;
               margin: 2em 0 0.2em; }
  .choice { border: none; border-top: 1px solid var(--line); margin: 0;
            padding: 18px 0 10px; min-width: 0; }
  .choice legend { float: left; width: 100%; padding: 0; font-size: 14px;
                   font-weight: 600; margin-bottom: 8px; }
  .choice > label { clear: both; }
  .check-row input[type="radio"] { border-radius: 50%; }
  .choice:disabled .check-row { opacity: 0.55; cursor: not-allowed; }
  .filters label strong { font-size: 14px; font-weight: 600; }
  .filters textarea { display: block; width: 100%; margin-top: 10px;
                      min-height: 8em; resize: vertical; padding: 10px 12px;
                      border: 1px solid var(--field); border-radius: 8px;
                      background: var(--paper); color: var(--ink);
                      font: 13px/1.5 Consolas, "Cascadia Mono", monospace; }
  .problem-list { margin: 8px 0 0; padding: 0; list-style: none;
                  font-size: 12px; }
  .problem-list li { padding: 4px 0; color: var(--warning); }
  .problem-list code { font: 12px Consolas, "Cascadia Mono", monospace;
                       color: var(--ink); overflow-wrap: anywhere; }
  .sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden;
             clip-path: inset(50%); white-space: nowrap; }
  @media (prefers-reduced-motion: reduce) {
    .switch, .switch::before { transition: none; }
  }
  @media (forced-colors: active) {
    button, input, select, textarea { border: 1px solid ButtonText; }
    .primary { background: Highlight; color: HighlightText; }
    .switch { appearance: auto; width: auto; height: auto; }
    .switch::before { display: none; }
  }
</style>
</head>
<body>
<div class="page">
  <h1>Protection</h1>
  <p class="muted">Useful safeguards. Clear choices.</p>

  <div class="state-row">
    <div class="state-line"><strong>Scam &amp; phishing sites</strong>
      <span class="state-value loading" id="scam-state">Starting</span></div>
    <p id="scam-desc"></p>
  </div>
  <div class="state-row">
    <div class="state-line"><strong>Ads &amp; trackers</strong>
      <span class="state-value loading" id="ads-state">Starting</span></div>
    <p id="ads-desc"></p>
  </div>
  <div class="state-row">
    <div class="state-line"><strong>Sites with blocking off</strong>
      <span class="state-value loading" id="off-sites-state">Starting</span></div>
    <p id="off-sites-desc">Turn blocking off for a site from the shield in
    the toolbar.</p>
    <ul class="site-list" id="off-sites" aria-label="Sites with blocking off"></ul>
  </div>
  <div class="state-row">
    <div class="state-line"><strong>Secure connections</strong>
      <span class="state-value loading" id="https-state">Starting</span></div>
    <p id="https-desc"></p>
  </div>
  <div class="state-row">
    <div class="state-line"><strong>Your IP address in calls</strong>
      <span class="state-value loading" id="webrtc-state">Starting</span></div>
    <p id="webrtc-desc"></p>
  </div>
  <div class="state-row">
    <div class="state-line"><strong>Chrome Web Store</strong>
      <span class="state-value loading" id="webstore-state">Starting</span></div>
    <p id="webstore-desc">Built in so you can add extensions from the Chrome
    Web Store. With store extensions installed, it asks Google for updates
    every 5 hours, when you add or remove one, and when you open its menu.
    It sends their IDs and the browser version. Turn off automatic checks
    in its options, or remove it in
    <a class="text-button" href="chrome://extensions">Extensions</a>.</p>
  </div>
  <div class="state-row">
    <div class="state-line"><strong>Blocking lists</strong>
      <span class="state-value loading" id="lists-state">Starting</span></div>
    <p id="lists-age"></p>
  </div>

  <label class="setting-row" for="list-updates" id="list-updates-row">
    <span><strong>Keep them up to date</strong>
      <p>Checks for newer lists about once a week. No account, no cookie,
      nothing about you or the pages you visit.</p></span>
    <input class="switch" type="checkbox" id="list-updates">
  </label>

  <label class="setting-row" for="hide-cookies">
    <span><strong>Hide cookie notices</strong></span>
    <input class="switch" type="checkbox" id="hide-cookies">
  </label>

  <fieldset class="regional" id="regional" hidden>
    <legend>Regional lists</legend>
    <div id="regional-lists"></div>
  </fieldset>

  <fieldset class="choice" id="level-choice">
    <legend>Blocking level</legend>
    <label class="check-row"><input type="radio" name="level" value="0"
        id="level-standard"> Standard</label>
    <label class="check-row"><input type="radio" name="level" value="1"
        id="level-aggressive"> Aggressive</label>
  </fieldset>

  <div class="state-row filters">
    <label for="my-filters"><strong>My filters</strong></label>
    <p id="my-filters-desc">One rule per line, as in uBlock Origin.</p>
    <textarea id="my-filters" rows="6" spellcheck="false"
        autocomplete="off" aria-describedby="my-filters-desc"></textarea>
    <div class="actions">
      <button class="secondary" id="save-filters">Save</button>
    </div>
    <p id="my-filters-status" role="status"></p>
    <div id="filter-problems" hidden>
      <strong id="filter-problems-title">Not used</strong>
      <ul class="problem-list" id="filter-problems-list"
          aria-labelledby="filter-problems-title"></ul>
    </div>
  </div>

  <div class="state-row">
    <div class="state-line"><strong>Browser updates</strong>
      <span class="state-value loading" id="update-state">Starting</span></div>
    <p id="update-desc"></p>
  </div>

  <label class="setting-row" for="auto-update" id="auto-update-row" hidden>
    <span><strong>Check for new versions every day</strong>
      <p>Asks our site whether a newer version exists. No account, no
      cookie, nothing about you or the pages you visit. A new version
      installs only after you say yes, and only if it carries our
      signature.</p></span>
    <input class="switch" type="checkbox" id="auto-update">
  </label>
  <div class="setting-row" id="check-update-row" hidden>
    <span><strong>Check now</strong>
      <p>Look for a new version straight away.</p></span>
    <button class="secondary" id="check-update">Check for updates</button>
  </div>

  <label class="setting-row" for="strip-params">
    <span><strong>Remove tracking from links</strong>
      <p>Takes identifiers such as fbclid and gclid out of an address
      when one site sends you to another, before the request is sent.
      Campaign labels like utm_source are left alone: they name an
      advert, not you.</p></span>
    <input class="switch" type="checkbox" id="strip-params">
  </label>

  <label class="setting-row" for="fingerprint">
    <span><strong>Fingerprint noise</strong>
      <p>Adds a tiny random change to what pages read back from canvas
      drawing, text sizes and element sizes, so those readings stop
      identifying this browser. A few sites that draw charts or games
      may look very slightly different.</p></span>
    <input class="switch" type="checkbox" id="fingerprint">
  </label>

  <label class="setting-row" for="hide-ads">
    <span><strong>Hide sponsored search results</strong>
      <p>Remove supported paid placements on Google and Bing. Paid
      placements are not the only bad link on a page.</p></span>
    <input class="switch" type="checkbox" id="hide-ads">
  </label>

  <label class="setting-row" for="senior">
    <span><strong>Senior Safe Mode</strong>
      <p id="senior-why">Keeps sponsored search results hidden.</p></span>
    <input class="switch" type="checkbox" id="senior">
  </label>
  <div id="confirm-off" class="information warning-note hidden"
      role="alertdialog" aria-labelledby="confirm-text">
    <p id="confirm-text">Nobody from a bank or tech company will ever ask
    you to turn this off. If someone is asking, hang up.</p>
    <div class="actions">
      <button class="primary" id="keep-on">Keep it on</button>
      <button class="secondary" id="turn-off">Turn it off</button>
    </div>
  </div>

  <h2 class="section">Memory</h2>
  <label class="setting-row" for="memory-saver" id="memory-saver-row">
    <span><strong>Memory Saver</strong>
      <p id="memory-saver-desc">Tabs you have not used for a while sleep
      to free memory.</p></span>
    <input class="switch" type="checkbox" id="memory-saver">
  </label>
  <fieldset class="choice" id="memory-level">
    <legend>Memory Saver level</legend>
    <label class="check-row"><input type="radio" name="memory-level"
        value="0" id="memory-moderate"> Moderate</label>
    <label class="check-row"><input type="radio" name="memory-level"
        value="1" id="memory-balanced"> Balanced</label>
    <label class="check-row"><input type="radio" name="memory-level"
        value="2" id="memory-maximum"> Maximum</label>
  </fieldset>
  <div class="state-row">
    <div class="state-line"><strong>Never sleep</strong>
      <span class="state-value" id="never-sleep-state">None</span></div>
    <p>Add a site from the shield in the toolbar.</p>
    <ul class="site-list" id="never-sleep" aria-label="Sites that never sleep"></ul>
  </div>

  <div id="status" class="sr-only" role="status"></div>
</div>
<script src="protection.js"></script>
</body>
</html>
)PAGE";

constexpr char kScript[] = R"SCRIPT(
function el(id) { return document.getElementById(id); }

// A failure is shown as a failure, with the reason, in the row's own
// description line rather than a separate element.
function showState(name, state, ready, problem) {
  var badge = el(name + '-state');
  var desc = el(name + '-desc');
  badge.className = 'state-value' + (state === 'ready' ? '' :
                                     state === 'failed' ? ' warn' :
                                     ' loading');
  badge.textContent = state === 'ready' ? 'On' :
                      state === 'failed' ? 'Unavailable' : 'Starting';
  if (state === 'off') {
    badge.className = 'state-value warn';
    badge.textContent = 'Off';
    desc.textContent = 'Turned off for this session.';
    return;
  }
  if (state === 'failed') {
    var reason = problem || 'unknown problem';
    desc.textContent = reason.charAt(0).toUpperCase() + reason.slice(1) + '.';
  } else {
    desc.textContent = ready;
  }
}

// Lists that stop being replaced stop recognising the scams people
// are being sent to now, so old lists are shown as a problem rather
// than as a detail.
function showLists(days, updating, available) {
  var badge = el('lists-state');
  var age = el('lists-age');
  var old = days < 0 || days > 14;
  badge.className = 'state-value' +
      (days < 0 ? ' loading' : old ? ' warn' : '');
  badge.textContent = days < 0 ? 'Unknown' : old ? 'Old' : 'Current';
  if (days < 0) {
    age.textContent = 'Cannot tell how old the lists are.';
  } else if (days < 1) {
    age.textContent = 'Updated today.';
  } else if (days === 1) {
    age.textContent = 'Updated yesterday.';
  } else {
    age.textContent = 'Updated ' + days + ' days ago.';
  }
  if (!available) {
    age.textContent += ' They update when you install a newer version.';
  } else if (old && !updating) {
    age.textContent += ' Updates are turned off.';
  }
  el('list-updates-row').hidden = !available;
  el('list-updates').checked = updating;
}

// A copy that cannot update itself says why, and what to do instead,
// rather than showing a switch that would do nothing.
function showUpdates(state, automatic, version) {
  var badge = el('update-state');
  var desc = el('update-desc');
  var ready = state === 'ready';
  badge.className = 'state-value' + (state === 'starting' ? ' loading' :
      ready ? '' : ' warn');
  badge.textContent = state === 'starting' ? 'Starting' :
      ready ? (automatic ? 'On' : 'Off') : 'Manual';
  var why = {
    starting: '',
    ready: '',
    nokey: 'This preview does not update itself.',
    portable: 'This copy was unpacked from the zip, so it does not ' +
        'update itself. Install it with the installer to get updates.',
    missing: 'The updater is missing from this copy. Reinstall it to ' +
        'get updates.',
    off: 'Updates are turned off for this session.',
  };
  desc.textContent = 'Version ' + version + '. ' + (why[state] || '') +
      (ready ? '' : ' Download new versions from the Boring Browser site.');
  el('auto-update-row').hidden = !ready;
  el('check-update-row').hidden = !ready;
  el('auto-update').checked = ready && automatic;
}

function showConnections(s) {
  var https = el('https-state');
  https.className = 'state-value' + (s.httpsFirst ? '' : ' warn');
  https.textContent = !s.httpsFirst ? 'Off' :
      s.httpsBalanced ? 'On' : 'Strict';
  el('https-desc').textContent = !s.httpsFirst ?
      'Pages may load without encryption and without a warning.' :
      s.httpsBalanced ?
      'Pages load over HTTPS when the site offers it, with a warning ' +
          'before a public site loads without it.' :
      'Every page that is not encrypted is stopped with a warning first.';

  // Chromium's own names for the WebRTC IP handling policy.
  var strict = s.webrtc === 'disable_non_proxied_udp';
  var hidden = strict || s.webrtc === 'default_public_interface_only';
  var webrtc = el('webrtc-state');
  webrtc.className = 'state-value' + (hidden ? '' : ' warn');
  webrtc.textContent = hidden ? 'Hidden' : 'Visible';
  el('webrtc-desc').textContent = strict ?
      'Video and voice calls in the browser cannot reveal your ' +
          'addresses on this network, and use only a route your proxy ' +
          'would allow. Some calls may need a relay and be slower.' :
      hidden ? 'Calls cannot reveal your addresses on this network.' :
      'Calls in the browser can reveal your addresses on this network.';
}

// Each site gets a button to turn blocking back on. The list is
// rebuilt from the profile's own list every time, never kept here.
function showOffSites(sites) {
  var list = el('off-sites');
  var badge = el('off-sites-state');
  list.textContent = '';
  badge.className = 'state-value' + (sites.length ? ' warn' : '');
  badge.textContent = sites.length === 0 ? 'None' :
      sites.length === 1 ? '1 site' : sites.length + ' sites';
  sites.forEach(function(site) {
    var item = document.createElement('li');
    var name = document.createElement('span');
    name.textContent = site;
    var on = document.createElement('button');
    on.className = 'secondary';
    on.textContent = 'Turn back on';
    on.setAttribute('aria-label', 'Turn blocking back on for ' + site);
    on.dataset.site = site;
    on.addEventListener('click', function() {
      chrome.send('setSiteBlocking', [site, true]);
      say('Blocking is back on for ' + site + '.');
    });
    item.append(name, on);
    list.append(item);
  });
}

// The store extension's real state in this profile: installed and
// enabled, installed but turned off, or not there at all.
function showWebStore(state) {
  var badge = el('webstore-state');
  badge.className = 'state-value' + (state === 'on' ? '' : ' warn');
  badge.textContent = state === 'on' ? 'On' :
      state === 'off' ? 'Off' : 'Removed';
}

// One real checkbox per regional list this build ships. Rebuilt only
// when the set of lists changes, so a click does not lose focus.
function showRegional(lists, chosen) {
  var box = el('regional-lists');
  el('regional').hidden = lists.length === 0;
  var ids = lists.map(function(l) { return l.id; }).join();
  if (box.dataset.ids !== ids) {
    box.textContent = '';
    box.dataset.ids = ids;
    lists.forEach(function(list) {
      var row = document.createElement('label');
      row.className = 'check-row';
      var check = document.createElement('input');
      check.type = 'checkbox';
      check.id = 'regional-' + list.id;
      check.dataset.id = list.id;
      check.addEventListener('change', function(e) {
        chrome.send('setRegionalList', [list.id, e.target.checked]);
        say(list.title + (e.target.checked ? ' on.' : ' off.'));
      });
      var name = document.createElement('span');
      name.textContent = list.title;
      row.append(check, name);
      box.append(row);
    });
  }
  box.querySelectorAll('input').forEach(function(check) {
    check.checked = chosen.indexOf(check.dataset.id) !== -1;
  });
}

function showLevel(level) {
  el('level-standard').checked = level !== 1;
  el('level-aggressive').checked = level === 1;
}

// The box is filled from the profile once, and again after a save, so
// a refresh of the rest of the page never overwrites typing.
var filtersLoaded = false;

function showFilterProblems(problems) {
  var list = el('filter-problems-list');
  list.textContent = '';
  problems.forEach(function(problem) {
    var item = document.createElement('li');
    var rule = document.createElement('code');
    rule.textContent = problem.rule;
    item.append('Line ' + problem.line + ': ', rule,
                problem.error ? ' (' + problem.error + ')' : '');
    list.append(item);
  });
  el('filter-problems').hidden = problems.length === 0;
  el('my-filters-status').textContent = problems.length === 0 ? 'Saved.' :
      problems.length === 1 ? 'Saved. 1 line not used.' :
      'Saved. ' + problems.length + ' lines not used.';
}

function showMemory(m) {
  var on = el('memory-saver');
  on.checked = m.on;
  on.disabled = !m.available || m.managed;
  el('memory-saver-desc').textContent = m.managed ?
      'Set by your organisation.' :
      'Tabs you have not used for a while sleep to free memory.';
  var names = ['memory-moderate', 'memory-balanced', 'memory-maximum'];
  names.forEach(function(id, level) {
    el(id).checked = m.level === level;
  });
  el('memory-level').disabled = !m.available || m.managed || !m.on;
}

// Sites whose tabs never sleep, each with a Remove button. Rebuilt from
// the profile's own list every time.
function showNeverSleep(sites) {
  var list = el('never-sleep');
  list.textContent = '';
  el('never-sleep-state').textContent = sites.length === 0 ? 'None' :
      sites.length === 1 ? '1 site' : sites.length + ' sites';
  sites.forEach(function(site) {
    var item = document.createElement('li');
    var name = document.createElement('span');
    name.textContent = site;
    var remove = document.createElement('button');
    remove.className = 'secondary';
    remove.textContent = 'Remove';
    remove.setAttribute('aria-label', 'Remove ' + site);
    remove.dataset.site = site;
    remove.addEventListener('click', function() {
      chrome.send('setNeverSleep', [site, false]);
      say(site + ' can sleep again.');
    });
    item.append(name, remove);
    list.append(item);
  });
}

var pollTimer = null;

function load(s) {
  if (s.scam === 'off') {
    // No blocklist ships in this version. What protects against known
    // dangerous sites is the resolver: Quad9 refuses to look them up.
    // Say exactly that, including what it looks like when it works,
    // and say plainly when the person has moved away from it.
    var badge = el('scam-state');
    var desc = el('scam-desc');
    desc.textContent = '';
    if (s.dnsFiltersThreats) {
      badge.className = 'state-value';
      badge.textContent = 'On';
      desc.append('Known malware and phishing sites are refused by ' +
          'Quad9 secure DNS, a Swiss non-profit, so they do not open. ' +
          'There is no warning page: a blocked site shows as not found. ');
    } else {
      badge.className = 'state-value warn';
      badge.textContent = s.dnsManaged ? 'Set by your organisation' : 'Off';
      desc.append('Secure DNS is not using Quad9, so known dangerous ' +
          'sites are not blocked by name. ');
    }
    if (!s.dnsManaged) {
      var change = document.createElement('a');
      change.className = 'text-button';
      change.textContent = 'Secure DNS settings';
      change.href = 'chrome://settings/security';
      desc.append(change);
    }
  } else {
    showState('scam', s.scam,
        'Known listed sites are blocked before they open.', s.scamProblem);
  }
  showState('ads', s.ads,
      'Known advertising and tracking requests are blocked.', s.adsProblem);
  showOffSites(s.offSites);
  showWebStore(s.webStore);
  showLists(s.listDays, s.listUpdates, s.listUpdatesAvailable);
  showConnections(s);
  el('hide-cookies').checked = s.hideCookies;
  el('fingerprint').checked = s.fingerprint;
  el('strip-params').checked = s.stripParams;
  showUpdates(s.update, s.updateAuto, s.version);
  showLevel(s.level);
  if (!filtersLoaded) {
    el('my-filters').value = s.customRules;
    filtersLoaded = true;
  }
  showMemory(s.memory);
  showNeverSleep(s.neverSleep);

  var senior = el('senior');
  senior.checked = s.senior;
  senior.disabled = s.seniorForced;
  el('senior-why').textContent = s.seniorForced ? 'Set for this computer.' :
      'Keeps sponsored search results hidden.';
  var hide = el('hide-ads');
  hide.checked = s.hideSponsored || s.senior;
  hide.disabled = s.senior;

  // Keep asking only while something is still starting up.
  var starting = s.scam === 'loading' || s.ads === 'loading' ||
      s.update === 'starting';
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

el('strip-params').addEventListener('change', function(e) {
  chrome.send('setStripParams', [e.target.checked]);
  say(e.target.checked ? 'Tracking will be removed from links.'
                       : 'Links will be opened as they are.');
});

el('fingerprint').addEventListener('change', function(e) {
  chrome.send('setFingerprintNoise', [e.target.checked]);
  say(e.target.checked ?
      'Fingerprint noise on for pages opened from now.' :
      'Fingerprint noise off for pages opened from now.');
});

el('hide-ads').addEventListener('change', function(e) {
  chrome.send('setHideSponsored', [e.target.checked]);
});

el('auto-update').addEventListener('change', function(e) {
  chrome.send('setAutoUpdate', [e.target.checked]);
  say(e.target.checked ? 'The browser will look for new versions daily.'
                       : 'The browser will not look for new versions.');
});

el('check-update').addEventListener('click', function() {
  chrome.send('checkUpdateNow');
});

el('list-updates').addEventListener('change', function(e) {
  chrome.send('setListUpdates', [e.target.checked]);
  say(e.target.checked ? 'Lists will be kept up to date.'
                       : 'Lists will not be updated.');
});

el('hide-cookies').addEventListener('change', function(e) {
  chrome.send('setHideCookieNotices', [e.target.checked]);
  say(e.target.checked ? 'Cookie notices hidden.' : 'Cookie notices shown.');
});

document.querySelectorAll('input[name="level"]').forEach(function(radio) {
  radio.addEventListener('change', function(e) {
    var aggressive = e.target.value === '1';
    chrome.send('setBlockingLevel', [aggressive ? 1 : 0]);
    say(aggressive ? 'Aggressive blocking on.' : 'Standard blocking on.');
  });
});

el('save-filters').addEventListener('click', function() {
  el('my-filters-status').textContent = 'Saving.';
  chrome.send('setCustomRules', [el('my-filters').value]);
});

el('memory-saver').addEventListener('change', function(e) {
  chrome.send('setMemorySaver', [e.target.checked]);
  say(e.target.checked ? 'Memory Saver on.' : 'Memory Saver off.');
});

document.querySelectorAll('input[name="memory-level"]').forEach(
    function(radio) {
  radio.addEventListener('change', function(e) {
    chrome.send('setMemorySaverLevel', [Number(e.target.value)]);
  });
});

window.loadProtection = load;
window.showLevel = showLevel;
window.showFilterProblems = showFilterProblems;
window.showNeverSleep = showNeverSleep;
window.showRegional = showRegional;
window.showOffSites = showOffSites;
window.showWebStore = showWebStore;
chrome.send('getProtection');
)SCRIPT";

// My filters is a text box, not a file; far more than anyone types.
constexpr size_t kMaxCustomRulesLength = 256 * 1024;

base::DictValue MemoryDict() {
  const MemorySaverState state = GetMemorySaverState();
  return base::DictValue()
      .Set("available", state.available)
      .Set("on", state.on)
      .Set("level", static_cast<int>(state.level))
      .Set("managed", state.managed);
}

const char* UpdateStateName(BrowserUpdater::State state) {
  switch (state) {
    case BrowserUpdater::State::kStarting:
      return "starting";
    case BrowserUpdater::State::kReady:
      return "ready";
    case BrowserUpdater::State::kNoKey:
      return "nokey";
    case BrowserUpdater::State::kNotInstalled:
      return "portable";
    case BrowserUpdater::State::kNoLibrary:
      return "missing";
    case BrowserUpdater::State::kDisabled:
      return "off";
  }
  return "starting";
}

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

// The Chromium Web Store extension we bundle (NeverDecaf, pinned by
// tools/get_chromium_web_store.py). It asks Google about installed store
// extensions, so the page says whether it is there.
constexpr char kWebStoreExtensionId[] = "ocaahdebbfolfmndjeplogmgcagdmblk";

class ProtectionMessageHandler : public content::WebUIMessageHandler,
                                 public extensions::ExtensionRegistryObserver {
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
        "setStripParams",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetStripParams,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setFingerprintNoise",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetFingerprint,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setAutoUpdate",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetAutoUpdate,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "checkUpdateNow",
        base::BindRepeating(&ProtectionMessageHandler::HandleCheckUpdateNow,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setListUpdates",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetListUpdates,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setHideCookieNotices",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetHideCookies,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setRegionalList",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetRegionalList,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setSiteBlocking",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetSiteBlocking,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setBlockingLevel",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetBlockingLevel,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setCustomRules",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetCustomRules,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setMemorySaver",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetMemorySaver,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setMemorySaverLevel",
        base::BindRepeating(
            &ProtectionMessageHandler::HandleSetMemorySaverLevel,
            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setNeverSleep",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetNeverSleep,
                            base::Unretained(this)));
  }

  // The list of sites can change from the shield while this page is
  // open, in this window or another, so follow the pref while the page
  // can be told.
  void OnJavascriptAllowed() override {
    PrefService* prefs = GetPrefs();
    if (!prefs) {
      return;
    }
    registrar_.Init(prefs);
    registrar_.Add(prefs::kBlockingOffSites,
                   base::BindRepeating(&ProtectionMessageHandler::SendOffSites,
                                       base::Unretained(this)));
    registrar_.Add(prefs::kBoringRegionalLists,
                   base::BindRepeating(&ProtectionMessageHandler::SendRegional,
                                       base::Unretained(this)));
    // Both also change from the shield in any window.
    registrar_.Add(prefs::kBoringBlockingLevel,
                   base::BindRepeating(&ProtectionMessageHandler::SendLevel,
                                       base::Unretained(this)));
    registrar_.Add(
        prefs::kBoringNeverSleepSites,
        base::BindRepeating(&ProtectionMessageHandler::SendNeverSleep,
                            base::Unretained(this)));
    if (extensions::ExtensionRegistry* registry = GetExtensionRegistry()) {
      extensions_observation_.Observe(registry);
    }
  }

  void OnJavascriptDisallowed() override {
    registrar_.RemoveAll();
    extensions_observation_.Reset();
  }

  // extensions::ExtensionRegistryObserver:
  // Turned on, off, added or removed on chrome://extensions while this
  // page is open: say so here too.
  void OnExtensionLoaded(content::BrowserContext* context,
                         const extensions::Extension* extension) override {
    SendWebStoreIfOurs(extension);
  }
  void OnExtensionUnloaded(
      content::BrowserContext* context,
      const extensions::Extension* extension,
      extensions::UnloadedExtensionReason reason) override {
    SendWebStoreIfOurs(extension);
  }
  void OnExtensionUninstalled(content::BrowserContext* context,
                              const extensions::Extension* extension,
                              extensions::UninstallReason reason) override {
    SendWebStoreIfOurs(extension);
  }
  void OnShutdown(extensions::ExtensionRegistry* registry) override {
    extensions_observation_.Reset();
  }

 private:
  PrefService* GetPrefs() {
    return user_prefs::UserPrefs::Get(
        web_ui()->GetWebContents()->GetBrowserContext());
  }

  // How many days old the oldest list in use is, or -1 when that
  // cannot be told. This is the timestamp on the files actually in
  // use, not anything the browser wrote down about them, so the page
  // cannot claim the lists are fresher than they are. The scam list
  // only counts when this build ships one.
  static int ListAgeInDays(const AdblockService* ads, const ScamService* scam) {
    const base::Time ads_at = ads->list_time();
    if (ads_at.is_null()) {
      return -1;
    }
    base::Time oldest = ads_at;
    if (kScamBlockingAvailable) {
      const base::Time scam_at = scam->list_time();
      if (scam_at.is_null()) {
        return -1;
      }
      oldest = std::min(oldest, scam_at);
    }
    const base::TimeDelta age = base::Time::Now() - oldest;
    return std::max(0, age.InDays());
  }

  // The profile's own list, as it is right now.
  base::ListValue OffSites() {
    base::ListValue sites;
    if (PrefService* prefs = GetPrefs()) {
      for (const base::Value& site : prefs->GetList(prefs::kBlockingOffSites)) {
        if (site.is_string()) {
          sites.Append(site.GetString());
        }
      }
    }
    return sites;
  }

  extensions::ExtensionRegistry* GetExtensionRegistry() {
    return extensions::ExtensionRegistry::Get(
        web_ui()->GetWebContents()->GetBrowserContext());
  }

  // "on", "off" or "removed", read from the registry each time.
  const char* WebStoreState() {
    extensions::ExtensionRegistry* registry = GetExtensionRegistry();
    if (!registry) {
      return "removed";
    }
    if (registry->enabled_extensions().Contains(kWebStoreExtensionId)) {
      return "on";
    }
    return registry->GetInstalledExtension(kWebStoreExtensionId) ? "off"
                                                                 : "removed";
  }

  void SendWebStoreIfOurs(const extensions::Extension* extension) {
    if (extension && extension->id() == kWebStoreExtensionId &&
        IsJavascriptAllowed()) {
      web_ui()->CallJavascriptFunctionUnsafe("showWebStore",
                                             base::Value(WebStoreState()));
    }
  }

  base::ListValue NeverSleepSites() {
    base::ListValue sites;
    if (PrefService* prefs = GetPrefs()) {
      for (const base::Value& site :
           prefs->GetList(prefs::kBoringNeverSleepSites)) {
        if (site.is_string()) {
          sites.Append(site.GetString());
        }
      }
    }
    return sites;
  }

  void SendNeverSleep() {
    if (IsJavascriptAllowed()) {
      web_ui()->CallJavascriptFunctionUnsafe("showNeverSleep",
                                             NeverSleepSites());
    }
  }

  void SendLevel() {
    PrefService* prefs = GetPrefs();
    if (prefs && IsJavascriptAllowed()) {
      web_ui()->CallJavascriptFunctionUnsafe(
          "showLevel",
          base::Value(prefs->GetInteger(prefs::kBoringBlockingLevel)));
    }
  }

  void SendOffSites() {
    if (IsJavascriptAllowed()) {
      web_ui()->CallJavascriptFunctionUnsafe("showOffSites", OffSites());
    }
  }

  // The shipped index is read once per page, off the UI thread.
  void LoadRegionalIndex() {
    if (regional_requested_) {
      SendRegional();
      return;
    }
    regional_requested_ = true;
    base::ThreadPool::PostTaskAndReplyWithResult(
        FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_VISIBLE},
        base::BindOnce(&ReadRegionalIndex),
        base::BindOnce(&ProtectionMessageHandler::OnRegionalIndex,
                       weak_factory_.GetWeakPtr()));
  }

  void OnRegionalIndex(std::vector<RegionalListInfo> lists) {
    regional_ = std::move(lists);
    SendRegional();
  }

  bool ShipsRegionalList(const std::string& id) const {
    return std::ranges::any_of(
        regional_, [&id](const RegionalListInfo& l) { return l.id == id; });
  }

  // The lists this build ships, and which of them this profile chose.
  // An id left in the pref by an older build that no longer ships it is
  // not shown, and does nothing.
  void SendRegional() {
    if (!IsJavascriptAllowed()) {
      return;
    }
    base::ListValue lists;
    for (const RegionalListInfo& info : regional_) {
      lists.Append(
          base::DictValue().Set("id", info.id).Set("title", info.title));
    }
    base::ListValue chosen;
    if (PrefService* prefs = GetPrefs()) {
      for (const base::Value& id :
           prefs->GetList(prefs::kBoringRegionalLists)) {
        if (id.is_string() && ShipsRegionalList(id.GetString())) {
          chosen.Append(id.GetString());
        }
      }
    }
    web_ui()->CallJavascriptFunctionUnsafe("showRegional", lists, chosen);
  }

  void HandleGet(const base::ListValue& args) {
    // Opening this page is a good moment to make sure the lists are
    // loading, so the answer is about the lists and not about timing.
    ScamService* scam = ScamService::GetInstance();
    AdblockService* ads = AdblockService::GetInstance();
    // Only start the scam service when there is a list for it to
    // load; otherwise it would log a missing-list error on a build
    // that is not supposed to have one.
    if (kScamBlockingAvailable) {
      scam->EnsureLoading();
    }
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
    out.Set("scam",
            kScamBlockingAvailable ? StatusName(scam->status()) : "off");
    out.Set("scamProblem", scam->status_message());
    // Turned off for this run by a switch: the engine may still load,
    // but no request is checked, so say off rather than on.
    out.Set("ads",
            AdblockService::IsDisabled() ? "off" : StatusName(ads->status()));
    out.Set("offSites", OffSites());
    out.Set("webStore", WebStoreState());
    out.Set("adsProblem", ads->status_message());
    out.Set("senior", IsSeniorSafeMode(prefs));
    out.Set("seniorForced", IsSeniorSafeModeForced());
    out.Set("hideSponsored",
            prefs && prefs->GetBoolean(prefs::kHideSponsoredResults));
    out.Set("listDays", ListAgeInDays(ads, scam));
    out.Set("listUpdates", ListUpdater::IsEnabled(prefs));
    out.Set("listUpdatesAvailable", ListUpdater::CanUpdate());
    const PrivacyState privacy = GetPrivacyState(context);
    out.Set("dnsFiltersThreats", privacy.dns_filters_threats);
    out.Set("dnsManaged", privacy.dns_managed);
    out.Set("httpsFirst", privacy.https_first);
    out.Set("httpsBalanced", privacy.https_balanced);
    out.Set("webrtc", privacy.webrtc_policy);
    out.Set("stripParams",
            prefs && prefs->GetBoolean(prefs::kStripTrackingParams));
    out.Set("fingerprint",
            prefs && prefs->GetBoolean(prefs::kFingerprintNoise));
    out.Set("hideCookies",
            prefs && prefs->GetBoolean(prefs::kBoringHideCookieNotices));
    out.Set("update", UpdateStateName(BrowserUpdater::GetState()));
    out.Set("updateAuto", BrowserUpdater::IsAutomatic());
    out.Set("version", BrowserUpdater::BuildVersion());
    out.Set("level",
            prefs ? prefs->GetInteger(prefs::kBoringBlockingLevel) : 0);
    out.Set("customRules", prefs ? prefs->GetString(prefs::kBoringCustomRules)
                                 : std::string());
    out.Set("memory", MemoryDict());
    out.Set("neverSleep", NeverSleepSites());
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("loadProtection", out);
    LoadRegionalIndex();
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

  void HandleSetStripParams(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kStripTrackingParams, args[0].GetBool());
    }
    HandleGet(args);
  }

  void HandleSetFingerprint(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kFingerprintNoise, args[0].GetBool());
    }
    HandleGet(args);
  }

  void HandleSetAutoUpdate(const base::ListValue& args) {
    if (!args.empty() && args[0].is_bool()) {
      BrowserUpdater::SetAutomatic(args[0].GetBool());
    }
    HandleGet(args);
  }

  // WinSparkle shows its own window from here on: checking, then either
  // "you have the latest" or the new version with its notes.
  void HandleCheckUpdateNow(const base::ListValue& args) {
    BrowserUpdater::CheckNow();
  }

  void HandleSetListUpdates(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kListUpdates, args[0].GetBool());
    }
    HandleGet(args);
  }

  void HandleSetHideCookies(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kBoringHideCookieNotices, args[0].GetBool());
    }
    HandleGet(args);
  }

  // [id, on]. Only ids this build ships are written to the pref.
  void HandleSetRegionalList(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (!prefs || args.size() != 2 || !args[0].is_string() ||
        !args[1].is_bool() || !ShipsRegionalList(args[0].GetString())) {
      SendRegional();
      return;
    }
    const std::string& id = args[0].GetString();
    const bool on = args[1].GetBool();
    if (prefs->GetList(prefs::kBoringRegionalLists).contains(id) != on) {
      ScopedListPrefUpdate update(prefs, prefs::kBoringRegionalLists);
      if (on) {
        update->Append(id);
      } else {
        update->EraseValue(base::Value(id));
      }
    }
    // The pref observer repaints; this covers a request that changed
    // nothing.
    SendRegional();
  }

  // [site, on]. Only turning blocking back on is offered here; a site is
  // added from the shield, on the site itself.
  void HandleSetSiteBlocking(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && args.size() == 2 && args[0].is_string() && args[1].is_bool() &&
        args[1].GetBool()) {
      SetBlockingOffForSite(prefs, args[0].GetString(), /*off=*/false);
      BlockingOffSites::ForContext(
          web_ui()->GetWebContents()->GetBrowserContext());
    }
    // The pref observer repaints the list; this covers a request that
    // changed nothing.
    SendOffSites();
  }

  // [0 or 1]. The pref observer repaints.
  void HandleSetBlockingLevel(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && args.size() == 1 && args[0].is_int() &&
        (args[0].GetInt() == 0 || args[0].GetInt() == 1)) {
      prefs->SetInteger(prefs::kBoringBlockingLevel, args[0].GetInt());
    }
    SendLevel();
  }

  // [text]. Saved as typed, applied at once, then checked off the UI
  // thread so the page can list the lines the engine will not use.
  void HandleSetCustomRules(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (!prefs || args.size() != 1 || !args[0].is_string() ||
        args[0].GetString().size() > kMaxCustomRulesLength) {
      return;
    }
    const std::string text = args[0].GetString();
    prefs->SetString(prefs::kBoringCustomRules, text);
    ApplyCustomRules(web_ui()->GetWebContents()->GetBrowserContext());
    base::ThreadPool::PostTaskAndReplyWithResult(
        FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_VISIBLE},
        base::BindOnce(
            [](const std::string& rules) { return CheckCustomRules(rules); },
            text),
        base::BindOnce(&ProtectionMessageHandler::OnCustomRulesChecked,
                       weak_factory_.GetWeakPtr()));
  }

  void OnCustomRulesChecked(std::vector<CustomRuleProblem> problems) {
    if (!IsJavascriptAllowed()) {
      return;
    }
    base::ListValue list;
    for (const CustomRuleProblem& problem : problems) {
      list.Append(base::DictValue()
                      .Set("line", static_cast<int>(problem.line))
                      .Set("rule", problem.rule)
                      .Set("error", problem.error));
    }
    web_ui()->CallJavascriptFunctionUnsafe("showFilterProblems", list);
  }

  void HandleSetMemorySaver(const base::ListValue& args) {
    if (args.size() == 1 && args[0].is_bool()) {
      SetMemorySaverOn(args[0].GetBool());
    }
    HandleGet(args);
  }

  // [0, 1 or 2]: Chromium's Moderate, Balanced and Maximum.
  void HandleSetMemorySaverLevel(const base::ListValue& args) {
    if (args.size() == 1 && args[0].is_int() && args[0].GetInt() >= 0 &&
        args[0].GetInt() <= static_cast<int>(MemorySaverLevel::kMaximum)) {
      SetMemorySaverLevel(static_cast<MemorySaverLevel>(args[0].GetInt()));
    }
    HandleGet(args);
  }

  // [site, false]. Only taking a site off is offered here; a site is
  // added from the shield, on the site itself.
  void HandleSetNeverSleep(const base::ListValue& args) {
    if (args.size() == 2 && args[0].is_string() && args[1].is_bool() &&
        !args[1].GetBool()) {
      const GURL site(args[0].GetString());
      if (site.is_valid() && site.SchemeIsHTTPOrHTTPS()) {
        performance::SetNeverSleep(
            web_ui()->GetWebContents()->GetBrowserContext(), site, false);
      }
    }
    // The pref observer repaints; this covers a request that changed
    // nothing.
    SendNeverSleep();
  }

  PrefChangeRegistrar registrar_;
  base::ScopedObservation<extensions::ExtensionRegistry,
                          extensions::ExtensionRegistryObserver>
      extensions_observation_{this};
  // The regional lists this build ships, once read.
  std::vector<RegionalListInfo> regional_;
  bool regional_requested_ = false;
  base::WeakPtrFactory<ProtectionMessageHandler> weak_factory_{this};
};

bool ShouldHandle(const std::string& path) {
  return path.empty() || path == "protection.js" || path == "brand.svg";
}

void Handle(const std::string& path,
            content::WebUIDataSource::GotDataCallback callback) {
  // The script is its own file so the page's security rules can stay
  // strict about inline script.
  // brand.svg is the tab icon; its type comes from the .svg ending
  // (WebUIDataSourceImpl::GetMimeType).
  std::string body;
  if (path == "protection.js") {
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
