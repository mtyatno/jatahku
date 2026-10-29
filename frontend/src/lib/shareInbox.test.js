import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  SHARE_DB, SHARE_STORE, MAX_FILES, shareStore, saveShare, handleShareTarget, nextToUpload, uploadFormFor,
  clearShares, clearSharesOnLogout, isShareTarget,
  uploadOutcome, needsPolling, POLL_MS, POLL_LIMIT_MS, SHARE_TEXT, offlineBannerText, shareFlag, sharePageMode,
  discardBatch, runSharePage, mergeItems, pollTargets, fetchPendingDetails, pageFinished, pageNotices, dropLine,
  shareUploadTimeoutMs, pageView, serialRuns, createPoller, sniffShareType, oversizeMessage,
  SHARE_OWNER_KEY, shareOwnerAction, ensureShareOwner, ownerGate, ownedShares, keptEntries, discardKept, withTimeout,
  pageReads, CONFIG_WAIT_MS, READ_WAIT_MS,
} from './shareInbox.js';
import { DB_NAME as OFFLINE_DB } from './offlineSync.js';
import { DEFAULT_CONFIG } from './appConfig.js';
import { uploadTimeoutMs } from './receiptProgress.js';

function memStore() {
  const map = new Map();
  return {
    map, all: async () => [...map.values()], put: async e => { map.set(e.id, e); }, del: async id => { map.delete(id); }, clear: async () => map.clear(),
    touch: async (id, patch) => { if (!map.has(id)) return false; map.set(id, { ...map.get(id), ...patch }); return true; },
  };
}
let n = 0; const newId = () => `id-${++n}`;

const form = (fields = {}, files = []) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  for (const f of files) fd.append('files', f);
  return fd;
};
const shareRequest = body => new Request('https://jatahku.com/bagikan', { method: 'POST', body });

// Teks yang tersimpan dari satu share (null bila tidak ada entri teks).
async function savedText(fields) {
  const store = memStore();
  await saveShare(store, form(fields), { now: () => 1, newId });
  const entries = await store.all();
  assert.ok(entries.length <= 1);
  return entries[0]?.text ?? null;
}

// ── Tes dari plan (D2: respons dibangun dengan status 303 + header Location) ─────────────────────

test('saveShare: file (maks 10) dan teks disimpan dengan batch yang sama', async () => {
  const store = memStore(); const fd = new FormData();
  for (let i = 0; i < 12; i++) fd.append('files', new Blob(['x'], { type: 'image/jpeg' }), `b${i}.jpg`);
  fd.append('text', 'Transfer berhasil Rp150.000');
  const batch = await saveShare(store, fd, { now: () => 5, newId });
  const all = await store.all();
  assert.equal(all.filter(e => e.blob).length, MAX_FILES);
  assert.equal(all.find(e => e.text).text, 'Transfer berhasil Rp150.000');
  assert.ok(all.every(e => e.batchId === batch && e.createdAt === 5));
});

test('handleShareTarget: 303 ke /bagikan dengan batch; form rusak → err', async () => {
  const fd = new FormData(); fd.append('files', new Blob(['%PDF'], { type: 'application/pdf' }), 'a.pdf');
  const res = await handleShareTarget(new Request('https://jatahku.com/bagikan', { method: 'POST', body: fd }), { store: memStore(), newId });
  assert.equal(res.status, 303);
  assert.match(res.headers.get('location'), /\/bagikan\?s=/);
  const bad = await handleShareTarget({ formData: async () => { throw new Error('x'); } }, { store: memStore(), newId });
  assert.match(bad.headers.get('location'), /err=baca/);
});

test('uploadFormFor dan nextToUpload', async () => {
  const fd = uploadFormFor({ id: 'e1', name: 'a.pdf', type: 'application/pdf', blob: new Blob(['%PDF']) }, { wait: 10 });
  assert.deepEqual([fd.get('source'), fd.get('upload_id'), fd.get('wait')], ['pwa_share', 'e1', '10']);
  assert.equal(fd.get('file').name, 'a.pdf');
  assert.equal(nextToUpload([{ id: 'b', createdAt: 2 }, { id: 'a', createdAt: 1 }]).id, 'a');
  const store = memStore(); await store.put({ id: 'x' }); await clearShares(store); assert.equal((await store.all()).length, 0);
});

// ── Bentuk entri dan batas ────────────────────────────────────────────────────────────────────────

test('handleShareTarget: Location relatif persis /bagikan?s=<batch> (tanpa Response.redirect), batch = entri tersimpan', async () => {
  const store = memStore();
  const fd = form({ text: 'QRIS Rp25.000' }, [new File(['\xff\xd8\xff'], 'q.jpg', { type: 'image/jpeg' })]);
  const res = await handleShareTarget(shareRequest(fd), { store, now: () => 7, newId });
  const entries = [...store.map.values()];
  assert.equal(entries.length, 2);
  const { batchId } = entries[0];
  assert.equal(res.status, 303);
  assert.equal(res.headers.get('location'), `/bagikan?s=${batchId}`);
  assert.equal(res.body, null);
  assert.ok(entries.every(e => e.batchId === batchId && e.createdAt === 7 && e.id !== batchId));
});

test('saveShare: entri file {id, batchId, name, type, blob, createdAt} dan entri teks {id, batchId, text, type text/plain}', async () => {
  const store = memStore();
  const file = new File(['%PDF-1.4'], 'mutasi.pdf', { type: 'application/pdf' });
  const batch = await saveShare(store, form({ text: 'Transfer berhasil' }, [file]), { now: () => 9, newId });
  const [f, t] = await store.all();
  assert.equal(f.batchId, batch);
  assert.deepEqual([f.name, f.type, f.blob, f.createdAt, 'text' in f], ['mutasi.pdf', 'application/pdf', file, 9, false]);
  assert.deepEqual([t.text, t.type, t.createdAt, 'blob' in t], ['Transfer berhasil', 'text/plain', 9, false]);
  assert.notEqual(f.id, t.id);
});

test('MAX_FILES = 10 (sama dengan MAX_FILES_PER_SHARE server): 10 file pertama disimpan, sisanya diabaikan', async () => {
  assert.equal(MAX_FILES, 10);
  const store = memStore();
  const files = Array.from({ length: 12 }, (_, i) => new File([`isi ${i}`], `b${i}.jpg`, { type: 'image/jpeg' }));
  await saveShare(store, form({}, files), { now: () => 1, newId });
  const saved = (await store.all()).filter(e => e.blob);
  assert.deepEqual(saved.map(e => e.name).sort(), ['b0.jpg', 'b1.jpg', 'b2.jpg', 'b3.jpg', 'b4.jpg', 'b5.jpg', 'b6.jpg', 'b7.jpg', 'b8.jpg', 'b9.jpg']);
  assert.equal(await saved.find(e => e.name === 'b9.jpg').blob.text(), 'isi 9');
});

test('saveShare: nilai bukan file dan file kosong (0 byte) di "files" diabaikan', async () => {
  const store = memStore();
  const fd = form({}, [new File([], '', { type: 'application/octet-stream' }), new File(['%PDF-1.4'], 'a.pdf', { type: 'application/pdf' })]);
  fd.append('files', 'bukan file');
  await saveShare(store, fd, { now: () => 1, newId });
  assert.deepEqual((await store.all()).map(e => e.name), ['a.pdf']);
});

test('saveShare: id entri dari newRef (bawaan) unik dan ≤ 64 karakter (batas upload_id server)', async () => {
  const store = memStore();
  const batch = await saveShare(store, form({ text: 'Rp1.000' }, [new File(['x'], 'a.jpg'), new File(['y'], 'b.jpg')]));
  const ids = (await store.all()).map(e => e.id);
  assert.equal(new Set([...ids, batch]).size, 4);
  assert.ok(ids.every(id => typeof id === 'string' && id.length > 0 && id.length <= 64));
});

// ── Teks share ────────────────────────────────────────────────────────────────────────────────────

test('teks share: judul lalu teks, digabung dengan baris baru; url hanya bila tidak ada teks lain', async () => {
  assert.equal(await savedText({ title: 'Bukti Transfer', text: 'Transfer berhasil Rp150.000', url: 'https://x.id/r/1' }),
    'Bukti Transfer\nTransfer berhasil Rp150.000');
  assert.equal(await savedText({ text: 'Transfer berhasil', url: 'https://x.id/r/1' }), 'Transfer berhasil');
  assert.equal(await savedText({ title: 'Struk', url: 'https://x.id/r/1' }), 'Struk');
  assert.equal(await savedText({ url: 'https://x.id/r/1' }), 'https://x.id/r/1');
});

test('teks share: spasi di tepi dibuang, kolom kosong diabaikan, judul yang sama dengan teks tidak diulang', async () => {
  assert.equal(await savedText({ text: '  Transfer berhasil\nRp25.000 \n' }), 'Transfer berhasil\nRp25.000');
  assert.equal(await savedText({ title: '  ', text: 'Rp25.000', url: ' ' }), 'Rp25.000');
  assert.equal(await savedText({ title: 'Rp25.000', text: 'Rp25.000' }), 'Rp25.000');
  assert.equal(await savedText({ title: ' ', text: '\n', url: '' }), null);
  assert.equal(await savedText({ title: 'Bukti\r\n', text: 'Transfer berhasil\r\nRp150.000\rRef 1' }), 'Bukti\nTransfer berhasil\nRp150.000\nRef 1');
});

test('share kosong (tanpa file dan teks): tidak menyimpan apa pun, tetap mengembalikan batch dan 303', async () => {
  const store = memStore();
  const batch = await saveShare(store, form({ title: ' ', text: '', url: '' }), { now: () => 1, newId });
  assert.equal(typeof batch, 'string');
  assert.ok(batch.length > 0);
  assert.equal(store.map.size, 0);
  const res = await handleShareTarget(shareRequest(new FormData()), { store, newId });
  assert.equal(res.status, 303);
  assert.match(res.headers.get('location'), /^\/bagikan\?s=id-\d+$/);
  assert.equal(store.map.size, 0);
});

// ── Kegagalan ─────────────────────────────────────────────────────────────────────────────────────

test('handleShareTarget: gagal menyimpan → err=baca dan entri batch itu dibuang (tidak setengah tersimpan)', async () => {
  const store = memStore(); let puts = 0;
  const failing = { ...store, put: async e => { if (++puts === 2) throw new Error('QuotaExceededError'); return store.put(e); } };
  const fd = form({ text: 'Rp1' }, [new File(['a'], 'a.jpg', { type: 'image/jpeg' }), new File(['b'], 'b.jpg', { type: 'image/jpeg' })]);
  const res = await handleShareTarget(shareRequest(fd), { store: failing, newId });
  assert.equal(res.status, 303);
  assert.equal(res.headers.get('location'), '/bagikan?err=baca');
  assert.equal(store.map.size, 0);
});

test('handleShareTarget: tidak pernah melempar (request rusak, store hilang)', async () => {
  for (const [request, opts] of [[undefined, { store: memStore(), newId }], [shareRequest(form({ text: 'x' })), {}]]) {
    const res = await handleShareTarget(request, opts);
    assert.equal(res.status, 303);
    assert.equal(res.headers.get('location'), '/bagikan?err=baca');
  }
});

// ── Urutan unggah dan form unggah ─────────────────────────────────────────────────────────────────

test('nextToUpload: share tertua dulu; dalam satu share urutan dibagikan (file lalu teks); kosong → null', async () => {
  assert.equal(nextToUpload([]), null);
  assert.equal(nextToUpload(null), null);
  const store = memStore();
  await saveShare(store, form({ text: 'lama' }), { now: () => 100, newId });
  const files = ['c.jpg', 'a.jpg', 'b.jpg'].map(name => new File([name], name, { type: 'image/jpeg' }));
  await saveShare(store, form({ text: 'baru' }, files), { now: () => 200, newId });
  const order = [];
  for (let next; (next = nextToUpload((await store.all()).reverse())); await store.del(next.id)) {
    order.push(next.name || next.text);
  }
  assert.deepEqual(order, ['lama', 'c.jpg', 'a.jpg', 'b.jpg', 'baru']);
});

test('uploadFormFor: tepat satu dari file/teks (server menolak keduanya), wait bawaan 10, nama cadangan', () => {
  const text = uploadFormFor({ id: 't1', batchId: 'b', text: 'Transfer berhasil', type: 'text/plain', createdAt: 1 });
  assert.deepEqual([text.get('text'), text.has('file')], ['Transfer berhasil', false]);
  assert.deepEqual([text.get('source'), text.get('upload_id'), text.get('wait')], ['pwa_share', 't1', '10']);
  const file = uploadFormFor({ id: 'f1', name: '', type: 'image/png', blob: new Blob(['\x89PNG'], { type: 'image/png' }) }, { wait: 0 });
  assert.equal(file.has('text'), false);
  assert.deepEqual([file.get('file').name, file.get('file').type, file.get('wait')], ['bukti', 'image/png', '0']);
});

