// Copyright 2026 boring. BSD style license.

#include "components/boring/protection/protection_ui.h"

#include <algorithm>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "base/functional/bind.h"
#include "base/json/json_reader.h"
#include "base/memory/ref_counted_memory.h"
#include "base/memory/weak_ptr.h"
#include "base/no_destructor.h"
#include "base/scoped_observation.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/thread_pool.h"
#include "base/time/time.h"
#include "base/values.h"
#include "chrome/browser/extensions/extension_uninstall_dialog.h"
#include "chrome/browser/profiles/profile.h"
#include "components/boring/adblock/adblock_service.h"
#include "components/boring/adblock/blocking_off_sites.h"
#include "components/boring/adblock/custom_rules.h"
#include "components/boring/ai/ai_prefs.h"
#include "components/boring/branding/brand_mark.h"
#include "components/boring/core/boring_capabilities.h"
#include "components/boring/core/boring_prefs.h"
#include "components/boring/lists/list_paths.h"
#include "components/boring/lists/list_updater.h"
#include "components/boring/performance/never_sleep_sites.h"
#include "components/boring/privacy/privacy_state.h"
#include "components/boring/protection/apps_data.h"
#include "components/boring/protection/connections_data.h"
#include "components/boring/protection/memory_saver.h"
#include "components/boring/scam/scam_service.h"
#include "components/boring/update/browser_updater.h"
#include "components/password_manager/core/common/password_manager_pref_names.h"
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
#include "extensions/browser/disable_reason.h"
#include "extensions/browser/extension_prefs.h"
#include "extensions/browser/extension_registrar.h"
#include "extensions/browser/extension_registry.h"
#include "extensions/browser/extension_registry_observer.h"
#include "extensions/browser/extension_system.h"
#include "extensions/browser/management_policy.h"
#include "extensions/browser/permissions_manager.h"
#include "extensions/browser/uninstall_reason.h"
#include "extensions/browser/unloaded_extension_reason.h"
#include "extensions/common/extension.h"
#include "extensions/common/manifest.h"
#include "extensions/common/permissions/permission_message.h"
#include "extensions/common/permissions/permission_message_provider.h"
#include "extensions/common/permissions/permission_set.h"
#include "extensions/common/permissions/permissions_data.h"
#include "url/gurl.h"

