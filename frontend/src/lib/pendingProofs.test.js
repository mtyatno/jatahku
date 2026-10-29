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
const pushDeferred = (list) => { const d = deferred(); list.push(d); return d.promise; };
const never = () => new Promise(() => {});
const flush = () => new Promise(r => setTimeout(r, 0));
const entriesOf = k => Array.from({ length: k }, (_, i) => ({ id: `e${i}` }));

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
  assert.deepEqual(seen.at(-1), { unsent: 2, ready: 3 });
  entries = [];
  ready = 0;
  await counter.refresh();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 0 });
});

test('createPendingCounter: tiap angka tampil begitu bacaannya sendiri selesai, tanpa menunggu yang lain', async () => {
  const seen = [];
  const reads = { unsent: [], ready: [] };
  const counter = createPendingCounter({
    loadUnsent: () => pushDeferred(reads.unsent),
    loadReady: () => pushDeferred(reads.ready),
    onCounts: c => seen.push(c),
  });
  const first = counter.refresh();
  reads.unsent[0].resolve(entriesOf(2));   // IndexedDB lebih dulu: jumlah lokal langsung tampil
  await flush();
  assert.deepEqual(seen, [{ unsent: 2, ready: 0 }]);
  reads.ready[0].resolve(3);
  await first;
  assert.deepEqual(seen.at(-1), { unsent: 2, ready: 3 });
  const second = counter.refresh();
  reads.ready[1].resolve(5);               // server lebih dulu: angka server langsung tampil
  await flush();
  assert.deepEqual(seen.at(-1), { unsent: 2, ready: 5 });
  reads.unsent[1].resolve(entriesOf(1));
  await second;
  assert.deepEqual(seen.at(-1), { unsent: 1, ready: 5 });
});

test('createPendingCounter: COUNT yang tidak pernah menjawab tidak menahan jumlah lokal; angka server terakhir tetap', async () => {
  const seen = [];
  let entries = entriesOf(2);
  let hang = false;
  const counter = createPendingCounter({
    loadUnsent: async () => entries,
    loadReady: () => (hang ? never() : Promise.resolve(3)),
    onCounts: c => seen.push(c),
  });
  await counter.refresh();
  assert.deepEqual(seen.at(-1), { unsent: 2, ready: 3 });
  hang = true;   // koneksi macet (sinyal ada, data tidak); api.request tanpa batas waktu
  entries = entriesOf(4);
  counter.refresh();
  counter.refresh();
  await flush();
  assert.deepEqual(seen.at(-1), { unsent: 4, ready: 3 });
  // Macet sejak awal (dipasang + online + pindah halaman): jumlah lokal tetap tampil.
  const fresh = [];
  const stuck = createPendingCounter({ loadUnsent: async () => entriesOf(2), loadReady: never, onCounts: c => fresh.push(c) });
  stuck.refresh();
  stuck.refresh();
  stuck.refresh();
  await flush();
  assert.deepEqual(fresh.at(-1), { unsent: 2, ready: 0 });
  assert.equal(bannerView({ enabled: true, pathname: '/', counts: fresh.at(-1) }).text, '2 bukti menunggu dikirim · Kirim');
});

test('createPendingCounter: IndexedDB yang tidak pernah selesai tidak menahan angka server', async () => {
  const seen = [];
  let ready = 3;
  const counter = createPendingCounter({ loadUnsent: never, loadReady: async () => ready, onCounts: c => seen.push(c) });
  counter.refresh();
  await flush();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 3 });
  ready = 5;
  counter.refresh();   // pembukaan IndexedDB dipakai bersama satu halaman: bacaan berikutnya juga macet
  await flush();
  assert.deepEqual(seen.at(-1), { unsent: 0, ready: 5 });
  assert.equal(bannerView({ enabled: true, pathname: '/', counts: seen.at(-1) }).text, '5 bukti menunggu dicatat · Tinjau');
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

// Hitung ulang ke-k (mulai 1) membaca k entri lokal dan angka server 10·k, jadi asal tiap angka yang tampil terbaca dari
// nilainya: "angka lama tidak pernah tampil sesudah yang lebih baru" = deret yang tampil tidak pernah turun.
test('createPendingCounter: jawaban hitung ulang yang lebih lama tidak pernah menimpa yang lebih baru', async () => {
  const seen = [];
  const reads = { unsent: [], ready: [] };
  const counter = createPendingCounter({
    loadUnsent: () => pushDeferred(reads.unsent),
    loadReady: () => pushDeferred(reads.ready),
    onCounts: c => seen.push(c),
  });
  const local = k => reads.unsent[k - 1].resolve(entriesOf(k));
  const server = (k, value = 10 * k) => reads.ready[k - 1].resolve(value);

  // 1 dan 2 bertumpuk; 2 selesai lebih dulu (kedua angkanya), jawaban 1 menyusul dan dibuang.
  const r1 = counter.refresh();
  const r2 = counter.refresh();
  local(2);
  server(2);
  await r2;
  assert.deepEqual(seen.at(-1), { unsent: 2, ready: 20 });
  local(1);
  server(1);
  await r1;
  assert.deepEqual(seen.at(-1), { unsent: 2, ready: 20 });

  // 3 lalu 4 selesai berurutan: keduanya dipakai, yang baru terakhir.
  const r3 = counter.refresh();
  const r4 = counter.refresh();
  local(3);
  server(3);
  await r3;
  assert.deepEqual(seen.at(-1), { unsent: 3, ready: 30 });
  local(4);
  server(4);
  await r4;
  assert.deepEqual(seen.at(-1), { unsent: 4, ready: 40 });

  // 5 dan 6: COUNT 6 gagal (null) → angka server terakhir tetap; COUNT 5 menyusul dengan angka yang lebih baru dari
  // yang tampil (40) → dipakai; jumlah lokal 5 lebih lama dari 6 → dibuang.
  const r5 = counter.refresh();
  const r6 = counter.refresh();
  local(6);
  server(6, null);
  await r6;
  assert.deepEqual(seen.at(-1), { unsent: 6, ready: 40 });
  local(5);
  server(5);
  await r5;
  assert.deepEqual(seen.at(-1), { unsent: 6, ready: 50 });

  // 7 dan 8 bercampur: lokal 8, server 7, server 8, lalu lokal 7 (dibuang). Tiap angka tampil begitu terbaca.
  const r7 = counter.refresh();
  const r8 = counter.refresh();
  local(8);
  await flush();
  assert.deepEqual(seen.at(-1), { unsent: 8, ready: 50 });
  server(7);
  await flush();
  assert.deepEqual(seen.at(-1), { unsent: 8, ready: 70 });
  server(8);
  local(7);
  await Promise.all([r7, r8]);
  assert.deepEqual(seen.at(-1), { unsent: 8, ready: 80 });

  const rising = xs => xs.every((x, i) => i === 0 || x >= xs[i - 1]);
  assert.ok(rising(seen.map(c => c.unsent)) && rising(seen.map(c => c.ready)), JSON.stringify(seen));
  assert.ok(!seen.some(c => [1, 5, 7].includes(c.unsent) || c.ready === 10), JSON.stringify(seen));
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