// ── Service worker: hanya POST /bagikan di origin aplikasi (D6) ───────────────────────────────────

test('isShareTarget: hanya POST /bagikan di origin aplikasi', () => {
  const O = 'https://jatahku.com';
  assert.equal(isShareTarget({ method: 'POST', url: `${O}/bagikan` }, O), true);
  assert.equal(isShareTarget({ method: 'POST', url: `${O}/bagikan?x=1` }, O), true);
  for (const [method, url] of [
    ['GET', `${O}/bagikan`], ['PUT', `${O}/bagikan`], ['POST', `${O}/bagikan/`], ['POST', `${O}/bagikan/x`],
    ['POST', `${O}/transactions`], ['POST', `${O}/`], ['POST', 'https://api.jatahku.com/bagikan'],
    ['POST', 'http://jatahku.com/bagikan'], ['POST', 'bukan url'],
  ]) {
    assert.equal(isShareTarget({ method, url }, O), false, `${method} ${url}`);
  }
  assert.equal(isShareTarget(undefined, O), false);
});

// ── Logout (D3): hanya logout yang diminta user mengosongkan kotak share ─────────────────────────

test('clearSharesOnLogout: refresh ditolak (revoke false) tidak menyentuh kotak share dan langsung pindah', async () => {
  const store = memStore(); await store.put({ id: 'a', text: 'Rp1' });
  let made = 0; const makeStore = () => { made += 1; return store; };
  for (const opts of [{ revoke: false }, {}, undefined]) {
    let moved = 0;
    const p = clearSharesOnLogout(opts, { makeStore, next: () => { moved += 1; } });
    assert.equal(moved, 1, 'pindah ke /login langsung (sinkron)');
    assert.equal(await p, false);
    assert.equal(moved, 1);
  }
  assert.equal(made, 0);
  assert.equal(store.map.size, 1);
});

test('clearSharesOnLogout: logout biasa (revoke true) mengosongkan kotak, pindah ke /login SETELAH penghapusan selesai', async () => {
  const store = memStore(); await store.put({ id: 'a', text: 'Rp1' }); await store.put({ id: 'b', blob: new Blob(['x']) });
  let release;
  const slow = { ...store, clear: () => new Promise((resolve) => { release = () => resolve(store.clear()); }) };
  const timers = [];
  let moved = 0;
  const p = clearSharesOnLogout({ revoke: true }, { makeStore: () => slow, next: () => { moved += 1; }, setTimer: (fn, ms) => timers.push({ fn, ms }) });
  await new Promise(r => setTimeout(r, 5));
  assert.equal(moved, 0, 'belum pindah selama penghapusan berjalan');
  assert.equal(timers[0].ms, 2000);
  release();
  assert.equal(await p, true);
  assert.equal(moved, 1);
  assert.equal(store.map.size, 0);
  timers[0].fn(); // batas waktu yang menyusul tidak memindahkan dua kali
  await new Promise(r => setTimeout(r, 5));
  assert.equal(moved, 1);
});

test('clearSharesOnLogout: penghapusan macet → tetap pindah setelah batas waktu (sekali)', async () => {
  const timers = [];
  let moved = 0;
  const p = clearSharesOnLogout({ revoke: true }, {
    makeStore: () => ({ clear: () => new Promise(() => {}) }), next: () => { moved += 1; }, waitMs: 50,
    setTimer: (fn, ms) => timers.push({ fn, ms }),
  });
  await new Promise(r => setTimeout(r, 5));
  assert.equal(moved, 0);
  assert.equal(timers[0].ms, 50);
  timers[0].fn();
  assert.equal(await p, false);
  assert.equal(moved, 1);
});

test('clearSharesOnLogout: timer batas waktu tetap aktif selama penghapusan berjalan, dibersihkan sekali begitu selesai', async () => {
  const realClear = globalThis.clearTimeout;
  const cleared = [];
  globalThis.clearTimeout = (h) => { cleared.push(h); return realClear(h); };
  try {
    const handle = { timer: 'batas' }; // pegangan tiruan: mutan yang lupa membersihkan tidak menahan proses tes
    let moved = 0;
    let release;
    const slow = { clear: () => new Promise((resolve) => { release = resolve; }) };
    const p = clearSharesOnLogout({ revoke: true }, { makeStore: () => slow, next: () => { moved += 1; }, setTimer: () => handle });
    await new Promise((r) => setTimeout(r, 5));
    assert.deepEqual([cleared, moved], [[], 0], 'batas waktu tetap aktif selama penghapusan berjalan');
    release();
    assert.equal(await p, true);
    assert.deepEqual([cleared, moved], [[handle], 1]);
  } finally {
    globalThis.clearTimeout = realClear;
  }
});

test('clearSharesOnLogout: gagal mengosongkan tidak pernah melempar, logout tetap pindah', async () => {
  for (const makeStore of [
    () => ({ clear: async () => { throw new Error('rusak'); } }),
    () => ({ clear: () => { throw new Error('sinkron'); } }),
    () => { throw new Error('tanpa store'); },
  ]) {
    let p; let moved = 0;
    assert.doesNotThrow(() => { p = clearSharesOnLogout({ revoke: true }, { makeStore, next: () => { moved += 1; } }); });
    assert.equal(await p, false);
    assert.equal(moved, 1);
  }
  assert.equal(await clearSharesOnLogout({ revoke: true }, { makeStore: () => memStore(), next: () => { throw new Error('x'); } }), true);
  assert.doesNotThrow(() => clearSharesOnLogout({ revoke: false }, { next: () => { throw new Error('y'); } }));
  let moved = 0; // timer rusak: tetap pindah, tidak tertahan
  const p = clearSharesOnLogout({ revoke: true }, {
    makeStore: () => ({ clear: () => new Promise(() => {}) }), next: () => { moved += 1; }, setTimer: () => { throw new Error('timer'); },
  });
  assert.equal(await p, false);
  assert.equal(moved, 1);
});

// ── shareStore (D4) ───────────────────────────────────────────────────────────────────────────────

test('shareStore tanpa IndexedDB (Node, browser lama): store memori yang tidak pernah melempar', async () => {
  assert.equal(typeof globalThis.indexedDB, 'undefined');
  for (const idb of [undefined, null, {}]) {
    const s = shareStore(idb);
    assert.deepEqual(await s.all(), []);
    await s.put({ id: 'a', text: 'x' });
    assert.deepEqual((await s.all()).map(e => e.id), ['a']);
    await s.put(undefined);
    await s.put({});
    await s.del('tidak-ada');
    await s.del('a');
    assert.deepEqual(await s.all(), []);
    await s.put({ id: 'b' });
    await s.clear();
    assert.deepEqual(await s.all(), []);
  }
  assert.doesNotThrow(() => shareStore());
  await clearShares(shareStore());
});

// IndexedDB tiruan secukupnya: open (+ upgrade), transaksi yang menjalankan request lalu 'complete' di tugas berikutnya.
function fakeIndexedDB() {
  const stores = new Map();
  let version = 0;
  const later = fn => setTimeout(fn, 0);
  const fake = { opens: [], created: [], events: [], failOpen: false, failNext: null, failCommit: false, lastDb: null };
  fake.open = (name, ver) => {
    fake.opens.push([name, ver]);
    const req = {};
    later(() => {
      if (fake.failOpen) { req.error = new Error('UnknownError'); req.onerror?.({ target: req }); return; }
      const db = makeDb();
      fake.lastDb = db;
      req.result = db;
      if (version < ver) { version = ver; req.onupgradeneeded?.({ target: req }); }
      req.onsuccess?.({ target: req });
    });
    return req;
  };
  fake.fireVersionChange = () => fake.lastDb.onversionchange?.({});
  function makeDb() {
    const db = {
      closed: false,
      objectStoreNames: { contains: name => stores.has(name) },
      createObjectStore(name, opts) { fake.created.push([name, opts]); stores.set(name, { keyPath: opts.keyPath, rows: new Map() }); },
      close() { db.closed = true; },
      transaction(name, mode) {
        if (db.closed) throw new Error('InvalidStateError');
        const st = stores.get(name);
        if (!st) throw new Error('NotFoundError');
        const tx = {}; const reqs = [];
        const request = (op, fn) => { const r = {}; reqs.push({ r, op, fn }); return r; };
        const writable = () => { if (mode !== 'readwrite') throw new Error('ReadOnlyError'); };
        tx.objectStore = (storeName) => {
          assert.equal(storeName, name);
          return {
            getAll: () => request('getAll', () => [...st.rows.keys()].sort().map(k => st.rows.get(k))),
            get: k => request('get', () => st.rows.get(k)),
            put: v => request('put', () => { writable(); st.rows.set(v[st.keyPath], v); return v[st.keyPath]; }),
            delete: k => request('delete', () => { writable(); st.rows.delete(k); }),
            clear: () => request('clear', () => { writable(); st.rows.clear(); }),
          };
        };
        later(() => {
          const snapshot = new Map(st.rows);
          for (const { r, op, fn } of reqs) {
            if (fake.failNext === op) {
              fake.failNext = null;
              r.error = tx.error = new Error('QuotaExceededError');
              r.onerror?.({ target: r }); tx.onerror?.({ target: r }); later(() => tx.onabort?.({}));
              return;
            }
            r.result = fn(); fake.events.push(op); r.onsuccess?.({ target: r });
          }
          later(() => {
            if (fake.failCommit && mode === 'readwrite') { // kuota penuh saat commit: request sudah sukses, hanya 'abort'
              fake.failCommit = false; st.rows = snapshot; tx.error = new Error('QuotaExceededError');
              fake.events.push('abort'); tx.onabort?.({}); return;
            }
            fake.events.push('complete'); tx.oncomplete?.({});
          });
        });
        return tx;
      },
    };
    return db;
  }
  return fake;
}

test('shareStore di IndexedDB: DB jatahku-share v1 + store shares (keyPath id), terpisah dari antrean offline', async () => {
  assert.deepEqual([SHARE_DB, SHARE_STORE], ['jatahku-share', 'shares']);
  assert.notEqual(SHARE_DB, OFFLINE_DB);
  const idb = fakeIndexedDB();
  const s = shareStore(idb);
  await s.put({ id: 'b', text: 'dua' });
  await s.put({ id: 'a', text: 'satu' });
  assert.deepEqual((await s.all()).map(e => e.text), ['satu', 'dua']);
  await s.del('a');
  assert.deepEqual((await s.all()).map(e => e.id), ['b']);
  await clearShares(s);
  assert.deepEqual(await s.all(), []);
  assert.deepEqual(idb.created, [['shares', { keyPath: 'id' }]]);
  assert.ok(idb.opens.length >= 1 && idb.opens.every(([name, ver]) => name === 'jatahku-share' && ver === 1));
});

test('shareStore: tulis baru selesai setelah transaksi complete (303 hanya setelah share benar-benar tersimpan)', async () => {
  const idb = fakeIndexedDB();
  const s = shareStore(idb);
  await s.put({ id: 'a' });
  idb.events.length = 0;
  await s.put({ id: 'b' });
  idb.events.push('selesai');
  assert.deepEqual(idb.events, ['put', 'complete', 'selesai']);
});

test('shareStore: tulis gagal (penyimpanan penuh) ditolak; buka gagal ditolak lalu panggilan berikutnya membuka ulang', async () => {
  const idb = fakeIndexedDB();
  const s = shareStore(idb);
  idb.failNext = 'put';
  await assert.rejects(s.put({ id: 'a' }), /QuotaExceededError/);
  assert.deepEqual(await s.all(), []);

  const idb2 = fakeIndexedDB();
  idb2.failOpen = true;
  const s2 = shareStore(idb2);
  await assert.rejects(s2.all(), /UnknownError/);
  idb2.failOpen = false;
  assert.deepEqual(await s2.all(), []);
  assert.equal(idb2.opens.length, 2);
});

test('shareStore: kuota penuh saat commit (Chromium: request sukses, transaksi hanya abort) → ditolak; share → err=baca tanpa sisa', async () => {
  const idb = fakeIndexedDB();
  const store = shareStore(idb);
  idb.failCommit = true;
  await assert.rejects(store.put({ id: 'a' }), /QuotaExceededError/);
  assert.deepEqual(await store.all(), []);
  await store.put({ id: 'lama', text: 'Rp9' });
  idb.failCommit = true;
  const fd = form({ text: 'Rp1' }, [new File(['a'], 'a.jpg', { type: 'image/jpeg' })]);
  const res = await handleShareTarget(shareRequest(fd), { store, newId });
  assert.equal(res.headers.get('location'), '/bagikan?err=baca');
  assert.deepEqual((await store.all()).map(e => e.id), ['lama']);
});