namespace boring {

namespace {

constexpr char kPage[] = R"PAGE(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Protection</title>
<link rel="icon" type="image/svg+xml" href="brand.svg">
<link rel="stylesheet" href="chrome://theme/colors.css?sets=ui,chrome">
<style>
  :root { color-scheme: light dark;
    --surface: var(--color-location-bar-background, light-dark(#faf9f6, #1c2422));
    --paper: var(--color-dialog-background, light-dark(#ffffff, #252e2b));
    --ink: var(--color-dialog-foreground, light-dark(#242e2d, #e8ede7));
    --muted: var(--color-label-foreground-secondary, light-dark(#5d6966, #adb9b2));
    --line: var(--color-bubble-border, light-dark(#d8ddd7, #414e47));
    /* Control edges: 3:1 or more against the page in both themes. */
    --field: color-mix(in srgb, var(--ink) 52%, var(--surface));
    --accent: var(--color-sys-primary, light-dark(#176b5b, #92d4bb));
    --on-accent: var(--color-sys-on-primary, light-dark(#faf9f6, #092b25));
    --soft: var(--color-sys-primary-container, light-dark(#e5f1eb, #273f35));
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
  .conn-part > h3 { font-size: 14px; font-weight: 600; margin: 4px 0 0; }
  .conn-part > h4 { font-size: 12px; font-weight: 600; margin: 14px 0 0;
                    color: var(--muted); }
  .conn-part > p.muted { margin: 4px 0 0; }
  #connections-lists { margin-top: 12px; }
  #connections-lists .setting-row { cursor: auto; }
  #connections-lists .setting-row strong { overflow-wrap: anywhere; }
  .add-list { padding: 16px 0; border-top: 1px solid var(--line); }
  .add-list label strong { font-size: 14px; font-weight: 600; }
  .add-list p { font-size: 12px; margin: 5px 0 0; color: var(--muted); }
  .add-list .actions { margin-top: 10px; display: flex; gap: 10px; }
  .add-list input[type="text"] { flex: 1; min-width: 0; padding: 8px 12px;
                      border: 1px solid var(--field); border-radius: 8px;
                      background: var(--paper); color: var(--ink);
                      font: inherit; }
  #connections-apps { margin-top: 24px; }
  #connections-apps .setting-row { cursor: auto; }
  #connections-apps .setting-row[hidden] { display: none; }
  #connections-apps .setting-row strong { overflow-wrap: anywhere; }
  .app-controls { display: flex; align-items: center; gap: 12px; }
  .app-remove { font: inherit; min-height: 32px; padding: 4px 0;
                background: none; border: none; cursor: pointer; }
  .conn-host { font-weight: 400; color: var(--muted); font-size: 12px;
               margin-inline-start: 8px; overflow-wrap: anywhere; }
  .conn-note { font-weight: 550; }
  .state-row p { font-size: 12px; margin: 6px 0 0; color: var(--muted); }
  .setting-row { display: flex; gap: 20px; justify-content: space-between;
                 align-items: center; border-top: 1px solid var(--line);
                 padding: 16px 0; cursor: pointer; }
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
  .primary { background: var(--accent); color: var(--on-accent); }
  .secondary { border: 1px solid var(--line); background: var(--paper);
               color: var(--ink); }
  /* Press and hover: colour and a small scale only, so input never waits. */
  .primary, .secondary, .text-button {
    transition: background-color 150ms ease-out, color 150ms ease-out,
                border-color 150ms ease-out, transform 150ms ease-out; }
  .primary:active, .secondary:active { transform: scale(0.98); }
  .text-button:active { transform: scale(0.98); }
  @media (hover: hover) {
    .primary:hover { background: color-mix(in srgb, var(--accent) 86%, var(--ink)); }
    .text-button:hover { text-decoration: underline; text-underline-offset: 3px; }
  }
  @media (hover: hover) { .secondary:hover { background: var(--soft); } }
  /* Status text and list reloads fade in rather than swap. */
  @keyframes settle { from { opacity: 0; } }
  .state-value, .site-list li, .problem-list li { animation: settle 150ms ease-out; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .hidden { display: none; }
  .text-button { color: var(--accent); }
  .site-list { list-style: none; margin: 10px 0 0; padding: 0; }
  /* With no sites the empty list would still add its 10px, and this row
     would stand taller than the others. */
  .site-list:empty { margin: 0; }
  .site-list li { display: flex; justify-content: space-between;
                  align-items: center; gap: 14px; padding: 6px 0;
                  font-size: 13px; }
  .site-list .secondary { min-height: 32px; padding: 6px 14px; }
  .regional { border: none; border-top: 1px solid var(--line);
              margin: 0; padding: 16px 0; min-width: 0; }
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
            padding: 16px 0; min-width: 0; }
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
    .primary, .secondary, .text-button { transition: none; }
    .primary:active, .secondary:active, .text-button:active { transform: none; }
    .state-value, .site-list li, .problem-list li { animation: none; }
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

  <label class="setting-row" for="hide-cookies">
    <span><strong>Block cookie banners</strong>
      <p>Hides cookie banners, and says no on the ones that ask for an
      answer.</p></span>
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

  <label class="setting-row" for="skip-redirects">
    <span><strong>Skip tracking redirects</strong>
      <p>Opens the real page when a link goes through a redirect page
      first, such as the ones Facebook and Google use for outside links,
      or through an AMP copy.</p></span>
    <input class="switch" type="checkbox" id="skip-redirects">
  </label>

  <label class="setting-row" for="fingerprint">
    <span><strong>Fingerprint noise</strong>
      <p>Adds a tiny random change to what pages read back from canvas
      drawing, text sizes and element sizes, so those readings stop
      identifying this browser. Every page also reads the same graphics
      card name, core count, touch points and a common screen size. A few
      sites that draw charts or games may look very slightly different.</p></span>
    <input class="switch" type="checkbox" id="fingerprint">
  </label>

  <label class="setting-row" for="stop-takeovers">
    <span><strong>Stop screen takeovers</strong>
      <p>Stops a page from locking your screen or keyboard with fake
      alerts.</p></span>
    <input class="switch" type="checkbox" id="stop-takeovers">
  </label>

  <label class="setting-row" for="warn-scam-tricks">
    <span><strong>Warn about scam tricks</strong>
      <p>Asks first before a download of a remote control tool such as
      AnyDesk, stops a page from copying a command for you to run, and
      warns when a site's name copies another site's.</p></span>
    <input class="switch" type="checkbox" id="warn-scam-tricks">
  </label>

  <label class="setting-row" for="no-bypass">
    <span><strong>No way past scam warnings</strong>
      <p>Takes away the continue anyway link on a scam warning.</p></span>
    <input class="switch" type="checkbox" id="no-bypass">
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

  <label class="setting-row" for="hide-ads">
    <span><strong>Hide sponsored results</strong>
      <p>Removes paid results from Google and Bing searches.</p></span>
    <input class="switch" type="checkbox" id="hide-ads">
  </label>

  <h2 class="section" id="connections-title">What the browser connects to</h2>
  <p class="muted">Everything this browser reaches on its own. Turn off
  what you do not want.</p>
  <div class="conn-part" id="connections-own" role="group"
      aria-label="On its own"></div>
  <div class="conn-part" id="connections-lists" role="group"
      aria-label="Filter lists you added">
    <div id="user-list-rows"></div>
    <div class="add-list">
      <label for="user-list-address"><strong>Add a filter list</strong></label>
      <p id="user-list-desc">Paste its address. It must start with https://
      and be under 5 MB. It is downloaded now and then about once a week.</p>
      <div class="actions">
        <input type="text" id="user-list-address" spellcheck="false"
            autocomplete="off" aria-describedby="user-list-desc">
        <button class="secondary" id="add-user-list">Add</button>
      </div>
      <p id="user-list-status" role="status"></p>
    </div>
  </div>
  <div class="conn-part" id="connections-apps" role="group"
      aria-label="Apps you added"></div>

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
  el('check-update-row').hidden = !ready;
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
  var row = el('conn-web_store');
  if (row) {
    row.checked = state === 'on';
    row.disabled = state === 'removed';
    el('conn-detail-web_store').textContent =
        state === 'removed' ? 'The store is not installed.' : '';
  }
}

// "What the browser connects to", part "On its own": one row for each
// connection in connections.json, with its host, why, and a real switch.
// Rebuilt only when the set of rows changes, so a click keeps focus.
function showOwnConnections(rows) {
  var box = el('connections-own');
  var ids = rows.map(function(r) { return r.id; }).join();
  if (box.dataset.ids !== ids) {
    box.textContent = '';
    box.dataset.ids = ids;
    var title = document.createElement('h3');
    title.textContent = 'On its own';
    box.append(title);
    rows.forEach(function(row) {
      var label = document.createElement('label');
      label.className = 'setting-row';
      label.id = 'conn-row-' + row.id;
      label.htmlFor = 'conn-' + row.id;
      var text = document.createElement('span');
      var name = document.createElement('strong');
      name.append(row.label);
      var host = document.createElement('span');
      host.className = 'conn-host';
      host.textContent = row.hosts.join(', ');
      name.append(host);
      var why = document.createElement('p');
      why.textContent = row.why;
      text.append(name, why);
      if (row.off_note) {
        var note = document.createElement('p');
        note.className = 'conn-note';
        note.id = 'conn-note-' + row.id;
        note.textContent = row.off_note;
        text.append(note);
      }
      var detail = document.createElement('p');
      detail.id = 'conn-detail-' + row.id;
      text.append(detail);
      var check = document.createElement('input');
      check.type = 'checkbox';
      check.className = 'switch';
      check.id = 'conn-' + row.id;
      check.addEventListener('change', function(e) {
        chrome.send('setConnection', [row.id, e.target.checked]);
        say(row.label + (e.target.checked ? ' on.' : ' off.'));
      });
      label.append(text, check);
      box.append(label);
    });
  }
  rows.forEach(function(row) {
    var check = el('conn-' + row.id);
    check.checked = row.on;
    check.disabled = !row.canSwitch;
    el('conn-detail-' + row.id).textContent = row.unavailable || '';
  });
}

// The filter lists a person added by address, each with its host, when it
// was last downloaded, and Remove. Rebuilt only when a row changes.
function showUserLists(lists) {
  var box = el('user-list-rows');
  var key = JSON.stringify(lists);
  if (box.dataset.key === key) { return; }
  var focused = document.activeElement;
  var focusUrl = focused && box.contains(focused) ? focused.dataset.url : '';
  box.dataset.key = key;
  box.textContent = '';
  lists.forEach(function(list) {
    var lines = [];
    var when = list.updated ?
        new Date(list.updated).toLocaleString() : '';
    if (list.busy) {
      lines.push('Downloading.');
    } else if (list.error) {
      lines.push(list.error + (when ? ' Using the copy from ' + when + '.' :
                                      ' Not used.'));
    } else if (when) {
      lines.push('Updated ' + when + '.');
    }
    var built = appRow('user-list-' + list.id, 'Filter list', list.host,
        lines, false);
    built.row.dataset.url = list.url;
    var remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'text-button app-remove';
    remove.textContent = 'Remove';
    remove.dataset.url = list.url;
    remove.setAttribute('aria-label', 'Remove the list from ' + list.host);
    remove.addEventListener('click', function() {
      chrome.send('removeUserList', [list.url]);
      say('List removed.');
    });
    built.controls.append(remove);
    box.append(built.row);
  });
  if (focusUrl) {
    var back = Array.prototype.find.call(box.querySelectorAll('button'),
        function(b) { return b.dataset.url === focusUrl; });
    if (back) { back.focus(); } else { el('user-list-address').focus(); }
  }
}

function showUserListStatus(text) {
  el('user-list-status').textContent = text;
  if (!text) { el('user-list-address').value = ''; }
}

// "What the browser connects to", part "Apps you added": one row per
// add-on with Chromium's own wording for what it can do.
// Rebuilt only when the rows change, so a click keeps focus.
function appRow(id, name, host, lines, withSwitch) {
  var row = document.createElement('div');
  row.className = 'setting-row';
  row.id = id + '-row';
  var text = document.createElement('span');
  var strong = document.createElement('strong');
  var label = document.createElement(withSwitch ? 'label' : 'span');
  if (withSwitch) { label.htmlFor = id; }
  label.textContent = name;
  strong.append(label);
  if (host) {
    var h = document.createElement('span');
    h.className = 'conn-host';
    h.textContent = host;
    strong.append(h);
  }
  text.append(strong);
  lines.forEach(function(line) {
    var p = document.createElement('p');
    p.textContent = line;
    text.append(p);
  });
  var controls = document.createElement('span');
  controls.className = 'app-controls';
  var check;
  if (withSwitch) {
    check = document.createElement('input');
    check.type = 'checkbox';
    check.className = 'switch';
    check.id = id;
    controls.append(check);
  }
  row.append(text, controls);
  return {row: row, check: check, controls: controls};
}

function appLink(href, name) {
  var link = document.createElement('a');
  link.className = 'text-button';
  link.href = href;
  link.textContent = name;
  return link;
}

function showApps(apps, ai, passwords) {
  var box = el('connections-apps');
  var key = JSON.stringify([apps.map(function(a) {
    return [a.id, a.name, a.group, a.line, a.perms, a.canRemove];
  }), ai.label, ai.host]);
  // A rebuild drops the focused control; the same one gets focus back.
  var focused = document.activeElement;
  var focusId = focused && box.contains(focused) ? focused.id : '';
  if (box.dataset.key !== key) {
    box.textContent = '';
    box.dataset.key = key;
    var title = document.createElement('h3');
    title.textContent = 'Apps you added';
    var intro = document.createElement('p');
    intro.className = 'muted';
    intro.textContent =
        'Any add-on can reach the internet. Turn off the ones you do not use.';
    box.append(title, intro);
    var addGroup = function(heading, group) {
      var rows = apps.filter(function(a) { return a.group === group; });
      if (!rows.length && group !== 'password' && group !== 'ai') { return; }
      var h = document.createElement('h4');
      h.textContent = heading;
      box.append(h);
      rows.forEach(function(app) {
        var lines = [];
        if (app.line) { lines.push(app.line); }
        app.perms.forEach(function(p) { lines.push(p); });
        var built = appRow('app-' + app.id, app.name, '', lines, true);
        built.check.addEventListener('change', function(e) {
          chrome.send('setApp', [app.id, e.target.checked]);
        });
        if (app.canRemove) {
          var remove = document.createElement('button');
          remove.type = 'button';
          remove.className = 'text-button app-remove';
          remove.textContent = 'Remove';
          remove.setAttribute('aria-label', 'Remove ' + app.name);
          remove.addEventListener('click', function() {
            chrome.send('removeApp', [app.id]);
          });
          built.controls.append(remove);
        }
        box.append(built.row);
      });
    };
    addGroup('Password managers', 'password');
    var saved = appRow('saved-passwords', 'Saved passwords in this browser',
        '', ['Stays on this computer.'], false);
    saved.controls.append(appLink('chrome://password-manager/settings',
                                 'Export'));
    box.append(saved.row);
    var saving = appRow('stop-saving-passwords',
        'Stop this browser offering to save passwords', '', [], true);
    saving.check.addEventListener('change', function(e) {
      chrome.send('setStopSavingPasswords', [e.target.checked]);
    });
    box.append(saving.row);
    addGroup('Folders and cloud', 'cloud');
    addGroup('AI', 'ai');
    var aiBuilt = appRow('ai-assistant', 'AI assistant', ai.host,
        [ai.label], true);
    aiBuilt.controls.append(appLink('chrome://boring-ai',
                                   ai.on ? 'Change' : 'Set up'));
    aiBuilt.check.addEventListener('change', function(e) {
      if (!e.target.checked) {
        chrome.send('setAiOff', []);
        say('AI assistant off.');
      }
    });
    box.append(aiBuilt.row);
    addGroup('Other add-ons', 'other');
    if (!apps.length) {
      var empty = document.createElement('p');
      empty.id = 'apps-empty';
      empty.className = 'muted';
      empty.append('No apps added. ');
      empty.append('To add one, install an add-on from the web store.');
      box.append(empty);
    }
  }
  apps.forEach(function(app) {
    var check = el('app-' + app.id);
    check.checked = app.on;
    check.disabled = !app.canSwitch;
  });
  el('stop-saving-passwords-row').hidden = !passwords.show;
  el('stop-saving-passwords').checked = passwords.stopped;
  el('stop-saving-passwords').disabled = !passwords.canChange;
  var aiCheck = el('ai-assistant');
  aiCheck.checked = ai.on;
  aiCheck.disabled = !ai.canTurnOff;
  if (focusId && !box.contains(document.activeElement)) {
    // The AI switch is unusable once it is off: go to Set up instead.
    var back = el(focusId);
    if (back && back.disabled && focusId === 'ai-assistant') {
      back = box.querySelector('#ai-assistant-row a');
    }
    if (back && !back.disabled) { back.focus(); }
  }
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
  showState('scam', s.scam,
      'Known listed sites are blocked before they open.', s.scamProblem);
  showState('ads', s.ads,
      'Known advertising and tracking requests are blocked.', s.adsProblem);
  showOffSites(s.offSites);
  showWebStore(s.webStore);
  showLists(s.listDays, s.listUpdates, s.listUpdatesAvailable);
  showConnections(s);
  showOwnConnections(s.connections);
  showUserLists(s.userLists);
  showApps(s.apps, s.ai, s.passwords);
  el('hide-cookies').checked = s.hideCookies;
  el('fingerprint').checked = s.fingerprint;
  el('strip-params').checked = s.stripParams;
  el('skip-redirects').checked = s.skipRedirects;
  showUpdates(s.update, s.updateAuto, s.version);
  showLevel(s.level);
  if (!filtersLoaded) {
    el('my-filters').value = s.customRules;
    filtersLoaded = true;
  }
  showMemory(s.memory);
  showNeverSleep(s.neverSleep);

  el('stop-takeovers').checked = s.stopTakeovers;
  el('warn-scam-tricks').checked = s.warnScamTricks;
  el('no-bypass').checked = s.noBypass;
  el('hide-ads').checked = s.hideSponsored;

  // Keep asking only while something is still starting up.
  var starting = s.scam === 'loading' || s.ads === 'loading' ||
      s.update === 'starting' || s.userLists.some(function(l) {
        return l.busy;
      });
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

el('stop-takeovers').addEventListener('change', function(e) {
  chrome.send('setStopTakeovers', [e.target.checked]);
  say(e.target.checked ? 'Screen takeovers will be stopped.'
                       : 'Screen takeovers will not be stopped.');
});

el('warn-scam-tricks').addEventListener('change', function(e) {
  chrome.send('setWarnScamTricks', [e.target.checked]);
  say(e.target.checked ? 'Scam tricks will be warned about.'
                       : 'Scam tricks will not be warned about.');
});

el('no-bypass').addEventListener('change', function(e) {
  if (e.target.checked) {
    chrome.send('setNoScamBypass', [true]);
    say('Scam warnings have no way past them.');
    return;
  }
  // Turning it off is the one change a scammer asks for, so ask first.
  e.target.checked = true;
  el('confirm-off').classList.remove('hidden');
  el('keep-on').focus();
});

el('keep-on').addEventListener('click', function() {
  el('confirm-off').classList.add('hidden');
  el('no-bypass').focus();
});

el('turn-off').addEventListener('click', function() {
  el('confirm-off').classList.add('hidden');
  chrome.send('setNoScamBypass', [false]);
  el('no-bypass').focus();
  say('Scam warnings can be continued past.');
});

el('strip-params').addEventListener('change', function(e) {
  chrome.send('setStripParams', [e.target.checked]);
  say(e.target.checked ? 'Tracking will be removed from links.'
                       : 'Links will be opened as they are.');
});

el('skip-redirects').addEventListener('change', function(e) {
  chrome.send('setSkipRedirects', [e.target.checked]);
  say(e.target.checked ? 'Redirect pages will be skipped.'
                       : 'Redirect pages will be opened.');
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

el('check-update').addEventListener('click', function() {
  chrome.send('checkUpdateNow');
});


el('hide-cookies').addEventListener('change', function(e) {
  chrome.send('setHideCookieNotices', [e.target.checked]);
  say(e.target.checked ? 'Cookie banners blocked.' : 'Cookie banners allowed.');
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

el('add-user-list').addEventListener('click', function() {
  el('user-list-status').textContent = 'Adding.';
  chrome.send('addUserList', [el('user-list-address').value]);
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
window.showUserListStatus = showUserListStatus;
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

// The rows of "On its own": connections.json, compiled in as
// kConnectionsJson. Null only if the file is broken, which
// tools/check_connections.py stops at push time.
const base::ListValue* ConnectionList() {
  static const base::NoDestructor<std::optional<base::DictValue>> root(
      base::JSONReader::ReadDict(kConnectionsJson, base::JSON_PARSE_RFC));
  return root->has_value() ? (*root)->FindList("connections") : nullptr;
}

// The Chromium Web Store extension we bundle (NeverDecaf, pinned by
// tools/get_chromium_web_store.py). It asks Google about installed store
// extensions, so the page says whether it is there.
constexpr char kWebStoreExtensionId[] = "ocaahdebbfolfmndjeplogmgcagdmblk";

class ProtectionMessageHandler : public content::WebUIMessageHandler,
                                 public extensions::ExtensionRegistryObserver,
                                 public extensions::PermissionsManager::Observer,
                                 public extensions::ExtensionUninstallDialog::Delegate {
 public:
  ProtectionMessageHandler() = default;
  ~ProtectionMessageHandler() override = default;

  void RegisterMessages() override {
    web_ui()->RegisterMessageCallback(
        "getProtection",
        base::BindRepeating(&ProtectionMessageHandler::HandleGet,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setStopTakeovers",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetStopTakeovers,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setWarnScamTricks",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetWarnScamTricks,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setNoScamBypass",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetNoScamBypass,
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
        "setSkipRedirects",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetSkipRedirects,
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
        "setConnection",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetConnection,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "addUserList",
        base::BindRepeating(&ProtectionMessageHandler::HandleAddUserList,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "removeUserList",
        base::BindRepeating(&ProtectionMessageHandler::HandleRemoveUserList,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setApp",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetApp,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "removeApp",
        base::BindRepeating(&ProtectionMessageHandler::HandleRemoveApp,
                            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setStopSavingPasswords",
        base::BindRepeating(
            &ProtectionMessageHandler::HandleSetStopSavingPasswords,
            base::Unretained(this)));
    web_ui()->RegisterMessageCallback(
        "setAiOff",
        base::BindRepeating(&ProtectionMessageHandler::HandleSetAiOff,
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
    for (const char* pref : {password_manager::prefs::kCredentialsEnableService,
                             ai::prefs::kProvider, ai::prefs::kOllamaUrl}) {
      if (prefs->FindPreference(pref)) {
        registrar_.Add(
            pref, base::BindRepeating(&ProtectionMessageHandler::SendApps,
                                      base::Unretained(this)));
      }
    }
    if (extensions::ExtensionRegistry* registry = GetExtensionRegistry()) {
      extensions_observation_.Observe(registry);
    }
    if (extensions::PermissionsManager* permissions =
            extensions::PermissionsManager::Get(
                web_ui()->GetWebContents()->GetBrowserContext())) {
      permissions_observation_.Observe(permissions);
    }
  }

  void OnJavascriptDisallowed() override {
    registrar_.RemoveAll();
    extensions_observation_.Reset();
    permissions_observation_.Reset();
  }

  // extensions::ExtensionRegistryObserver:
  // Turned on, off, added or removed on chrome://extensions while this
  // page is open: say so here too.
  void OnExtensionLoaded(content::BrowserContext* context,
                         const extensions::Extension* extension) override {
    SendWebStoreIfOurs(extension);
    SendApps();
  }
  void OnExtensionUnloaded(
      content::BrowserContext* context,
      const extensions::Extension* extension,
      extensions::UnloadedExtensionReason reason) override {
    SendWebStoreIfOurs(extension);
    SendApps();
  }
  void OnExtensionInstalled(content::BrowserContext* context,
                            const extensions::Extension* extension,
                            bool is_update) override {
    SendApps();
  }
  void OnExtensionUninstalled(content::BrowserContext* context,
                              const extensions::Extension* extension,
                              extensions::UninstallReason reason) override {
    SendWebStoreIfOurs(extension);
    SendApps();
  }
  void OnShutdown(extensions::ExtensionRegistry* registry) override {
    extensions_observation_.Reset();
  }

  // extensions::PermissionsManager::Observer:
  // Site access changed on chrome://extensions or by policy: the rows
  // quote Chromium's permission text, so repaint them.
  void OnExtensionPermissionsUpdated(
      const extensions::Extension& extension,
      const extensions::PermissionSet& permissions,
      extensions::PermissionsManager::UpdateReason reason) override {
    SendApps();
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

  static bool IsListedAddon(const extensions::Extension& extension) {
    return extension.is_extension() && extension.id() != kWebStoreExtensionId &&
           !extensions::Manifest::IsComponentLocation(extension.location());
  }

  extensions::ManagementPolicy* AddonPolicy() {
    auto* context = web_ui()->GetWebContents()->GetBrowserContext();
    auto* system = extensions::ExtensionSystem::Get(context);
    return !context->IsOffTheRecord() && system ? system->management_policy()
                                               : nullptr;
  }

  bool CanSwitchAddon(const extensions::Extension& extension, bool on) {
    auto* policy = AddonPolicy();
    if (!policy || !policy->UserMayModifySettings(&extension, nullptr)) {
      return false;
    }
    if (on) {
      return !policy->MustRemainEnabled(&extension, nullptr);
    }
    // Anything Chromium disabled for a reason other than a user choosing
    // Off must go through Chromium's own review and recovery flow.
    auto* registry = GetExtensionRegistry();
    auto* prefs = extensions::ExtensionPrefs::Get(
        web_ui()->GetWebContents()->GetBrowserContext());
    return !policy->MustRemainDisabled(&extension, nullptr) && prefs &&
           registry->disabled_extensions().Contains(extension.id()) &&
           prefs->HasOnlyDisableReason(
               extension.id(), extensions::disable_reason::DISABLE_USER_ACTION);
  }

  bool CanRemoveAddon(const extensions::Extension& extension) {
    auto* policy = AddonPolicy();
    return policy && policy->UserMayModifySettings(&extension, nullptr) &&
           !policy->MustRemainInstalled(&extension, nullptr);
  }

  base::ListValue AppRows() {
    base::ListValue rows;
    extensions::ExtensionRegistry* registry = GetExtensionRegistry();
    if (!registry) {
      return rows;
    }
    std::vector<std::pair<std::string, base::DictValue>> found;
    const extensions::PermissionMessageProvider* provider =
        extensions::PermissionMessageProvider::Get();
    for (const auto& extension : registry->GenerateInstalledExtensionsSet()) {
      if (!IsListedAddon(*extension)) {
        continue;
      }
      base::ListValue perms;
      for (const extensions::PermissionMessage& message :
           provider->GetPermissionMessages(provider->GetAllPermissionIDs(
               extension->permissions_data()->active_permissions(),
               extension->GetType()))) {
        perms.Append(base::UTF16ToUTF8(message.message()));
        for (const auto& detail : message.submessages()) {
          perms.Append(base::UTF16ToUTF8(detail));
        }
      }
      const KnownAddon* known = FindKnownAddon(extension->id());
      base::DictValue row;
      row.Set("id", extension->id());
      row.Set("name", extension->name());
      row.Set("group", AddonGroupKey(GroupForAddon(extension->id())));
      row.Set("line", known ? known->line : "");
      row.Set("perms", std::move(perms));
      const bool on = registry->enabled_extensions().Contains(extension->id());
      row.Set("on", on);
      row.Set("canSwitch", CanSwitchAddon(*extension, on));
      row.Set("canRemove", CanRemoveAddon(*extension));
      found.emplace_back(extension->name(), std::move(row));
    }
    std::sort(found.begin(), found.end(),
              [](const auto& a, const auto& b) { return a.first < b.first; });
    for (auto& entry : found) {
      rows.Append(std::move(entry.second));
    }
    return rows;
  }

  // The AI assistant row, read from what chrome://boring-ai saved.
  base::DictValue AiRowValue() {
    std::string provider;
    std::string host;
    bool on_this_computer = false;
    bool can_change = false;
    if (PrefService* prefs = GetPrefs()) {
      if (const auto* pref = prefs->FindPreference(ai::prefs::kProvider)) {
        provider = prefs->GetString(ai::prefs::kProvider);
        can_change = pref->IsUserModifiable();
      }
      if (prefs->FindPreference(ai::prefs::kOllamaUrl)) {
        const GURL url(prefs->GetString(ai::prefs::kOllamaUrl));
        if (url.SchemeIsHTTPOrHTTPS()) {
          host = url.host();
        }
        on_this_computer = ai::OllamaStaysOnThisMachine(prefs);
      }
    }
    const AiRow row = DescribeAiRow(provider, host, on_this_computer);
    base::DictValue out;
    out.Set("on", row.on);
    out.Set("label", row.label);
    out.Set("host", row.host);
    out.Set("canTurnOff", row.on && can_change);
    return out;
  }

  bool HasEnabledPasswordAddon() {
    if (auto* registry = GetExtensionRegistry()) {
      for (const auto& extension : registry->enabled_extensions()) {
        if (GroupForAddon(extension->id()) == AddonGroup::kPasswordManager) {
          return true;
        }
      }
    }
    return false;
  }

  base::DictValue PasswordRowValue() {
    PrefService* prefs = GetPrefs();
    const auto* pref = prefs ? prefs->FindPreference(
                                   password_manager::prefs::kCredentialsEnableService)
                             : nullptr;
    base::DictValue out;
    out.Set("show", pref && HasEnabledPasswordAddon());
    out.Set("stopped", pref && !pref->GetValue()->GetBool());
    out.Set("canChange", pref && pref->IsUserModifiable() &&
                             !web_ui()->GetWebContents()->GetBrowserContext()
                                  ->IsOffTheRecord());
    return out;
  }

  void SendApps() {
    if (IsJavascriptAllowed()) {
      web_ui()->CallJavascriptFunctionUnsafe("showApps", AppRows(),
                                             AiRowValue(), PasswordRowValue());
    }
  }

  // The switch behind one add-on row. Only an add-on that has a row can be
  // switched from here, never one the page names by guess.
  void HandleSetApp(const base::ListValue& args) {
    extensions::ExtensionRegistry* registry = GetExtensionRegistry();
    if (registry && args.size() == 2 && args[0].is_string() &&
        args[1].is_bool()) {
      const std::string& id = args[0].GetString();
      const extensions::Extension* extension =
          registry->GetInstalledExtension(id);
      extensions::ExtensionRegistrar* registrar =
          extensions::ExtensionRegistrar::Get(
              web_ui()->GetWebContents()->GetBrowserContext());
      const bool on = registry->enabled_extensions().Contains(id);
      if (extension && registrar && IsListedAddon(*extension) &&
          on != args[1].GetBool() && CanSwitchAddon(*extension, on)) {
        if (args[1].GetBool()) {
          registrar->EnableExtension(id);
        } else {
          registrar->DisableExtension(
              id, {extensions::disable_reason::DISABLE_USER_ACTION});
        }
      }
    }
    SendApps();
  }

  void HandleRemoveApp(const base::ListValue& args) {
    auto* registry = GetExtensionRegistry();
    if (uninstall_dialog_open_ || !registry || args.size() != 1 ||
        !args[0].is_string()) {
      return;
    }
    const auto* extension = registry->GetInstalledExtension(args[0].GetString());
    if (!extension || !IsListedAddon(*extension) || !CanRemoveAddon(*extension)) {
      return;
    }
    auto* contents = web_ui()->GetWebContents();
    auto parent = contents->GetTopLevelNativeWindow();
    if (!parent) {
      return;
    }
    uninstall_dialog_ = extensions::ExtensionUninstallDialog::Create(
        Profile::FromBrowserContext(contents->GetBrowserContext()), parent, this);
    uninstall_dialog_open_ = true;
    uninstall_dialog_->ConfirmUninstall(
        base::WrapRefCounted(extension), extensions::UNINSTALL_REASON_USER_INITIATED,
        extensions::UNINSTALL_SOURCE_CHROME_EXTENSIONS_PAGE);
  }

  void OnExtensionUninstallDialogClosed(bool did_start_uninstall,
                                       const std::u16string& error) override {
    uninstall_dialog_open_ = false;
  }

  void HandleSetStopSavingPasswords(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    const auto settings = PasswordRowValue();
    if (args.size() == 1 && args[0].is_bool() &&
        settings.FindBool("show").value_or(false) &&
        settings.FindBool("canChange").value_or(false)) {
      prefs->SetBoolean(password_manager::prefs::kCredentialsEnableService,
                        !args[0].GetBool());
    }
    SendApps();
  }

  // The AI switch only turns the assistant off. Choosing a provider and
  // typing a key stay on chrome://boring-ai.
  void HandleSetAiOff(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (args.empty() && prefs &&
        AiRowValue().FindBool("canTurnOff").value_or(false)) {
      prefs->SetString(ai::prefs::kProvider, "off");
    }
    SendApps();
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

  // The switch behind one "On its own" row. The row's kind and pref come
  // from the compiled-in file, never from the page.
  void ApplyConnection(const std::string& id, bool on) {
    const base::ListValue* list = ConnectionList();
    if (!list) {
      return;
    }
    for (const base::Value& item : *list) {
      const base::DictValue* entry = item.GetIfDict();
      const std::string* entry_id = entry ? entry->FindString("id") : nullptr;
      const base::DictValue* sw = entry ? entry->FindDict("switch") : nullptr;
      const std::string* kind = sw ? sw->FindString("kind") : nullptr;
      if (!entry_id || *entry_id != id || !kind) {
        continue;
      }
      content::BrowserContext* context =
          web_ui()->GetWebContents()->GetBrowserContext();
      if (*kind == "local_state") {
        SetSecureDnsEnabled(on);
      } else if (*kind == "profile") {
        const std::string* pref = sw->FindString("pref");
        PrefService* prefs = GetPrefs();
        if (pref && prefs) {
          prefs->SetBoolean(*pref, on);
        }
      } else if (*kind == "updater") {
        BrowserUpdater::SetAutomatic(on);
      } else if (*kind == "extension") {
        const std::string* ext = sw->FindString("extension_id");
        extensions::ExtensionRegistrar* registrar =
            extensions::ExtensionRegistrar::Get(context);
        if (ext && registrar && std::string(WebStoreState()) != "removed") {
          if (on) {
            registrar->EnableExtension(*ext);
          } else {
            registrar->DisableExtension(
                *ext, {extensions::disable_reason::DISABLE_USER_ACTION});
          }
        }
      }
      return;
    }
  }

  void HandleAddUserList(const base::ListValue& args) {
    std::string problem = "Could not add the list.";
    if (args.size() == 1 && args[0].is_string()) {
      problem = AddUserList(web_ui()->GetWebContents()->GetBrowserContext(),
                            args[0].GetString());
    }
    AllowJavascript();
    web_ui()->CallJavascriptFunctionUnsafe("showUserListStatus",
                                           base::Value(problem));
    HandleGet(args);
  }

  void HandleRemoveUserList(const base::ListValue& args) {
    if (args.size() == 1 && args[0].is_string()) {
      RemoveUserList(web_ui()->GetWebContents()->GetBrowserContext(),
                     args[0].GetString());
    }
    HandleGet(args);
  }

  // The lists added by address, as the page draws them.
  base::ListValue UserListRows() {
    base::ListValue rows;
    int id = 0;
    for (const UserListInfo& list : GetUserLists(
             web_ui()->GetWebContents()->GetBrowserContext())) {
      base::DictValue row;
      row.Set("id", id++);
      row.Set("url", list.url);
      row.Set("host", list.host);
      row.Set("updated",
              list.updated.is_null()
                  ? 0.0
                  : list.updated.InMillisecondsFSinceUnixEpochIgnoringNull());
      row.Set("error", list.error);
      row.Set("busy", list.busy);
      rows.Append(std::move(row));
    }
    return rows;
  }

  void HandleSetConnection(const base::ListValue& args) {
    if (args.size() >= 2 && args[0].is_string() && args[1].is_bool()) {
      ApplyConnection(args[0].GetString(), args[1].GetBool());
    }
    HandleGet(args);
  }

  // What each "On its own" row shows: its text from the file and the
  // real state of its switch, read fresh each time.
  base::ListValue OwnConnections() {
    base::ListValue rows;
    const base::ListValue* list = ConnectionList();
    if (!list) {
      return rows;
    }
    content::BrowserContext* context =
        web_ui()->GetWebContents()->GetBrowserContext();
    PrefService* prefs = GetPrefs();
    for (const base::Value& item : *list) {
      const base::DictValue* entry = item.GetIfDict();
      const base::DictValue* sw = entry ? entry->FindDict("switch") : nullptr;
      const std::string* kind = sw ? sw->FindString("kind") : nullptr;
      if (!kind) {
        continue;
      }
      bool on = false;
      bool can_switch = true;
      std::string detail;
      if (*kind == "local_state") {
        const PrivacyState privacy = GetPrivacyState(context);
        on = !privacy.dns_mode.empty() && privacy.dns_mode != "off";
        can_switch = !privacy.dns_managed;
        if (privacy.dns_managed) {
          detail = "Set by your administrator.";
        }
      } else if (*kind == "profile") {
        const std::string* pref = sw->FindString("pref");
        on = pref && prefs && prefs->GetBoolean(*pref);
        if (!ListUpdater::CanUpdate()) {
          detail = "This copy gets new lists when you install a newer version.";
        }
      } else if (*kind == "updater") {
        const BrowserUpdater::State state = BrowserUpdater::GetState();
        const bool ready = state == BrowserUpdater::State::kReady;
        on = ready && BrowserUpdater::IsAutomatic();
        can_switch = ready;
        if (state == BrowserUpdater::State::kNoKey) {
          detail = "This preview does not update itself.";
        } else if (state == BrowserUpdater::State::kNotInstalled) {
          detail = "This copy was unpacked from a zip, so it does not "
                   "update itself.";
        } else if (state == BrowserUpdater::State::kNoLibrary) {
          detail = "The updater is missing from this copy.";
        } else if (state == BrowserUpdater::State::kDisabled) {
          detail = "Updates are turned off for this session.";
        }
      } else if (*kind == "extension") {
        const std::string state = WebStoreState();
        on = state == "on";
        can_switch = state != "removed";
        if (state == "removed") {
          detail = "The store is not installed.";
        }
      }
      base::DictValue row = entry->Clone();
      row.Remove("switch");
      row.Remove("code");
      row.Remove("scenario");
      row.Set("on", on);
      row.Set("canSwitch", can_switch);
      row.Set("unavailable", detail);
      rows.Append(std::move(row));
    }
    return rows;
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
    out.Set("connections", OwnConnections());
    out.Set("userLists", UserListRows());
    out.Set("apps", AppRows());
    out.Set("ai", AiRowValue());
    out.Set("passwords", PasswordRowValue());
    out.Set("adsProblem", ads->status_message());
    out.Set("stopTakeovers",
            prefs && prefs->GetBoolean(prefs::kStopTakeovers));
    out.Set("warnScamTricks",
            prefs && prefs->GetBoolean(prefs::kWarnScamTricks));
    out.Set("noBypass", prefs && prefs->GetBoolean(prefs::kNoScamBypass));
    out.Set("hideSponsored",
            prefs && prefs->GetBoolean(prefs::kHideSponsoredResults));
    out.Set("listDays", ListAgeInDays(ads, scam));
    out.Set("listUpdates", ListUpdater::IsEnabled(prefs));
    out.Set("listUpdatesAvailable", ListUpdater::CanUpdate());
    const PrivacyState privacy = GetPrivacyState(context);
    out.Set("httpsFirst", privacy.https_first);
    out.Set("httpsBalanced", privacy.https_balanced);
    out.Set("webrtc", privacy.webrtc_policy);
    out.Set("stripParams",
            prefs && prefs->GetBoolean(prefs::kStripTrackingParams));
    out.Set("skipRedirects",
            prefs && prefs->GetBoolean(prefs::kSkipRedirects));
    out.Set("fingerprint",
            prefs && prefs->GetBoolean(prefs::kFingerprintNoise));
    out.Set("hideCookies",
            prefs && prefs->GetBoolean(prefs::kBoringBlockCookieBanners));
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

  void HandleSetStopTakeovers(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kStopTakeovers, args[0].GetBool());
    }
    HandleGet(args);
  }

  void HandleSetWarnScamTricks(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kWarnScamTricks, args[0].GetBool());
    }
    HandleGet(args);
  }

  void HandleSetNoScamBypass(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kNoScamBypass, args[0].GetBool());
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

  void HandleSetSkipRedirects(const base::ListValue& args) {
    PrefService* prefs = GetPrefs();
    if (prefs && !args.empty() && args[0].is_bool()) {
      prefs->SetBoolean(prefs::kSkipRedirects, args[0].GetBool());
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
      prefs->SetBoolean(prefs::kBoringBlockCookieBanners, args[0].GetBool());
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
  base::ScopedObservation<extensions::PermissionsManager,
                          extensions::PermissionsManager::Observer>
      permissions_observation_{this};
  // The regional lists this build ships, once read.
  std::vector<RegionalListInfo> regional_;
  bool regional_requested_ = false;
  bool uninstall_dialog_open_ = false;
  std::unique_ptr<extensions::ExtensionUninstallDialog> uninstall_dialog_;
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
