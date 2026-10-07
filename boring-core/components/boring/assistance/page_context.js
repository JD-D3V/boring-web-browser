// Copyright 2026 boring. BSD style license.
// Install only on user request, in a browser-owned isolated world. Native code
// enforces profile/scheme policy and retains the document identity too.
(() => {
  'use strict';
  const MAX_BYTES = 48 * 1024;
  const MAX_CANDIDATES = 160;
  const MAX_NODES = 20000;
  const BLOCK_TAGS = new Set(['P','H1','H2','H3','H4','H5','H6','LI','TR','PRE','BLOCKQUOTE']);
  const EXCLUDED = new Set(['INPUT','TEXTAREA','SELECT','OPTION','SCRIPT','STYLE','NOSCRIPT','TEMPLATE','IFRAME','OBJECT','EMBED']);
  // Question words say nothing about the control. Without them, "create" would
  // match every "Create ..." button.
  const STOP_WORDS = new Set(['a','an','and','are','can','do','does','find','for','get','go','how','i','in','is','it','me','my','of','on','or','show','the','to','where','which','with','you','your','create','make','new','open']);
  const encoder = new TextEncoder();
  let revision = 0, active = null, overlay = null, timer = null, frame = null, highlighted = null;
  const targets = new Map();
  function clean(text) {
    return String(text || '').replace(/\s+/g, ' ').trim()
      .replace(/\b(?:sk-[a-zA-Z0-9_-]{16,}|gh[pousr]_[a-zA-Z0-9]{16,}|AIza[a-zA-Z0-9_-]{20,}|Bearer\s+[a-zA-Z0-9_.-]{12,})\b/g, '[redacted]')
      .replace(/https?:\/\/[^\s<>"']+/g, value => safeURL(value));
  }
  function safeURL(value) {
    try {
      const url = new URL(value, document.baseURI);
      if (!/^https?:$/.test(url.protocol)) return '';
      url.username = ''; url.password = ''; url.search = ''; url.hash = '';
      return url.href;
    } catch { return ''; }
  }
  function parent(element) {
    return element.parentElement || element.getRootNode().host || null;
  }
  // One node only. The capture walk prunes excluded subtrees, so it never needs ancestors.
  function excludedSelf(element) {
    if (EXCLUDED.has(element.tagName) || element.isContentEditable ||
        element.hidden || element.getAttribute('aria-hidden') === 'true') return true;
    const style = getComputedStyle(element);
    return style.display === 'none' || style.visibility === 'hidden' ||
      style.visibility === 'collapse' || style.opacity === '0';
  }
  function excluded(element) {
    for (let node = element; node; node = parent(node)) {
      if (excludedSelf(node)) return true;
    }
    return false;
  }
  function readable(element) {
    return element.isConnected && !excluded(element) && element.getClientRects().length > 0;
  }
  function label(element) {
    // Do not use innerText: it includes editable descendants.
    const explicit = element.getAttribute('aria-label');
    if (explicit) return clean(explicit).slice(0,240);
    let text = '', count = 0;
    const stack = Array.from(element.childNodes).reverse();
    while (stack.length && count++ < 300 && text.length < 480) {
      const node = stack.pop();
      if (node.nodeType === Node.TEXT_NODE) text += ' ' + node.textContent;
      else if (node.nodeType === Node.ELEMENT_NODE && !excludedSelf(node)) {
        if (node.tagName === 'IMG') text += ' ' + (node.getAttribute('alt') || '');
        stack.push(...Array.from(node.childNodes).reverse());
      }
    }
    return clean(text || element.getAttribute('title')).slice(0,240);
  }
  function role(element) {
    const declared = element.getAttribute('role');
    if (['button','link','menuitem','tab','summary'].includes(declared)) return declared;
    if (element.tagName === 'A' && element.hasAttribute('href')) return 'link';
    if (element.tagName === 'BUTTON' || element.tagName === 'SUMMARY') return 'button';
    return null;
  }
  function clearHighlight() {
    clearTimeout(timer); timer = null;
    cancelAnimationFrame(frame); frame = null; highlighted = null;
    if (overlay) overlay.remove();
    overlay = null;
  }
  // Keep the outline on its control while the page scrolls or relayouts.
  function track() {
    frame = null;
    if (!highlighted || !overlay) return;
    if (!highlighted.node.isConnected || location.href !== highlighted.href) {
      clearHighlight(); return;
    }
    place(highlighted.node);
    frame = requestAnimationFrame(track);
  }
  function place(node) {
    const rect = node.getBoundingClientRect();
    Object.assign(overlay.style,{left:(rect.left-4)+'px',top:(rect.top-4)+'px',
      width:(rect.width+8)+'px',height:(rect.height+8)+'px'});
  }
  function dispose() {
    clearHighlight();
    document.removeEventListener('keydown', onKey, true);
    targets.clear(); active = null;
  }
  function onKey(event) { if (event.key === 'Escape') clearHighlight(); }
  function capture(requestId) {
    dispose();
    if (!/^[a-zA-Z0-9_-]{6,64}$/.test(requestId) || !/^https?:$/.test(location.protocol)) {
      throw new Error('Unsupported page or invalid request');
    }
    const result = {requestId,revision:++revision,title:clean(document.title).slice(0,300),
      url:safeURL(location.href),candidates:[],blocks:[],
      coverage:{partial:false,framesExcluded:0,scope:'Loaded main document and open shadow roots; hidden and unloaded content excluded'}};
    let visited = 0, textSize = 0;
    const blocks = new Map();
    // Check the walk root's ancestors once; below it, a pruned node stops its subtree.
    const stack = excluded(document.body) ? [] : [{node:document.body,block:document.body,nav:false}];
    while (stack.length && visited++ < MAX_NODES && textSize < 96 * 1024) {
      const {node,block,nav} = stack.pop();
      if (!node) continue;
      if (node.nodeType === Node.TEXT_NODE) {
        const value = clean(node.textContent);
        // Navigation is listed by its controls (candidates), not narrated as page text.
        if (value && !nav) {
          const prior = blocks.get(block) || '';
          blocks.set(block,prior + (prior ? ' ' : '') + value.slice(0,4096));
          textSize += value.length;
          if (value.length > 4096) result.coverage.partial = true;
        }
        continue;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) continue;
      if (['IFRAME','OBJECT','EMBED'].includes(node.tagName)) {
        result.coverage.framesExcluded++; result.coverage.partial = true;
      }
      if (excludedSelf(node)) continue;
      const kind = role(node);
      // Connected and excluded-free ancestry are guaranteed by the walk itself.
      if (kind && node.getClientRects().length > 0) {
        const name = label(node);
        if (name && result.candidates.length < MAX_CANDIDATES) {
          const id = 'c' + (result.candidates.length + 1);
          const href = node.tagName === 'A' ? safeURL(node.href) : '';
          result.candidates.push({id,role:kind,label:name,url:href});
          targets.set(id,{node,role:kind,label:name,href,rawHref:node.getAttribute('href')});
        } else if (name) result.coverage.partial = true;
      }
      const inNav = nav || node.tagName === 'NAV' || node.getAttribute('role') === 'navigation';
      const nextBlock = BLOCK_TAGS.has(node.tagName) ? node : block;
      // A shadow host shows its light children only through a slot; the rest is
      // hidden text. Closed roots are invisible here and out of scope.
      const children = Array.from(node.childNodes)
        .filter(child => !node.shadowRoot || child.assignedSlot);
      stack.push(...children.reverse().map(child => ({node:child,block:nextBlock,nav:inNav})));
      if (node.shadowRoot) {
        stack.push(...Array.from(node.shadowRoot.childNodes).reverse().map(child => ({node:child,block:node,nav:inNav})));
      }
    }
    if (stack.length) result.coverage.partial = true;
    for (const [element,text] of blocks) result.blocks.push({kind:element.tagName.toLowerCase(),text});
    // Bound serialized UTF-8 including JSON overhead, never slice encoded data.
    // Measure each dropped item once rather than reserializing per drop; the
    // exact loop below then settles any rounding (the last item has no comma).
    const size = value => encoder.encode(JSON.stringify(value)).length;
    if (size(result) > MAX_BYTES) {
      result.coverage.partial = true;
      let total = size(result);
      while (total > MAX_BYTES && result.blocks.length) {
        total -= size(result.blocks.pop()) + 1;
      }
      while (total > MAX_BYTES && result.candidates.length) {
        const dropped = result.candidates.pop();
        targets.delete(dropped.id);
        total -= size(dropped) + 1;
      }
    }
    while (size(result) > MAX_BYTES) {
      result.coverage.partial = true;
      if (result.blocks.length) result.blocks.pop();
      else if (result.candidates.length) targets.delete(result.candidates.pop().id);
      else throw new Error('Snapshot metadata exceeds limit');
    }
    active = {requestId,revision,href:location.href,root:document.documentElement};
    document.addEventListener('keydown',onKey,true);
    return result;
  }
  function highlight(requestId, expectedRevision, candidateId) {
    const target = targets.get(candidateId);
    if (!active || active.requestId !== requestId ||
        active.revision !== expectedRevision || active.href !== location.href ||
        active.root !== document.documentElement || !target ||
        !readable(target.node) || role(target.node) !== target.role ||
        label(target.node) !== target.label || target.node.getAttribute('href') !== target.rawHref) {
      clearHighlight(); return {ok:false,reason:'stale_or_unknown_target'};
    }
    clearHighlight();
    target.node.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
    overlay = document.createElement('div');
    overlay.setAttribute('aria-hidden','true');
    Object.assign(overlay.style,{position:'fixed',pointerEvents:'none',zIndex:'2147483647',
      border:'3px solid #176b5b',borderRadius:'6px',boxSizing:'border-box'});
    highlighted = {node:target.node,href:active.href};
    place(target.node);
    document.documentElement.append(overlay);
    timer = setTimeout(clearHighlight,10000);
    frame = requestAnimationFrame(track);
    return {ok:true,reason:'highlighted'};
  }
  function words(text) {
    return text.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  }
  // Drop one plural s, so "keys" meets "key". Short words keep theirs: "bus" stays whole.
  function stem(word) {
    return word.length > 3 && word.endsWith('s') ? word.slice(0,-1) : word;
  }
  // A prefix only counts from 3 characters up, so "bi" does not find "billing".
  function sameWord(a, b) {
    if (a === b) return true;
    return Math.min(a.length,b.length) >= 3 && (a.startsWith(b) || b.startsWith(a));
  }
  // Pure local reading: the question never leaves the page or the isolated world.
  function find(requestId, query) {
    // Check before capture, so a rejected query keeps the last snapshot's targets.
    const text = typeof query === 'string' ? query.trim() : '';
    if (text.length < 1 || text.length > 200) throw new Error('Invalid query');
    const snapshot = capture(requestId);
    // Dedupe after stemming, so "key keys" cannot raise the score twice.
    const wanted = [...new Set(words(text).filter(w => w.length >= 2 && !STOP_WORDS.has(w)).map(stem))];
    const ranked = snapshot.candidates.map((candidate, order) => {
      const labelWords = words(candidate.label).map(stem);
      const score = wanted.filter(q => labelWords.some(w => sameWord(q,w))).length;
      return {candidate,order,score};
    });
    const matches = ranked
      .filter(r => r.score > 0)
      .sort((a,b) => b.score - a.score ||
        a.candidate.label.length - b.candidate.label.length || a.order - b.order)
      .slice(0,5)
      .map(({candidate}) => ({id:candidate.id,role:candidate.role,label:candidate.label}));
    return {requestId,revision:snapshot.revision,matches};
  }
  return Object.freeze({capture,highlight,find,dispose});
})()
