import { test } from 'node:test';
import assert from 'node:assert/strict';
import { docTypeCounts, docTypeLine, issuerRows } from './scanStats.js';

// Bentuk GET /admin/receipt-scans/stats (receipt_scan.accuracy_stats + _kotak_breakdown, admin.py).
const STATS = {
  total: 20, accepted: 5, corrected: 2, discarded: 1, expired: 0, pending: 12, llm: 0, accuracy_pct: 71.4,
  most_corrected: [{ merchant_key: 'indomaret', count: 2 }],
  by_doc_type: { struk_belanja: 12, qris: 3, transfer: 2, tidak_dikenali: 1 },
  unrecognized: 1,
  by_issuer: {
    jago: { total: 2, recorded: 1, corrected: 1 },
    bca_mobile: { total: 3, recorded: 3, corrected: 1 },
    indomaret: { total: 5, recorded: 0, corrected: 0 },
    gopay: { total: 2, recorded: 2, corrected: 0 },
  },
  llm_budget: null,
};

test('docTypeCounts: urutan tetap Struk belanja · QRIS · Transfer · Tidak dikenali', () => {
  assert.deepEqual(docTypeCounts(STATS), [
    { key: 'struk_belanja', label: 'Struk belanja', count: 12 },
    { key: 'qris', label: 'QRIS', count: 3 },
    { key: 'transfer', label: 'Transfer', count: 2 },
    { key: 'tidak_dikenali', label: 'Tidak dikenali', count: 1 },
  ]);
  assert.equal(docTypeLine(STATS), 'Struk belanja 12 · QRIS 3 · Transfer 2 · Tidak dikenali 1');
});

test('docTypeCounts: kunci yang tidak ada → 0; kunci baru di belakang dengan nama aslinya (urut nama)', () => {
  const stats = { by_doc_type: { transfer: 4, zz_baru: 2, kwitansi: 1, qris: 0 }, unrecognized: 0 };
  assert.equal(docTypeLine(stats), 'Struk belanja 0 · QRIS 0 · Transfer 4 · Tidak dikenali 0 · kwitansi 1 · zz_baru 2');
  assert.equal(docTypeLine({ by_doc_type: {} }), 'Struk belanja 0 · QRIS 0 · Transfer 0 · Tidak dikenali 0');
  // Nilai yang bukan bilangan bulat ≥ 0 → 0.
  assert.equal(docTypeLine({ by_doc_type: { struk_belanja: '7', qris: -2, transfer: 1.5, lain: null } }),
    'Struk belanja 0 · QRIS 0 · Transfer 0 · Tidak dikenali 0 · lain 0');
});

test('docTypeCounts: tidak dikenali tampil sekali, dari `unrecognized` (cadangan: peta)', () => {
  const line = docTypeLine({ by_doc_type: { tidak_dikenali: 3 }, unrecognized: 4 });
  assert.equal(line, 'Struk belanja 0 · QRIS 0 · Transfer 0 · Tidak dikenali 4');
  assert.equal(line.match(/Tidak dikenali/g).length, 1);
  assert.equal(docTypeLine({ by_doc_type: { tidak_dikenali: 3 } }), 'Struk belanja 0 · QRIS 0 · Transfer 0 · Tidak dikenali 3');
  assert.equal(docTypeLine({ by_doc_type: { tidak_dikenali: 3 }, unrecognized: null }),
    'Struk belanja 0 · QRIS 0 · Transfer 0 · Tidak dikenali 3');
  assert.equal(docTypeLine({ by_doc_type: { tidak_dikenali: 3 }, unrecognized: 0 }),
    'Struk belanja 0 · QRIS 0 · Transfer 0 · Tidak dikenali 0');
});

test('issuerRows: label penerbit (kunci asli bila tidak dikenal), urut total lalu label', () => {
  assert.deepEqual(issuerRows(STATS), [
    { key: 'indomaret', label: 'indomaret', total: 5, recorded: 0, corrected: 0, correctedPct: '–' },
    { key: 'bca_mobile', label: 'BCA mobile', total: 3, recorded: 3, corrected: 1, correctedPct: '33%' },
    { key: 'gopay', label: 'GoPay', total: 2, recorded: 2, corrected: 0, correctedPct: '0%' },
    { key: 'jago', label: 'Jago', total: 2, recorded: 1, corrected: 1, correctedPct: '100%' },
  ]);
});

test('issuerRows: total sama → urut label yang tampil, bukan kunci', () => {
  const rows = issuerRows({ by_issuer: {
    bni: { total: 2, recorded: 0, corrected: 0 }, jago: { total: 2, recorded: 0, corrected: 0 }, alfamart: { total: 2, recorded: 0, corrected: 0 },
  } });
  assert.deepEqual(rows.map(r => r.label), ['alfamart', 'Jago', 'wondr by BNI']);
});

test('issuerRows: % dikoreksi = Math.round(100 × dikoreksi / tercatat), "–" tanpa yang tercatat', () => {
  const pct = (recorded, corrected) => issuerRows({ by_issuer: { x: { total: 9, recorded, corrected } } })[0].correctedPct;
  assert.equal(pct(3, 2), '67%');
  assert.equal(pct(8, 1), '13%');
  assert.equal(pct(3, 0), '0%');
  assert.equal(pct(0, 0), '–');
  assert.equal(pct(0, 2), '–');
  // Tidak terjadi dengan data hari ini: untuk QRIS/transfer server menghitung koreksi hanya pada bukti yang tercatat
  // (dikoreksi ≤ tercatat). Jaga-jaga bila kelak pembaca lain mengisi penerbit: angkanya tampil apa adanya, tanpa dipotong.
  assert.equal(pct(2, 3), '150%');
});

test('issuerRows: angka rusak → 0; kunci seperti "constructor" tetap kunci asli; tanpa penerbit → []', () => {
  assert.deepEqual(issuerRows({ by_issuer: { constructor: { total: 1, recorded: 1, corrected: 0 } } }),
    [{ key: 'constructor', label: 'constructor', total: 1, recorded: 1, corrected: 0, correctedPct: '0%' }]);
  assert.deepEqual(issuerRows({ by_issuer: { ovo: null, dana: { total: '4', recorded: -1, corrected: 2.5 } } }), [
    { key: 'dana', label: 'DANA', total: 0, recorded: 0, corrected: 0, correctedPct: '–' },
    { key: 'ovo', label: 'OVO', total: 0, recorded: 0, corrected: 0, correctedPct: '–' },
  ]);
  assert.deepEqual(issuerRows({ by_issuer: {} }), []);
});

test('server lama tanpa field rincian → null (bagian tidak tampil), tanpa galat', () => {
  const old = { total: 4, accepted: 1, corrected: 1, discarded: 0, pending: 2, accuracy_pct: 50, most_corrected: [], llm_budget: null };
  for (const stats of [old, null, undefined, { ...old, by_doc_type: null, by_issuer: [] }, { ...old, by_doc_type: [1], by_issuer: 'x' }]) {
    assert.equal(docTypeCounts(stats), null);
    assert.equal(docTypeLine(stats), null);
    assert.equal(issuerRows(stats), null);
  }
  // `unrecognized` saja tanpa peta jenis → tetap tidak tampil.
  assert.equal(docTypeLine({ ...old, unrecognized: 3 }), null);
});
