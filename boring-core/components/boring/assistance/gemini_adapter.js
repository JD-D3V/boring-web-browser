// Copyright 2026 boring. BSD style license.
// Factory for the isolated Gemini document. Native callers must pass the real
// document and () => location, and independently validate the destination.
// expectedOrigin is only overridden by the localhost test hook.
// English controls observed 2026-10-07. Unsupported UI fails closed.
((doc, currentLocation, suppliedOrigin) => {
  'use strict';
  // Defaulted in the body: a default parameter would make 'use strict' illegal.
  const expectedOrigin = suppliedOrigin === undefined ?
    'https://gemini.google.com' : suppliedOrigin;
  let prepared = null;
  let attempted = false;
  let disposed = false;
  let baselineReplies = new Set();
  const result = (ok, reason) => ({ok, reason});
  // Only the two origin shapes native code can pass; anything else fails closed.
  const originOk = typeof expectedOrigin === 'string' &&
    (/^https:\/\/[a-z0-9.-]+$/.test(expectedOrigin) ||
     /^http:\/\/127\.0\.0\.1:[0-9]+$/.test(expectedOrigin));
  function allowed() {
    if (!originOk) return false;
    const url = currentLocation();
    return url.origin === expectedOrigin &&
      /^\/app(?:\/|$)/.test(url.pathname);
  }
  function visible(element) {
    return element.isConnected && element.getClientRects().length > 0 &&
      doc.defaultView.getComputedStyle(element).visibility !== 'hidden';
  }
  function controls(selector) {
    return Array.from(doc.querySelectorAll(selector)).filter(visible);
  }
  function editor() {
    const matches = controls('[role="textbox"][contenteditable="true"][aria-label="Enter a prompt for Gemini"]');
    return matches.length === 1 ? matches[0] : null;
  }
  function busy() {
    return controls('button[aria-label="Stop response"]').length > 0;
  }
  function status() {
    if (disposed) return result(false, 'disposed');
    if (!allowed()) return result(false, 'unexpected_destination');
    if (busy()) return result(false, 'generating');
    if (!editor()) {
      // A signed-out page shows a sign-in link where the composer would be.
      const signedOut = controls('a[href^="https://accounts.google.com/"]').length > 0;
      return result(false, signedOut ? 'signed_out' : 'composer_unavailable');
    }
    return result(true, attempted ? 'submitted_unverified' : 'ready');
  }
  function prepare(prompt) {
    const state = status();
    if (!state.ok) return state;
    if (attempted || prepared) return result(false, 'request_already_started');
    if (typeof prompt !== 'string' || !prompt.trim() ||
        new TextEncoder().encode(prompt).length > 56 * 1024) return result(false, 'invalid_prompt');
    const input = editor();
    if (input.innerText.trim()) return result(false, 'existing_draft');
    const before = new InputEvent('beforeinput', {
      bubbles:true, cancelable:true, inputType:'insertText', data:prompt,
    });
    if (!input.dispatchEvent(before)) return result(false, 'input_rejected');
    // Recheck after the event: the site's handler can replace the document/UI.
    if (!allowed() || editor() !== input || input.innerText.trim()) {
      return result(false, 'composer_changed');
    }
    input.focus();
    input.textContent = prompt;
    input.dispatchEvent(new InputEvent('input', {
      bubbles:true, inputType:'insertText', data:prompt,
    }));
    if (!allowed() || editor() !== input || input.textContent !== prompt) {
      return result(false, 'insertion_unverified');
    }
    prepared = {input, prompt, href:currentLocation().href};
    baselineReplies = new Set(doc.querySelectorAll('response-container'));
    return result(true, 'prepared');
  }
  function submit() {
    if (attempted) return result(false, 'submission_already_attempted');
    const state = status();
    if (!state.ok) return state;
    if (!prepared || currentLocation().href !== prepared.href ||
        editor() !== prepared.input || prepared.input.textContent !== prepared.prompt) {
      return result(false, 'draft_changed');
    }
    const buttons = controls('button[aria-label="Send message"]');
    if (buttons.length !== 1 || buttons[0].disabled ||
        buttons[0].getAttribute('aria-disabled') === 'true') return result(false, 'send_unavailable');
    // Mark before click. An exception or uncertain network outcome must not
    // permit a second send. Reply verification belongs to the response bridge.
    attempted = true;
    prepared = null;
    buttons[0].click();
    return result(true, 'submission_attempted');
  }
  // The person pressed Gemini's Send: our prompt has left the composer.
  function sentByPerson() {
    if (!prepared) return false;
    const input = editor();
    // A composer rebuilt on send has no prompt in it, so it counts as sent.
    return !input || !input.textContent.includes(prepared.prompt);
  }
  function readReply() {
    // Without this, a reply already on screen would pass as new: dispose
    // forgets the baseline.
    if (disposed) return result(false, 'disposed');
    if (!allowed()) return result(false, 'unexpected_destination');
    if (busy() || !(attempted || sentByPerson())) return result(false, 'waiting');
    const responses = Array.from(doc.querySelectorAll('response-container'))
      .filter(node => !baselineReplies.has(node));
    if (responses.length !== 1) return result(false, 'reply_unavailable');
    const response = responses[0];
    // All three were observed in a completed Gemini message. An idle composer
    // alone is insufficient: cancellation and provider errors can also be idle.
    const labels = response.querySelectorAll('.model-response-label-announcer[aria-busy="false"]');
    const messages = response.querySelectorAll('message-content');
    const copies = response.querySelectorAll('button[aria-label="Copy"]');
    if (labels.length !== 1 || messages.length !== 1 || copies.length !== 1 ||
        copies[0].disabled) return result(false, 'reply_incomplete');
    const text = messages[0].innerText;
    if (!text.trim() || new TextEncoder().encode(text).length > 32 * 1024) {
      return result(false, 'invalid_reply_size');
    }
    return {ok:true,reason:'reply_observed',text};
  }
  function dispose() {
    disposed = true; prepared = null; attempted = true; baselineReplies.clear();
  }
  return Object.freeze({prepare, submit, status, readReply, dispose});
})
