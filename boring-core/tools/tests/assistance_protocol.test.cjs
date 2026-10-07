// Copyright 2026 boring. BSD style license.
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const filename = path.join(__dirname, '../../components/boring/assistance/protocol.js');
const snapshot = {requestId: 'abc123', revision: 1, candidates: [{id:'c1',label:'Settings'}], blocks:[], coverage:{partial:false}};
function api() {
  assert.ok(fs.existsSync(filename), 'page-assistance protocol must exist');
  return vm.runInNewContext(fs.readFileSync(filename,'utf8'), {TextEncoder});
}
test('accepts only the current observed candidate', () => {
  assert.equal(api().parseGuidance('Open Settings.\nBORING_STEP abc123 1 c1', snapshot), 'c1');
});
test('rejects stale, unknown, duplicated, trailing, or oversized instructions', () => {
  for (const text of [
    'BORING_STEP wrong 1 c1', 'BORING_STEP abc123 2 c1', 'BORING_STEP abc123 1 c999',
    'BORING_STEP abc123 1 none', 'BORING_STEP abc123 1 c1\nBORING_STEP abc123 1 c1',
    'BORING_STEP abc123 1 c1\nextra', '<script>BORING_STEP abc123 1 c1</script>',
    '界'.repeat(12000)+'\nBORING_STEP abc123 1 c1'
  ]) assert.equal(api().parseGuidance(text,snapshot), null, text.slice(0,80));
});
test('prompt preserves the question and labels page content as untrusted', () => {
  const prompt=api().makePrompt('Where is Settings?',snapshot);
  assert.match(prompt,/Where is Settings\?/);
  assert.match(prompt,/untrusted/i);
  assert.match(prompt,/BORING_STEP abc123 1/);
  assert.match(prompt,/"label":"Settings"/);
});
test('rejects invalid request metadata and oversized questions', () => {
  assert.throws(()=>api().makePrompt('x',{...snapshot,requestId:'bad\nmarker'}));
  assert.throws(()=>api().makePrompt('x'.repeat(4097),snapshot));
  assert.throws(()=>api().makePrompt('',snapshot));
});
