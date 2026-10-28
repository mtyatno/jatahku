import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  SHARE_DB, SHARE_STORE, MAX_FILES, shareStore, saveShare, handleShareTarget, nextToUpload, uploadFormFor,
  clearShares, clearSharesOnLogout, isShareTarget,
} from './shareInbox.js';
import { DB_NAME as OFFLINE_DB } from './offlineSync.js';

function memStore() {
  const map = new Map();
  return { map, all: async () => [...map.values()], put: async e => { map.set(e.id, e); }, del: async id => { map.delete(id); }, clear: async () => map.clear() };
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
  const fake = { opens: [], created: [], events: [], failOpen: false, failNext: null, lastDb: null };
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
            put: v => request('put', () => { writable(); st.rows.set(v[st.keyPath], v); return v[st.keyPath]; }),
            delete: k => request('delete', () => { writable(); st.rows.delete(k); }),
            clear: () => request('clear', () => { writable(); st.rows.clear(); }),
          };
        };
        later(() => {
          for (const { r, op, fn } of reqs) {
            if (fake.failNext === op) {
              fake.failNext = null;
              r.error = tx.error = new Error('QuotaExceededError');
              r.onerror?.({ target: r }); tx.onerror?.({ target: r }); later(() => tx.onabort?.({}));
              return;
            }
            r.result = fn(); fake.events.push(op); r.onsuccess?.({ target: r });
          }
          later(() => { fake.events.push('complete'); tx.oncomplete?.({}); });
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
