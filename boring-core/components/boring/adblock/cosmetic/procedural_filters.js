// Copyright 2026 boring. BSD style license.

// Procedural cosmetic filters: the uBlock Origin syntax that plain CSS
// cannot express, such as `div:has-text(Sponsored)`. adblock-rust hands
// each one over as JSON:
//
//   {"selector": [{"type": "css-selector", "arg": "div"},
//                 {"type": "has-text", "arg": "Sponsored"}],
//    "action": {"type": "remove"}}
//
// The operators are the ones adblock-rust 0.13 emits (CosmeticFilterOperator
// in its filters/cosmetic.rs). compile() returns null for anything else, so
// one filter we cannot handle never stops the others.
//
// This file runs in the cosmetic filter isolated world, wrapped together
// with cosmetic_filters.js. It is also loaded by test_procedural_filters.js
// under node, so it only reaches the page through the `doc` and `win` it
// is handed, never through globals.

const proceduralFilters = (() => {
  'use strict';

  const ELEMENT_NODE = 1;
  const DOCUMENT_NODE = 9;
  const ORDERED_NODE_SNAPSHOT_TYPE = 7;
  // :upward(n) climbs at most this far, as in uBO.
  const MAX_UPWARD = 256;

  const ACTIONS = new Set(['remove', 'style', 'remove-attr', 'remove-class']);

  // "/pattern/flags" is a regular expression, anything else is plain text.
  // Returns null for plain text, undefined for a regex that does not
  // compile.
  function parseRegex(arg) {
    const match = /^\/(.+)\/([a-z]*)$/s.exec(arg);
    if (!match) {
      return null;
    }
    try {
      // g and y make test() stateful across calls, which would make an
      // element match every other time.
      return new RegExp(match[1], match[2].replace(/[gy]/g, ''));
    } catch (e) {
      return undefined;
    }
  }

  // A test for text: a regex, a substring, or with `exact` the whole
  // string. Returns null when the regex is invalid.
  function textTest(arg, exact) {
    const re = parseRegex(arg);
    if (re === undefined) {
      return null;
    }
    if (re) {
      return (text) => re.test(text);
    }
    return exact ? (text) => text === arg : (text) => text.includes(arg);
  }

  function unquote(text) {
    const trimmed = text.trim();
    if (trimmed.length >= 2 &&
        (trimmed[0] === '"' || trimmed[0] === '\'') &&
        trimmed[trimmed.length - 1] === trimmed[0]) {
      return trimmed.slice(1, -1);
    }
    return trimmed;
  }

  // Splits a selector into steps of (combinator, compound selector), so a
  // selector that continues after a procedural operator, like the
  // " > span" in `div:has-text(ad) > span`, can be applied to the
  // elements found so far. The combinator is '' when the compound narrows
  // those elements themselves (`div:upward(2).box`). Returns null for a
  // selector with unbalanced brackets or quotes.
  function splitSteps(text) {
    const selector = text.trimEnd();
    const steps = [];
    let combinator = '';
    let compound = '';
    let depth = 0;
    let quote = '';
    const flush = () => {
      if (compound) {
        steps.push({combinator, compound});
        combinator = '';
        compound = '';
      }
    };
    for (let i = 0; i < selector.length; i++) {
      const c = selector[i];
      if (c === '\\') {
        compound += selector.slice(i, i + 2);
        i++;
        continue;
      }
      if (quote) {
        compound += c;
        if (c === quote) {
          quote = '';
        }
        continue;
      }
      if (c === '"' || c === '\'') {
        quote = c;
      } else if (c === '(' || c === '[') {
        depth++;
      } else if (c === ')' || c === ']') {
        if (--depth < 0) {
          return null;
        }
      } else if (depth === 0 && /[\s>+~]/.test(c)) {
        flush();
        if (/\s/.test(c)) {
          combinator = combinator || ' ';
        } else if (combinator && combinator !== ' ') {
          return null;
        } else {
          combinator = c;
        }
        continue;
      }
      compound += c;
    }
    if (quote || depth !== 0) {
      return null;
    }
    // A selector that starts with a combinator applies it to the elements
    // found so far; a trailing one is malformed.
    if (combinator && !compound) {
      return null;
    }
    flush();
    return steps.length ? steps : null;
  }

  function isElement(node) {
    return node && node.nodeType === ELEMENT_NODE;
  }

  // One step of a split selector, from each node in `nodes`.
  function applyStep(nodes, step) {
    const out = [];
    const {combinator, compound} = step;
    for (const node of nodes) {
      if (node.nodeType === DOCUMENT_NODE) {
        // Only descendants make sense from the document itself.
        if (combinator === '' || combinator === ' ' || combinator === '>') {
          out.push(...node.querySelectorAll(compound));
        }
        continue;
      }
      if (!isElement(node)) {
        continue;
      }
      switch (combinator) {
        case '':
          if (node.matches(compound)) {
            out.push(node);
          }
          break;
        case ' ':
          out.push(...node.querySelectorAll(compound));
          break;
        case '>':
          for (const child of node.children) {
            if (child.matches(compound)) {
              out.push(child);
            }
          }
          break;
        case '+': {
          const next = node.nextElementSibling;
          if (next && next.matches(compound)) {
            out.push(next);
          }
          break;
        }
        case '~':
          for (let next = node.nextElementSibling; next;
               next = next.nextElementSibling) {
            if (next.matches(compound)) {
              out.push(next);
            }
          }
          break;
      }
    }
    return out;
  }

  // Each builder takes an operator's argument and returns a function from
  // a node list to a node list, or null when the argument is unusable.
  const OPERATORS = {
    'css-selector'(arg, isFirst) {
      if (isFirst) {
        return (nodes) => {
          const out = [];
          for (const node of nodes) {
            out.push(...node.querySelectorAll(arg));
          }
          return out;
        };
      }
      const steps = splitSteps(arg);
      if (!steps) {
        return null;
      }
      return (nodes) => steps.reduce(applyStep, nodes);
    },

    'has-text'(arg) {
      const test = textTest(arg, false);
      if (!test) {
        return null;
      }
      return (nodes) =>
          nodes.filter((node) => isElement(node) && test(node.textContent));
    },

    'min-text-length'(arg) {
      if (!/^\s*\d+\s*$/.test(arg)) {
        return null;
      }
      const min = parseInt(arg, 10);
      return (nodes) => nodes.filter(
          (node) => isElement(node) && node.textContent.length >= min);
    },

    // name or name=value, where either side may be quoted or a /regex/.
    'matches-attr'(arg) {
      let name = arg;
      let value = null;
      const nameRe = parseRegex(arg.trim());
      if (nameRe === null) {
        const eq = arg.indexOf('=');
        if (eq !== -1) {
          name = arg.slice(0, eq);
          value = arg.slice(eq + 1);
        }
      }
      const nameTest = textTest(unquote(name), true);
      const valueTest = value === null ? () => true :
                                         textTest(unquote(value), true);
      if (!nameTest || !valueTest || !unquote(name)) {
        return null;
      }
      return (nodes) => nodes.filter((node) => {
        if (!isElement(node)) {
          return false;
        }
        for (const attr of node.attributes) {
          if (nameTest(attr.name) && valueTest(attr.value)) {
            return true;
          }
        }
        return false;
      });
    },

    'matches-css'(arg, isFirst, env) {
      return matchesCss(arg, null, env);
    },
    'matches-css-before'(arg, isFirst, env) {
      return matchesCss(arg, '::before', env);
    },
    'matches-css-after'(arg, isFirst, env) {
      return matchesCss(arg, '::after', env);
    },

    // Keeps the nodes only when the page's path and query match.
    'matches-path'(arg, isFirst, env) {
      const test = textTest(arg, false);
      if (!test) {
        return null;
      }
      return (nodes) => {
        const location = env.win.location;
        return test(location.pathname + location.search) ? nodes : [];
      };
    },

    // A number climbs that many parents; anything else is a selector for
    // the nearest matching ancestor.
    upward(arg) {
      const trimmed = arg.trim();
      if (/^\d+$/.test(trimmed)) {
        const count = parseInt(trimmed, 10);
        if (count < 1 || count > MAX_UPWARD) {
          return null;
        }
        return (nodes) => {
          const out = [];
          for (const node of nodes) {
            let up = node;
            for (let i = 0; up && i < count; i++) {
              up = up.parentElement;
            }
            if (isElement(up)) {
              out.push(up);
            }
          }
          return out;
        };
      }
      if (!trimmed) {
        return null;
      }
      return (nodes) => {
        const out = [];
        for (const node of nodes) {
          const up = isElement(node) && node.parentElement ?
              node.parentElement.closest(trimmed) :
              null;
          if (up) {
            out.push(up);
          }
        }
        return out;
      };
    },

    xpath(arg, isFirst, env) {
      if (!arg.trim()) {
        return null;
      }
      return (nodes) => {
        const out = [];
        for (const node of nodes) {
          const result = env.doc.evaluate(
              arg, node, null, ORDERED_NODE_SNAPSHOT_TYPE, null);
          for (let i = 0; i < result.snapshotLength; i++) {
            const found = result.snapshotItem(i);
            if (isElement(found)) {
              out.push(found);
            }
          }
        }
        return out;
      };
    },
  };

  // "property: value", value plain or /regex/, matched against the
  // computed style of the element or of its pseudo element.
  function matchesCss(arg, pseudo, env) {
    const colon = arg.indexOf(':');
    if (colon <= 0) {
      return null;
    }
    const property = arg.slice(0, colon).trim().toLowerCase();
    const test = textTest(unquote(arg.slice(colon + 1)), true);
    if (!property || !test) {
      return null;
    }
    return (nodes) => nodes.filter((node) => {
      if (!isElement(node)) {
        return false;
      }
      const style = env.win.getComputedStyle(node, pseudo);
      return !!style && test(style.getPropertyValue(property));
    });
  }

  function unique(nodes) {
    return [...new Set(nodes)];
  }

  // Turns one filter (already parsed from JSON) into
  // {run(doc, win) -> Element[], action}, or null when any part of it is
  // not supported.
  function compile(filter) {
    if (!filter || !Array.isArray(filter.selector) ||
        filter.selector.length === 0) {
      return null;
    }
    let action = null;
    if (filter.action) {
      if (!ACTIONS.has(filter.action.type)) {
        return null;
      }
      if (filter.action.type !== 'remove' &&
          typeof filter.action.arg !== 'string') {
        return null;
      }
      action = {type: filter.action.type, arg: filter.action.arg};
    }
    const env = {doc: null, win: null};
    const tasks = [];
    for (let i = 0; i < filter.selector.length; i++) {
      const operator = filter.selector[i];
      if (!operator || typeof operator.arg !== 'string' ||
          !Object.hasOwn(OPERATORS, operator.type)) {
        return null;
      }
      const task = OPERATORS[operator.type](operator.arg, i === 0, env);
      if (!task) {
        return null;
      }
      tasks.push(task);
    }
    return {
      action,
      run(doc, win) {
        env.doc = doc;
        env.win = win;
        let nodes = [doc];
        for (const task of tasks) {
          nodes = unique(task(nodes));
          if (nodes.length === 0) {
            break;
          }
        }
        return nodes.filter(isElement);
      },
    };
  }

  return {compile, splitSteps};
})();
