// Copyright 2026 boring. BSD style license.

// Tests for procedural_filters.js and cosmetic_filters.js, without a
// browser: a small DOM stand-in covers what the two files use.
//
// Usage: node test_procedural_filters.js

'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function load() {
  const read = (name) => fs.readFileSync(path.join(__dirname, name), 'utf8');
  return new Function(
      read('procedural_filters.js') + '\n' + read('cosmetic_filters.js') +
      '\nreturn {proceduralFilters, startCosmeticFilters};')();
}
const {proceduralFilters, startCosmeticFilters} = load();

// ---------------------------------------------------------------------------
// DOM stand-in. Selectors: compounds of tag, #id, .class, [attr],
// [attr=v], [attr^=v], [attr*=v], joined by ' ' or '>'. Anything else
// throws, as a browser does for a selector it cannot parse.

let pendingRecords = [];
const observers = [];

function queueRecord(record) {
  if (observers.length) {
    pendingRecords.push(record);
  }
}

function parseCompound(text) {
  const parts = [];
  const re = /^(?:([a-zA-Z*][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:([\^*]?=)"?([^"\]]*)"?)?\])/;
  let rest = text;
  while (rest) {
    const m = re.exec(rest);
    if (!m) {
      throw new SyntaxError('unsupported selector: ' + text);
    }
    parts.push(m);
    rest = rest.slice(m[0].length);
  }
  if (!parts.length) {
    throw new SyntaxError('empty selector');
  }
  return (el) => parts.every((m) => {
    if (m[1]) {
      return m[1] === '*' || el.tagName === m[1].toUpperCase();
    }
    if (m[2]) {
      return el.id === m[2];
    }
    if (m[3]) {
      return el.classList.contains(m[3]);
    }
    const value = el.getAttribute(m[4]);
    if (value === null) {
      return false;
    }
    if (!m[5]) {
      return true;
    }
    if (m[5] === '=') {
      return value === m[6];
    }
    if (m[5] === '^=') {
      return value.startsWith(m[6]);
    }
    return value.includes(m[6]);
  });
}

// "a b > c" as [[' ', a], [' ', b], ['>', c]], matched right to left.
function parseSelector(text) {
  if (text.includes(',')) {
    const each = text.split(',').map(parseSelector);
    return (el, scope) => each.some((test) => test(el, scope));
  }
  const tokens = text.trim().split(/\s*(>)\s*|\s+/).filter((t) => t);
  const chain = [];
  let combinator = ' ';
  for (const token of tokens) {
    if (token === '>') {
      combinator = '>';
      continue;
    }
    chain.push([combinator, parseCompound(token)]);
    combinator = ' ';
  }
  if (!chain.length) {
    throw new SyntaxError('empty selector');
  }
  return (el, scope) => {
    const match = (node, i) => {
      if (!chain[i][1](node)) {
        return false;
      }
      if (i === 0) {
        return !scope || isDescendant(node, scope);
      }
      if (chain[i][0] === '>') {
        const parent = node.parentElement;
        return !!parent && match(parent, i - 1);
      }
      for (let up = node.parentElement; up; up = up.parentElement) {
        if (match(up, i - 1)) {
          return true;
        }
      }
      return false;
    };
    return match(el, chain.length - 1);
  };
}

function isDescendant(node, ancestor) {
  for (let up = node.parentNode; up; up = up.parentNode) {
    if (up === ancestor) {
      return true;
    }
  }
  return false;
}

class ClassList {
  constructor(el) {
    this.el = el;
  }
  get names() {
    return (this.el.getAttribute('class') || '').split(/\s+/).filter((c) => c);
  }
  contains(name) {
    return this.names.includes(name);
  }
  remove(name) {
    this.el.setAttribute('class', this.names.filter((c) => c !== name).join(' '));
  }
  [Symbol.iterator]() {
    return this.names[Symbol.iterator]();
  }
}

