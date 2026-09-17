/* Interface study: all state is local and simulated. No network requests. */
"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  view: "home",
  theme: "light",
  density: "comfortable",
  tabs: 3,
  activeTab: 0,
  failed: false,
  hideAds: true,
  senior: false,
  summary: "consent",
  section: "protection",
  history: [],
  forward: [],
  bookmarked: false,
};
const titles = ["New tab", "A quieter web", "Reading list"];
const names = {
  home: "New tab",
  search: "Search results",
  reader: "A quieter web",
  settings: "Settings",
  warning: "Site blocked",
  summary: "Page summary",
};
const escape = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
function announce(message) {
  $("announcement").textContent = message;
}
function closePanels() {
  for (const id of ["protection-panel", "download-panel"]) $(id).hidden = true;
  for (const id of ["protection", "downloads"])
    $(id).setAttribute("aria-expanded", "false");
}
function tabs() {
  $("tabs").innerHTML = Array.from(
    { length: state.tabs },
    (_, i) =>
      `<div class="tab-item" role="presentation"><button class="tab" role="tab" aria-controls="content" aria-selected="${i === state.activeTab}" tabindex="${i === state.activeTab ? 0 : -1}" data-tab="${i}"><span class="tab-mark" aria-hidden="true">${i === 0 ? "b." : i === 1 ? "R" : "◦"}</span><span>${i === state.activeTab ? names[state.view] : titles[i % 3] + (i > 2 ? " " + (i + 1) : "")}</span></button><button class="tab-close" data-close-tab="${i}" tabindex="${i === state.activeTab ? 0 : -1}" aria-label="Close tab ${i + 1}">×</button></div>`,
  ).join("");
}
function navigate(view, history = true) {
  if (history && view !== state.view) {
    state.history.push(state.view);
    state.forward = [];
  }
  state.view = view;
  closePanels();
  render();
}
function protectionRows() {
  return `<div class="state-row"><div class="state-line"><strong>Scam & phishing sites</strong><span class="state-value ${state.failed ? "warn" : ""}">${state.failed ? "Unavailable" : "On"}</span></div><p>${state.failed ? "The blocklist could not be loaded. Known scam sites are not being blocked." : "Known listed sites are blocked before they open."}</p></div><div class="state-row"><div class="state-line"><strong>Ads & trackers</strong><span class="state-value">On</span></div><p>Known advertising and tracking requests are blocked.</p></div><div class="state-row"><div class="state-line"><strong>Sponsored search results</strong><span class="state-value">${state.hideAds || state.senior ? "Hidden" : "Labeled"}</span></div><p>This applies to supported ad formats. Sponsored does not necessarily mean unsafe.</p></div>`;
}
function home() {
  return `<section class="home"><div class="eyebrow">A little less noise</div><h1>Your web.<br>Room to breathe.</h1><p class="intro">Find what you came for.</p><form class="search-form" id="home-search"><span aria-hidden="true">⌕</span><input aria-label="Search the web" placeholder="Search the web" autocomplete="off"><button aria-label="Search">→</button></form><div class="shortcuts"><button class="shortcut" data-view="reader"><span class="shortcut-mark">R</span>Reading</button><button class="shortcut" data-view="search"><span class="shortcut-mark">W</span>Wikipedia</button><button class="shortcut" data-view="settings"><span class="shortcut-mark">＋</span>Customize</button></div><div class="home-bottom"><span class="status-dot"></span><span>${state.failed ? "Scam protection needs attention." : "Protection is on. You’re in control."}</span><button class="text-button" id="home-protection">View →</button></div></section>`;
}
function search() {
  return `<section class="search-page"><div class="eyebrow">Search preview</div><h1>${escape(state.query || "web browser")}</h1><div class="search-status">${state.hideAds || state.senior ? "Sponsored results are hidden in this sample." : "Sponsored results are labeled in this sample."} <button class="text-button" data-view="settings">Change</button></div><div class="search-results">${state.hideAds || state.senior ? "" : `<article class="sponsored search-result"><span class="ad-label">Sponsored · paid advertisement</span><h2>A sponsored browser offer</h2><p>Advertising is labeled without implying that every advertiser is a scam.</p></article>`}<article class="search-result"><span class="domain">wikipedia.org › wiki › Web_browser</span><h2>Web browser — Wikipedia</h2><p>A web browser is an application for accessing websites. Learn how browsers retrieve and display information on the web.</p><button class="text-button" data-view="reader">Open reader preview →</button></article><article class="search-result"><span class="domain">example.org › journal</span><h2>A quieter place for the web</h2><p>On useful software, thoughtful defaults, and leaving room for the things that matter.</p></article></div><p class="muted">This sample demonstrates ad removal. It does not imply that organic results have been checked for scams.</p></section>`;
}
function reader() {
  return `<div class="reader-top"><button class="text-button" data-view="search">← Back to page</button><span>Reader view</span><button class="secondary" id="reader-type">Aa · Text size</button></div><article class="reader"><div class="eyebrow">The everyday web</div><h1>A quieter place<br>for the things that matter.</h1><p class="byline">Sample article · 3 minute read</p><p>The best tools leave us with more attention than they take. They open quickly, make the next step clear, and let us settle into what we came to do.</p><p>A browser is where much of our day happens. We read a story, compare a few ideas, write to someone we care about. The interface should give those moments room.</p><blockquote>Good design makes the ordinary feel effortless.</blockquote><p>That means clear type, familiar controls, and useful choices that stay where we put them. Protection should be understandable. Optional features should wait until they are wanted.</p><button class="text-button" data-view="summary">Summarize this article →</button></article>`;
}
function settings() {
  const nav = ["protection", "appearance", "reading", "ai"];
  let inner = "";
  if (state.section === "protection")
    inner = `<h1>Protection</h1><p class="muted">Useful safeguards. Clear choices.</p>${protectionRows()}<label class="setting-row"><span><strong>Hide sponsored search results</strong><p>Remove supported paid placements on Google and Bing. This does not remove every scam link.</p></span><input class="switch" id="hide-ads" type="checkbox" ${state.hideAds || state.senior ? "checked" : ""} ${state.senior ? "disabled" : ""}></label><label class="setting-row"><span><strong>Senior Safe Mode</strong><p>Hide sponsored results and remove the option to bypass known scam warnings.</p></span><input class="switch" id="senior" type="checkbox" ${state.senior ? "checked" : ""}></label>${state.failed ? '<div class="information warning-note"><strong>Scam protection is unavailable.</strong><br>Check for a browser update. Until protection is restored, use extra care with unfamiliar sites.</div>' : ""}`;
  else if (state.section === "appearance")
    inner = `<h1>Appearance</h1><p class="muted">Make room for the way you browse.</p><label class="setting-row"><span><strong>Color theme</strong><p>A consistent appearance across the browser.</p></span><select id="settings-theme"><option value="light" ${state.theme === "light" ? "selected" : ""}>Light</option><option value="dark" ${state.theme === "dark" ? "selected" : ""}>Dark</option></select></label><label class="setting-row"><span><strong>Interface spacing</strong><p>Change control size without making text harder to read.</p></span><select id="settings-density">${["comfortable", "compact", "large"].map((x) => `<option value="${x}" ${state.density === x ? "selected" : ""}>${x === "large" ? "Larger controls" : x[0].toUpperCase() + x.slice(1)}</option>`).join("")}</select></label><div class="information">Your layout choices should stay in place when the browser updates.</div>`;
  else if (state.section === "reading")
    inner = `<h1>Reading</h1><p class="muted">Comfortable text. Fewer distractions.</p><p>Reader view gives articles a clear layout, with adjustable type and a consistent return to the original page.</p><button class="primary" data-view="reader">Try reader view</button>`;
  else
    inner = `<h1>Page summaries</h1><p class="muted">Optional. Only when you ask.</p><div class="state-row"><div class="state-line"><strong>AI features</strong><span class="state-value">Off by default</span></div><p>Choose a service during setup. The browser should tell you where the text will go before you send it.</p></div><button class="secondary" data-view="summary">Preview the consent screen</button><div class="information">This prototype does not collect keys, connect to a service, or send page content.</div>`;
  return `<section class="settings-layout"><nav class="settings-nav" aria-label="Settings"><strong>Settings</strong>${nav.map((n) => `<button data-section="${n}" ${n === state.section ? 'aria-current="page"' : ""}>${{ protection: "Protection", appearance: "Appearance", reading: "Reading", ai: "Page summaries" }[n]}</button>`).join("")}</nav><div class="settings-main">${inner}</div></section>`;
}
function warning() {
  return `<section class="warning-page"><div class="warning-symbol" aria-hidden="true">!</div><div class="eyebrow">Site blocked</div><h1>This site looks dangerous.</h1><p>The address is on a list of known scam or phishing sites. It may try to steal your passwords, payment details, or money.</p><div class="host">boring-scam-test.invalid</div><div class="actions"><button class="primary" data-view="home">Go back to safety</button></div>${state.senior ? '<p class="panel-note">Senior Safe Mode is on. This site cannot be opened from this warning.</p>' : '<details><summary>Why was this blocked?</summary><p>Its address matched the local blocklist. Lists can make mistakes.</p><button class="text-button" id="bypass-demo">Continue anyway</button></details>'}</section>`;
}
function summary() {
  let body =
    state.summary === "consent"
      ? `<div class="summary-destination"><strong>Destination · Google Gemini</strong><p>The article text will leave your device and be sent to Google. About 4,200 characters would be shared.</p></div><p class="muted">Nothing has been sent. You can cancel and keep reading.</p><div class="actions"><button class="primary" id="send-summary">Send and summarize</button><button class="secondary" data-view="reader">Cancel</button></div>`
      : state.summary === "done"
        ? `<p>Good software protects your attention with clear typography, predictable navigation and optional features that stay out of the way.</p><p class="muted">Sample result · no service was contacted.</p><div class="actions"><button class="secondary" data-view="reader">Back to article</button><button class="text-button" id="summary-error">Preview error state</button></div>`
        : `<div class="information warning-note"><strong>The service couldn’t be reached.</strong><br>Your article is still here. Check the service settings before trying again.</div><div class="actions"><button class="secondary" id="summary-reset">Review before retrying</button><button class="text-button" data-view="reader">Back to article</button></div>`;
  return `<section class="summary-page"><div class="eyebrow">Only when you ask</div><h1>${state.summary === "consent" ? "Summarize this page?" : state.summary === "done" ? "The key ideas." : "Summary unavailable."}</h1><div class="summary-source"><strong>A quieter place for the things that matter</strong><p>example.org / journal</p></div>${body}</section>`;
}
function render() {
  document.documentElement.dataset.theme = state.theme;
  document.documentElement.dataset.density = state.density;
  $("theme").value = state.theme;
  $("density").value = state.density;
  $("content").innerHTML = { home, search, reader, settings, warning, summary }[
    state.view
  ]();
  tabs();
  $("address").value = {
    home: "",
    search: "Search · " + (state.query || "web browser"),
    reader: "example.org / journal",
    settings: "boring / settings",
    warning: "boring-scam-test.invalid",
    summary: "boring / page summary",
  }[state.view];
  $("protection").classList.toggle("failed", state.failed);
  $("protection-label").textContent = state.failed
    ? "Needs attention"
    : "Protection";
  $("footer-status").textContent = state.failed
    ? "Scam protection unavailable · check protection settings"
    : "Known threats are checked on this device";
  $("protection-rows").innerHTML = protectionRows();
  $("simulate-failure").textContent = state.failed
    ? "Restore protection preview"
    : "Protection failure";
  $("back").disabled = !state.history.length;
  $("forward").disabled = !state.forward.length;
  document
    .querySelectorAll(".study-nav [data-view]")
    .forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.view === state.view)),
    );
}
function togglePanel(id, trigger) {
  const opening = $(id).hidden;
  closePanels();
  $(id).hidden = !opening;
  $(trigger).setAttribute("aria-expanded", String(opening));
  if (opening) $(id).querySelector("button").focus();
}
document.addEventListener("click", (e) => {
  const button = e.target.closest("button");
  if (!button) return;
  if (button.dataset.closeTab !== undefined) {
    const closed = Number(button.dataset.closeTab);
    state.tabs = Math.max(1, state.tabs - 1);
    if (closed < state.activeTab) state.activeTab--;
    state.activeTab = Math.min(state.activeTab, state.tabs - 1);
    render();
    document.querySelector('.tab[aria-selected="true"]').focus();
    announce("Tab closed in this preview");
    return;
  }
  if (button.dataset.view) {
    navigate(button.dataset.view);
    return;
  }
  if (button.dataset.section) {
    state.section = button.dataset.section;
    render();
    return;
  }
  if (button.dataset.tab !== undefined) {
    state.activeTab = Number(button.dataset.tab);
    navigate(["home", "reader", "search"][state.activeTab % 3]);
    return;
  }
  if (button.classList.contains("close")) {
    const trigger =
      button.closest("aside").id === "protection-panel"
        ? "protection"
        : "downloads";
    closePanels();
    $(trigger).focus();
    return;
  }
  switch (button.id) {
    case "new-tab":
      state.tabs++;
      state.activeTab = state.tabs - 1;
      navigate("home");
      $("tabs").lastElementChild.scrollIntoView({
        block: "nearest",
        inline: "nearest",
      });
      break;
    case "back":
      if (state.history.length) {
        state.forward.push(state.view);
        navigate(state.history.pop(), false);
      }
      break;
    case "forward":
      if (state.forward.length) {
        state.history.push(state.view);
        navigate(state.forward.pop(), false);
      }
      break;
    case "reload":
      render();
      announce("Preview refreshed");
      break;
    case "menu":
      navigate("settings");
      break;
    case "protection":
    case "home-protection":
      togglePanel("protection-panel", "protection");
      break;
    case "downloads":
      togglePanel("download-panel", "downloads");
      break;
    case "simulate-failure":
      state.failed = !state.failed;
      render();
      togglePanel("protection-panel", "protection");
      break;
    case "bookmark":
      state.bookmarked = !state.bookmarked;
      button.textContent = state.bookmarked ? "★" : "☆";
      button.setAttribute("aria-pressed", String(state.bookmarked));
      announce(
        state.bookmarked
          ? "Bookmarked in this preview"
          : "Bookmark removed from this preview",
      );
      break;
    case "pause":
      const paused = button.textContent === "Pause";
      button.textContent = paused ? "Resume" : "Pause";
      $("download-status").textContent = paused
        ? "6.4 of 12 MB · Paused"
        : "6.4 of 12 MB · Downloading";
      break;
    case "reader-type":
      document.querySelector(".reader").style.fontSize = document.querySelector(
        ".reader",
      ).style.fontSize
        ? ""
        : "22px";
      break;
    case "send-summary":
      state.summary = "done";
      render();
      announce("Sample summary shown. No data was sent.");
      break;
    case "summary-error":
      state.summary = "failed";
      render();
      break;
    case "summary-reset":
      state.summary = "consent";
      render();
      break;
    case "bypass-demo":
      announce("Prototype only. No unsafe site was opened.");
      break;
  }
});
document.addEventListener("change", (e) => {
  switch (e.target.id) {
    case "theme":
    case "settings-theme":
      state.theme = e.target.value;
      break;
    case "density":
    case "settings-density":
      state.density = e.target.value;
      break;
    case "tab-count":
      state.tabs = Number(e.target.value);
      state.activeTab = 0;
      break;
    case "hide-ads":
      state.hideAds = e.target.checked;
      break;
    case "senior":
      state.senior = e.target.checked;
      break;
    default:
      return;
  }
  render();
});
document.addEventListener("submit", (e) => {
  e.preventDefault();
  state.query = e.target.querySelector("input").value || "web browser";
  navigate("search");
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const trigger = !$("protection-panel").hidden
      ? "protection"
      : !$("download-panel").hidden
        ? "downloads"
        : null;
    closePanels();
    if (trigger) $(trigger).focus();
  }
  if (
    e.target.matches(".tab") &&
    ["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)
  ) {
    e.preventDefault();
    state.activeTab =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? state.tabs - 1
          : (state.activeTab + (e.key === "ArrowRight" ? 1 : -1) + state.tabs) %
            state.tabs;
    navigate(["home", "reader", "search"][state.activeTab % 3]);
    document.querySelector('.tab[aria-selected="true"]').focus();
  }
  if (e.key === "Tab") {
    const panel = [...document.querySelectorAll(".popover")].find(
      (p) => !p.hidden,
    );
    if (panel) {
      const items = [
        ...panel.querySelectorAll("button:not(:disabled),a,input,select"),
      ];
      if (e.shiftKey && document.activeElement === items[0]) {
        e.preventDefault();
        items.at(-1).focus();
      } else if (!e.shiftKey && document.activeElement === items.at(-1)) {
        e.preventDefault();
        items[0].focus();
      }
    }
  }
});
render();
