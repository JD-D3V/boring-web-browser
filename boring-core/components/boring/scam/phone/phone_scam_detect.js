// Copyright 2026 boring. BSD style license.
// Decides whether a page looks like a scary warning that shows a phone
// number: the tech support scam pop-up ("your computer is infected, call
// Microsoft now"). Evaluates to a plain object, so node tests it as it
// ships (test_phone_scam_detect.js) and the browser runs it in an
// isolated world (PhoneScamTabHelper).
//
// Three things have to be true together, which is what keeps normal
// pages quiet (a tab that already looked like a scam needs less, see
// analyse):
//   1. a phone number is on the page,
//   2. the text is scare talk with a way out: a threat or pressure or a
//      support brand, plus an invitation to call, in at least three
//      kinds of wording,
//   3. the page is laid out like a warning: a pop-up holding the number,
//      full screen, or a bare page with almost nothing else on it.
// A shop's contact page, a bank's fraud advice or a news story about
// scams can have the words and the number but not the layout.
(() => {
  'use strict';

  const MAX_TEXT = 30000;
  const MIN_KINDS = 3;
  const MIN_KINDS_SUSPICIOUS = 2;

  // Phone numbers as people write them. Fiction numbers (555-01xx) are
  // matched too, so the samples can use them.
  const PHONE_PATTERNS = [
    // 1-888-555-0142, (888) 555-0142, +1 888 555 0142, 888.555.0142
    /(?<![\w.+-])(?:\+?1[\s.-]+)?\(?[2-9]\d{2}\)?[\s.-]+[2-9]\d{2}[\s.-]+\d{4}(?![\w-])/,
    // 1-800-MICROSOFT, 1-844-WIN-HELP
    /(?<![\w.+-])1[\s.-]?8(?:00|33|44|55|66|77|88)[\s.-]?[A-Z0-9]{3}[\s.-]?[A-Z0-9]{4,6}(?![\w-])/,
    // 18885550142
    /(?<![\w.+-])1?8(?:00|33|44|55|66|77|88)\d{7}(?!\w)/,
    // +44 20 7946 0958, +61 2 5550 1234
    /(?<![\w.])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,4}){2,4}(?![\w-])/,
    // 0800 555 0133, 020 7946 0958
    /(?<![\w.+])0[1-9]\d{1,3}[\s.-]\d{3,4}[\s.-]?\d{3,4}(?![\w-])/,
    // 1800 555 019, 1300 555 019
    /(?<![\w.+])1[38]00[\s.-]\d{3}[\s.-]\d{3}(?![\w-])/,
  ];

  // The wording, by kind. Lower case text is matched against these.
  const WORDING = {
    // Something is wrong with the computer or the account.
    threat: [
      /\b(?:virus(?:es)?|malware|spyware|trojans?|ransomware|keylogger|worm)\b/,
      /\b(?:infected|infection|hacked|compromised|breached|corrupted)\b/,
      /\b(?:suspicious|unusual|illegal|unauthori[sz]ed)\s+(?:activity|activities|login|sign-?in|access|attempts?)\b/,
      /\bsecurity\s+(?:alert|warning|breach|threat|risk)\b/,
      /\bcritical\s+(?:alert|warning|error|failure)\b/,
      /\byour\s+(?:computer|pc|mac|laptop|device|browser|system|windows|ip(?:\s+address)?|network)\b[^.!?\n]{0,50}?\b(?:locked|blocked|disabled|suspended|damaged|at risk|in danger|not safe)\b/,
    ],
    // Somebody official is on the other end: a big brand's support.
    support: [
      /\b(?:microsoft|windows|apple|macos|mac os|icloud|norton|mcafee|geek squad|defender|google|amazon|paypal|facebook|instagram|yahoo|gmail|outlook|hotmail|aol)\b[^.!?\n]{0,40}\b(?:support|technicians?|engineers?|specialists?|helpline|help ?desk|security (?:team|center|centre)|customer (?:service|care)|billing)\b/,
      /\b(?:support|technicians?|engineers?|specialists?|helpline|help ?desk)\b[^.!?\n]{0,40}\b(?:microsoft|windows|apple|norton|mcafee|geek squad|google|facebook|paypal|amazon)\b/,
      /\bbilling\s+(?:department|team|desk)\b/,
      /\bcertified\s+(?:microsoft|windows|apple)\b/,
    ],
    // Call this number.
    call: [
      /\b(?:call|dial|phone|ring|contact)\b[^.!?\n]{0,40}\b(?:now|immediately|right away|asap|urgently|today|toll[- ]?free|helpline|support|technicians?|hotline)\b/,
      /\b(?:call|dial)\b[^.!?\n]{0,20}\b(?:microsoft|windows|apple|paypal|amazon|google|facebook|norton|mcafee|support|us|our|the)\b/,
      /\b(?:toll[- ]?free|helpline|hotline)\b/,
      /\bspeak\s+(?:to|with)\s+(?:a|an|our)\b[^.!?\n]{0,25}\b(?:technician|engineer|specialist|agent|representative|expert)\b/,
    ],
    // Do not stop, or something bad follows.
    pressure: [
      /\b(?:do not|don't|dont|never)\s+(?:close|restart|reboot|shut\s?down|turn\s+off|power\s+off|ignore|navigate|leave|exit|use|continue|enter|type)\b/,
      /\b(?:prevent|avoid|stop)\s+(?:further|more|any|additional|permanent|data|serious|identity)\s+(?:damage|loss|theft|harm|attacks?)\b/,
      /\b(?:will|may|could)\s+(?:be\s+)?(?:lost|deleted|erased|disabled|suspended|blocked|locked|stolen|shared|corrupted|damaged)\b/,
      /\b(?:failure|failing)\s+to\s+(?:call|respond|contact|act|comply|take)\b/,
      /\bwithin\s+(?:the\s+next\s+)?\d+\s*(?:seconds?|minutes?|mins?|hours?)\b/,
      /\b(?:immediate|urgent)\s+(?:action|attention|assistance|support|help|response)\b/,
      /\b(?:your|all)\s+(?:personal|private|banking|financial|bank|credit card|login|saved)?\s*(?:data|information|passwords?|photos|files|details|accounts?)\b[^.!?\n]{0,50}\b(?:at risk|stolen|exposed|compromised|in danger|being stolen|deleted|lost|leaked)\b/,
      /\bif you (?:close|leave|ignore|refresh|restart)\b/,
    ],
    // A code that looks technical.
    errorCode: [
      /\berror\s*(?:code|number|no\.?|#)\s*[:#-]?\s*[a-z]*\d[a-z0-9-]{2,}/,
      /\b0x[0-9a-f]{6,8}\b/,
      /\b(?:dw6vb36|ms-?\d{3,}|err_[a-z_]+)\b/,
    ],
    // A charge you did not make.
    billing: [
      /\b(?:unauthori[sz]ed|suspicious|fraudulent|unknown)\s+(?:charge|transaction|purchase|payment|order|debit)s?\b/,
      /\b(?:charged|debited|billed|deducted)\b[^.!?\n]{0,25}[$£€]\s?\d/,
      /[$£€]\s?\d[\d,.]*\b[^.!?\n]{0,40}\b(?:charged|debited|billed|deducted|invoice|auto[- ]?renew|renewal)/,
      /\b(?:subscription|licen[cs]e|membership)\b[^.!?\n]{0,30}\b(?:expired|renewed|auto[- ]?renew|will (?:renew|be charged))/,
      /\b(?:cancel|refund|dispute)\b[^.!?\n]{0,40}\b(?:call|dial|contact)\b/,
    ],
  };

  function normalise(text) {
    return String(text || '')
        .slice(0, MAX_TEXT)
        .replace(/[​-‍⁠﻿]/g, '')
        .replace(/[‘’]/g, "'")
        // Amounts and numbers like $349.99 are not the end of a sentence.
        .replace(/(\d)[.,](?=\d)/g, '$1')
        .replace(/\s+/g, ' ')
        .toLowerCase();
  }

  function findPhones(text) {
    const source = String(text || '').slice(0, MAX_TEXT);
    const found = [];
    for (const pattern of PHONE_PATTERNS) {
      const match = pattern.exec(source);
      if (match) found.push(match[0].trim());
    }
    return found;
  }

  // Which kinds of wording the text has, by name.
  function classify(text) {
    const lower = normalise(text);
    const kinds = [];
    for (const kind of Object.keys(WORDING)) {
      if (WORDING[kind].some((pattern) => pattern.test(lower))) {
        kinds.push(kind);
      }
    }
    return kinds;
  }

  // The scare talk part of the decision. `popup` is true when the page
  // is laid out as a pop-up or full screen, false for a bare page.
  function wordingOk(kinds, popup, alertColor) {
    const has = (kind) => kinds.includes(kind);
    const specific = has('threat') || has('pressure') ||
        (has('billing') && has('support'));
    if (!has('call') || !specific) return false;
    if (popup) return kinds.length >= MIN_KINDS;
    // A bare page has to sound like a brand's support desk as well.
    return has('support') && kinds.length >= (alertColor ? MIN_KINDS : MIN_KINDS + 1);
  }

  // snapshot: {
  //   text,          the page's visible text
  //   telLinks,      how many tel: links the page has
  //   layout: {
  //     overlay,     a pop-up or dialog that holds the phone number
  //     fullscreen,  the page is full screen
  //     bare,        almost no links and no menu, header or footer
  //     alertColor,  big red, orange or yellow areas
  //   }
  // }
  // `tabSuspicious` is true when the tab already looked like a scam (the
  // takeover detector tripped, or an earlier page here was one). Then a
  // number, an invitation to call and one more kind of scare wording is
  // enough, wherever it sits on the page.
  function analyse(snapshot, tabSuspicious) {
    const quiet = {scary: false, kinds: [], layout: []};
    const text = snapshot && snapshot.text;
    const layout = (snapshot && snapshot.layout) || {};
    const phones = findPhones(text);
    if (!phones.length && !(snapshot && snapshot.telLinks > 0)) return quiet;
    const kinds = classify(text);
    if (tabSuspicious) {
      return {
        scary: kinds.includes('call') && kinds.length >= MIN_KINDS_SUSPICIOUS,
        kinds,
        layout: [],
      };
    }
    const popup = !!(layout.overlay || layout.fullscreen);
    const bare = !!layout.bare;
    const layoutNames = ['overlay', 'fullscreen', 'bare', 'alertColor']
        .filter((name) => layout[name]);
    const scary = (popup || bare) && wordingOk(kinds, popup, !!layout.alertColor);
    return {scary, kinds, layout: layoutNames};
  }

  // ---- Reading a real page ----

  function visible(win, el) {
    const style = win.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' ||
        parseFloat(style.opacity) < 0.1) {
      return null;
    }
    return style;
  }

  function isAlertColor(css) {
    const m = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?/.exec(css);
    if (!m) return false;
    const alpha = m[4] === undefined ? 1 : parseFloat(m[4]);
    if (alpha < 0.5) return false;
    const r = +m[1] / 255, g = +m[2] / 255, b = +m[3] / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    if (max < 0.45 || max - min < 0.55 * max) return false;
    // Hue in degrees. Red, orange and yellow only.
    let hue;
    const d = max - min;
    if (max === r) hue = ((g - b) / d + 6) % 6;
    else if (max === g) hue = (b - r) / d + 2;
    else hue = (r - g) / d + 4;
    hue *= 60;
    return hue <= 55 || hue >= 345;
  }

  const DIALOG_SELECTOR =
      'dialog, [role="dialog"], [role="alertdialog"], [aria-modal="true"]';

  // bodyText is the page's text, read once by the caller: reading it again
  // is a second layout of the whole page.
  function collectLayout(doc, win, bodyText) {
    const vw = win.innerWidth || 1, vh = win.innerHeight || 1;
    const viewport = vw * vh;
    const layout = {
      overlay: false, fullscreen: !!doc.fullscreenElement, bare: false,
      alertColor: false,
    };

    // A pop-up that holds the number: a dialog, or a fixed or stacked
    // block over a good part of the window, short, with next to no
    // links. A page wrapper that happens to be positioned is long and
    // full of links, which is how it is told apart.
    const candidates = doc.querySelectorAll('div, section, aside, form, dialog');
    const limit = Math.min(candidates.length, 800);
    for (let i = 0; i < limit; i++) {
      const el = candidates[i];
      const style = visible(win, el);
      if (!style) continue;
      const rect = el.getBoundingClientRect();
      const area = rect.width * rect.height;
      if (area >= 0.1 * viewport && !layout.alertColor &&
          isAlertColor(style.backgroundColor)) {
        layout.alertColor = true;
      }
      if (layout.overlay || area <= 0) continue;
      const dialog = el.matches(DIALOG_SELECTOR);
      const placed = style.position === 'fixed' ||
          (style.position === 'absolute' && parseInt(style.zIndex, 10) > 0);
      if (!dialog && !(placed && area >= 0.12 * viewport)) continue;
      // textContent costs no layout and is about as long as the visible
      // text, so a long block is passed over before its text is laid out.
      // Without this, nested blocks on a huge page each lay out the whole
      // page's text again.
      if ((el.textContent || '').length > 1500) continue;
      const inner = el.innerText || '';
      if (inner.length > 1500 || el.querySelectorAll('a[href]').length > 4) {
        continue;
      }
      if (findPhones(inner).length || el.querySelector('a[href^="tel:" i]')) {
        layout.overlay = true;
      }
    }

    if (!layout.alertColor && doc.body) {
      const body = visible(win, doc.body);
      layout.alertColor = !!body && isAlertColor(body.backgroundColor);
    }
    if (!layout.alertColor) {
      const headings = doc.querySelectorAll('h1, h2, h3');
      for (let i = 0; i < Math.min(headings.length, 20); i++) {
        if (isAlertColor(win.getComputedStyle(headings[i]).color)) {
          layout.alertColor = true;
          break;
        }
      }
    }

    // A bare page: nothing but the warning.
    const links = Array.from(doc.querySelectorAll('a[href]'))
        .filter((a) => !/^tel:/i.test(a.getAttribute('href'))).length;
    const landmarks = doc.querySelectorAll(
        'nav, header, footer, [role="navigation"], [role="contentinfo"]').length;
    layout.bare = links <= 4 && landmarks === 0 && bodyText.length <= 1800;
    return layout;
  }

  // The whole job for a live page. The cheap checks come first, so an
  // ordinary page costs one read of its text and a few patterns.
  function scanDocument(doc, win, tabSuspicious) {
    const text = (doc.body && doc.body.innerText) || '';
    const telLinks = doc.querySelectorAll('a[href^="tel:" i]').length;
    if (!findPhones(text).length && !telLinks) {
      return {scary: false, kinds: [], layout: []};
    }
    const kinds = classify(text);
    const needed = tabSuspicious ? MIN_KINDS_SUSPICIOUS : MIN_KINDS;
    if (!kinds.includes('call') || kinds.length < needed) {
      return {scary: false, kinds, layout: []};
    }
    return analyse(
        {text, telLinks, layout: tabSuspicious ? {} : collectLayout(doc, win, text)},
        !!tabSuspicious);
  }

  return Object.freeze({findPhones, classify, analyse, scanDocument});
})();
