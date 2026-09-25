// Copyright 2026 boring. BSD style license.
//
// Helper for get_ubo_resources.py. Not run on its own.
//
// Loads uBlock Origin's own scriptlet and redirect modules from an
// unpacked source tree and prints what they declare as JSON, so the
// Python side never has to parse JavaScript with regular expressions.
// uBO does exactly this itself when it loads its resources
// (src/js/redirect-engine.js, loadBuiltinResources): it imports the
// module and keeps each scriptlet's fn.toString().
//
// Usage: node ubo_resources_dump.mjs <uBlock source root>
//
// Prints {"scriptlets": [...], "redirects": [...]} on stdout.

import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[2];
if (!root) {
  console.error('usage: node ubo_resources_dump.mjs <uBlock source root>');
  process.exit(2);
}

function moduleUrl(...parts) {
  return pathToFileURL(path.join(root, ...parts)).href;
}

const scriptletModule =
    await import(moduleUrl('src', 'js', 'resources', 'scriptlets.js'));
const redirectModule =
    await import(moduleUrl('src', 'js', 'redirect-resources.js'));

if (!Array.isArray(scriptletModule.builtinScriptlets)) {
  console.error('scriptlets.js no longer exports a builtinScriptlets array');
  process.exit(1);
}
if (!(redirectModule.default instanceof Map)) {
  console.error('redirect-resources.js no longer exports a default Map');
  process.exit(1);
}

const scriptlets = scriptletModule.builtinScriptlets.map(entry => {
  if (typeof entry.fn !== 'function') {
    throw new TypeError(`scriptlet ${entry.name} has no function`);
  }
  // Every field is passed on as it is, apart from the function, which
  // becomes its source text. The Python side decides what it knows.
  const out = {};
  for (const [key, value] of Object.entries(entry)) {
    out[key] = key === 'fn' ? entry.fn.toString() : value;
  }
  return out;
});

const redirects = [];
for (const [name, details] of redirectModule.default) {
  redirects.push([name, details || {}]);
}

process.stdout.write(JSON.stringify({ scriptlets, redirects }));
