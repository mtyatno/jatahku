import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  KOTAK_CHANGED, REFRESH_EVENTS, NO_COUNTS, SHARE_TIP, receiptInboxOn, pendingCountOf, bannerHiddenAt, bannerView,
  createPendingCounter, watchRefreshTriggers, announceKotakChange,
} from './pendingProofs.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

test('receiptInboxOn: banner dan tips hanya bila features.receipt_inbox === true', () => {
  assert.equal(receiptInboxOn({ features: { receipt_inbox: true } }), true);
  for (const config of [null, undefined, {}, { features: {} }, { features: null }, { features: { receipt_inbox: false } },
    { features: { receipt_inbox: 'true' } }, { features: { receipt_inbox: 1 } }, { features: { receipt_inbox: { web: true } } }]) {
    assert.equal(receiptInboxOn(config), false, JSON.stringify(config));
  }
});

test('pendingCountOf: `count` bilangan bulat ≥ 0 dari GET /kotak-struk/count; bentuk lain → null', () => {
  assert.equal(pendingCountOf({ count: 0 }), 0);
  assert.equal(pendingCountOf({ count: 7 }), 7);
  for (const data of [null, undefined, {}, { count: '3' }, { count: 2.5 }, { count: -1 }, { count: null }, { count: NaN },
    { count: Infinity }, { items: [] }, [3], 3, 'count']) {
    assert.equal(pendingCountOf(data), null, String(JSON.stringify(data)));
  }
});

test('bannerHiddenAt: /bagikan dan /bagikan/ (besar-kecil huruf seperti router); halaman lain tidak', () => {
  for (const p of ['/bagikan', '/bagikan/', '/Bagikan', '/BAGIKAN/']) assert.equal(bannerHiddenAt(p), true, p);
  for (const p of ['/', '/transactions', '/settings', '/bagikan/x', '/bagikan-lama', '/x/bagikan', '/bagikan//', '', null, undefined]) {
    assert.equal(bannerHiddenAt(p), false, String(p));
  }
});

test('bannerView: saklar mati, halaman /bagikan, atau tanpa hitungan → tidak tampil', () => {
  const counts = { unsent: 1, ready: 2 };
  assert.equal(bannerView({ enabled: false, pathname: '/', counts }), null);
  assert.equal(bannerView({ pathname: '/', counts }), null);
  assert.equal(bannerView({ enabled: true, pathname: '/bagikan', counts }), null);
  assert.equal(bannerView({ enabled: true, pathname: '/bagikan/', counts }), null);
  assert.equal(bannerView({ enabled: true, pathname: '/', counts: NO_COUNTS }), null);
  assert.equal(bannerView({ enabled: true, pathname: '/' }), null);
  assert.equal(bannerView(), null);
});

test('bannerView: teks dari pendingBannerText, kata tindakan dipisah untuk tampilan (teks utuh tetap sama)', () => {
  const views = [
    [{ unsent: 1, ready: 2 }, '1 bukti menunggu dikirim, 2 menunggu dicatat · Tinjau', '1 bukti menunggu dikirim, 2 menunggu dicatat', 'Tinjau'],
    [{ unsent: 2, ready: 0 }, '2 bukti menunggu dikirim · Kirim', '2 bukti menunggu dikirim', 'Kirim'],
    [{ unsent: 0, ready: 3 }, '3 bukti menunggu dicatat · Tinjau', '3 bukti menunggu dicatat', 'Tinjau'],
  ];
  for (const [counts, text, lead, action] of views) {
    const view = bannerView({ enabled: true, pathname: '/transactions', counts });
    assert.deepEqual(view, { text, lead, action });
    assert.equal(`${view.lead} · ${view.action}`, view.text);
  }
});

test('createPendingCounter: unsent = jumlah entri kotak share, ready = angka server', async () => {
  const seen = [];
  let entries = [{ id: 'a' }, { id: 'b' }];
  let ready = 3;
  const counter = createPendingCounter({
    loadUnsent: async () => entries,
    loadReady: async () => ready,
    onCounts: c => seen.push(c),
  });
  await counter.refresh();
  assert.deepEqual(seen, [{ unsent: 2, ready: 3 }]);
  entries = [];
  ready = 0;
  await counter.refresh();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 0 });
});

test('createPendingCounter: server gagal (null) → angka terakhir yang diketahui; awalnya 0', async () => {
  const seen = [];
  let ready = null;
  const counter = createPendingCounter({ loadUnsent: async () => [], loadReady: async () => ready, onCounts: c => seen.push(c) });
  await counter.refresh();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 0 });
  ready = 4;
  await counter.refresh();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 4 });
  ready = null;
  await counter.refresh();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 4 });
  ready = 1;
  await counter.refresh();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 1 });
});

test('createPendingCounter: galat IndexedDB atau server (ditolak / melempar) tidak pernah lolos', async () => {
  const seen = [];
  const rejecting = createPendingCounter({
    loadUnsent: () => Promise.reject(new Error('IndexedDB rusak')),
    loadReady: () => Promise.reject(new Error('jaringan')),
    onCounts: c => seen.push(c),
  });
  await rejecting.refresh();
  assert.deepEqual(seen, [{ unsent: 0, ready: 0 }]);
  const throwing = createPendingCounter({
    loadUnsent: () => { throw new Error('sinkron'); },
    loadReady: () => { throw new Error('sinkron'); },
    onCounts: c => seen.push(c),
  });
  await throwing.refresh();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 0 });
  const odd = createPendingCounter({ loadUnsent: async () => null, loadReady: async () => '5', onCounts: c => seen.push(c) });
  await odd.refresh();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 0 });
  const notList = createPendingCounter({ loadUnsent: async () => ({ length: 4 }), loadReady: async () => 1.5, onCounts: c => seen.push(c) });
  await notList.refresh();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 0 });
});

