// Copyright 2026 boring. BSD style license.

// Answers cookie banners with "reject", in the cosmetic filter isolated
// world, so the page can neither see nor break it. CosmeticFilterAgent
// starts it in the main frame, before any page script, when the profile
// blocks cookie banners and blocking is on for the site (config.cookies).
//
// The Easylist Cookie List only hides a banner, and a hidden banner is
// still unanswered: the platform behind it treats the visitor as
// undecided and a site may go on tracking. Here the banner is answered
// instead, with the same button a person would press. Hiding stays as the
// fallback for every banner these rules do not know.
//
// A hidden banner can still be clicked, so nothing here asks whether a
// banner is visible (the cookie list hides them with display:none). A
// platform is only touched when its own banner is on the page, only
// through that platform's own buttons, and not when its consent cookie
// says the visitor has answered already.
//
// Rules are data, one per platform. Our own, for the six platforms
// that put most of the banners on the web: OneTrust, Cookiebot,
// TrustArc, Quantcast Choice, Didomi and Usercentrics. The selectors are
// the public element ids and classes each platform's banner ships with.
// DuckDuckGo's autoconsent (MPL-2.0, github.com/duckduckgo/autoconsent)
// was read to check them, and nothing is copied from it. Its rule files,
// and Consent-O-Matic's (MIT), could be shipped with credit, but both
// need an engine many times this size and a pass over hundreds of
// platforms on every page, for banners the cookie list already hides.
//
// Rule shape:
//   name      for people reading this file
//   detect    selectors; any one on the page means the banner is there
//   answered  matched against document.cookie; a match means the
//             visitor has already answered, so leave it alone
//   flows     ways to say no, tried in order. A flow runs when its first
//             button is on the page, and ends when its last step is done
// Flow steps, run one after another:
//   'selector'          click it, waiting for it to appear
//   ['host', 'inner']   the same through a shadow root: each selector
//                       but the last has to be an element with an open
//                       shadow root that the next one is looked up in
//   {any: [a, b]}       click the first of these that is on the page
//   {all: a}            click every match, now (switches that are on)
//   {wait: ms}          let the banner settle after a click
// A step that finds nothing within STEP_WAIT_MS ends its flow.

const COOKIE_REJECT_RULES = [
  {
    name: 'OneTrust',
    detect: ['#onetrust-banner-sdk', '#onetrust-pc-sdk'],
    answered: /(?:^|;\s*)OptanonAlertBoxClosed=/,
    flows: [
      ['#onetrust-reject-all-handler'],
      ['.ot-pc-refuse-all-handler'],
      // No reject button on the banner: open the settings, switch every
      // category off, and save. A "Reject all" there does all of it.
      [
        '#onetrust-pc-btn-handler',
        {wait: 800},
        {all: '#onetrust-consent-sdk input.category-switch-handler:checked'},
        {any: ['.ot-pc-refuse-all-handler', '.save-preference-btn-handler']},
      ],
    ],
  },
  {
    name: 'Cookiebot',
    detect: ['#CybotCookiebotDialog'],
    answered: /(?:^|;\s*)CookieConsent=/,
    flows: [
      [{any: [
        '#CybotCookiebotDialogBodyButtonDecline',
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll',
      ]}],
      // "Allow selection" saves whatever is switched on, so switch
      // everything off first. The necessary category cannot be.
      [
        {all: '#CybotCookiebotDialog .CybotCookiebotDialogBodyLevelButton:checked:enabled'},
        '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowallSelection',
      ],
    ],
  },
  {
    name: 'TrustArc',
    detect: ['#truste-consent-track', '#truste-show-consent'],
    answered: /(?:^|;\s*)(?:notice_preferences|cmapi_cookie_privacy)=/,
    flows: [
      ['#truste-consent-required'],
    ],
  },
  {
    name: 'Quantcast Choice',
    detect: ['#qc-cmp2-container'],
    answered: /(?:^|;\s*)euconsent-v2=/,
    flows: [
      ['#disagree-btn:not([disabled])'],
      // Without a "Reject" id, the second secondary button rejects.
      ['.qc-cmp2-summary-buttons button[mode="secondary"]:nth-of-type(2)'],
      // The default layout, "More options" and "Agree" only: open the
      // second screen, switch every purpose off and save.
      [
        '.qc-cmp2-summary-buttons button[mode="secondary"]:nth-of-type(1)',
        {wait: 800},
        {all: '.qc-cmp2-toggle-switch > button[aria-checked="true"]'},
        '.qc-cmp2-buttons-desktop > button[mode=primary]',
      ],
    ],
  },
  {
    name: 'Didomi',
    detect: ['#didomi-host', '#didomi-notice'],
    answered: /(?:^|;\s*)didomi_token=/,
    flows: [
      [{any: [
        '#didomi-notice-disagree-button',
        '.didomi-continue-without-agreeing',
      ]}],
    ],
  },
  {
    name: 'Usercentrics',
    detect: ['#usercentrics-root', '#usercentrics-cmp-ui', '#usercentrics-button'],
    flows: [
      [['#usercentrics-root', '[data-testid=uc-deny-all-button]']],
      [['#usercentrics-cmp-ui', '[data-action-type=deny]']],
      ['#usercentrics-button #uc-btn-deny-banner'],
    ],
  },
];

