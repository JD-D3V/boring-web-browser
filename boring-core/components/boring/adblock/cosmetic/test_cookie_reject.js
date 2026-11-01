// Copyright 2026 boring. BSD style license.

// Tests for cookie_reject.js without a browser: a stand-in page where an
// element answers to the exact selector strings it is given, and a clock
// the test moves by hand. What this checks is the flows: which button is
// pressed, in what order, how long it is waited for and when it stops.
// That the selectors match real platform markup is checked in a browser,
// by smoke_cookies.py.
//
// Usage: node --test test_cookie_reject.js

'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');

// ---------------------------------------------------------------------------
// The stand-in page and clock.

class Root {
  constructor() {
    this.elements = [];
    this.cookie = '';
  }

  add(element) {
    element.root = this;
    this.elements.push(element);
    return element;
  }

  querySelectorAll(selector) {
    return this.elements.filter((e) => e.selectors.includes(selector));
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}

class Element {
  // `selectors`: every selector string this element answers to.
  constructor(selectors, {disabled = false, onClick = null} = {}) {
    this.selectors = selectors;
    this.disabled = disabled;
    this.onClick = onClick;
    this.clicks = 0;
    this.shadowRoot = null;
  }

  getAttribute() {
    return null;
  }

  click() {
    this.clicks++;
    if (this.onClick) {
      this.onClick(this);
    }
  }
}

function setUp() {
  const clock = {now: 1000, timers: []};
  const doc = new Root();
  const win = {
    setTimeout(fn, ms) {
      clock.timers.push({at: clock.now + ms, fn});
    },
  };
  const fakeDate = {now: () => clock.now};
  const source = fs.readFileSync(path.join(__dirname, 'cookie_reject.js'), 'utf8');
  const loaded = new Function(
      'Date', source + '\nreturn {startCookieReject, COOKIE_REJECT_RULES};')(
      fakeDate);

  // Moves the clock on in small steps, running what is due and letting
  // the flows' promises catch up after each step.
  async function advance(ms) {
    const end = clock.now + ms;
    while (clock.now < end) {
      clock.now = Math.min(clock.now + 25, end);
      const due = clock.timers.filter((t) => t.at <= clock.now);
      clock.timers = clock.timers.filter((t) => t.at > clock.now);
      for (const t of due) {
        t.fn();
      }
      for (let i = 0; i < 5; i++) {
        await new Promise((resolve) => setImmediate(resolve));
      }
    }
  }

  return {
    doc, clock, advance, rules: loaded.COOKIE_REJECT_RULES,
    start: () => loaded.startCookieReject(doc, win),
  };
}

// An element answering to one selector, added to the page.
function button(page, selector, options) {
  return page.doc.add(new Element([selector], options));
}

// ---------------------------------------------------------------------------

test('every rule is complete and names a platform we claim to cover', () => {
  const {rules} = setUp();
  const names = rules.map((r) => r.name);
  for (const want of ['OneTrust', 'Cookiebot', 'TrustArc', 'Quantcast Choice',
                      'Didomi', 'Usercentrics']) {
    assert.ok(names.includes(want), want);
  }
  const selectors = [];
  for (const rule of rules) {
    assert.ok(rule.detect.length > 0, rule.name);
    assert.ok(rule.flows.length > 0, rule.name);
    selectors.push(...rule.detect);
    for (const flow of rule.flows) {
      assert.ok(flow.length > 0, rule.name);
      for (const step of flow) {
        if (typeof step === 'string' || Array.isArray(step)) {
          selectors.push(...[].concat(step));
        } else if (step.any) {
          selectors.push(...step.any.flat());
        } else if (step.all) {
          selectors.push(step.all);
        } else {
          assert.ok(step.wait > 0, rule.name);
        }
      }
    }
  }
  for (const selector of selectors) {
    assert.equal(typeof selector, 'string');
    assert.ok(selector.trim().length > 0);
    // Brackets and quotes balance: what a typo in a long selector breaks.
    assert.equal(selector.split('[').length, selector.split(']').length, selector);
    assert.equal(selector.split('(').length, selector.split(')').length, selector);
    assert.equal(selector.split('"').length % 2, 1, selector);
  }
});

test('a page with no banner is left alone and watching stops', async () => {
  const page = setUp();
  button(page, '.something-else');
  page.start();
  await page.advance(30000);
  assert.equal(page.doc.elements[0].clicks, 0);
  assert.equal(page.clock.timers.length, 0);
});

test('a reject button on the banner is pressed once', async () => {
  const page = setUp();
  button(page, '#onetrust-banner-sdk');
  const reject = button(page, '#onetrust-reject-all-handler');
  const accept = button(page, '#onetrust-accept-btn-handler');
  page.start();
  await page.advance(5000);
  assert.equal(reject.clicks, 1);
  assert.equal(accept.clicks, 0);
  assert.equal(page.clock.timers.length, 0);
});

test('a banner drawn late is answered when it shows up', async () => {
  const page = setUp();
  page.start();
  await page.advance(4000);
  const banner = button(page, '#CybotCookiebotDialog');
  const decline = button(page, '#CybotCookiebotDialogBodyButtonDecline');
  await page.advance(1000);
  assert.ok(banner);
  assert.equal(decline.clicks, 1);
});

test('a banner drawn after the watch is over is not', async () => {
  const page = setUp();
  page.start();
  await page.advance(21000);
  button(page, '#CybotCookiebotDialog');
  const decline = button(page, '#CybotCookiebotDialogBodyButtonDecline');
  await page.advance(5000);
  assert.equal(decline.clicks, 0);
});

test('the first button in an any-list wins', async () => {
  const page = setUp();
  button(page, '#didomi-host');
  const later = button(page, '.didomi-continue-without-agreeing');
  const first = button(page, '#didomi-notice-disagree-button');
  page.start();
  await page.advance(2000);
  assert.equal(first.clicks, 1);
  assert.equal(later.clicks, 0);
});

test('a visitor who has answered already is not asked again', async () => {
  const page = setUp();
  page.doc.cookie = 'a=1; OptanonAlertBoxClosed=2026-10-28T10:00:00; b=2';
  button(page, '#onetrust-banner-sdk');
  const reject = button(page, '#onetrust-reject-all-handler');
  page.start();
  await page.advance(5000);
  assert.equal(reject.clicks, 0);
});

test('a switched off button is waited for, not pressed', async () => {
  const page = setUp();
  button(page, '#qc-cmp2-container');
  const reject = button(page, '#disagree-btn:not([disabled])', {disabled: true});
  page.start();
  await page.advance(3000);
  assert.equal(reject.clicks, 0);
  reject.disabled = false;
  await page.advance(1000);
  assert.equal(reject.clicks, 1);
});

test('with no reject button, the settings are opened, switched off and saved',
     async () => {
  const page = setUp();
  button(page, '#onetrust-banner-sdk');
  const toggles = [];
  const save = {};
  button(page, '#onetrust-pc-btn-handler', {
    onClick: () => {
      for (let i = 0; i < 2; i++) {
        const toggle = new Element(
            ['#onetrust-consent-sdk input.category-switch-handler:checked']);
        toggles.push(page.doc.add(toggle));
      }
      save.button = button(page, '.save-preference-btn-handler');
    },
  });
  page.start();
  await page.advance(5000);
  assert.deepEqual(toggles.map((t) => t.clicks), [1, 1]);
  assert.equal(save.button.clicks, 1);
});

test('an open preference centre is rejected with its Reject all', async () => {
  const page = setUp();
  button(page, '#onetrust-pc-sdk');
  const reject = button(page, '.ot-pc-refuse-all-handler');
  const save = button(page, '.save-preference-btn-handler');
  page.start();
  await page.advance(2000);
  assert.equal(reject.clicks, 1);
  assert.equal(save.clicks, 0);
});

test('Cookiebot with only "Allow selection" switches the rest off first',
     async () => {
  const page = setUp();
  button(page, '#CybotCookiebotDialog');
  const on = button(page,
      '#CybotCookiebotDialog .CybotCookiebotDialogBodyLevelButton:checked:enabled');
  const order = [];
  on.onClick = () => order.push('switch');
  const allow = button(page,
      '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowallSelection',
      {onClick: () => order.push('save')});
  page.start();
  await page.advance(2000);
  assert.deepEqual(order, ['switch', 'save']);
  assert.equal(allow.clicks, 1);
});

test('a button inside an open shadow root is reached', async () => {
  const page = setUp();
  const host = button(page, '#usercentrics-root');
  host.shadowRoot = new Root();
  const deny = host.shadowRoot.add(
      new Element(['[data-testid=uc-deny-all-button]']));
  page.start();
  await page.advance(2000);
  assert.equal(deny.clicks, 1);
});

test('a closed shadow root is left alone', async () => {
  const page = setUp();
  button(page, '#usercentrics-root');
  const accept = button(page, '[data-testid=uc-accept-all-button]');
  page.start();
  await page.advance(30000);
  assert.equal(accept.clicks, 0);
});

test('a flow that cannot finish is tried twice and then given up', async () => {
  const page = setUp();
  button(page, '#onetrust-banner-sdk');
  // The settings button is there but nothing ever follows it.
  const settings = button(page, '#onetrust-pc-btn-handler');
  page.start();
  await page.advance(30000);
  assert.equal(settings.clicks, 2);
  assert.equal(page.clock.timers.length, 0);
});

test('only the platform whose banner is there is touched', async () => {
  const page = setUp();
  button(page, '#didomi-host');
  const didomi = button(page, '#didomi-notice-disagree-button');
  // Another platform's button on the page, without its banner.
  const stray = button(page, '#onetrust-reject-all-handler');
  page.start();
  await page.advance(2000);
  assert.equal(didomi.clicks, 1);
  assert.equal(stray.clicks, 0);
});