class Node {
  constructor(nodeType) {
    this.nodeType = nodeType;
    this.parentNode = null;
    this.childNodes = [];
  }
  get parentElement() {
    return this.parentNode && this.parentNode.nodeType === 1 ?
        this.parentNode : null;
  }
  get children() {
    return this.childNodes.filter((n) => n.nodeType === 1);
  }
  get textContent() {
    return this.childNodes.map((n) => n.textContent).join('');
  }
  get isConnected() {
    let top = this;
    while (top.parentNode) {
      top = top.parentNode;
    }
    return top.nodeType === 9;
  }
  *descendants() {
    for (const child of this.children) {
      yield child;
      yield* child.descendants();
    }
  }
  querySelectorAll(selector) {
    const test = parseSelector(selector);
    const scope = this.nodeType === 1 ? this : null;
    return [...this.descendants()].filter((el) => test(el, scope));
  }
  appendChild(child) {
    child.parentNode = this;
    this.childNodes.push(child);
    queueRecord({type: 'childList', target: this, addedNodes: [child]});
    return child;
  }
}

class Text extends Node {
  constructor(text) {
    super(3);
    this.text = text;
  }
  get textContent() {
    return this.text;
  }
}

class Element extends Node {
  constructor(tag, attrs = {}) {
    super(1);
    this.tagName = tag.toUpperCase();
    this.attrMap = new Map(Object.entries(attrs));
    this.classList = new ClassList(this);
    this.style = {};
  }
  get id() {
    return this.getAttribute('id') || '';
  }
  get attributes() {
    return [...this.attrMap].map(([name, value]) => ({name, value}));
  }
  getAttribute(name) {
    return this.attrMap.has(name) ? this.attrMap.get(name) : null;
  }
  hasAttribute(name) {
    return this.attrMap.has(name);
  }
  setAttribute(name, value) {
    this.attrMap.set(name, String(value));
    queueRecord({type: 'attributes', target: this, attributeName: name});
  }
  removeAttribute(name) {
    if (this.attrMap.delete(name)) {
      queueRecord({type: 'attributes', target: this, attributeName: name});
    }
  }
  matches(selector) {
    return parseSelector(selector)(this, null);
  }
  closest(selector) {
    for (let el = this; el; el = el.parentElement) {
      if (el.matches(selector)) {
        return el;
      }
    }
    return null;
  }
  get nextElementSibling() {
    if (!this.parentNode) {
      return null;
    }
    const siblings = this.parentNode.children;
    return siblings[siblings.indexOf(this) + 1] || null;
  }
  remove() {
    if (this.parentNode) {
      const list = this.parentNode.childNodes;
      list.splice(list.indexOf(this), 1);
      this.parentNode = null;
    }
  }
}