function startCookieReject(doc, win) {
  'use strict';

  // How long the page is watched for a banner. They are added by script,
  // most within a second or two of load.
  const WATCH_MS = 20000;
  const POLL_MS = 250;
  // How long one step waits for its button, banners draw in two stages.
  const STEP_WAIT_MS = 3000;
  const STEP_POLL_MS = 100;
  // A flow that ran and failed (a button vanished mid-way) is tried
  // once more, then left alone.
  const MAX_TRIES = 2;

  const deadline = Date.now() + WATCH_MS;
  const tries = new Map();
  let running = false;
  let stopped = false;

  function sleep(ms) {
    return new Promise((resolve) => win.setTimeout(resolve, ms));
  }

  // One selector, or a chain through open shadow roots.
  function findAll(selector) {
    if (typeof selector === 'string') {
      return Array.from(doc.querySelectorAll(selector));
    }
    let roots = [doc];
    for (let i = 0; i < selector.length; i++) {
      const found = [];
      for (const root of roots) {
        found.push(...root.querySelectorAll(selector[i]));
      }
      if (i === selector.length - 1) {
        return found;
      }
      roots = found.map((el) => el.shadowRoot).filter(Boolean);
    }
    return [];
  }

  // A button that is on the page and not switched off. The banner may be
  // hidden, which is fine: a click reaches it all the same.
  function ready(selector) {
    return findAll(selector).find(
        (el) => !el.disabled && el.getAttribute('aria-disabled') !== 'true');
  }

  function firstReady(alternatives) {
    for (const selector of alternatives) {
      const el = ready(selector);
      if (el) {
        return el;
      }
    }
    return null;
  }

  function normalize(step) {
    if (typeof step === 'string' || Array.isArray(step)) {
      return {any: [step]};
    }
    return step;
  }

  // The first step that clicks a single button: a flow runs when that
  // one is on the page.
  function leadAlternatives(flow) {
    const step = flow.map(normalize).find((s) => s.any);
    return step ? step.any : [];
  }

  async function runFlow(flow) {
    for (const raw of flow) {
      const step = normalize(raw);
      if (step.wait) {
        await sleep(step.wait);
      } else if (step.all) {
        for (const el of findAll(step.all)) {
          el.click();
        }
      } else {
        let el = firstReady(step.any);
        for (let waited = 0; !el && waited < STEP_WAIT_MS;
             waited += STEP_POLL_MS) {
          await sleep(STEP_POLL_MS);
          el = firstReady(step.any);
        }
        if (!el) {
          return false;
        }
        el.click();
      }
    }
    return true;
  }

  function answeredAlready(rule) {
    try {
      return !!rule.answered && rule.answered.test(doc.cookie);
    } catch (e) {
      // Cookies are blocked for this document: assume nothing.
      return false;
    }
  }

  async function attempt(rule, flow) {
    tries.set(rule, (tries.get(rule) || 0) + 1);
    running = true;
    let ok = false;
    try {
      ok = await runFlow(flow);
    } catch (e) {
      ok = false;
    }
    running = false;
    if (ok) {
      // One banner per page: it is answered, stop looking.
      stopped = true;
    }
  }

  // The first platform whose banner is on the page with a way to say no
  // in reach, and that way. A banner with no button yet is waited for.
  function nextAttempt() {
    for (const rule of COOKIE_REJECT_RULES) {
      if ((tries.get(rule) || 0) >= MAX_TRIES ||
          !rule.detect.some((selector) => !!doc.querySelector(selector)) ||
          answeredAlready(rule)) {
        continue;
      }
      const flow = rule.flows.find((f) => firstReady(leadAlternatives(f)));
      if (flow) {
        return {rule, flow};
      }
    }
    return null;
  }

  function check() {
    if (stopped || Date.now() > deadline) {
      return;
    }
    if (!running) {
      const next = nextAttempt();
      if (next) {
        attempt(next.rule, next.flow);
      }
    }
    win.setTimeout(check, POLL_MS);
  }

  check();
}