test('shareStore: koneksi ditutup saat versionchange (tidak menahan upgrade/hapus DB), lalu dibuka ulang', async () => {
  const idb = fakeIndexedDB();
  const s = shareStore(idb);
  await s.put({ id: 'a' });
  const first = idb.lastDb;
  idb.fireVersionChange();
  assert.equal(first.closed, true);
  await s.put({ id: 'b' });
  assert.equal(idb.opens.length, 2);
  assert.deepEqual((await s.all()).map(e => e.id), ['a', 'b']);
});

// ══ Halaman /bagikan (Task B5): fungsi murni alur halaman ═════════════════════════════════════════

// ── Tes dari plan ─────────────────────────────────────────────────────────────────────────────────

test('uploadOutcome: sukses, simpan untuk nanti, buang', () => {
  assert.equal(uploadOutcome({ ok: true, status: 201, data: { id: 'i1' } }).action, 'done');
  for (const r of [{ ok: false, status: 0, data: {} }, { ok: false, status: 503, data: {} }, { ok: false, status: 0, timedOut: true, data: {} }])
    assert.equal(uploadOutcome(r).action, 'keep');
  assert.deepEqual(uploadOutcome({ ok: false, status: 415, data: { detail: 'Kirim foto (JPG/PNG/WebP), PDF, atau teks' } }),
    { action: 'drop', message: 'Kirim foto (JPG/PNG/WebP), PDF, atau teks' });
  assert.equal(uploadOutcome({ ok: false, status: 429, data: { detail: 'Terlalu banyak bukti. Coba lagi sebentar.' } }).action, 'keep');
});

test('needsPolling: berhenti saat siap atau lewat 30 detik', () => {
  assert.equal(needsPolling({ status: 'diproses' }, 0, 29999), true);
  assert.equal(needsPolling({ status: 'diproses' }, 0, 30000), false);
  assert.equal(needsPolling({ status: 'siap' }, 0, 10), false);
});

// ── uploadOutcome / needsPolling: rincian ─────────────────────────────────────────────────────────

const KEEP_TEXT = 'Bukti belum terkirim. Akan dikirim lagi saat online.';

test('uploadOutcome: done membawa item = data; 0/timeout/5xx/401 disimpan dengan pesan kirim lagi', () => {
  const data = { id: 'i1', status: 'siap' };
  assert.deepEqual(uploadOutcome({ ok: true, status: 201, data }), { action: 'done', item: data });
  assert.deepEqual(uploadOutcome({ ok: true, status: 200, data }), { action: 'done', item: data }); // upload_id sama
  for (const r of [
    { ok: false, status: 0, data: {} }, { ok: false, status: 0, timedOut: true, data: {} },
    { ok: false, status: 500, data: { detail: 'Internal Server Error' } }, { ok: false, status: 502, data: {} },
    { ok: false, status: 503, data: { detail: 'x' } }, { ok: false, status: 401, data: { detail: 'Not authenticated' } },
    null, undefined, {},
  ]) {
    assert.deepEqual(uploadOutcome(r), { action: 'keep', message: KEEP_TEXT }, JSON.stringify(r));
  }
});

test('uploadOutcome: 429 disimpan dengan pesan server; tanpa detail teks → pesan batas server', () => {
  for (const detail of ['Terlalu banyak bukti. Coba lagi sebentar.', 'Masih ada bukti yang sedang dibaca. Tunggu sebentar.']) {
    assert.deepEqual(uploadOutcome({ ok: false, status: 429, data: { detail } }), { action: 'keep', message: detail });
  }
  for (const data of [{ error: 'Rate limit exceeded: 30 per 1 hour' }, {}, { detail: ['x'] }]) {
    assert.deepEqual(uploadOutcome({ ok: false, status: 429, data }), { action: 'keep', message: 'Terlalu banyak bukti. Coba lagi sebentar.' });
  }
});

test('uploadOutcome: 413/415/422 dibuang dengan pesan server (teks)', () => {
  for (const [status, detail] of [
    [413, 'Foto terlalu besar (maks 8 MB)'], [413, 'PDF terlalu besar (maks 10 MB)'], [413, 'Teks terlalu panjang'],
    [415, 'Kirim foto (JPG/PNG/WebP), PDF, atau teks'], [422, 'Kirim satu file atau teks'], [422, 'Sumber tidak dikenal'],
  ]) {
    assert.deepEqual(uploadOutcome({ ok: false, status, data: { detail } }), { action: 'drop', message: detail });
  }
});

test('uploadOutcome (D2): 413/415/422 dengan detail bukan teks (validasi FastAPI, kosong, HTML nginx) → "Bukti tidak bisa dikirim."', () => {
  const validation = { detail: [{ type: 'less_than_equal', loc: ['body', 'wait'], msg: 'Input should be less than or equal to 45' }] };
  for (const status of [413, 415, 422]) {
    for (const data of [validation, {}, { detail: '   ' }, { detail: null }, { detail: { msg: 'x' } }]) {
      assert.deepEqual(uploadOutcome({ ok: false, status, data }), { action: 'drop', message: 'Bukti tidak bisa dikirim.' }, `${status} ${JSON.stringify(data)}`);
    }
  }
});

test('uploadOutcome: 4xx lain (rute belum ada, akses ditolak) tidak membuang bukti', () => {
  for (const status of [400, 403, 404, 405, 409]) {
    assert.deepEqual(uploadOutcome({ ok: false, status, data: {} }), { action: 'keep', message: KEEP_TEXT }, String(status));
  }
  assert.deepEqual(uploadOutcome({ ok: false, status: 403, data: { detail: 'Akun dinonaktifkan' } }), { action: 'keep', message: 'Akun dinonaktifkan' });
});

test('needsPolling: hanya diterima/diproses, 30 dtk sejak startedAt; tanpa startedAt tidak dipantau', () => {
  assert.equal(POLL_MS, 1500);
  assert.equal(POLL_LIMIT_MS, 30000);
  assert.equal(needsPolling({ status: 'diterima' }, 1000, 30999), true);
  assert.equal(needsPolling({ status: 'diterima' }, 1000, 31000), false);
  for (const status of ['siap', 'gagal', 'tercatat', 'dilewati', 'kedaluwarsa', undefined]) {
    assert.equal(needsPolling({ status }, 0, 1), false, String(status));
  }
  assert.equal(needsPolling(null, 0, 1), false);
  assert.equal(needsPolling({ status: 'diproses' }, undefined, 1), false);
});

// ── Saklar dan mode halaman (D1, D8, D9) ──────────────────────────────────────────────────────────

test('shareFlag: saklar receipt_inbox dari /app/config; config bawaan (belum pernah terbaca) = belum diketahui', () => {
  assert.equal(shareFlag({ features: { receipt_inbox: true } }), 'on');
  assert.equal(shareFlag({ features: { receipt_inbox: false, push: true } }), 'off');
  for (const c of [DEFAULT_CONFIG, { features: {} }, {}, null, undefined, { features: null }, { features: { receipt_inbox: 'true' } }, { features: { receipt_inbox: 1 } }]) {
    assert.equal(shareFlag(c), 'unknown', JSON.stringify(c));
  }
});

test('sharePageMode: saklar mati menang; offline atau saklar belum diketahui → tahan; selain itu kirim', () => {
  assert.equal(sharePageMode({ flag: 'off', online: true }), 'off');
  assert.equal(sharePageMode({ flag: 'off', online: false }), 'off');
  assert.equal(sharePageMode({ flag: 'on', online: false }), 'hold');
  assert.equal(sharePageMode({ flag: 'unknown', online: true }), 'hold');
  assert.equal(sharePageMode({ flag: 'unknown', online: false }), 'hold');
  assert.equal(sharePageMode({ flag: 'on', online: true }), 'send');
  assert.equal(sharePageMode({}), 'hold');
});

test('offlineBannerText dan teks halaman persis', () => {
  assert.equal(offlineBannerText(1), '1 bukti menunggu dikirim. Akan dikirim saat online.');
  assert.equal(offlineBannerText(3), '3 bukti menunggu dikirim. Akan dikirim saat online.');
  for (const n of [0, -1, undefined, NaN]) assert.equal(offlineBannerText(n), null);
  assert.equal(SHARE_TEXT.soon, 'Fitur ini segera hadir.');
  assert.equal(SHARE_TEXT.errSw, 'Buka Jatahku sekali, lalu bagikan lagi.');
  assert.equal(SHARE_TEXT.errBaca, 'File yang dibagikan tidak bisa dibaca. Coba bagikan lagi.');
  assert.equal(SHARE_TEXT.storageHint, 'Kalau memori HP penuh, kosongkan sedikit lalu bagikan lagi.');
  assert.equal(SHARE_TEXT.notSent, KEEP_TEXT);
  assert.equal(SHARE_TEXT.cannotSend, 'Bukti tidak bisa dikirim.');
});

test('pageNotices (D3): ?err=sw, ?err=baca + petunjuk memori penuh, kotak share halaman gagal dibaca', () => {
  const baca = ['File yang dibagikan tidak bisa dibaca. Coba bagikan lagi.', 'Kalau memori HP penuh, kosongkan sedikit lalu bagikan lagi.'];
  for (const mode of ['send', 'hold']) {
    assert.deepEqual(pageNotices({ mode, err: 'sw' }), ['Buka Jatahku sekali, lalu bagikan lagi.']);
    assert.deepEqual(pageNotices({ mode, err: 'baca' }), baca);
    assert.deepEqual(pageNotices({ mode, storeFailed: true }), ['File yang dibagikan tidak bisa dibaca. Coba bagikan lagi.']);
    assert.deepEqual(pageNotices({ mode, err: 'baca', storeFailed: true }), baca); // tidak dobel
    assert.deepEqual(pageNotices({ mode, err: 'sw', storeFailed: true }), ['Buka Jatahku sekali, lalu bagikan lagi.', 'File yang dibagikan tidak bisa dibaca. Coba bagikan lagi.']);
    for (const err of [null, undefined, '', 'lain']) assert.deepEqual(pageNotices({ mode, err }), []);
  }
});

test('pageView: memeriksa → hanya "Memuat…"; saklar mati → hanya "Fitur ini segera hadir." (kartu dan hasil unggah disembunyikan)', () => {
  const busyPage = { err: 'baca', storeFailed: true, waiting: 3, items: [{ id: 'a', status: 'siap' }], dropped: [{ name: 'x', message: 'y' }], kept: 'z' };
  assert.deepEqual(pageView({ ...busyPage, mode: null }), { checking: true, soon: null, results: true, notices: [], banner: null, finished: false, empty: null, retry: false, discard: false });
  assert.deepEqual(pageView({ ...busyPage, mode: 'off' }), { checking: false, soon: 'Fitur ini segera hadir.', results: false, notices: [], banner: null, finished: false, empty: null, retry: false, discard: false });
});

test('pageView: tahan (offline) → banner jumlah entri + pemberitahuan, tanpa Ke Transaksi', () => {
  const v = pageView({ mode: 'hold', err: 'sw', waiting: 2, items: [] });
  assert.deepEqual(v, {
    checking: false, soon: null, results: true, notices: ['Buka Jatahku sekali, lalu bagikan lagi.'],
    banner: '2 bukti menunggu dikirim. Akan dikirim saat online.', finished: false, empty: null, retry: true, discard: false,
  });
  assert.equal(pageView({ mode: 'hold', waiting: 0 }).banner, null);
});

test('pageView: kirim → Ke Transaksi saat selesai; teks kosong hanya tanpa kartu, tanpa entri dibuang, tanpa pesan simpan', () => {
  assert.deepEqual(pageView({ mode: 'send' }), { checking: false, soon: null, results: true, notices: [], banner: null, finished: true, empty: 'Tidak ada bukti yang menunggu.', retry: false, discard: false });
  assert.equal(pageView({ mode: 'send', waiting: 5 }).banner, null);
  assert.equal(pageView({ mode: 'send', running: true }).finished, false);
  assert.equal(pageView({ mode: 'send', running: true }).empty, null);
  assert.equal(pageView({ mode: 'send', dropped: [{ name: 'a.heic', message: 'x' }] }).empty, null);
  assert.equal(pageView({ mode: 'send', kept: 'Bukti belum terkirim. Akan dikirim lagi saat online.' }).empty, null);
  const siap = [{ id: 'a', status: 'siap' }];
  assert.equal(pageView({ mode: 'send', items: siap }).finished, false);
  assert.deepEqual(pageView({ mode: 'send', items: siap, handled: new Set(['a']) }), { checking: false, soon: null, results: true, notices: [], banner: null, finished: true, empty: null, retry: false, discard: false });
});

test('pageNotices: tidak ada selama saklar diperiksa (mode null) dan dengan saklar mati (hanya "segera hadir")', () => {
  for (const mode of [null, undefined, 'off']) {
    assert.deepEqual(pageNotices({ mode, err: 'sw', storeFailed: true }), []);
    assert.deepEqual(pageNotices({ mode, err: 'baca' }), []);
  }
  assert.deepEqual(pageNotices(), []);
});

