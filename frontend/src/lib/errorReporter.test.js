import test from 'node:test';
import assert from 'node:assert/strict';
import { createErrorReporter, installErrorReporter, MAX_REPORTS } from './errorReporter.js';

const on = { error_reporting: { enabled: true, sample_rate: 1 } };

function setup(config = on, random = () => 0) {
  const sent = [];
  const report = createErrorReporter({ send: (r) => sent.push(r), getConfig: () => config, random });
  return { sent, report };
}

test('mati bila config tidak mengizinkan', () => {
  const { sent, report } = setup({ error_reporting: { enabled: false, sample_rate: 1 } });
  assert.equal(report({ message: 'x' }), false);
  assert.equal(sent.length, 0);
  assert.equal(setup(null).report({ message: 'x' }), false);
});

test('pesan sama sekali saja, maksimal MAX_REPORTS', () => {
  const { sent, report } = setup();
  report({ message: 'a' });
  report({ message: 'a' });
  for (let i = 0; i < 10; i += 1) report({ message: `m${i}` });
  assert.equal(sent.length, MAX_REPORTS);
  assert.equal(sent.filter(r => r.message === 'a').length, 1);
});

test('sample_rate dihormati', () => {
  const { sent, report } = setup({ error_reporting: { enabled: true, sample_rate: 0.5 } }, () => 0.9);
  assert.equal(report({ message: 'x' }), false);
  assert.equal(sent.length, 0);
});

test('memotong pesan dan stack panjang', () => {
  const { sent, report } = setup();
  report({ message: 'x'.repeat(5000), stack: 'y'.repeat(9000) });
  assert.equal(sent[0].message.length, 2000);
  assert.equal(sent[0].stack.length, 8000);
});

test('installErrorReporter menangkap error dan promise ditolak, lalu bisa dilepas', () => {
  const listeners = {};
  const target = {
    location: { href: 'https://jatahku.com/envelopes' },
    addEventListener: (t, f) => { listeners[t] = f; },
    removeEventListener: (t) => { delete listeners[t]; },
  };
  const got = [];
  const off = installErrorReporter(target, (r) => got.push(r));
  listeners.error({ message: 'Boom', error: { stack: 'at x' } });
  listeners.unhandledrejection({ reason: new Error('Nolak') });
  assert.deepEqual(got.map(r => [r.kind, r.message]), [['error', 'Boom'], ['unhandledrejection', 'Nolak']]);
  assert.equal(got[0].url, 'https://jatahku.com/envelopes');
  off();
  assert.deepEqual(Object.keys(listeners), []);
});
