// Kabel penangan "Bagikan ke Jatahku" di service worker (src/sw.js): file sw.js yang sebenarnya dimuat di Node dengan
// `self`, `caches`, dan `fetch` tiruan. `fetch` tiruan mencatat panggilan: tes ini tidak pernah menyentuh jaringan.
// (node --test menjalankan tiap file tes di prosesnya sendiri, jadi global tiruan ini tidak bocor ke tes lain.)
import { test } from 'node:test';
import assert from 'node:assert/strict';

const ORIGIN = 'https://jatahku.com';
const listeners = {};
const network = [];
const shellPuts = [];   // cache.put dari service worker: [kunci, status]
const shellReads = [];  // caches.match: kunci yang dibaca
const SHELL = new Response('<!doctype html><title>app shell</title>', { status: 200, headers: { 'Content-Type': 'text/html' } });
globalThis.self = {
  __WB_MANIFEST: [],
  location: { origin: ORIGIN },
  addEventListener: (type, fn) => { listeners[type] = fn; },
  skipWaiting: async () => {},
  clients: { claim: async () => {}, matchAll: async () => [] },
};
globalThis.caches = {
  open: async () => ({ put: async (key, res) => { shellPuts.push([key, res.status]); }, addAll: async () => {} }),
  match: async (key) => { shellReads.push(key); return key === '/index.html' ? SHELL : undefined; },
  keys: async () => [],
  delete: async () => true,
};
// Jawaban jaringan tiruan untuk navigasi; tes boleh menggantinya (respond = …).
let respond = () => new Response('<!doctype html>', { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
globalThis.fetch = async (request) => { network.push(request); return respond(request); };

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

// ── App shell offline (D4): hanya navigasi 2xx HTML yang disimpan sebagai /index.html ─────────────

const settle = () => new Promise(r => setTimeout(r, 5)); // cache.put berjalan tanpa ditunggu jawaban
const navigate = path => ({ method: 'GET', url: `${ORIGIN}${path}`, mode: 'navigate' });

test('sw (D4): navigasi 2xx HTML menjadi app shell offline (/index.html)', async () => {
  for (const [status, type] of [[200, 'text/html; charset=utf-8'], [200, 'text/html'], [203, 'TEXT/HTML']]) {
    shellPuts.length = 0;
    respond = () => new Response('<!doctype html>', { status, headers: { 'Content-Type': type } });
    const res = await dispatch(navigate('/bagikan?s=abc'));
    await settle();
    assert.equal(res.status, status);
    assert.deepEqual(shellPuts, [['/index.html', status]], `${status} ${type}`);
  }
});

test('sw (D4): navigasi 404/5xx/redirect atau bukan HTML tidak menimpa app shell, tetap diteruskan ke halaman', async () => {
  for (const [status, type] of [
    [404, 'text/html'], [500, 'text/html; charset=utf-8'], [502, 'text/html'], [503, 'text/html'], [302, 'text/html'],
    [200, 'application/json'], [200, 'text/plain'], [200, 'application/pdf'], [200, null], [204, null],
  ]) {
    shellPuts.length = 0;
    respond = () => {
      const body = status === 204 || status === 302 ? null : 'isi';
      const headers = type ? { 'Content-Type': type } : {};
      if (status === 302) headers.Location = '/login';
      const res = new Response(body, { status, headers });
      if (!type) res.headers.delete('Content-Type');
      return res;
    };
    const res = await dispatch(navigate('/bagikan'));
    await settle();
    assert.equal(res.status, status, 'jawaban jaringan diteruskan apa adanya');
    assert.deepEqual(shellPuts, [], `${status} ${type} tidak boleh disimpan sebagai app shell`);
  }
});

test('sw (D4): jaringan gagal → app shell dari cache (NetworkFirst tetap)', async () => {
  shellReads.length = 0;
  shellPuts.length = 0;
  respond = () => { throw new TypeError('Failed to fetch'); };
  const res = await dispatch(navigate('/transactions'));
  assert.equal(res, SHELL);
  assert.deepEqual(shellReads, ['/index.html']);
  assert.deepEqual(shellPuts, []);
});