test('dropLine: nama file lalu pesan; teks (tanpa nama) hanya pesan', () => {
  assert.equal(dropLine({ name: 'struk.heic', message: 'Kirim foto (JPG/PNG/WebP), PDF, atau teks' }), 'struk.heic: Kirim foto (JPG/PNG/WebP), PDF, atau teks');
  assert.equal(dropLine({ name: '', message: 'Teks terlalu panjang' }), 'Teks terlalu panjang');
  assert.equal(dropLine({ message: 'Bukti tidak bisa dikirim.' }), 'Bukti tidak bisa dikirim.');
});

test('shareUploadTimeoutMs: file share dikirim apa adanya → aturan waktu PDF (60 dtk + 1 dtk/25 kB, maks 5 mnt) juga untuk foto; teks 60 dtk', () => {
  assert.equal(shareUploadTimeoutMs({ id: 't', text: 'Rp1' }), 60000);
  assert.equal(shareUploadTimeoutMs({ id: 'f', blob: { size: 100000, type: 'image/jpeg' } }), 64000);
  assert.equal(shareUploadTimeoutMs({ id: 'f', blob: { size: 8 * 1024 * 1024, type: 'image/jpeg' } }), 300000);
  const pdf = { size: 2 * 1024 * 1024, type: 'application/pdf' };
  assert.equal(shareUploadTimeoutMs({ id: 'p', blob: pdf }), uploadTimeoutMs(pdf));
  assert.equal(shareUploadTimeoutMs(undefined), 60000);
});

// ── runSharePage: satu putaran halaman (D1, D3, D8, D9) ───────────────────────────────────────────

const shareEntry = (id, batchId, createdAt, seq = 0, extra = {}) => ({
  id, batchId, createdAt, seq, name: `${id}.jpg`, type: 'image/jpeg', blob: new Blob([id]), ...extra,
});

// Dependensi tiruan: setiap panggilan ke "server" dicatat di `calls` (config, unggah, bukti menunggu).
function pageDeps({ flag = true, online = true, entries = [], replies = {}, pending = [], batchId = null } = {}) {
  const store = memStore();
  for (const e of entries) store.map.set(e.id, e);
  const calls = [];
  const items = [];
  const modes = [];
  const deps = {
    getConfig: async () => { calls.push('config'); return flag === null ? DEFAULT_CONFIG : { features: { receipt_inbox: flag } }; },
    isOnline: () => online,
    batchId,
    store,
    upload: async (entry) => {
      calls.push(`upload:${entry.id}`);
      const r = replies[entry.id];
      if (typeof r === 'function') return r(entry);
      return r ?? { ok: true, status: 201, data: { id: `item-${entry.id}`, status: 'siap' } };
    },
    loadPending: async () => { calls.push('pending'); return pending; },
    onItem: (item) => items.push(item.id),
    onMode: (mode) => modes.push(mode),
  };
  return { deps, calls, store, items, modes };
}

test('runSharePage (D1): saklar mati → entri batch ?s= dihapus, tanpa unggah dan tanpa permintaan Kotak (online dan offline)', async () => {
  for (const online of [true, false]) {
    const { deps, calls, store, items, modes } = pageDeps({
      flag: false, online, batchId: 'b2',
      entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b2', 2), shareEntry('c', 'b2', 2, 1, { blob: undefined, text: 'Rp1' })],
    });
    const out = await runSharePage(deps);
    assert.equal(out.mode, 'off');
    assert.deepEqual(modes, ['off']);
    assert.deepEqual([...store.map.keys()], ['a'], 'hanya batch di URL yang dihapus');
    assert.deepEqual(calls, ['config'], 'tidak ada unggahan dan tidak ada GET bukti menunggu');
    assert.deepEqual(items, []);
  }
});