class Document extends Node {
  constructor() {
    super(9);
  }
  get documentElement() {
    return this.children[0] || null;
  }
  // XPath: "..", "//tag" and ".//tag", enough to test the plumbing.
  evaluate(expr, context) {
    let found;
    if (expr === '..') {
      found = context.parentNode ? [context.parentNode] : [];
    } else if (/^\.?\/\/\w+$/.test(expr)) {
      const tag = expr.replace(/^\.?\/\//, '').toUpperCase();
      const root = expr.startsWith('.') ? context : this;
      found = [...root.descendants()].filter((el) => el.tagName === tag);
    } else {
      throw new Error('unsupported xpath ' + expr);
    }
    return {snapshotLength: found.length, snapshotItem: (i) => found[i]};
  }
}

// Builds a tree from ['tag', {attrs}, ...children], children being
// nested arrays or strings.
function h(tag, attrs, ...children) {
  const el = new Element(tag, attrs || {});
  for (const child of children) {
    if (typeof child === 'string') {
      el.appendChild(new Text(child));
    } else {
      el.appendChild(child);
    }
  }
  return el;
}

function makeWindow(doc, {pathname = '/', search = '', styles} = {}) {
  const timers = [];
  return {
    location: {pathname, search},
    getComputedStyle(el, pseudo) {
      const all = (styles && styles.get(el)) || {};
      const own = all[pseudo || ''] || {};
      return {getPropertyValue: (name) => own[name] || ''};
    },
    setTimeout(fn) {
      timers.push(fn);
      return timers.length;
    },
    runTimers() {
      while (timers.length) {
        timers.shift()();
      }
    },
    MutationObserver: class {
      constructor(callback) {
        this.callback = callback;
      }
      observe() {
        observers.push(this);
      }
    },
  };
}

// Delivers queued mutation records, as the browser does between tasks.
function deliverMutations() {
  const records = pendingRecords;
  pendingRecords = [];
  if (records.length) {
    for (const observer of observers) {
      observer.callback(records);
    }
  }
}

function page(body) {
  const doc = new Document();
  doc.appendChild(h('html', null, body));
  return doc;
}

function run(filter, doc, win) {
  const compiled = proceduralFilters.compile(filter);
  assert.ok(compiled, 'filter should compile: ' + JSON.stringify(filter));
  return compiled.run(doc, win || makeWindow(doc));
}

const css = (arg) => ({type: 'css-selector', arg});
const op = (type, arg) => ({type, arg});

// ---------------------------------------------------------------------------

const tests = [];
function test(name, fn) {
  tests.push({name, fn});
}

test('splitSteps', () => {
  const split = proceduralFilters.splitSteps;
  assert.deepEqual(split(' > span'), [{combinator: '>', compound: 'span'}]);
  assert.deepEqual(split(' span'), [{combinator: ' ', compound: 'span'}]);
  assert.deepEqual(split('.box'), [{combinator: '', compound: '.box'}]);
  assert.deepEqual(split(' + a ~ b'), [
    {combinator: '+', compound: 'a'},
    {combinator: '~', compound: 'b'},
  ]);
  assert.deepEqual(split(' div[title="a > b"] > p'), [
    {combinator: ' ', compound: 'div[title="a > b"]'},
    {combinator: '>', compound: 'p'},
  ]);
  assert.deepEqual(split(':not(.a .b) p'), [
    {combinator: '', compound: ':not(.a .b)'},
    {combinator: ' ', compound: 'p'},
  ]);
  assert.equal(split('div[x'), null);
  assert.equal(split('a >'), null);
  assert.equal(split('a > + b'), null);
  assert.equal(split('"open'), null);
});

test('has-text, literal and regex', () => {
  const ad = h('div', {class: 'card'}, 'Sponsored post');
  const real = h('div', {class: 'card'}, 'Real post');
  const doc = page(h('body', null, ad, real));
  assert.deepEqual(run({selector: [css('div.card'), op('has-text', 'Sponsored')]}, doc), [ad]);
  assert.deepEqual(run({selector: [css('div'), op('has-text', '/^sponsored/i')]}, doc), [ad]);
  assert.deepEqual(run({selector: [css('div'), op('has-text', '/post$/')]}, doc), [ad, real]);
});

test('upward by count and by selector', () => {
  const label = h('span', null, 'Ad');
  const inner = h('div', {class: 'inner'}, label);
  const outer = h('section', {class: 'slot'}, inner);
  const doc = page(h('body', null, outer));
  assert.deepEqual(run({selector: [css('span'), op('has-text', 'Ad'), op('upward', '2')]}, doc), [outer]);
  assert.deepEqual(run({selector: [css('span'), op('upward', 'section.slot')]}, doc), [outer]);
  assert.deepEqual(run({selector: [css('span'), op('upward', '99')]}, doc), []);
  assert.equal(proceduralFilters.compile({selector: [css('a'), op('upward', '0')]}), null);
  assert.equal(proceduralFilters.compile({selector: [css('a'), op('upward', '300')]}), null);
});

test('css after a procedural operator', () => {
  const first = h('p', {class: 'x'}, 'one');
  const second = h('p', null, 'two');
  const third = h('p', {class: 'x'}, 'three');
  const box = h('div', {class: 'box'}, h('span', null, 'Promoted'), first, second, third);
  const doc = page(h('body', null, box));
  const promoted = [css('span'), op('has-text', 'Promoted')];
  assert.deepEqual(run({selector: [...promoted, css(' + p')]}, doc), [first]);
  assert.deepEqual(run({selector: [...promoted, css(' ~ p.x')]}, doc), [first, third]);
  assert.deepEqual(run({selector: [...promoted, op('upward', '1'), css(' > p')]}, doc), [first, second, third]);
  assert.deepEqual(run({selector: [...promoted, op('upward', '1'), css(' p.x')]}, doc), [first, third]);
  assert.deepEqual(run({selector: [...promoted, op('upward', '1'), css('.box')]}, doc), [box]);
  assert.deepEqual(run({selector: [...promoted, op('upward', '1'), css('.nope')]}, doc), []);
});

test('matches-attr', () => {
  const a = h('div', {'data-ad-slot': '123'});
  const b = h('div', {'data-ad-slot': 'abc'});
  const c = h('div', {'data-kind': 'x'});
  const doc = page(h('body', null, a, b, c));
  assert.deepEqual(run({selector: [css('div'), op('matches-attr', 'data-ad-slot')]}, doc), [a, b]);
  assert.deepEqual(run({selector: [css('div'), op('matches-attr', '"data-ad-slot"="123"')]}, doc), [a]);
  assert.deepEqual(run({selector: [css('div'), op('matches-attr', 'data-ad-slot="/^[a-z]+$/"')]}, doc), [b]);
  assert.deepEqual(run({selector: [css('div'), op('matches-attr', '/^data-ad-/')]}, doc), [a, b]);
  assert.equal(proceduralFilters.compile({selector: [css('a'), op('matches-attr', '/[/')]}), null);
});

test('matches-css and its pseudo elements', () => {
  const fixed = h('div');
  const plain = h('div');
  const tagged = h('div');
  const doc = page(h('body', null, fixed, plain, tagged));
  const styles = new Map([
    [fixed, {'': {position: 'fixed'}}],
    [plain, {'': {position: 'static'}}],
    [tagged, {'::before': {content: '"Ad"'}, '::after': {content: '"x"'}}],
  ]);
  const win = makeWindow(doc, {styles});
  assert.deepEqual(run({selector: [css('div'), op('matches-css', 'position: fixed')]}, doc, win), [fixed]);
  assert.deepEqual(run({selector: [css('div'), op('matches-css', 'position: /fix|stat/')]}, doc, win), [fixed, plain]);
  assert.deepEqual(run({selector: [css('div'), op('matches-css-before', 'content: /Ad/')]}, doc, win), [tagged]);
  assert.deepEqual(run({selector: [css('div'), op('matches-css-after', 'content: /Ad/')]}, doc, win), []);
  assert.equal(proceduralFilters.compile({selector: [css('a'), op('matches-css', 'no colon')]}), null);
});

test('matches-path', () => {
  const ad = h('div', {class: 'ad'});
  const doc = page(h('body', null, ad));
  const filter = {selector: [op('matches-path', '/^\\/watch/'), css(' .ad')]};
  assert.deepEqual(run(filter, doc, makeWindow(doc, {pathname: '/watch', search: '?v=1'})), [ad]);
  assert.deepEqual(run(filter, doc, makeWindow(doc, {pathname: '/home'})), []);
  const plain = {selector: [css('.ad'), op('matches-path', 'v=1')]};
  assert.deepEqual(run(plain, doc, makeWindow(doc, {pathname: '/watch', search: '?v=1'})), [ad]);
});

test('min-text-length', () => {
  const long = h('p', null, 'x'.repeat(50));
  const short = h('p', null, 'hi');
  const doc = page(h('body', null, long, short));
  assert.deepEqual(run({selector: [css('p'), op('min-text-length', '10')]}, doc), [long]);
  assert.equal(proceduralFilters.compile({selector: [css('p'), op('min-text-length', 'ten')]}), null);
});

test('xpath, first and after css', () => {
  const span = h('span');
  const div = h('div', {class: 'a'}, span);
  const doc = page(h('body', null, div));
  assert.deepEqual(run({selector: [op('xpath', '//span')]}, doc), [span]);
  assert.deepEqual(run({selector: [css('span'), op('xpath', '..')]}, doc), [div]);
  assert.deepEqual(run({selector: [css('div'), op('xpath', './/span')]}, doc), [span]);
});

test('unsupported filters compile to null', () => {
  const bad = [
    null,
    {},
    {selector: []},
    {selector: [op('matches-media', '(min-width: 1px)')]},
    {selector: [op('has', 'a')]},
    {selector: [css('a'), op('has-text', '/(/')]},
    {selector: [css('a'), {type: 'has-text'}]},
    {selector: [css('a'), css('[unclosed')]},
    {selector: [css('a')], action: {type: 'explode'}},
    {selector: [css('a')], action: {type: 'style'}},
    {selector: [css('a')], action: {type: 'remove-attr', arg: 1}},
    {selector: [css('a'), op('toString', 'x')]},
  ];
  for (const filter of bad) {
    assert.equal(proceduralFilters.compile(filter), null, JSON.stringify(filter));
  }
  assert.deepEqual(proceduralFilters.compile({selector: [css('a')], action: {type: 'remove'}}).action,
                   {type: 'remove', arg: undefined});
});

test('a selector the browser rejects throws at run time only', () => {
  const doc = page(h('body'));
  const compiled = proceduralFilters.compile({selector: [css('a:has-text(x)'), op('has-text', 'y')]});
  assert.ok(compiled);
  assert.throws(() => compiled.run(doc, makeWindow(doc)));
});

test('startCosmeticFilters: generic names, actions, marking', () => {
  observers.length = 0;
  pendingRecords = [];
  const body = h('body');
  const doc = page(body);
  const win = makeWindow(doc);
  const sent = [];
  startCosmeticFilters((classes, ids) => sent.push({classes, ids}), {
    generic: true,
    filters: [
      {selector: [css('div'), op('has-text', 'Sponsored')], attr: 'bb1'},
      {selector: [css('p'), op('has-text', 'Promo')], action: {type: 'remove'}, attr: ''},
      {selector: [css('i'), op('min-text-length', '1')], action: {type: 'remove-class', arg: 'bad|worse'}, attr: ''},
      {selector: [css('b'), op('min-text-length', '1')], action: {type: 'remove-attr', arg: 'onclick'}, attr: ''},
      {selector: [css('span'), op('min-text-length', '1')], action: {type: 'style', arg: 'color: red'}, attr: 'bb1s0'},
      {selector: [css('q:broken'), op('has-text', 'x')], attr: 'bb1'},
      {selector: [op('matches-media', 'x')], attr: 'bb1'},
    ],
  }, doc, win);

  const ad = body.appendChild(h('div', {class: 'ad-card promo', id: 'slot1'}, 'Sponsored'));
  const promo = body.appendChild(h('p', {class: 'x'}, 'Promo'));
  const italic = body.appendChild(h('i', {class: 'bad keep'}, 'i'));
  const bold = body.appendChild(h('b', {onclick: 'go()'}, 'b'));
  const span = body.appendChild(h('span', null, 's'));
  deliverMutations();
  win.runTimers();

  const classes = sent.flatMap((s) => s.classes).sort();
  const ids = sent.flatMap((s) => s.ids);
  assert.deepEqual(classes, ['ad-card', 'bad', 'keep', 'promo', 'x']);
  assert.deepEqual(ids, ['slot1']);
  assert.ok(ad.hasAttribute('bb1'));
  assert.equal(promo.parentNode, null, 'removed');
  assert.deepEqual([...italic.classList], ['keep']);
  assert.equal(bold.hasAttribute('onclick'), false);
  assert.ok(span.hasAttribute('bb1s0'));

  // Names are only sent once; a changed class is noticed.
  sent.length = 0;
  ad.setAttribute('class', 'ad-card fresh');
  deliverMutations();
  win.runTimers();
  assert.deepEqual(sent.flatMap((s) => s.classes), ['fresh']);

  // An element that stops matching is unmarked.
  ad.childNodes[0].text = 'Now plain';
  ad.setAttribute('id', 'slot1');
  deliverMutations();
  win.runTimers();
  assert.equal(ad.hasAttribute('bb1'), false);

  // Our own changes settle: no endless reruns.
  for (let i = 0; i < 3; i++) {
    deliverMutations();
    win.runTimers();
  }
  assert.equal(pendingRecords.length, 0);
});

test('startCosmeticFilters: nothing to do starts nothing', () => {
  observers.length = 0;
  const doc = page(h('body'));
  const win = makeWindow(doc);
  startCosmeticFilters(() => assert.fail('no call expected'),
                       {generic: false, filters: [{selector: [op('nope', '')]}]},
                       doc, win);
  assert.equal(observers.length, 0);
});

let failed = 0;
for (const {name, fn} of tests) {
  try {
    fn();
    console.log('ok   ' + name);
  } catch (e) {
    failed++;
    console.log('FAIL ' + name);
    console.log(e);
  }
}
console.log(`${tests.length - failed}/${tests.length} passed`);
process.exitCode = failed ? 1 : 0;
