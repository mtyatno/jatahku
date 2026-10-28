// Kabel penangan "Bagikan ke Jatahku" di service worker (src/sw.js): file sw.js yang sebenarnya dimuat di Node dengan
// `self`, `caches`, dan `fetch` tiruan. `fetch` tiruan mencatat panggilan: tes ini tidak pernah menyentuh jaringan.
// (node --test menjalankan tiap file tes di prosesnya sendiri, jadi global tiruan ini tidak bocor ke tes lain.)
import { test } from 'node:test';
import assert from 'node:assert/strict';

const ORIGIN = 'https://jatahku.com';
const listeners = {};
const network = [];
globalThis.self = {
  __WB_MANIFEST: [],
  location: { origin: ORIGIN },
  addEventListener: (type, fn) => { listeners[type] = fn; },
  skipWaiting: async () => {},
  clients: { claim: async () => {}, matchAll: async () => [] },
};
globalThis.caches = {
  open: async () => ({ put: async () => {}, addAll: async () => {} }),
  match: async () => undefined,
  keys: async () => [],
  delete: async () => true,
};
globalThis.fetch = async (request) => { network.push(request); return new Response('<!doctype html>', { status: 200 }); };

await import('../sw.js');

// Satu event fetch → janji jawaban service worker, atau null bila tidak dijawab (browser meneruskan ke jaringan).
function dispatch(request) {
  let answered = null;
  listeners.fetch({ request, respondWith: (p) => { answered = Promise.resolve(p); } });
  return answered;
}

const post = (url, body, headers) => new Request(url, { method: 'POST', body, headers });

test('sw: POST /bagikan dijawab service worker dengan 303 ke /bagikan?s=<batch>, tanpa jaringan', async () => {
  network.length = 0;
  const fd = new FormData();
  fd.append('files', new File(['%PDF-1.4'], 'bukti.pdf', { type: 'application/pdf' }));
  fd.append('text', 'Transfer berhasil Rp150.000');
  const answered = dispatch(post(`${ORIGIN}/bagikan`, fd));
  assert.ok(answered, 'POST /bagikan harus dijawab service worker');
  const res = await answered;
  assert.equal(res.status, 303);
  assert.match(res.headers.get('location'), /^\/bagikan\?s=[\w-]+$/);
  assert.equal(network.length, 0);
});

test('sw: form share rusak → 303 ke /bagikan?err=baca', async () => {
  const answered = dispatch(post(`${ORIGIN}/bagikan`, 'rusak', { 'Content-Type': 'multipart/form-data; boundary=zzz' }));
  assert.ok(answered, 'POST /bagikan harus dijawab service worker');
  const res = await answered;
  assert.equal(res.status, 303);
  assert.equal(res.headers.get('location'), '/bagikan?err=baca');
});

test('sw: POST lain, metode lain, dan host API tidak dicegat', () => {
  network.length = 0;
  for (const request of [
    post(`${ORIGIN}/transactions`, '{}'),
    post(`${ORIGIN}/bagikan/lain`, '{}'),
    post(`${ORIGIN}/`, '{}'),
    post('https://api.jatahku.com/bagikan', new FormData()),
    post('https://api.jatahku.com/kotak-struk/', new FormData()),
    new Request(`${ORIGIN}/bagikan`, { method: 'PUT', body: 'x' }),
    { method: 'GET', url: 'https://api.jatahku.com/auth/me', mode: 'cors' },
  ]) {
    assert.equal(dispatch(request), null, `${request.method} ${request.url}`);
  }
  assert.equal(network.length, 0);
});

test('sw: GET /bagikan?s=… tetap navigasi biasa (jaringan dulu), bukan penangan share', async () => {
  network.length = 0;
  const request = { method: 'GET', url: `${ORIGIN}/bagikan?s=abc`, mode: 'navigate' };
  const answered = dispatch(request);
  assert.ok(answered);
  const res = await answered;
  assert.equal(res.status, 200);
  assert.deepEqual(network, [request]);
});
