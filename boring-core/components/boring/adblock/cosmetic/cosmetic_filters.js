// Copyright 2026 boring. BSD style license.

// The page side of cosmetic filtering, run once per document in the
// cosmetic filter isolated world, so the page can neither see nor break
// it. CosmeticFilterAgent starts it at document start, before any page
// script, with:
//
//   sendClassIds(classes, ids)  native; asks the browser for the generic
//                               hiding rules for these names and inserts
//                               the result as a user stylesheet.
//   config.generic              false when the page has $generichide.
//   config.filters              procedural and action filters, each the
//                               adblock-rust JSON plus `attr`, the
//                               attribute that hides or styles a match
//                               (the agent's stylesheet targets it).
//
// Everything here is driven by one MutationObserver and one throttled
// timer, so a busy page costs at most one pass every MIN_INTERVAL_MS.

function startCosmeticFilters(sendClassIds, config, doc, win) {
  'use strict';

  const MIN_INTERVAL_MS = 100;
  // Past this many added subtrees in one pass, one scan of the whole
  // document is cheaper than scanning each.
  const MAX_PENDING_ROOTS = 1000;
  // Names per native call, so one huge page cannot build one huge message.
  const MAX_NAMES_PER_CALL = 1000;
  // A page that invents endless class names (some do, per element) stops
  // being asked about after this many.
  const MAX_SEEN_NAMES = 20000;

  const generic = !!config.generic;
  const filters = [];
  for (const entry of config.filters || []) {
    const compiled = proceduralFilters.compile(entry);
    if (compiled) {
      filters.push({compiled, attr: entry.attr || ''});
    }
  }
  if (!generic && filters.length === 0) {
    return;
  }

  const seenClasses = new Set();
  const seenIds = new Set();
  let newClasses = [];
  let newIds = [];
  // Elements whose subtree is new since the last pass, and elements that
  // only changed their own class or id.
  let pendingRoots = [];
  let pendingSelf = [];
  let scanAll = true;
  // For each marking attribute, the elements it was set on last pass.
  let marked = new Map();
  let timer = 0;
  let lastRun = -Infinity;

  function note(element) {
    const id = element.id;
    if (id && typeof id === 'string' && !seenIds.has(id)) {
      seenIds.add(id);
      newIds.push(id);
    }
    const classList = element.classList;
    if (!classList) {
      return;
    }
    for (const name of classList) {
      if (!seenClasses.has(name)) {
        seenClasses.add(name);
        newClasses.push(name);
      }
    }
  }

  function noteSubtree(root) {
    note(root);
    for (const element of root.querySelectorAll('[id],[class]')) {
      note(element);
    }
  }

  function scanGeneric() {
    if (seenClasses.size + seenIds.size > MAX_SEEN_NAMES) {
      pendingRoots = [];
      pendingSelf = [];
      return;
    }
    if (scanAll) {
      if (doc.documentElement) {
        noteSubtree(doc.documentElement);
      }
    } else {
      for (const root of pendingRoots) {
        if (root.isConnected) {
          noteSubtree(root);
        }
      }
      for (const element of pendingSelf) {
        note(element);
      }
    }
    pendingRoots = [];
    pendingSelf = [];
    while (newClasses.length || newIds.length) {
      const classes = newClasses.splice(0, MAX_NAMES_PER_CALL);
      const ids = newIds.splice(0, MAX_NAMES_PER_CALL - classes.length);
      sendClassIds(classes, ids);
    }
  }

  function applyAction(action, element) {
    switch (action.type) {
      case 'remove':
        element.remove();
        break;
      case 'remove-attr':
        for (const name of action.arg.split('|')) {
          if (name && element.hasAttribute(name)) {
            element.removeAttribute(name);
          }
        }
        break;
      case 'remove-class':
        // Only touch the attribute when something changes: every write
        // is a mutation, and the observer would run us again for it.
        for (const name of action.arg.split('|')) {
          if (name && element.classList.contains(name)) {
            element.classList.remove(name);
          }
        }
        break;
    }
  }

  function applyProcedural() {
    const nowMarked = new Map();
    for (const filter of filters) {
      if (filter.broken) {
        continue;
      }
      let found;
      try {
        found = filter.compiled.run(doc, win);
      } catch (e) {
        // A selector the browser rejects: drop this filter, keep the rest.
        filter.broken = true;
        continue;
      }
      const action = filter.compiled.action;
      if (action && action.type !== 'style') {
        for (const element of found) {
          applyAction(action, element);
        }
        continue;
      }
      if (!filter.attr) {
        continue;
      }
      let set = nowMarked.get(filter.attr);
      if (!set) {
        set = new Set();
        nowMarked.set(filter.attr, set);
      }
      for (const element of found) {
        set.add(element);
      }
    }
    // Elements that stopped matching get their attribute back off; the
    // rest get it on. Unchanged ones are left alone.
    for (const [attr, before] of marked) {
      const now = nowMarked.get(attr);
      for (const element of before) {
        if ((!now || !now.has(element)) && element.hasAttribute(attr)) {
          element.removeAttribute(attr);
        }
      }
    }
    for (const [attr, now] of nowMarked) {
      for (const element of now) {
        if (!element.hasAttribute(attr)) {
          element.setAttribute(attr, '');
        }
      }
    }
    marked = nowMarked;
  }

  function run() {
    timer = 0;
    lastRun = Date.now();
    if (generic) {
      scanGeneric();
    }
    if (filters.length) {
      applyProcedural();
    }
    scanAll = false;
  }

  function schedule() {
    if (timer) {
      return;
    }
    const wait = Math.max(0, lastRun + MIN_INTERVAL_MS - Date.now());
    timer = win.setTimeout(run, wait);
  }

  const observer = new win.MutationObserver((records) => {
    for (const record of records) {
      if (record.type === 'attributes') {
        pendingSelf.push(record.target);
        continue;
      }
      for (const node of record.addedNodes) {
        if (node.nodeType === 1) {
          pendingRoots.push(node);
        }
      }
    }
    if (pendingRoots.length + pendingSelf.length > MAX_PENDING_ROOTS) {
      scanAll = true;
      pendingRoots = [];
      pendingSelf = [];
    }
    schedule();
  });
  observer.observe(doc, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'id'],
  });
  schedule();
}