test('createPendingCounter: jawaban hitung ulang yang lebih lama tidak pernah menimpa yang lebih baru', async () => {
  const seen = [];
  const pending = [];
  let unsent = [{ id: 'lama' }];
  const counter = createPendingCounter({
    loadUnsent: async () => unsent,
    loadReady: () => { const d = deferred(); pending.push(d); return d.promise; },
    onCounts: c => seen.push(c),
  });
  const older = counter.refresh();
  unsent = [];
  const newer = counter.refresh();
  pending[1].resolve(2);   // yang baru selesai lebih dulu
  await newer;
  pending[0].resolve(5);   // jawaban lama menyusul: dibuang
  await older;
  assert.deepEqual(seen, [{ unsent: 0, ready: 2 }]);

  // Urutan biasa (yang lama selesai lebih dulu): keduanya dipakai, yang baru terakhir.
  const a = counter.refresh();
  const b = counter.refresh();
  pending[2].resolve(7);
  await a;
  pending[3].resolve(1);
  await b;
  assert.deepEqual(seen.slice(1), [{ unsent: 0, ready: 7 }, { unsent: 0, ready: 1 }]);

  // Yang baru gagal (null), yang lama menyusul dengan angka: angka server itu tetap lebih baru dari angka yang tampil
  // (dimulai sesudahnya) → dipakai; jumlah lokal dari jawaban lama tetap dibuang.
  unsent = [{ id: 'x' }];
  const c = counter.refresh();
  unsent = [];
  const d = counter.refresh();
  pending[5].resolve(null);
  await d;
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 1 });
  pending[4].resolve(9);
  await c;
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 9 });
  assert.equal(seen.length, 5);
  // Lalu jawaban yang lebih lama lagi dari angka itu tidak pernah menimpanya.
  const e = counter.refresh();
  const f = counter.refresh();
  pending[7].resolve(6);
  await f;
  pending[6].resolve(8);
  await e;
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 6 });
  assert.equal(seen.length, 6);
});

test('createPendingCounter: sesudah stop() tidak ada hasil, permintaan, atau baca IndexedDB lagi', async () => {
  const seen = [];
  let unsentLoads = 0;
  let readyLoads = 0;
  const d = deferred();
  const counter = createPendingCounter({
    loadUnsent: async () => { unsentLoads += 1; return [{ id: 'x' }]; },
    loadReady: () => { readyLoads += 1; return d.promise; },
    onCounts: c => seen.push(c),
  });
  const inFlight = counter.refresh();
  counter.stop();
  d.resolve(3);
  await inFlight;
  await counter.refresh();
  assert.deepEqual(seen, []);
  assert.deepEqual([unsentLoads, readyLoads], [1, 1]);
});

test('watchRefreshTriggers: online, jatahku:txn-added, jatahku:kotak-changed, visibilitychange saat terlihat; pelepas mencabut semuanya', () => {
  assert.deepEqual([...REFRESH_EVENTS], ['online', 'jatahku:txn-added', 'jatahku:kotak-changed']);
  const win = new EventTarget();
  const doc = new EventTarget();
  doc.visibilityState = 'hidden';
  let n = 0;
  const args = [];
  const unwatch = watchRefreshTriggers((...a) => { n += 1; args.push(a.length); }, { win, doc });
  win.dispatchEvent(new Event('online'));
  win.dispatchEvent(new Event('jatahku:txn-added'));
  win.dispatchEvent(new Event(KOTAK_CHANGED));
  assert.equal(n, 3);
  doc.dispatchEvent(new Event('visibilitychange'));   // tersembunyi: tidak dihitung ulang
  assert.equal(n, 3);
  doc.visibilityState = 'visible';
  doc.dispatchEvent(new Event('visibilitychange'));
  assert.equal(n, 4);
  win.dispatchEvent(new Event('jatahku:offline-queue'));   // bukan pemicu
  win.dispatchEvent(new Event('visibilitychange'));        // hanya di document
  assert.equal(n, 4);
  assert.deepEqual(args, [0, 0, 0, 0]);   // refresh dipanggil tanpa objek event
  unwatch();
  for (const name of REFRESH_EVENTS) win.dispatchEvent(new Event(name));
  doc.dispatchEvent(new Event('visibilitychange'));
  assert.equal(n, 4);
});

test('announceKotakChange: event jatahku:kotak-changed hanya sesudah jawaban 2xx', () => {
  assert.equal(KOTAK_CHANGED, 'jatahku:kotak-changed');
  const win = new EventTarget();
  let n = 0;
  win.addEventListener(KOTAK_CHANGED, () => { n += 1; });
  assert.equal(announceKotakChange({ ok: true, status: 200, data: {} }, win), true);
  assert.equal(n, 1);
  for (const res of [{ ok: false, status: 409 }, { ok: false, status: 404 }, { ok: false, status: 0 }, { status: 200 }, null, undefined]) {
    assert.equal(announceKotakChange(res, win), false, JSON.stringify(res));
  }
  assert.equal(n, 1);
});

test('SHARE_TIP: teks tips Settings persis dari rencana', () => {
  assert.equal(SHARE_TIP, 'Bagikan bukti bayar ke Jatahku: di Android, pasang Jatahku dari browser lalu pilih Jatahku di menu '
    + 'Bagikan. Di iPhone, bagikan bukti ke bot Telegram Jatahku.');
});
