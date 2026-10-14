import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classifyBatch, syncQueue, toBatchItem, CHUNK } from './offlineSync.js';

function memStore(items) {
  const map = new Map(items.map(it => [it.id, { ...it }]));
  return {
    map,
    all: async () => [...map.values()].map(it => ({ ...it })),
    put: async (it) => { map.set(it.id, { ...it }); },
    del: async (id) => { map.delete(id); },
  };
}

const item = (id, extra = {}) => ({
  id, envelope_id: 'e1', amount: 1000 * id, description: `barang ${id}`, source: 'webapp',
  client_ref: `ref-${id}`, token: 't', queuedAt: id, ...extra,
});

let refN = 0;
const newRef = () => `new-${++refN}`;

test('classifyBatch: tersimpan / sedang diproses / ditolak / pemberitahuan kuota', () => {
  const items = [item(1), item(2), item(3), item(4)];
  const res = { ok: true, status: 200, data: [
    { index: 0, ok: true },
    { index: 1, ok: false, pending: true, error: 'Sedang diproses' },
    { index: 2, ok: false, error: 'Dana tidak cukup', quota_notice: 'Kuota habis' },
  ] };
  const out = classifyBatch(items, res);
  assert.deepEqual(out.done, [1]);
  assert.deepEqual(out.keep, [2, 4]); // tanpa hasil → tetap menunggu
  assert.deepEqual(out.rejected, [{ id: 3, message: 'Dana tidak cukup' }]);
  assert.equal(out.notice, 'Kuota habis');
});

test('classifyBatch: kiriman gagal / respons tidak jelas → semua tetap menunggu', () => {
  for (const res of [null, { ok: false, status: 0, data: [] }, { ok: false, status: 503, data: {} },
    { ok: false, status: 401, data: {} }, { ok: false, status: 200, data: {} }]) {
    const out = classifyBatch([item(1), item(2)], res);
    assert.deepEqual(out.keep, [1, 2]);
    assert.equal(out.failed, true);
  }
  assert.equal(classifyBatch([item(1)], { ok: false, status: 422, data: {} }).invalid, true);
});

test('syncQueue: satu kiriman untuk semua; yang ditolak disimpan dengan alasannya, bukan dibuang', async () => {
  const store = memStore([item(1), item(2), item(3)]);
  const calls = [];
  const send = async (payloads) => {
    calls.push(payloads);
    return { ok: true, status: 200, data: payloads.map((p, i) => (i === 1
      ? { index: i, ok: false, error: 'Dana tidak cukup. Sisa: Rp0' }
      : { index: i, ok: true })) };
  };
  const s = await syncQueue({ store, send, newRef, now: () => 42 });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].length, 3);
  assert.deepEqual(s, { saved: 2, rejected: 1, kept: 0, notice: null });
  assert.deepEqual([...store.map.keys()], [2]);
  assert.deepEqual(store.map.get(2).rejected, { message: 'Dana tidak cukup. Sisa: Rp0', at: 42 });

  // Yang ditolak tidak dikirim ulang otomatis.
  const again = await syncQueue({ store, send, newRef });
  assert.equal(calls.length, 1);
  assert.deepEqual(again, { saved: 0, rejected: 0, kept: 0, notice: null });
});

test('syncQueue: item lama tanpa client_ref diberi kunci & disimpan sebelum dikirim', async () => {
  const store = memStore([item(1, { client_ref: undefined })]);
  let sentRef = null;
  const send = async (payloads) => {
    sentRef = payloads[0].client_ref;
    assert.equal(store.map.get(1).client_ref, sentRef); // sudah tersimpan saat dikirim
    return { ok: false, status: 0, data: [] }; // respons hilang
  };
  await syncQueue({ store, send, newRef });
  assert.ok(sentRef);
  assert.equal(store.map.get(1).client_ref, sentRef); // kirim ulang memakai kunci yang sama
});

test('syncQueue: data tidak lengkap langsung butuh perhatian, tidak dikirim', async () => {
  const store = memStore([item(1, { envelope_id: '' }), item(2, { amount: 0 }), item(3)]);
  const calls = [];
  const send = async (p) => { calls.push(p); return { ok: true, status: 200, data: p.map((_, i) => ({ index: i, ok: true })) }; };
  const s = await syncQueue({ store, send, newRef });
  assert.equal(calls[0].length, 1);
  assert.equal(s.rejected, 2);
  assert.ok(store.map.get(1).rejected && store.map.get(2).rejected);
});

test('syncQueue: offline / server error → semua tetap menunggu & berhenti', async () => {
  const items = Array.from({ length: CHUNK + 10 }, (_, i) => item(i + 1));
  const store = memStore(items);
  let n = 0;
  const s = await syncQueue({ store, send: async () => { n += 1; return { ok: false, status: 502, data: {} }; }, newRef });
  assert.equal(n, 1); // potongan kedua tidak dikirim
  assert.equal(s.kept, items.length);
  assert.equal(store.map.size, items.length);
  assert.ok([...store.map.values()].every(it => !it.rejected));
});

test('syncQueue: dipotong per CHUNK; 422 dipisah satu per satu', async () => {
  const items = Array.from({ length: CHUNK + 2 }, (_, i) => item(i + 1));
  items[3].description = 'RUSAK';
  const store = memStore(items);
  const sizes = [];
  const send = async (p) => {
    sizes.push(p.length);
    if (p.some(x => x.description === 'RUSAK')) return { ok: false, status: 422, data: { detail: [] } };
    return { ok: true, status: 200, data: p.map((_, i) => ({ index: i, ok: true })) };
  };
  const s = await syncQueue({ store, send, newRef });
  assert.equal(sizes[0], CHUNK);
  assert.equal(sizes.filter(x => x === 1).length, CHUNK); // potongan pertama dipisah
  assert.equal(s.saved, items.length - 1);
  assert.equal(store.map.get(4).rejected.message, 'Data transaksi tidak valid.');
});

test('toBatchItem: kolom batch saja (token & id antrean tidak ikut)', () => {
  const p = toBatchItem({ ...item(7), transaction_date: '2026-10-14', raise_daily_limit: true, is_private: true });
  assert.deepEqual(p, {
    envelope_id: 'e1', amount: 7000, description: 'barang 7', source: 'webapp', is_private: true,
    transaction_date: '2026-10-14', raise_daily_limit: true, client_ref: 'ref-7',
  });
});
