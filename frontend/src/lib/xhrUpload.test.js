import test from 'node:test';
import assert from 'node:assert/strict';
import { xhrUpload, sendWithRefresh, UPLOAD_TIMEOUT_MS } from './xhrUpload.js';

// XHR tiruan: tes memicu event lewat inst.fire / inst.upload.fire.
function fakeXHR() {
  const insts = [];
  class X {
    constructor() { this.headers = {}; this.l = {}; this.upload = { l: {}, addEventListener: (t, f) => { this.upload.l[t] = f; } }; insts.push(this); }
    open(m, u) { this.method = m; this.url = u; }
    setRequestHeader(k, v) { this.headers[k] = v; }
    addEventListener(t, f) { this.l[t] = f; }
    send(b) { this.body = b; }
    fire(t) { this.l[t]?.(); }
  }
  return { X, insts };
}

test('xhrUpload: POST dengan header, progres hanya bila lengthComputable, onUploaded, jawaban JSON', async () => {
  const { X, insts } = fakeXHR();
  const seen = [];
  let uploaded = false;
  const p = xhrUpload({ url: '/u', body: 'B', headers: { A: '1' }, XHR: X, onProgress: v => seen.push(v), onUploaded: () => { uploaded = true; } });
  const x = insts[0];
  assert.equal(x.method, 'POST'); assert.equal(x.url, '/u'); assert.equal(x.headers.A, '1'); assert.equal(x.body, 'B');
  assert.equal(x.timeout, UPLOAD_TIMEOUT_MS);
  x.upload.l.progress({ lengthComputable: false, loaded: 1, total: 0 });
  x.upload.l.progress({ lengthComputable: true, loaded: 50, total: 200 });
  x.upload.l.load();
  x.status = 200; x.responseText = '{"merchant":"Indomaret"}'; x.fire('load');
  assert.deepEqual(await p, { status: 200, data: { merchant: 'Indomaret' }, timedOut: false });
  assert.deepEqual(seen, [25]);
  assert.equal(uploaded, true);
});

test('xhrUpload: error jaringan → status 0; timeout → timedOut; body bukan JSON → {}', async () => {
  const a = fakeXHR(); const pa = xhrUpload({ url: '/u', body: 'B', XHR: a.X }); a.insts[0].fire('error');
  assert.deepEqual(await pa, { status: 0, data: {}, timedOut: false });
  const b = fakeXHR(); const pb = xhrUpload({ url: '/u', body: 'B', XHR: b.X }); b.insts[0].fire('timeout');
  assert.deepEqual(await pb, { status: 0, data: {}, timedOut: true });
  const c = fakeXHR(); const pc = xhrUpload({ url: '/u', body: 'B', XHR: c.X });
  c.insts[0].status = 502; c.insts[0].responseText = '<html>'; c.insts[0].fire('load');
  assert.deepEqual(await pc, { status: 502, data: {}, timedOut: false });
});

test('sendWithRefresh: 401 + refresh berhasil → kirim ulang sekali', async () => {
  const results = [{ status: 401 }, { status: 200 }];
  let sends = 0;
  const r = await sendWithRefresh(async () => results[sends++], { hasRefreshToken: () => true, refresh: async () => true });
  assert.equal(sends, 2); assert.equal(r.status, 200);
});

test('sendWithRefresh: refresh gagal atau tanpa refresh token → 401 apa adanya', async () => {
  let sends = 0;
  const r1 = await sendWithRefresh(async () => { sends++; return { status: 401 }; }, { hasRefreshToken: () => true, refresh: async () => false });
  assert.equal(r1.status, 401); assert.equal(sends, 1);
  const r2 = await sendWithRefresh(async () => ({ status: 401 }), { hasRefreshToken: () => false, refresh: async () => { throw new Error('tidak boleh dipanggil'); } });
  assert.equal(r2.status, 401);
});
