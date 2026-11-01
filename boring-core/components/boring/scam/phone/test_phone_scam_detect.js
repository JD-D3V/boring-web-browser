// Copyright 2026 boring. BSD style license.

// Tests for phone_scam_detect.js without a browser: phone number formats,
// and a hand-written set of tech support scam pop-ups and ordinary pages
// (phone_scam_samples.json) run through the detector as it ships. Each
// sample says how the page is laid out, because the real page reading
// (scanDocument) needs a browser; smoke_phone_banner.py runs that part in
// the built browser. The false positive rate is printed.
//
// Usage: node --test test_phone_scam_detect.js

'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'phone_scam_detect.js'), 'utf8');
const samples = JSON.parse(
    fs.readFileSync(path.join(__dirname, 'phone_scam_samples.json'), 'utf8'));

// Runs the file the way the browser does: a fresh context with nothing in
// it, and the script's last value is the detector.
const detect = vm.runInNewContext(source, {});

function layoutOf(code) {
  return {
    overlay: code.includes('o'),
    fullscreen: code.includes('f'),
    bare: code.includes('b'),
    alertColor: code.includes('a'),
  };
}

function snapshot(sample) {
  return {text: sample.text, telLinks: 0, layout: layoutOf(sample.layout)};
}

// The wording alone, as if every page were laid out like a warning. Shows
// what the layout check is worth.
function wordingOnly(sample) {
  return detect.analyse(
      {text: sample.text, telLinks: 0, layout: {overlay: true}});
}

test('phone numbers as people write them are found', () => {
  for (const text of samples.phones.yes) {
    assert.ok(detect.findPhones('call ' + text + ' now').length > 0, text);
  }
});

test('dates, prices, versions and codes are not phone numbers', () => {
  for (const text of samples.phones.no) {
    assert.equal(detect.findPhones(text).length, 0, text);
  }
});

test('a page with no number is never scary', () => {
  const result = detect.analyse({
    text: 'Your computer is infected with a virus. Do not close this window. ' +
        'Call Microsoft Support immediately.',
    telLinks: 0,
    layout: {overlay: true, fullscreen: true, bare: true, alertColor: true},
  });
  assert.equal(result.scary, false);
});

test('a tel: link counts as a number', () => {
  const result = detect.analyse({
    text: 'Your computer is infected with a virus. Do not close this window. ' +
        'Call Microsoft Support immediately.',
    telLinks: 1,
    layout: {overlay: true},
  });
  assert.equal(result.scary, true);
});

test('scare wording and a number on an ordinary page stay quiet', () => {
  const text = 'Your computer is infected with a virus. Do not close this ' +
      'window. Call Microsoft Support immediately on 1-844-555-0142.';
  assert.equal(detect.analyse({text, layout: {}}).scary, false);
  assert.equal(detect.analyse({text, layout: {overlay: true}}).scary, true);
  assert.equal(detect.analyse({text, layout: {fullscreen: true}}).scary, true);
});

test('a tab that already looked like a scam needs much less', () => {
  const text = 'Your PC has a problem. Please call Windows Support on ' +
      '1-800-555-0117 to fix it.';
  assert.equal(detect.analyse({text, layout: {}}).scary, false);
  assert.equal(detect.analyse({text, layout: {}}, true).scary, true);
  // Still needs a number and an invitation to call.
  assert.equal(
      detect.analyse({text: 'Your PC has a problem.', layout: {}}, true).scary,
      false);
  assert.equal(
      detect.analyse(
          {text: 'Opening hours 9 to 5. Phone 1-800-555-0117.', layout: {}},
          true).scary,
      false);
});

test('the detector is frozen and leaves no globals', () => {
  assert.ok(Object.isFrozen(detect));
  const context = vm.createContext({});
  vm.runInContext(source, context);
  assert.deepEqual(Object.keys(context), []);
});

test('rates on the written samples', () => {
  const caught = samples.scam.filter((s) => detect.analyse(snapshot(s)).scary);
  const missed = samples.scam.filter((s) => !detect.analyse(snapshot(s)).scary);
  const falsePositives =
      samples.normal.filter((s) => detect.analyse(snapshot(s)).scary);
  const wordingFalsePositives = samples.normal.filter((s) => wordingOnly(s).scary);
  const wordingCaught = samples.scam.filter((s) => wordingOnly(s).scary);

  const percent = (n, of) => (100 * n / of).toFixed(1) + '%';
  console.log(
      'scam pages caught: %d of %d (%s); missed: %s',
      caught.length, samples.scam.length,
      percent(caught.length, samples.scam.length),
      missed.map((s) => s.name).join(', ') || 'none');
  console.log(
      'normal pages flagged: %d of %d (%s)%s',
      falsePositives.length, samples.normal.length,
      percent(falsePositives.length, samples.normal.length),
      falsePositives.length ?
          ': ' + falsePositives.map((s) => s.name).join(', ') : '');
  console.log(
      'wording alone (layout ignored): scam caught %d of %d, normal flagged ' +
          '%d of %d (%s): %s',
      wordingCaught.length, samples.scam.length, wordingFalsePositives.length,
      samples.normal.length,
      percent(wordingFalsePositives.length, samples.normal.length),
      wordingFalsePositives.map((s) => s.name).join(', ') || 'none');

  assert.equal(falsePositives.length, 0,
               falsePositives.map((s) => s.name).join(', '));
  // Known misses, let go on purpose as the price of staying quiet: pages
  // laid out like any ordinary page, a pop-up with only one kind of
  // wording, and invoice or network wording with no brand and no call to
  // action. Any other miss is a regression.
  const quietOnPurpose = new Set([
    'cloned page with menu', 'cloned page plain', 'quiet pop-up',
    'geek squad invoice', 'isp hijack',
  ]);
  const unexpected = missed.filter((s) => !quietOnPurpose.has(s.name));
  assert.deepEqual(unexpected.map((s) => s.name), []);
});