test('runSharePage (D1): saklar mati tanpa ?s= tidak menghapus apa pun; kotak share rusak tidak melempar', async () => {
  const none = pageDeps({ flag: false, entries: [shareEntry('a', 'b1', 1)] });
  assert.equal((await runSharePage(none.deps)).mode, 'off');
  assert.deepEqual([...none.store.map.keys()], ['a']);
  assert.deepEqual(none.calls, ['config']);

  const broken = pageDeps({ flag: false, batchId: 'b1' });
  broken.deps.store = { all: async () => { throw new Error('UnknownError'); }, del: async () => { throw new Error('x'); } };
  assert.equal((await runSharePage(broken.deps)).mode, 'off');
  const delFails = pageDeps({ flag: false, batchId: 'b1', entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b1', 1, 1)] });
  delFails.deps.store = { ...delFails.store, del: async () => { throw new Error('QuotaExceededError'); } };
  assert.equal((await runSharePage(delFails.deps)).mode, 'off');
  assert.deepEqual(delFails.calls, ['config']);
});

test('discardBatch: hanya entri batch itu, → jumlah terhapus; tanpa batch/kotak rusak → 0 tanpa melempar', async () => {
  const store = memStore();
  for (const e of [shareEntry('a', 'b1', 1), shareEntry('b', 'b2', 1), shareEntry('c', 'b2', 1, 1)]) await store.put(e);
  assert.equal(await discardBatch(store, 'b2'), 2);
  assert.deepEqual([...store.map.keys()], ['a']);
  assert.equal(await discardBatch(store, null), 0);
  assert.equal(await discardBatch(store, 'tidak-ada'), 0);
  assert.equal(await discardBatch({ all: async () => { throw new Error('x'); } }, 'b1'), 0);
  assert.equal(await discardBatch({ all: async () => [{ id: 'z', batchId: 'b1' }], del: async () => { throw new Error('x'); } }, 'b1'), 0);
  assert.equal(await discardBatch(undefined, 'b1'), 0);
});

test('runSharePage: config belum pernah terbaca (bawaan) → tahan: tidak menghapus, tidak mengunggah, jumlah menunggu', async () => {
  const { deps, calls, store } = pageDeps({ flag: null, batchId: 'b1', entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b1', 1, 1)] });
  const out = await runSharePage(deps);
  assert.deepEqual([out.mode, out.waiting], ['hold', 2]);
  assert.deepEqual([...store.map.keys()], ['a', 'b']);
  assert.deepEqual(calls, ['config']);
  const throwing = pageDeps({ entries: [shareEntry('a', 'b1', 1)] });
  throwing.deps.getConfig = async () => { throw new Error('jaringan'); };
  const out2 = await runSharePage(throwing.deps);
  assert.deepEqual([out2.mode, out2.waiting], ['hold', 1]);
  assert.deepEqual(throwing.calls, []);
});

test('runSharePage (D8): offline → jumlah entri menunggu; tidak ada unggahan dan tidak ada permintaan Kotak', async () => {
  const { deps, calls, store, modes } = pageDeps({ online: false, batchId: 'b1', entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b0', 0)] });
  const out = await runSharePage(deps);
  assert.deepEqual([out.mode, out.waiting, out.storeFailed], ['hold', 2, false]);
  assert.deepEqual(modes, ['hold']);
  assert.deepEqual(calls, ['config']);
  assert.equal(store.map.size, 2);
  const empty = pageDeps({ online: false });
  assert.deepEqual([(await runSharePage(empty.deps)).waiting], [0]);
});

test('runSharePage (D3): offline dan kotak share ditolak → storeFailed, tanpa melempar', async () => {
  const { deps } = pageDeps({ online: false });
  deps.store = { all: async () => { throw new Error('UnknownError'); } };
  const out = await runSharePage(deps);
  assert.deepEqual([out.mode, out.waiting, out.storeFailed], ['hold', 0, true]);
});

test('runSharePage (D8): online → unggah tertua dulu satu per satu; done/drop dihapus; keep berhenti dan entrinya tetap', async () => {
  const { deps, calls, store, items } = pageDeps({
    entries: [shareEntry('d', 'b3', 3), shareEntry('c', 'b2', 2, 1), shareEntry('b', 'b2', 2), shareEntry('a', 'b1', 1, 0, { blob: undefined, name: '', text: 'Rp1' })],
    replies: {
      b: { ok: false, status: 415, data: { detail: 'Kirim foto (JPG/PNG/WebP), PDF, atau teks' } },
      c: { ok: false, status: 503, data: {} },
    },
    pending: [{ id: 'p1', status: 'siap' }],
  });
  const out = await runSharePage(deps);
  assert.equal(out.mode, 'send');
  assert.deepEqual(calls, ['config', 'upload:a', 'upload:b', 'upload:c', 'pending']);
  assert.deepEqual(items, ['item-a'], 'item langsung diteruskan begitu diterima server');
  assert.deepEqual(out.items.map(i => i.id), ['item-a']);
  assert.deepEqual(out.dropped, [{ name: 'b.jpg', message: 'Kirim foto (JPG/PNG/WebP), PDF, atau teks' }]);
  assert.equal(out.kept, KEEP_TEXT);
  assert.deepEqual([...store.map.keys()].sort(), ['c', 'd'], 'done/drop dihapus, keep dan sisanya tetap');
  assert.deepEqual(out.pending, [{ id: 'p1', status: 'siap' }]);
});

test('runSharePage: semua terkirim → kotak share kosong, bukti menunggu dimuat sekali sesudahnya', async () => {
  const { deps, calls, store } = pageDeps({ entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b1', 1, 1)] });
  const out = await runSharePage(deps);
  assert.deepEqual(calls, ['config', 'upload:a', 'upload:b', 'pending']);
  assert.equal(store.map.size, 0);
  assert.equal(out.kept, null);
  const none = pageDeps({});
  await runSharePage(none.deps);
  assert.deepEqual(none.calls, ['config', 'pending']);
});

test('runSharePage: 429 menghentikan putaran dengan pesan server; entri tetap untuk nanti', async () => {
  const { deps, calls, store } = pageDeps({
    entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b1', 1, 1)],
    replies: { a: { ok: false, status: 429, data: { detail: 'Masih ada bukti yang sedang dibaca. Tunggu sebentar.' } } },
  });
  const out = await runSharePage(deps);
  assert.equal(out.kept, 'Masih ada bukti yang sedang dibaca. Tunggu sebentar.');
  assert.deepEqual(calls, ['config', 'upload:a', 'pending']);
  assert.equal(store.map.size, 2);
});

test('runSharePage: satu unggahan pada satu waktu (berikutnya mulai setelah yang sebelumnya selesai)', async () => {
  let release;
  const { deps, calls } = pageDeps({
    entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b1', 1, 1)],
    replies: { a: () => new Promise((resolve) => { release = () => resolve({ ok: true, status: 201, data: { id: 'item-a', status: 'siap' } }); }) },
  });
  const running = runSharePage(deps);
  await new Promise(r => setTimeout(r, 5));
  assert.deepEqual(calls, ['config', 'upload:a']);
  release();
  await running;
  assert.deepEqual(calls, ['config', 'upload:a', 'upload:b', 'pending']);
});

test('runSharePage (D3): hapus entri gagal → tetap lanjut, tiap entri dicoba sekali per putaran', async () => {
  const { deps, calls, store } = pageDeps({ entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b1', 1, 1)] });
  deps.store = { all: store.all, del: async () => { throw new Error('QuotaExceededError'); } };
  const out = await runSharePage(deps);
  assert.deepEqual(calls, ['config', 'upload:a', 'upload:b', 'pending']);
  assert.deepEqual(out.items.map(i => i.id), ['item-a', 'item-b']);
});

test('runSharePage (D3): kotak share ditolak saat online → storeFailed, tidak ada unggahan, bukti menunggu tetap dimuat', async () => {
  const { deps, calls } = pageDeps({ pending: [{ id: 'p1', status: 'siap' }] });
  deps.store = { all: async () => { throw new Error('UnknownError'); } };
  const out = await runSharePage(deps);
  assert.deepEqual([out.mode, out.storeFailed], ['send', true]);
  assert.deepEqual(calls, ['config', 'pending']);
  assert.deepEqual(out.pending, [{ id: 'p1', status: 'siap' }]);
});

test('runSharePage: unggah melempar → disimpan (seperti status 0); loadPending melempar → []', async () => {
  const { deps, store } = pageDeps({ entries: [shareEntry('a', 'b1', 1)], replies: { a: async () => { throw new Error('x'); } } });
  deps.loadPending = async () => { throw new Error('y'); };
  const out = await runSharePage(deps);
  assert.equal(out.kept, KEEP_TEXT);
  assert.equal(store.map.size, 1);
  assert.deepEqual(out.pending, []);
});

test('runSharePage: halaman ditutup → tidak memulai unggahan berikutnya; hasil yang sedang jalan tetap diterapkan', async () => {
  let open = true;
  const { deps, calls, store } = pageDeps({
    entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b1', 1, 1)],
    replies: { a: async () => { open = false; return { ok: true, status: 201, data: { id: 'item-a', status: 'siap' } }; } },
  });
  deps.alive = () => open;
  await runSharePage(deps);
  assert.deepEqual(calls, ['config', 'upload:a']);
  assert.deepEqual([...store.map.keys()], ['b'], 'entri yang sudah diterima server tetap dihapus');
  const closed = pageDeps({ entries: [shareEntry('a', 'b1', 1)] });
  closed.deps.alive = () => false;
  await runSharePage(closed.deps);
  assert.deepEqual(closed.calls, ['config']);
});

// ── Kartu: satu per id, pemantauan, selesai (D5) ──────────────────────────────────────────────────

test('mergeItems (D5): satu kartu per id; detail terbaru menggantikan di tempat yang sama; id baru ditambah di belakang', () => {
  const a1 = { id: 'a', status: 'diproses' };
  const b = { id: 'b', status: 'siap' };
  const a2 = { id: 'a', status: 'siap', document: { doc_type: 'qris' } };
  const list = [a1, b];
  const next = mergeItems(list, [a2, { id: 'c', status: 'siap' }, { id: 'c', status: 'siap', flags: { blocked: 'sudah_tercatat' } }]);
  assert.deepEqual(next.map(i => i.id), ['a', 'b', 'c']);
  assert.equal(next[0], a2);
  assert.equal(next[1], b);
  assert.deepEqual(next[2].flags, { blocked: 'sudah_tercatat' });
  assert.deepEqual(list, [a1, b], 'daftar lama tidak diubah');
  assert.deepEqual(mergeItems([], [null, undefined, {}, { id: '' }, 'x']), []);
  assert.deepEqual(mergeItems(undefined, [b]), [b]);
  assert.deepEqual(mergeItems([b], undefined), [b]);
});

test('mergeItems: jawaban lama yang tiba belakangan tidak memundurkan status; status setara → terbaru menang', () => {
  const siap = { id: 'a', status: 'siap', flags: { blocked: null } };
  assert.equal(mergeItems([siap], [{ id: 'a', status: 'diproses' }])[0], siap);
  assert.equal(mergeItems([siap], [{ id: 'a', status: 'diterima' }])[0], siap);
  const tercatat = { id: 'a', status: 'tercatat' };
  assert.equal(mergeItems([siap], [tercatat])[0], tercatat);
  assert.equal(mergeItems([tercatat], [siap])[0], tercatat);
  const blocked = { id: 'a', status: 'siap', flags: { blocked: 'sudah_tercatat' } };
  assert.equal(mergeItems([siap], [blocked])[0], blocked);
  const diterima = { id: 'a', status: 'diterima' };
  const diproses = { id: 'a', status: 'diproses' };
  assert.equal(mergeItems([diproses], [diterima])[0], diterima, 'diterima/diproses setara (pemulihan worker)');
  const gagal = { id: 'a', status: 'gagal', error: 'Bukti tidak bisa dibaca' };
  assert.equal(mergeItems([diproses], [gagal])[0], gagal);
  assert.equal(mergeItems([{ id: 'a', status: 'dilewati' }], [{ id: 'a', status: 'kedaluwarsa' }])[0].status, 'kedaluwarsa');
});

test('pollTargets: item diterima/diproses yang dipantau < 30 dtk', () => {
  const started = new Map([['a', 0], ['b', 0], ['c', 10000]]);
  const items = [{ id: 'a', status: 'diproses' }, { id: 'b', status: 'siap' }, { id: 'c', status: 'diterima' }, { id: 'd', status: 'diproses' }];
  assert.deepEqual(pollTargets(items, started, 29999), ['a', 'c']);
  assert.deepEqual(pollTargets(items, started, 30000), ['c']);
  assert.deepEqual(pollTargets(items, started, 40000), []);
  assert.deepEqual(pollTargets(undefined, started, 0), []);
  assert.deepEqual(pollTargets(items, undefined, 0), []);
});

test('fetchPendingDetails (D5): bukti menunggu + detail baru kartu siap yang hilang dari daftar (dicatat/dilewati di tempat lain)', async () => {
  const items = [
    { id: 'a', status: 'siap' }, { id: 'b', status: 'siap' }, { id: 'c', status: 'siap' }, { id: 'd', status: 'diproses' },
    { id: 'e', status: 'tercatat' }, { id: 'f', status: 'siap' },
  ];
  const asked = [];
  const out = await fetchPendingDetails({
    items, handled: new Set(['c']),
    loadPending: async () => [{ id: 'a', status: 'siap', x: 1 }, { id: 'n', status: 'siap' }],
    loadItem: async (id) => { asked.push(id); return id === 'b' ? { id: 'b', status: 'tercatat' } : null; },
  });
  assert.deepEqual(asked, ['b', 'f'], 'hanya kartu siap yang belum ditangani dan tidak ada di daftar');
  assert.deepEqual(out, [{ id: 'a', status: 'siap', x: 1 }, { id: 'n', status: 'siap' }, { id: 'b', status: 'tercatat' }]);
  const failing = await fetchPendingDetails({ items, handled: new Set(), loadPending: async () => { throw new Error('x'); }, loadItem: async () => { throw new Error('y'); } });
  assert.deepEqual(failing, []);
});

test('pageFinished: Ke Transaksi saat tidak ada kartu siap yang belum ditangani, tidak ada unggahan dan pantauan', () => {
  const handled = new Set(['a']);
  const base = { handled, running: false, polling: false };
  assert.equal(pageFinished({ ...base, items: [] }), true);
  assert.equal(pageFinished({ ...base, items: [{ id: 'a', status: 'siap' }] }), true);
  assert.equal(pageFinished({ ...base, items: [{ id: 'a', status: 'siap' }, { id: 'b', status: 'siap' }] }), false);
  for (const status of ['gagal', 'tercatat', 'dilewati', 'kedaluwarsa', 'diproses', 'diterima']) {
    assert.equal(pageFinished({ ...base, items: [{ id: 'b', status }] }), true, status);
  }
  assert.equal(pageFinished({ ...base, items: [], running: true }), false);
  assert.equal(pageFinished({ ...base, items: [{ id: 'b', status: 'diproses' }], polling: true }), false);
  assert.equal(pageFinished({ items: [{ id: 'b', status: 'siap' }] }), false);
});

// ── Satu putaran pada satu waktu, rantai pantau (D5, D8): aturan halaman di luar JSX ──────────────────────

// Janji yang diselesaikan dari luar; flush = biarkan semua janji yang siap berjalan.
const deferred = () => { let resolve; const promise = new Promise((r) => { resolve = r; }); return { promise, resolve }; };
const flush = () => new Promise(r => setImmediate(r));

test('serialRuns (D8): start() selama putaran berjalan → tepat satu putaran lagi sesudahnya, tidak pernah bersamaan', async () => {
  const gates = [];
  let runs = 0;
  let running = 0;
  let maxRunning = 0;
  const start = serialRuns(async () => {
    runs += 1;
    running += 1;
    maxRunning = Math.max(maxRunning, running);
    const gate = deferred();
    gates.push(gate);
    await gate.promise;
    running -= 1;
  });
  const first = start();
  await flush();
  assert.equal(runs, 1);
  start(); // dua event `online` di tengah putaran
  start();
  await flush();
  assert.equal(runs, 1, 'tidak ada putaran kedua yang bersamaan');
  gates[0].resolve();
  await flush();
  assert.equal(runs, 2, 'satu putaran susulan untuk semua start() selama putaran pertama');
  gates[1].resolve();
  await first;
  assert.equal(runs, 2);
  assert.equal(maxRunning, 1);
  const again = start(); // antrean kosong → putaran baru
  await flush();
  assert.equal(runs, 3);
  gates[2].resolve();
  await again;
});

test('serialRuns: halaman ditutup → tidak ada putaran baru; putaran yang melempar tidak memutus antrean', async () => {
  let open = true;
  let runs = 0;
  const gate = deferred();
  const start = serialRuns(async () => { runs += 1; if (runs === 1) await gate.promise; }, { alive: () => open });
  const first = start();
  await flush();
  start(); // susulan diminta …
  open = false; // … lalu halaman ditutup
  gate.resolve();
  await first;
  assert.equal(runs, 1, 'susulan batal saat halaman ditutup');
  await start();
  assert.equal(runs, 1, 'start() sesudah ditutup tidak menjalankan apa pun');

  let calls = 0;
  const gate2 = deferred();
  const flaky = serialRuns(async () => {
    calls += 1;
    if (calls === 1) {
      await gate2.promise;
      throw new Error('putaran gagal');
    }
  });
  const p = flaky();
  await flush();
  flaky();
  gate2.resolve();
  await assert.doesNotReject(p);
  assert.equal(calls, 2, 'susulan tetap jalan sesudah putaran yang melempar');
  await assert.doesNotReject(flaky());
  assert.equal(calls, 3);
});

// Timer tiruan: fire() menjalankan callback terjadwal yang tertua dan menunggu janjinya.
function fakeTimers() {
  let seq = 0;
  const pending = new Map();
  const delays = [];
  const cleared = [];
  return {
    setTimer: (fn, ms) => { seq += 1; pending.set(seq, fn); delays.push(ms); return seq; },
    clearTimer: (h) => { cleared.push(h); pending.delete(h); },
    pending: () => pending.size,
    delays,
    cleared,
    fire() {
      const [h, fn] = pending.entries().next().value;
      pending.delete(h);
      return fn();
    },
  };
}

function pollerDeps(over = {}) {
  const t = fakeTimers();
  const log = { asked: [], got: [], running: [] };
  const deps = {
    targets: () => ['a'],
    fetchItem: async (id) => { log.asked.push(id); return { id, status: 'diproses' }; },
    onDetails: list => log.got.push(list),
    onRunning: on => log.running.push(on),
    setTimer: t.setTimer,
    clearTimer: t.clearTimer,
    ...over,
  };
  return { t, log, deps };
}

test('createPoller (D5): GET tiap 1,5 dtk untuk semua item yang dipantau, satu rantai, berhenti begitu tidak ada target', async () => {
  let targets = ['a', 'b'];
  const { t, log, deps } = pollerDeps({
    targets: () => targets,
    fetchItem: async (id) => { log.asked.push(id); return id === 'b' ? null : { id, status: 'diproses' }; },
  });
  const poller = createPoller(deps);
  assert.equal(poller.start(), true);
  assert.equal(poller.start(), false, 'satu rantai saja');
  assert.equal(poller.running, true);
  assert.deepEqual(log.running, [true]);
  assert.deepEqual(t.delays, [1500], 'GET pertama sesudah 1,5 dtk');
  assert.deepEqual(log.asked, []);
  await t.fire();
  assert.deepEqual(log.asked, ['a', 'b']);
  assert.deepEqual(log.got, [[{ id: 'a', status: 'diproses' }]], 'null (404/gagal) dibuang');
  assert.deepEqual(t.delays, [1500, 1500]);
  targets = ['a'];
  await t.fire();
  assert.deepEqual(log.asked, ['a', 'b', 'a']);
  assert.equal(t.pending(), 1);
  targets = []; // item terakhir lewat 30 dtk (atau saklar mati)
  await t.fire();
  assert.deepEqual(log.asked, ['a', 'b', 'a'], 'tanpa target tidak ada GET');
  assert.equal(log.got.length, 2, 'tanpa target tidak ada detail');
  assert.equal(t.pending(), 0);
  assert.equal(poller.running, false);
  assert.deepEqual(log.running, [true, false]);
});

test('createPoller: detail yang membuat target habis menghentikan rantai saat itu juga (tanpa timer kosong)', async () => {
  let targets = ['a'];
  const { t, log, deps } = pollerDeps({ targets: () => targets });
  deps.onDetails = (list) => { log.got.push(list); targets = []; }; // induk menggabungkan: item jadi siap
  const poller = createPoller(deps);
  poller.start();
  await t.fire();
  assert.deepEqual(log.asked, ['a']);
  assert.equal(t.pending(), 0);
  assert.deepEqual(log.running, [true, false]);
  targets = ['c']; // item baru yang masih dibaca → rantai baru
  assert.equal(poller.start(), true);
  assert.deepEqual(log.running, [true, false, true]);
});

test('createPoller: tanpa target tidak mulai; fetchItem melempar → dianggap null, rantai lanjut', async () => {
  const none = pollerDeps({ targets: () => [] });
  const idle = createPoller(none.deps);
  assert.equal(idle.start(), false);
  assert.equal(none.t.pending(), 0);
  assert.deepEqual(none.log.running, []);

  let n = 0;
  const { t, log, deps } = pollerDeps({ fetchItem: async () => { n += 1; if (n === 1) throw new Error('jaringan'); return { id: 'a', status: 'siap' }; } });
  const poller = createPoller(deps);
  poller.start();
  await t.fire();
  assert.deepEqual(log.got, [[]]);
  assert.equal(t.pending(), 1, 'tetap dipantau');
  await t.fire();
  assert.deepEqual(log.got, [[], [{ id: 'a', status: 'siap' }]]);
});

test('createPoller (D5): stop() saat halaman dilepas membatalkan timer; GET yang sedang berjalan tidak menjadwalkan GET baru', async () => {
  const waiting = pollerDeps();
  const poller = createPoller(waiting.deps);
  poller.start();
  poller.stop();
  assert.deepEqual(waiting.t.cleared, [1]);
  assert.equal(waiting.t.pending(), 0);
  assert.equal(poller.running, false);
  assert.equal(poller.start(), false, 'sesudah stop() tidak bisa dimulai lagi');
  assert.deepEqual(waiting.log.asked, []);

  const gate = deferred();
  const { t, log, deps } = pollerDeps({ fetchItem: async (id) => { log.asked.push(id); await gate.promise; return { id, status: 'siap' }; } });
  const inFlight = createPoller(deps);
  inFlight.start();
  const tick = t.fire(); // GET berjalan …
  await flush();
  inFlight.stop(); // … halaman dilepas
  gate.resolve();
  await tick;
  assert.deepEqual(log.asked, ['a']);
  assert.deepEqual(log.got, [], 'jawaban yang tiba sesudah dilepas diabaikan');
  assert.equal(t.pending(), 0, 'tidak ada GET baru');
  assert.deepEqual(log.running, [true], 'tidak ada pembaruan tampilan sesudah dilepas');
});

// ── Perbaikan putaran 1 (review B5): antrean tidak macet, file terlalu besar, respons tanpa item, Kirim lagi ──────

test('uploadOutcome (m3): 2xx tanpa item (bukan jawaban Kotak Struk) → disimpan, entri tidak dihapus', () => {
  for (const data of [{}, [], { detail: 'x' }, { id: '' }, null, undefined]) {
    assert.deepEqual(uploadOutcome({ ok: true, status: 200, data }), { action: 'keep', message: KEEP_TEXT }, JSON.stringify(data));
  }
});

test('runSharePage (m3): 2xx tanpa item → entri tetap di HP, tidak ada kartu', async () => {
  const { deps, store, items } = pageDeps({ entries: [shareEntry('a', 'b1', 1)], replies: { a: { ok: true, status: 200, data: {} } } });
  const out = await runSharePage(deps);
  assert.equal(out.kept, KEEP_TEXT);
  assert.deepEqual([out.items, items], [[], []]);
  assert.deepEqual([...store.map.keys()], ['a']);
});

test('pageView: "Kirim lagi" sesudah putaran berhenti dengan entri disimpan, atau entri ditahan; tidak selama putaran berjalan', () => {
  assert.equal(pageView({ mode: 'send', kept: KEEP_TEXT }).retry, true);
  assert.equal(pageView({ mode: 'send', kept: 'Terlalu banyak bukti. Coba lagi sebentar.' }).retry, true);
  assert.equal(pageView({ mode: 'send', kept: KEEP_TEXT, running: true }).retry, false);
  assert.equal(pageView({ mode: 'send' }).retry, false);
  assert.equal(pageView({ mode: 'hold', waiting: 1 }).retry, true);
  assert.equal(pageView({ mode: 'hold', waiting: 1, running: true }).retry, false);
  assert.equal(pageView({ mode: 'hold', waiting: 0 }).retry, false);
  assert.equal(pageView({ mode: 'off', kept: KEEP_TEXT, waiting: 2 }).retry, false);
  assert.equal(pageView({ mode: null, kept: KEEP_TEXT, waiting: 2 }).retry, false);
});

test('nextToUpload (m1): yang belum pernah dicoba dulu, lalu yang paling lama tidak dicoba; yang setara menurut urutan share', () => {
  const e = (id, createdAt, seq, triedAt) => ({ id, createdAt, seq, ...(triedAt ? { triedAt } : {}) });
  assert.equal(nextToUpload([e('racun', 1, 0, 500), e('baik', 2, 0)]).id, 'baik', 'entri yang gagal pindah ke belakang');
  assert.equal(nextToUpload([e('a', 1, 0, 900), e('b', 2, 0, 700)]).id, 'b', 'paling lama tidak dicoba');
  assert.equal(nextToUpload([e('a', 2, 0, 700), e('b', 1, 1, 700), e('c', 1, 0, 700)]).id, 'c', 'triedAt sama → share tertua, urutan dibagikan');
  assert.equal(nextToUpload([e('x', 5, 0), e('y', 3, 2), e('z', 3, 1)]).id, 'z', 'belum ada yang dicoba → urutan lama');
});

test('runSharePage (m1): keep mencatat triedAt pada entri; putaran berikutnya mendahulukan entri lain (satu file rusak tidak menahan antrean)', async () => {
  let t = 1000;
  const { deps, calls, store } = pageDeps({
    entries: [shareEntry('racun', 'b1', 1), shareEntry('baik', 'b2', 2)],
    replies: { racun: { ok: false, status: 500, data: {} } },
  });
  deps.now = () => t;
  const first = await runSharePage(deps);
  assert.equal(first.kept, KEEP_TEXT);
  assert.deepEqual(calls, ['config', 'upload:racun', 'pending'], 'putaran tetap berhenti pada keep');
  assert.equal(store.map.get('racun').triedAt, 1000);
  assert.equal(store.map.get('baik').triedAt, undefined);
  t = 2000;
  calls.length = 0;
  const second = await runSharePage(deps);
  assert.deepEqual(calls, ['config', 'upload:baik', 'upload:racun', 'pending'], 'yang belum dicoba dulu');
  assert.deepEqual(second.items.map(i => i.id), ['item-baik']);
  assert.deepEqual([...store.map.keys()], ['racun']);
  assert.equal(store.map.get('racun').triedAt, 2000);
});

test('runSharePage (m1): entri yang dihapus selama unggahan (logout) tidak dihidupkan lagi oleh triedAt', async () => {
  const { deps, store } = pageDeps({ entries: [shareEntry('a', 'b1', 1)] });
  deps.upload = async () => { await store.clear(); return { ok: false, status: 0, data: {} }; }; // logout di tengah unggahan
  const out = await runSharePage(deps);
  assert.equal(out.kept, KEEP_TEXT);
  assert.equal(store.map.size, 0);
});

test('shareStore.touch (m1): mengubah entri yang masih ada; entri yang sudah dihapus (logout, tab lain) tidak dibuat ulang', async () => {
  for (const s of [shareStore(fakeIndexedDB()), shareStore(null)]) { // IndexedDB tiruan, lalu store memori
    await s.put({ id: 'a', text: 'Rp1' });
    assert.equal(await s.touch('a', { triedAt: 5 }), true);
    assert.deepEqual(await s.all(), [{ id: 'a', text: 'Rp1', triedAt: 5 }]);
    await clearShares(s);
    assert.equal(await s.touch('a', { triedAt: 6 }), false);
    assert.deepEqual(await s.all(), [], 'tidak dibuat ulang');
  }
});

const MiB = 1024 * 1024;
const HEAD = {
  pdf: [0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x34],
  jpg: [0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10],
  png: [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
  webp: [0x52, 0x49, 0x46, 0x46, 0x24, 0x00, 0x00, 0x00, 0x57, 0x45, 0x42, 0x50],
  heic: [0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70, 0x68, 0x65, 0x69, 0x63],
};
// File besar tiruan tanpa mengalokasikan isinya: `size` + `slice()` byte awal (Blob kecil sungguhan); atau tidak terbaca.
const bigBlob = (size, head, type = '') => ({ size, type, slice: (a = 0, b = head.length) => new Blob([new Uint8Array(head.slice(a, b))]) });
const unreadableBlob = (size, type = '') => ({ size, type, slice: () => { throw new DOMException('rusak', 'NotReadableError'); } });

test('sniffShareType: jenis dari byte awal seperti server (JPG/PNG/WebP/PDF); lainnya, terlalu pendek, atau kosong → null', () => {
  assert.equal(sniffShareType(new Uint8Array(HEAD.jpg)), 'image/jpeg');
  assert.equal(sniffShareType(new Uint8Array(HEAD.png)), 'image/png');
  assert.equal(sniffShareType(new Uint8Array(HEAD.webp)), 'image/webp');
  assert.equal(sniffShareType(new Uint8Array(HEAD.pdf)), 'application/pdf');
  assert.equal(sniffShareType(new Uint8Array(HEAD.pdf).buffer), 'application/pdf', 'ArrayBuffer');
  const riffAvi = [0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x41, 0x56, 0x49, 0x20];
  for (const head of [HEAD.heic, riffAvi, HEAD.webp.slice(0, 11), [0xff, 0xd8], [0x89, 0x50, 0x4e], [0x25, 0x50, 0x44, 0x46], []]) {
    assert.equal(sniffShareType(new Uint8Array(head)), null, JSON.stringify(head));
  }
  assert.equal(sniffShareType(null), null);
});

test('oversizeMessage (m1): file > 10 MB → pesan server untuk isinya; byte awal tak terbaca → menurut tipe; ≤ 10 MB atau teks → null', () => {
  const over = 10 * MiB + 1;
  const e = (type, size = over) => ({ id: 'x', name: 'x', type, blob: { size, type } });
  const h = k => new Uint8Array(HEAD[k]);
  assert.equal(SHARE_TEXT.pdfTooBig, 'PDF terlalu besar (maks 10 MB)'); // = MSG_PDF_BIG server (intake.py)
  assert.equal(SHARE_TEXT.photoTooBig, 'Foto terlalu besar (maks 8 MB)'); // = MSG_IMAGE_BIG
  assert.equal(SHARE_TEXT.badType, 'Kirim foto (JPG/PNG/WebP), PDF, atau teks'); // = MSG_TYPE
  assert.equal(oversizeMessage(e('application/pdf'), h('pdf')), SHARE_TEXT.pdfTooBig);
  assert.equal(oversizeMessage(e(''), h('pdf')), SHARE_TEXT.pdfTooBig, 'tanpa tipe: isinya yang menentukan, seperti server');
  for (const k of ['jpg', 'png', 'webp']) assert.equal(oversizeMessage(e('image/jpeg'), h(k)), SHARE_TEXT.photoTooBig, k);
  assert.equal(oversizeMessage(e('application/pdf'), h('jpg')), SHARE_TEXT.photoTooBig, 'tipe keliru: isinya yang menentukan');
  assert.equal(oversizeMessage(e('image/heic'), h('heic')), SHARE_TEXT.badType, 'isi tidak dikenal: 415 server');
  assert.equal(oversizeMessage(e('application/pdf'), null), SHARE_TEXT.pdfTooBig, 'tidak terbaca → tipe yang dibagikan');
  for (const type of ['image/jpeg', 'image/heic', '', 'application/octet-stream']) {
    assert.equal(oversizeMessage(e(type), null), SHARE_TEXT.photoTooBig, type);
  }
  assert.equal(oversizeMessage({ id: 'x', type: '', blob: { size: over, type: 'application/pdf' } }, null), SHARE_TEXT.pdfTooBig, 'tipe Blob');
  assert.equal(oversizeMessage(e('application/pdf', 10 * MiB), h('pdf')), null, 'tepat 10 MB (= PDF_MAX_BYTES server) tetap diunggah');
  assert.equal(oversizeMessage(e('image/jpeg', 9 * MiB), h('jpg')), null, 'foto 8–10 MB: server yang memutuskan');
  assert.equal(oversizeMessage({ id: 't', text: 'x'.repeat(5000) }, null), null, 'teks tidak pernah dibuang di HP');
  assert.equal(oversizeMessage(undefined, null), null);
});

test('runSharePage (m1): file > 10 MB dibuang di HP tanpa diunggah, dengan pesan server; putaran lanjut ke entri berikutnya', async () => {
  const over = 10 * MiB + 1;
  const { deps, calls, store } = pageDeps({
    entries: [
      shareEntry('pdf', 'b1', 1, 0, { name: 'mutasi.pdf', type: 'application/pdf', blob: bigBlob(over, HEAD.pdf, 'application/pdf') }),
      shareEntry('foto', 'b1', 1, 1, { name: 'struk.jpg', type: 'image/jpeg', blob: bigBlob(15 * MiB, HEAD.jpg, 'image/jpeg') }),
      shareEntry('heic', 'b1', 1, 2, { name: 'IMG_1.heic', type: 'image/heic', blob: bigBlob(over, HEAD.heic, 'image/heic') }),
      shareEntry('rusak', 'b1', 1, 3, { name: 'rusak.pdf', type: 'application/pdf', blob: unreadableBlob(over, 'application/pdf') }),
      shareEntry('pas', 'b1', 1, 4, { name: 'pas.pdf', type: 'application/pdf', blob: bigBlob(10 * MiB, HEAD.pdf, 'application/pdf') }),
    ],
  });
  const out = await runSharePage(deps);
  assert.deepEqual(calls, ['config', 'upload:pas', 'pending'], 'hanya file ≤ 10 MB yang diunggah');
  assert.deepEqual(out.dropped, [
    { name: 'mutasi.pdf', message: 'PDF terlalu besar (maks 10 MB)' },
    { name: 'struk.jpg', message: 'Foto terlalu besar (maks 8 MB)' },
    { name: 'IMG_1.heic', message: 'Kirim foto (JPG/PNG/WebP), PDF, atau teks' },
    { name: 'rusak.pdf', message: 'PDF terlalu besar (maks 10 MB)' },
  ]);
  assert.equal(out.kept, null);
  assert.deepEqual(out.items.map(i => i.id), ['item-pas']);
  assert.equal(store.map.size, 0, 'entri yang dibuang dihapus dari HP');
});

// ── Review akhir Bagian B: pemilik kotak (R1), antrean offline (R2), Hapus (R5), batas waktu baca (R6) ────────────

// localStorage tiruan: `writes` mencatat setiap setItem.
function memStorage(init = {}) {
  const map = new Map(Object.entries(init));
  const writes = [];
  return {
    map, writes,
    getItem: k => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { writes.push([k, String(v)]); map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); },
  };
}
// Kotak share tiruan yang menghitung clear(); `hold` (opsional) menahan clear sampai janjinya selesai.
function countedBox(entries = [], { hold = null } = {}) {
  const store = memStore();
  for (const e of entries) store.map.set(e.id, e);
  let clears = 0;
  const clear = store.clear;
  store.clear = async () => { clears += 1; if (hold) await hold; return clear(); };
  return { store, clears: () => clears };
}
const tick = () => new Promise(r => setImmediate(r));
async function until(cond, n = 200) {
  for (let i = 0; i < n && !cond(); i += 1) await tick();
  assert.ok(cond(), 'kondisi tidak tercapai');
}
const OWNER = 'jatahku_share_owner';

test('shareOwnerAction (R1): belum ada pemilik → claim; akun yang sama → keep; akun lain → clear', () => {
  assert.equal(SHARE_OWNER_KEY, OWNER);
  for (const stored of [null, undefined, '']) assert.equal(shareOwnerAction(stored, 'u-b'), 'claim', String(stored));
  assert.equal(shareOwnerAction('u-a', 'u-a'), 'keep');
  assert.equal(shareOwnerAction('u-a', 'u-b'), 'clear');
  assert.equal(shareOwnerAction('42', 42), 'keep', 'localStorage menyimpan teks');
});

test('ensureShareOwner (R1): claim menulis pemilik; keep tidak menulis; akun lain → kotak dikosongkan, lalu pemilik baru', async () => {
  const claim = countedBox([shareEntry('a', 'b1', 1)]);
  const s1 = memStorage();
  assert.equal(await ensureShareOwner(claim.store, 'u-a', { storage: s1 }), true);
  assert.deepEqual(s1.writes, [[OWNER, 'u-a']]);
  assert.deepEqual([claim.store.map.size, claim.clears()], [1, 0], 'kotak tanpa pemilik diklaim, tidak dikosongkan');

  const keep = countedBox([shareEntry('a', 'b1', 1)]);
  const s2 = memStorage({ [OWNER]: 'u-a' });
  assert.equal(await ensureShareOwner(keep.store, 'u-a', { storage: s2 }), true);
  assert.deepEqual([s2.writes, keep.store.map.size, keep.clears()], [[], 1, 0]);

  const other = countedBox([shareEntry('a', 'b1', 1), shareEntry('b', 'b1', 1, 1)]);
  const s3 = memStorage({ [OWNER]: 'u-a' });
  assert.equal(await ensureShareOwner(other.store, 'u-b', { storage: s3 }), true);
  assert.deepEqual([other.store.map.size, other.clears(), s3.map.get(OWNER)], [0, 1, 'u-b']);
});

test('ensureShareOwner (R1): pemilik baru ditulis SESUDAH kotak akun lain kosong; hapus gagal → false, pemilik tetap', async () => {
  let release;
  const hold = new Promise((r) => { release = r; });
  const box = countedBox([shareEntry('a', 'b1', 1)], { hold });
  const storage = memStorage({ [OWNER]: 'u-a' });
  const p = ensureShareOwner(box.store, 'u-b', { storage });
  await tick();
  assert.equal(box.clears(), 1);
  assert.deepEqual([storage.writes, storage.map.get(OWNER), box.store.map.size], [[], 'u-a', 1], 'belum ditulis selama penghapusan berjalan');
  release();
  assert.equal(await p, true);
  assert.deepEqual([storage.map.get(OWNER), box.store.map.size], ['u-b', 0]);

  const failing = { all: async () => [shareEntry('a', 'b1', 1)], clear: async () => { throw new Error('UnknownError'); } };
  const s2 = memStorage({ [OWNER]: 'u-a' });
  assert.equal(await ensureShareOwner(failing, 'u-b', { storage: s2 }), false);
  assert.deepEqual([s2.writes, s2.map.get(OWNER)], [[], 'u-a'], 'tanpa pemilik baru: berikutnya dicoba lagi');
});

test('ensureShareOwner (R1): banner dan halaman bersamaan → dikosongkan paling banyak dua kali, entri akun lain tidak terbaca', async () => {
  let release;
  const hold = new Promise((r) => { release = r; });
  const box = countedBox([shareEntry('a', 'b1', 1), shareEntry('b', 'b2', 2)], { hold });
  const storage = memStorage({ [OWNER]: 'u-a' });
  const owned = ownerGate(box.store, 'u-b', { storage });   // banner: refresh yang bertumpuk
  const banner = () => ownedShares(box.store, owned);
  // Halaman: satu pemeriksaan per putaran, dan putarannya berurutan (serialRuns).
  const page = async () => ((await ensureShareOwner(box.store, 'u-b', { storage })) ? box.store.all() : null);
  const reads = Promise.all([banner(), page(), banner()]);
  await tick();
  release();
  const got = await reads;
  assert.ok(box.clears() <= 2, `clear ${box.clears()}×`);
  for (const r of got) assert.deepEqual(r, [], 'tidak ada entri akun sebelumnya yang terbaca');
  assert.equal(storage.map.get(OWNER), 'u-b');
  // Share baru milik akun ini (sesudah ganti akun) tetap: pemeriksaan berikutnya "keep".
  await box.store.put(shareEntry('n', 'b9', 9));
  assert.deepEqual((await banner()).map(e => e.id), ['n']);
  assert.equal(await ensureShareOwner(box.store, 'u-b', { storage }), true);
  assert.deepEqual([...box.store.map.keys()], ['n']);
});

test('ensureShareOwner (R1): tanpa user, atau penyimpanan yang melempar/tidak ada → false; kotak tidak disentuh; tidak pernah melempar', async () => {
  for (const userId of [null, undefined, '']) {
    const box = countedBox([shareEntry('a', 'b1', 1)]);
    const storage = memStorage({ [OWNER]: 'u-a' });
    assert.equal(await ensureShareOwner(box.store, userId, { storage }), false, String(userId));
    assert.deepEqual([box.store.map.size, box.clears(), storage.writes], [1, 0, []]);
  }
  const blocked = { getItem: () => { throw new Error('SecurityError'); }, setItem: () => { throw new Error('SecurityError'); } };
  const box = countedBox([shareEntry('a', 'b1', 1)]);
  assert.equal(await ensureShareOwner(box.store, 'u-b', { storage: blocked }), false);
  assert.deepEqual([box.store.map.size, box.clears()], [1, 0]);
  // Cap tidak terbaca (getItem melempar) walau bisa ditulis: tidak dianggap "belum ada pemilik".
  const unreadable = { writes: [], getItem: () => { throw new Error('SecurityError'); }, setItem(k, v) { this.writes.push([k, v]); } };
  const box4 = countedBox([shareEntry('a', 'b1', 1)]);
  assert.equal(await ensureShareOwner(box4.store, 'u-b', { storage: unreadable }), false);
  assert.deepEqual([unreadable.writes, box4.store.map.size, box4.clears()], [[], 1, 0]);
  // Pemilik tidak bisa ditulis (penuh): kotak tetap tidak boleh dibaca.
  const full = { getItem: () => null, setItem: () => { throw new Error('QuotaExceededError'); } };
  const box2 = countedBox([shareEntry('a', 'b1', 1)]);
  assert.equal(await ensureShareOwner(box2.store, 'u-b', { storage: full }), false);
  assert.deepEqual([box2.store.map.size, box2.clears()], [1, 0]);
  // Tanpa localStorage (Node, diblokir), opsi null, atau getter storage yang melempar: tetap false, tidak ditolak.
  const box3 = countedBox([shareEntry('a', 'b1', 1)]);
  assert.equal(await ensureShareOwner(box3.store, 'u-b', { storage: null }), false);
  assert.equal(await ensureShareOwner(box3.store, 'u-b'), false);
  assert.equal(await ensureShareOwner(box3.store, 'u-b', null), false);
  assert.equal(await ensureShareOwner(box3.store, 'u-b', { get storage() { throw new Error('SecurityError'); } }), false);
  assert.deepEqual([box3.store.map.size, box3.clears()], [1, 0]);
  // Kotak hilang saat akun lain → false (tidak melempar).
  assert.equal(await ensureShareOwner(null, 'u-b', { storage: memStorage({ [OWNER]: 'u-a' }) }), false);
});

test('ownerGate (R1, banner): refresh bersamaan memakai satu pemeriksaan; sesudah selesai diperiksa lagi (akun berganti di tab lain)', async () => {
  let release;
  const hold = new Promise((r) => { release = r; });
  const box = countedBox([shareEntry('a', 'b1', 1)], { hold });
  const storage = memStorage({ [OWNER]: 'u-a' });
  const owned = ownerGate(box.store, 'u-b', { storage });
  const p1 = owned();
  const p2 = owned();
  assert.equal(p1, p2, 'janji yang sama selama pemeriksaan berjalan');
  release();
  assert.deepEqual(await Promise.all([p1, p2]), [true, true]);
  assert.equal(box.clears(), 1);
  const p3 = owned();
  assert.notEqual(p3, p1);
  assert.equal(await p3, true);
  assert.equal(box.clears(), 1, 'akun yang sama: keep');
  storage.map.set(OWNER, 'u-c');
  await box.store.put(shareEntry('c', 'b3', 3));
  assert.equal(await owned(), true);
  assert.deepEqual([box.clears(), box.store.map.size, storage.map.get(OWNER)], [2, 0, 'u-b']);
});

test('ownedShares (R1): hitungan banner hanya dari kotak milik user ini; bukan miliknya → [] tanpa membaca kotak', async () => {
  let reads = 0;
  const store = { all: async () => { reads += 1; return [shareEntry('a', 'b1', 1)]; } };
  assert.deepEqual(await ownedShares(store, async () => false), []);
  assert.equal(reads, 0);
  assert.deepEqual((await ownedShares(store, async () => true)).map(e => e.id), ['a']);
  assert.equal(reads, 1);
});

// Dependensi halaman dengan log urutan bersama: pemilik, baca kotak, antrean offline, unggah, bukti menunggu.
function loggedPage(opts, { owner = async () => true, queued = async () => new Set() } = {}) {
  const d = pageDeps(opts);
  const log = [];
  const all = d.deps.store.all;
  d.deps.store = { ...d.deps.store, all: async () => { log.push('store'); return all(); } };
  d.deps.ensureOwner = async () => { log.push('owner'); return owner(); };
  d.deps.loadQueued = async () => { log.push('queued'); return queued(); };
  d.deps.onQueued = ids => log.push(`onQueued:${[...ids].join(',')}`);
  const upload = d.deps.upload;
  d.deps.upload = (entry) => { log.push(`upload:${entry.id}`); return upload(entry); };
  const loadPending = d.deps.loadPending;
  d.deps.loadPending = () => { log.push('pending'); return loadPending(); };
  return { ...d, log };
}

test('runSharePage (R1): pemilik diperiksa sebelum kotak dibaca (tahan dan kirim); saklar mati tidak memeriksa pemilik', async () => {
  const off = loggedPage({ flag: false, batchId: 'b1', entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b2', 2)] });
  await runSharePage(off.deps);
  assert.ok(!off.log.includes('owner') && !off.log.includes('queued'), off.log.join(' '));
  assert.deepEqual([...off.store.map.keys()], ['b'], 'saklar mati: tetap hanya batch ?s= yang dihapus');

  const hold = loggedPage({ online: false, entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b2', 2)] });
  assert.equal((await runSharePage(hold.deps)).waiting, 2);
  assert.deepEqual(hold.log, ['owner', 'store']);

  const send = loggedPage({ entries: [shareEntry('a', 'b1', 1)] });
  await runSharePage(send.deps);
  assert.deepEqual(send.log.slice(0, 2), ['owner', 'store']);
});

test('runSharePage (R1): kotak bukan milik user ini (false / melempar) → tidak dibaca dan tidak diunggah; storeFailed; bukti server tetap dimuat', async () => {
  for (const owner of [async () => false, async () => { throw new Error('x'); }]) {
    const send = loggedPage({ entries: [shareEntry('a', 'b1', 1)], pending: [{ id: 'p1', status: 'siap' }] }, { owner });
    const out = await runSharePage(send.deps);
    assert.deepEqual([out.mode, out.storeFailed, out.items, out.pending.map(i => i.id)], ['send', true, [], ['p1']]);
    assert.ok(!send.log.includes('store') && !send.log.some(l => l.startsWith('upload')), send.log.join(' '));
    assert.equal(send.store.map.size, 1);
    const hold = loggedPage({ online: false, entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b2', 2)] }, { owner });
    const outH = await runSharePage(hold.deps);
    assert.deepEqual([outH.mode, outH.waiting, outH.storeFailed], ['hold', 0, true]);
    assert.ok(!hold.log.includes('store'));
  }
});

test('runSharePage (R2): mode kirim membaca id antrean offline sekali, sebelum unggahan dan kartu pertama; mati/tahan tidak', async () => {
  const send = loggedPage({ entries: [shareEntry('a', 'b1', 1)], pending: [{ id: 'p1', status: 'siap' }] }, { queued: async () => new Set(['p1']) });
  const out = await runSharePage(send.deps);
  assert.deepEqual(send.log, ['owner', 'store', 'queued', 'onQueued:p1', 'upload:a', 'pending']);
  assert.deepEqual([...out.queued], ['p1']);
  for (const opts of [{ flag: false }, { online: false }, { flag: null }]) {
    const d = loggedPage(opts);
    const o = await runSharePage(d.deps);
    assert.ok(!d.log.includes('queued'), JSON.stringify(opts));
    assert.deepEqual([...o.queued], []);
  }
  const bad = loggedPage({}, { queued: async () => { throw new Error('x'); } });
  const o = await runSharePage(bad.deps);
  assert.deepEqual([...o.queued], []);
  assert.ok(bad.log.includes('onQueued:'), 'gagal membaca antrean → Set kosong');
});

test('keptEntries (R5): entri tertahan untuk daftar Hapus — nama file, "teks" untuk teks, urutan share', () => {
  assert.equal(SHARE_TEXT.remove, 'Hapus');
  assert.equal(SHARE_TEXT.textEntry, 'teks');
  const list = keptEntries([
    shareEntry('c', 'b2', 2, 1, { name: '' }),
    shareEntry('t', 'b1', 1, 1, { blob: undefined, name: '', text: 'Transfer Rp150.000', type: 'text/plain' }),
    shareEntry('a', 'b1', 1, 0, { name: 'mutasi.pdf' }),
    null,
    { name: 'tanpa-id.jpg' },
  ]);
  assert.deepEqual(list, [{ id: 'a', label: 'mutasi.pdf' }, { id: 't', label: 'teks' }, { id: 'c', label: 'bukti' }]);
  for (const bad of [null, undefined, 'x', {}]) assert.deepEqual(keptEntries(bad), [], String(bad));
});

test('runSharePage (R5): putaran berhenti dengan keep → entri yang tertahan di kotak (dibaca ulang); tanpa keep → []', async () => {
  const kept = pageDeps({
    entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b2', 2), shareEntry('c', 'b3', 3, 0, { blob: undefined, name: '', text: 'Rp1' })],
    replies: { b: { ok: false, status: 0, data: {} } },
  });
  const out = await runSharePage(kept.deps);
  assert.equal(out.kept, KEEP_TEXT);
  assert.deepEqual(out.keptEntries, [{ id: 'b', label: 'b.jpg' }, { id: 'c', label: 'teks' }], 'a terkirim; b tertahan; c belum dicoba');
  // Kotak tidak terbaca ulang → sisa putaran ini (tanpa yang sudah terkirim/dibuang).
  const reread = pageDeps({ entries: [shareEntry('a', 'b1', 1), shareEntry('b', 'b2', 2)], replies: { b: { ok: false, status: 503, data: {} } } });
  let reads = 0;
  const all = reread.deps.store.all;
  reread.deps.store = { ...reread.deps.store, all: async () => { reads += 1; if (reads > 1) throw new Error('x'); return all(); } };
  assert.deepEqual((await runSharePage(reread.deps)).keptEntries.map(e => e.id), ['b']);
  for (const opts of [{ entries: [shareEntry('a', 'b1', 1)] }, { online: false, entries: [shareEntry('a', 'b1', 1)] }, { flag: false }]) {
    assert.deepEqual((await runSharePage(pageDeps(opts).deps)).keptEntries, [], JSON.stringify(opts));
  }
});

test('discardKept (R5): Hapus membuang satu entri lalu menghitung ulang; hapus gagal → tetap terdaftar; kotak tak terbaca → []', async () => {
  const store = memStore();
  for (const e of [shareEntry('a', 'b1', 1), shareEntry('b', 'b1', 1, 1)]) await store.put(e);
  assert.deepEqual(await discardKept(store, 'a'), [{ id: 'b', label: 'b.jpg' }]);
  assert.deepEqual([...store.map.keys()], ['b']);
  assert.deepEqual(await discardKept(store, 'b'), []);
  const stuck = { all: async () => [shareEntry('a', 'b1', 1)], del: async () => { throw new Error('UnknownError'); } };
  assert.deepEqual(await discardKept(stuck, 'a'), [{ id: 'a', label: 'a.jpg' }]);
  const broken = { all: async () => { throw new Error('x'); }, del: async () => {} };
  assert.deepEqual(await discardKept(broken, 'a'), []);
  await assert.doesNotReject(discardKept(null, 'a'));
});

test('pageView (R5): daftar Hapus hanya sesudah putaran berhenti dengan entri tertahan (mode kirim, tidak sedang berjalan)', () => {
  const keptList = [{ id: 'b', label: 'b.jpg' }];
  assert.equal(pageView({ mode: 'send', kept: KEEP_TEXT, keptList }).discard, true);
  assert.equal(pageView({ mode: 'send', kept: KEEP_TEXT, keptList, running: true }).discard, false);
  assert.equal(pageView({ mode: 'send', kept: null, keptList }).discard, false);
  assert.equal(pageView({ mode: 'send', kept: KEEP_TEXT, keptList: [] }).discard, false);
  assert.equal(pageView({ mode: 'send', kept: KEEP_TEXT }).discard, false);
  for (const mode of ['hold', 'off', null]) {
    assert.equal(pageView({ mode, waiting: 1, kept: KEEP_TEXT, keptList }).discard, false, String(mode));
  }
});

test('withTimeout (R6): nilai atau penolakan sebelum batas waktu; sesudahnya cadangan; jawaban terlambat diabaikan', async () => {
  const t = fakeTimers();
  assert.equal(await withTimeout(Promise.resolve(5), 1000, 'x', t), 5);
  assert.deepEqual([t.delays, t.cleared, t.pending()], [[1000], [1], 0], 'timer dibersihkan begitu ada jawaban');
  await assert.rejects(withTimeout(Promise.reject(new Error('boom')), 1000, 'x', t), /boom/);
  assert.equal(t.pending(), 0);
  let late;
  const p = withTimeout(new Promise((r) => { late = r; }), 20000, null, t);
  assert.equal(t.delays.at(-1), 20000);
  t.fire();
  assert.equal(await p, null);
  late('terlambat');
  await tick();
  assert.equal(await p, null);
  assert.equal(await withTimeout('langsung', 10, 'x', t), 'langsung');
});

test('pageReads (R6): config 10 dtk → config cache atau null (ditahan); bukti menunggu 20 dtk → []; satu item 20 dtk → null', async () => {
  assert.deepEqual([CONFIG_WAIT_MS, READ_WAIT_MS], [10000, 20000]);
  const t = fakeTimers();
  const never = () => new Promise(() => {});
  const cached = { features: { receipt_inbox: true } };
  const hang = pageReads({ getConfig: never, cachedConfig: () => cached, loadPending: never, loadItem: never }, t);
  const c = hang.config();
  assert.equal(t.delays.at(-1), CONFIG_WAIT_MS);
  t.fire();
  assert.equal(await c, cached);
  const pl = hang.pending();
  assert.equal(t.delays.at(-1), READ_WAIT_MS);
  t.fire();
  assert.deepEqual(await pl, []);
  const it = hang.item('i1');
  assert.equal(t.delays.at(-1), READ_WAIT_MS);
  t.fire();
  assert.equal(await it, null);
  // Tanpa cache (atau cache tak terbaca) → null: saklar belum diketahui → ditahan seperti offline.
  for (const cachedConfig of [() => null, () => { throw new Error('x'); }]) {
    const r = pageReads({ getConfig: never, cachedConfig, loadPending: never, loadItem: never }, t);
    const p = r.config();
    t.fire();
    const config = await p;
    assert.equal(config, null);
    assert.equal(sharePageMode({ flag: shareFlag(config), online: true }), 'hold');
  }
  // Jawaban yang tepat waktu dipakai; id diteruskan; tidak ada timer yang tertinggal.
  const asked = [];
  const ok = pageReads({
    getConfig: async () => ({ features: { receipt_inbox: false } }), cachedConfig: () => cached,
    loadPending: async () => [{ id: 'p1' }], loadItem: async (id) => { asked.push(id); return { id, status: 'siap' }; },
  }, t);
  assert.deepEqual(await ok.config(), { features: { receipt_inbox: false } });
  assert.deepEqual(await ok.pending(), [{ id: 'p1' }]);
  assert.deepEqual(await ok.item('i9'), { id: 'i9', status: 'siap' });
  assert.deepEqual([asked, t.pending()], [['i9'], 0]);
});

test('runSharePage + pageReads (R6): config dan daftar bukti menunggu yang menggantung → putaran tetap selesai (Kirim lagi / Ke Transaksi)', async () => {
  const never = () => new Promise(() => {});
  // Config menggantung, tanpa cache → ditahan: jumlah menunggu dan "Kirim lagi".
  const t1 = fakeTimers();
  const hold = pageDeps({ entries: [shareEntry('a', 'b1', 1)] });
  hold.deps.getConfig = pageReads({ getConfig: never, cachedConfig: () => null, loadPending: never, loadItem: never }, t1).config;
  const p1 = runSharePage(hold.deps);
  await until(() => t1.pending() === 1);
  t1.fire();
  const out1 = await p1;
  assert.deepEqual([out1.mode, out1.waiting], ['hold', 1]);
  assert.equal(pageView({ mode: out1.mode, waiting: out1.waiting }).retry, true);
  // Config menggantung, cache menyala → kirim; daftar bukti menunggu menggantung → [] sesudah 20 dtk → Ke Transaksi.
  const t2 = fakeTimers();
  const reads = pageReads({ getConfig: never, cachedConfig: () => ({ features: { receipt_inbox: true } }), loadPending: never, loadItem: never }, t2);
  const send = pageDeps({});
  send.deps.getConfig = reads.config;
  send.deps.loadPending = () => fetchPendingDetails({ items: [], loadPending: reads.pending, loadItem: reads.item });
  const p2 = runSharePage(send.deps);
  await until(() => t2.pending() === 1);
  assert.equal(t2.delays.at(-1), CONFIG_WAIT_MS);
  t2.fire();
  await until(() => t2.pending() === 1);
  assert.equal(t2.delays.at(-1), READ_WAIT_MS);
  t2.fire();
  const out2 = await p2;
  assert.deepEqual([out2.mode, out2.pending], ['send', []]);
  const view = pageView({ mode: out2.mode, items: out2.pending, running: false });
  assert.deepEqual([view.finished, view.empty], [true, 'Tidak ada bukti yang menunggu.']);
});

test('createPoller + pageReads (R6): GET item yang menggantung berakhir null sesudah 20 dtk; pantauan lanjut lalu berhenti', async () => {
  const reads = fakeTimers();
  const chain = fakeTimers();
  const item = pageReads({ getConfig: async () => null, loadPending: async () => [], loadItem: () => new Promise(() => {}) }, reads).item;
  let rounds = 0;
  const got = [];
  const running = [];
  const poller = createPoller({
    targets: () => (rounds < 2 ? ['a'] : []), fetchItem: item, onDetails: (d) => { rounds += 1; got.push(d); },
    onRunning: on => running.push(on), setTimer: chain.setTimer, clearTimer: chain.clearTimer,
  });
  assert.equal(poller.start(), true);
  const first = chain.fire();
  await until(() => reads.pending() === 1);
  assert.equal(reads.delays.at(-1), READ_WAIT_MS);
  reads.fire();
  await first;
  assert.deepEqual(got, [[]], 'GET yang menggantung dianggap null');
  assert.equal(chain.pending(), 1, 'rantai lanjut');
  const second = chain.fire();
  await until(() => reads.pending() === 1);
  reads.fire();
  await second;
  assert.deepEqual([got.length, chain.pending(), running], [2, 0, [true, false]], 'berhenti: pantauan tidak tertahan');
});
