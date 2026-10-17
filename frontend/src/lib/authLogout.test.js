import { test } from 'node:test';
import assert from 'node:assert/strict';
import { revokeSession } from './authLogout.js';

test('mengirim refresh token ke /auth/logout dengan keepalive', () => {
  const calls = [];
  revokeSession('https://api.x', 'rt-1', (url, opts) => { calls.push([url, opts]); return Promise.resolve(); });
  assert.equal(calls.length, 1);
  const [url, opts] = calls[0];
  assert.equal(url, 'https://api.x/auth/logout');
  assert.equal(opts.method, 'POST');
  assert.equal(opts.keepalive, true);
  assert.deepEqual(JSON.parse(opts.body), { refresh_token: 'rt-1' });
});

test('tanpa refresh token tidak mengirim apa pun', () => {
  let n = 0;
  revokeSession('https://api.x', null, () => { n++; return Promise.resolve(); });
  assert.equal(n, 0);
});

test('jaringan gagal tidak melempar (logout lokal tetap jalan)', async () => {
  assert.doesNotThrow(() => revokeSession('https://api.x', 'rt', () => Promise.reject(new Error('offline'))));
  assert.doesNotThrow(() => revokeSession('https://api.x', 'rt', () => { throw new Error('sync'); }));
  await new Promise(r => setTimeout(r, 0)); // tidak ada unhandled rejection
});
