// Copyright 2026 boring. BSD style license.

// The element picker: "Block this element" on the toolbar shield. Run
// in the cosmetic filter isolated world, so the page's scripts cannot
// reach into it, and the picker's own nodes sit in a closed shadow
// root the page's styles do not apply to. ElementPickerAgent starts it
// with:
//
//   done(selector)  native; called once with the CSS selector to block,
//                   or '' when the person cancels.
//
// Mouse: hovering outlines an element, a click picks it. Keyboard: focus
// starts on the panel; the arrow keys pick the element in the middle of
// the window and then move the pick (Up widens to the parent, Down
// narrows back, Left and Right go to the siblings). Enter or Space on
// Block blocks it; Escape cancels from anywhere.

function startElementPicker(done, doc, win) {
  'use strict';

  const MAX_DEPTH = 12;
  const MAX_CLASSES = 2;
  const MAX_NAME_LENGTH = 40;

  // Clicks and presses the page must not see while the picker is up,
  // so picking a link or a button does not also follow or press it.
  const SWALLOWED = [
    'click', 'dblclick', 'auxclick', 'contextmenu', 'mousedown', 'mouseup',
    'pointerdown', 'pointerup', 'touchstart', 'touchend',
  ];

  const STYLE = `
    :host { all: initial; }
    .box {
      position: fixed; pointer-events: none; box-sizing: border-box;
      border: 2px solid #1a5fd0; background: rgba(26, 95, 208, 0.16);
      border-radius: 2px; display: none;
      transition: top 80ms ease-out, left 80ms ease-out,
                  width 80ms ease-out, height 80ms ease-out;
    }
    .box.picked { border-color: #b3261e; background: rgba(179, 38, 30, 0.18); }
    .panel {
      position: fixed; right: 16px; bottom: 16px; max-width: min(420px, 90vw);
      pointer-events: auto; box-sizing: border-box; padding: 14px 16px;
      font: 14px/1.4 system-ui, sans-serif; color: #1b1b1b;
      background: #ffffff; border: 1px solid #8a8a8a; border-radius: 8px;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
    }
    .title { margin: 0 0 4px; font-weight: 600; font-size: 15px; }
    .hint { margin: 0 0 10px; }
    code {
      display: block; margin: 0 0 12px; padding: 6px 8px; max-height: 6em;
      overflow: auto; word-break: break-all; border-radius: 4px;
      font: 13px/1.4 ui-monospace, Consolas, monospace;
      background: #f0f0f0; color: #1b1b1b;
    }
    code[hidden] { display: none; }
    .buttons { display: flex; gap: 8px; justify-content: flex-end; }
    button {
      font: inherit; padding: 6px 14px; border-radius: 6px; cursor: pointer;
      border: 1px solid #8a8a8a; background: #ffffff; color: #1b1b1b;
    }
    button.block { background: #1a5fd0; border-color: #1a5fd0; color: #ffffff; }
    button:disabled { opacity: 0.5; cursor: default; }
    button:focus-visible { outline: 3px solid #1a5fd0; outline-offset: 2px; }
    @media (prefers-color-scheme: dark) {
      .panel { color: #ececec; background: #202124; border-color: #6f6f6f; }
      code { background: #303134; color: #ececec; }
      button { background: #303134; color: #ececec; border-color: #6f6f6f; }
      button.block { background: #8ab4f8; border-color: #8ab4f8; color: #202124; }
      button:focus-visible { outline-color: #8ab4f8; }
    }
    @media (prefers-reduced-motion: reduce) {
      .box { transition: none; }
    }
  `;

  // The host is a plain div: a custom element name could be defined by
  // the page, and would then run the page's code on our node.
  const host = doc.createElement('div');
  host.style.cssText =
      'all: initial !important; position: fixed !important; inset: 0 !important;' +
      ' z-index: 2147483647 !important; pointer-events: none !important;' +
      ' display: block !important;';
  const root = host.attachShadow({mode: 'closed'});
  // A constructed stylesheet and nodes made one by one, not a <style>
  // element or innerHTML: a page's CSP or Trusted Types policy would
  // refuse those, and the picker has to work on every page.
  const sheet = new win.CSSStyleSheet();
  sheet.replaceSync(STYLE);
  root.adoptedStyleSheets = [sheet];

  function make(tag, className, text) {
    const node = doc.createElement(tag);
    if (className) {
      node.className = className;
    }
    if (text) {
      node.textContent = text;
    }
    return node;
  }

  const box = make('div', 'box');
  const panel = make('div', 'panel');
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Block element');
  const title = make('p', 'title', 'Block element');
  const hint = make('p', 'hint',
      'Click the part of the page to block. Arrow keys change the pick. ' +
      'Esc cancels.');
  hint.setAttribute('aria-live', 'polite');
  const code = make('code');
  code.hidden = true;
  const buttons = make('div', 'buttons');
  const cancelButton = make('button', 'cancel', 'Cancel');
  const blockButton = make('button', 'block', 'Block');
  cancelButton.type = 'button';
  blockButton.type = 'button';
  blockButton.disabled = true;
  buttons.append(cancelButton, blockButton);
  panel.append(title, hint, code, buttons);
  root.append(box, panel);

  let picked = null;
  let pickedSelector = '';
  // Narrower picks the arrow keys widened from, to go back down to.
  let narrower = [];
  let finished = false;
  let frame = 0;

  // ---- Selectors ----

  // Names a page generates per build or per visit (hashes, counters,
  // CSS-in-JS classes) would stop matching next time, so they are not
  // used when anything steadier will do.
  function isStableName(name) {
    return name.length > 0 && name.length <= MAX_NAME_LENGTH &&
        !/\d{3,}/.test(name) &&
        !/^(css|sc|jsx|emotion|svelte)-/i.test(name) &&
        !/__[A-Za-z0-9-]{5,}$/.test(name) &&
        !(/\d/.test(name) && /^[0-9a-f-]{8,}$/i.test(name));
  }

  function matchesOnly(selector, element) {
    try {
      const found = doc.querySelectorAll(selector);
      return found.length === 1 && found[0] === element;
    } catch (e) {
      return false;
    }
  }

  function stableId(element) {
    const id = element.id;
    if (!id || !isStableName(id)) {
      return '';
    }
    const selector = '#' + CSS.escape(id);
    return matchesOnly(selector, element) ? selector : '';
  }

  // Tag and up to two stable class names, with nth-of-type when a
  // sibling would match the same.
  function step(element) {
    let part = element.localName;
    const classes = Array.from(element.classList)
        .filter(isStableName).slice(0, MAX_CLASSES);
    for (const name of classes) {
      part += '.' + CSS.escape(name);
    }
    const parent = element.parentElement;
    if (!parent) {
      return part;
    }
    const sameTag = Array.from(parent.children)
        .filter((child) => child.localName === element.localName);
    const clash = sameTag.some(
        (child) => child !== element && child.matches(part));
    if (clash) {
      part += ':nth-of-type(' + (sameTag.indexOf(element) + 1) + ')';
    }
    return part;
  }

  function selectorFor(element) {
    const id = stableId(element);
    if (id) {
      return id;
    }
    const steps = [];
    let node = element;
    for (let depth = 0; node && depth < MAX_DEPTH; depth++) {
      if (node === doc.documentElement) {
        steps.unshift('html');
        break;
      }
      const anchor = node === element ? '' : stableId(node);
      if (anchor) {
        steps.unshift(anchor);
        break;
      }
      steps.unshift(step(node));
      const selector = steps.join(' > ');
      if (matchesOnly(selector, element)) {
        return selector;
      }
      node = node.parentElement;
    }
    const selector = steps.join(' > ');
    return matchesOnly(selector, element) ? selector : '';
  }

  // ---- Showing the pick ----

  function isOurs(event) {
    return event.composedPath().includes(host);
  }

  function isPickable(element) {
    return element && element.nodeType === 1 && element !== host &&
        element !== doc.documentElement && element !== doc.body;
  }

  function outline(element) {
    if (!element) {
      box.style.display = 'none';
      return;
    }
    const rect = element.getBoundingClientRect();
    box.style.display = 'block';
    box.style.top = rect.top + 'px';
    box.style.left = rect.left + 'px';
    box.style.width = rect.width + 'px';
    box.style.height = rect.height + 'px';
  }

  function pick(element) {
    if (!isPickable(element)) {
      return;
    }
    const selector = selectorFor(element);
    if (!selector) {
      hint.textContent = 'That part cannot be blocked on its own. ' +
          'Try the part around it.';
      return;
    }
    picked = element;
    pickedSelector = selector;
    box.classList.add('picked');
    outline(element);
    code.textContent = selector;
    code.hidden = false;
    hint.textContent = 'Block this part of the page? ' +
        'Arrow keys change the pick. Esc cancels.';
    blockButton.disabled = false;
    blockButton.focus();
  }

  function refresh() {
    frame = 0;
    if (picked) {
      outline(picked);
    }
  }

  function scheduleRefresh() {
    if (!frame) {
      frame = win.requestAnimationFrame(refresh);
    }
  }

  // ---- Events ----

  function onMove(event) {
    if (picked || isOurs(event)) {
      return;
    }
    outline(isPickable(event.target) ? event.target : null);
  }

  function onPress(event) {
    if (isOurs(event)) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    if (event.type === 'click') {
      narrower = [];
      pick(event.target);
    }
  }

  function moveTo(element) {
    if (isPickable(element)) {
      pick(element);
    }
  }

  function onKey(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      finish('');
      return;
    }
    const arrows = ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
    if (!arrows.includes(event.key)) {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!picked) {
      moveTo(doc.elementFromPoint(win.innerWidth / 2, win.innerHeight / 2));
      return;
    }
    if (event.key === 'ArrowUp') {
      const current = picked;
      if (isPickable(current.parentElement)) {
        narrower.push(current);
        moveTo(current.parentElement);
      }
    } else if (event.key === 'ArrowDown') {
      moveTo(narrower.pop() || picked.firstElementChild);
    } else {
      narrower = [];
      moveTo(event.key === 'ArrowLeft' ? picked.previousElementSibling
                                       : picked.nextElementSibling);
    }
  }

  function finish(selector) {
    if (finished) {
      return;
    }
    finished = true;
    win.removeEventListener('mousemove', onMove, true);
    win.removeEventListener('keydown', onKey, true);
    win.removeEventListener('scroll', scheduleRefresh, true);
    win.removeEventListener('resize', scheduleRefresh, true);
    for (const type of SWALLOWED) {
      win.removeEventListener(type, onPress, true);
    }
    if (frame) {
      win.cancelAnimationFrame(frame);
    }
    host.remove();
    done(selector);
  }

  blockButton.addEventListener('click', () => {
    if (pickedSelector) {
      finish(pickedSelector);
    }
  });
  cancelButton.addEventListener('click', () => finish(''));

  win.addEventListener('mousemove', onMove, true);
  win.addEventListener('keydown', onKey, true);
  win.addEventListener('scroll', scheduleRefresh, true);
  win.addEventListener('resize', scheduleRefresh, true);
  for (const type of SWALLOWED) {
    // Not passive, or a touch could not be kept from the page.
    win.addEventListener(type, onPress, {capture: true, passive: false});
  }
  doc.documentElement.appendChild(host);
  cancelButton.focus();
}
