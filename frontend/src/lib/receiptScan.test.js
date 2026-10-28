import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  fitDimensions, receiptToItem, scanMessage, feedbackFor, proofBlockReason, wibDate, wibTime, wibToday,
  shortDate, periodLabel, currentPeriod, documentDateKind, applyDocumentDate, dateNotice, docNoun, isProofRow,
} from './receiptScan.js';

test('fitDimensions: foto besar diperkecil ke sisi panjang 1600, rasio tetap', () => {
  assert.deepEqual(fitDimensions(3000, 4000), { width: 1200, height: 1600 });
  assert.deepEqual(fitDimensions(800, 600), { width: 800, height: 600 });
});

test('receiptToItem: hasil scan jadi item dengan tanggal struk', () => {
  const item = receiptToItem({ scan_id: 's1', merchant: 'Indomaret', total: 140500, date: '2026-10-14', confidence: 'tinggi' }, 'k1');
  assert.equal(item.origin, 'receipt');
  assert.equal(item.description, 'Indomaret');
  assert.equal(item.amount, 140500);
  assert.equal(item.transactionDate, '2026-10-14');
  assert.equal(item.envelopeId, '');
  // Scan tanpa field Kotak Struk (bentuk lama): tanpa item, tanpa jenis, tanpa blokir.
  assert.deepEqual([item.receiptItemId, item.docType, item.blockedReason], [null, null, null]);
});

test('receiptToItem: toko tak terbaca → "Belanja", total kosong → 0', () => {
  const item = receiptToItem({ scan_id: 's2', merchant: null, total: null, date: null, confidence: 'gagal' }, 'k2');
  assert.equal(item.description, 'Belanja');
  assert.equal(item.amount, 0);
});

test('scanMessage: tanpa kalimat sisa kuota (bentuk kuota apa pun); keyakinan rendah minta cek', () => {
  for (const quota of [{ limit: 15, used: 3, remaining: 12 }, { limit: null, used: 0, remaining: null }, undefined]) {
    const m = scanMessage({ merchant: 'Alfamart', total: 45400, confidence: 'sedang', quota });
    assert.equal(m.type, 'mixed');
    assert.equal(m.text, 'Struk Alfamart terbaca: Rp 45.400. Mohon cek nominalnya (cek lagi nominalnya). Pilih amplop lalu simpan.');
    assert.doesNotMatch(m.text, /Sisa scan|12 dari 15/);
  }
  const pro = scanMessage({ merchant: 'Alfamart', total: 45400, confidence: 'tinggi', quota: { limit: null } });
  assert.deepEqual(pro, { type: 'success', text: 'Struk Alfamart terbaca: Rp 45.400. Pilih amplop lalu simpan.' });
});

test('receiptToItem: membawa rincian barang & penyesuaian', () => {
  const item = receiptToItem({
    scan_id: 's3', merchant: 'Indomaret', total: 70600, date: null, confidence: 'tinggi',
    items: [{ name: 'IDM F.TIS', amount: 37800, discount: 0, unit_price: 37800, qty: 1, flag: 'ok' }],
    adjustments: [{ label: 'VC PL', amount: 5900, kind: 'discount' }],
  }, 'k3');
  assert.equal(item.receiptItems.length, 1);
  assert.equal(item.receiptItems[0].unitPrice, 37800);
  assert.equal(item.adjustments[0].kind, 'discount');
  assert.equal(item.plan, null);
});

test('scanMessage: rincian cocok / selisih disebut', () => {
  const base = { merchant: 'Indomaret', total: 140500, confidence: 'tinggi', quota: { limit: null } };
  const cocok = scanMessage({ ...base, items: [{}, {}], reconciliation: { status: 'cocok', diff: 0 } });
  assert.match(cocok.text, /2 barang cocok/);
  assert.equal(cocok.type, 'success');
  const beda = scanMessage({ ...base, items: [{}], reconciliation: { status: 'selisih', diff: -7600 } });
  assert.match(beda.text, /selisih Rp 7\.600/);
  assert.equal(beda.type, 'mixed');
});

test('scanMessage: total gagal dibaca → error minta isi manual', () => {
  assert.equal(scanMessage({ total: null, confidence: 'gagal', quota: {} }).type, 'error');
  assert.equal(scanMessage({ total: null, confidence: 'gagal', quota: { limit: 15, remaining: 3 } }).text,
    'Total struk tidak terbaca. Isi nominalnya manual di baris struk.');
});

test('feedbackFor: nilai akhir yang disimpan user', () => {
  const fb = feedbackFor({ amount: 9200, transactionDate: '2026-10-01', description: 'Indomaret' }, true);
  assert.deepEqual(fb, { saved: true, total: 9200, transaction_date: '2026-10-01', merchant: 'Indomaret' });
  assert.deepEqual(feedbackFor({}, false), { saved: false });
});

// ── Bagikan ke Jatahku, Task B1: baris bukti bayar ──────────────────────────

test('receiptToItem: bukti QRIS → satu baris dengan saran yakin dan tanggal bayar', () => {
  const item = receiptToItem({ item_id: 'i1', scan_id: 'i1', doc_type: 'qris', total: 25000, merchant: 'SITI AMINAH',
    description_preview: 'Siti Aminah (QRIS)', paid_at: '2026-10-26T08:12:00+07:00',
    suggestion: { envelope_id: 'e1', confident: true }, flags: { blocked: null, warnings: [] }, items: [] }, 'k1');
  assert.deepEqual([item.receiptItemId, item.description, item.transactionDate, item.envelopeId, item.suggested, item.blockedReason],
    ['i1', 'Siti Aminah (QRIS)', '2026-10-26', 'e1', true, null]);
});

test('receiptToItem: transfer gagal diblokir; saran tidak yakin tidak dipilihkan', () => {
  const item = receiptToItem({ item_id: 'i2', doc_type: 'transfer', total: 50000, suggestion: { envelope_id: 'e1', confident: false },
    flags: { blocked: 'transaksi_gagal', warnings: [] }, items: [] }, 'k2');
  assert.equal(item.envelopeId, '');
  assert.equal(item.blockedReason, 'Transaksi ini gagal di bank, jadi tidak bisa dicatat.');
});

test('scanMessage: tanpa sisa kuota; bukti dengan duplikat lunak memberi peringatan', () => {
  assert.doesNotMatch(scanMessage({ total: 51000, merchant: 'Indomaret', confidence: 'tinggi', quota: { limit: 15, remaining: 3 } }).text, /Sisa scan/);
  const m = scanMessage({ doc_type: 'qris', total: 25000, merchant: 'SITI AMINAH', counterparty: { name: 'SITI AMINAH' },
    flags: { duplicate_of: { kind: 'soft', transaction: { description: 'bakso 25rb' } }, warnings: [] } });
  assert.equal(m.type, 'mixed');
  assert.match(m.text, /Mirip "bakso 25rb" yang sudah dicatat/);
});

test('receiptToItem: struk belanja tetap bentuk lama + receiptItemId (saran server tidak dipakai)', () => {
  const item = receiptToItem({ scan_id: 's9', item_id: 's9', doc_type: 'struk_belanja', merchant: 'Indomaret', total: 70600,
    date: '2026-10-14', paid_at: '2026-10-13T17:00:00+00:00', confidence: 'tinggi', description_preview: 'Indomaret (x)',
    suggestion: { envelope_id: 'e1', confident: true }, flags: { blocked: null, warnings: [] },
    items: [{ name: 'ROTI', amount: 70600 }] }, 'k9');
  assert.deepEqual(
    [item.receiptItemId, item.docType, item.description, item.transactionDate, item.envelopeId, item.suggested, item.blockedReason, item.receiptItems.length],
    ['s9', 'struk_belanja', 'Indomaret', '2026-10-14', '', false, null, 1]);
});

test('receiptToItem: tidak dikenali seperti bukti — keterangan server, saran yakin, tanpa rincian', () => {
  const base = { item_id: 'i4', scan_id: 'i4', doc_type: 'tidak_dikenali', total: 12000, merchant: 'TOKO X', confidence: 'rendah',
    flags: { blocked: null, warnings: [] }, items: [{ name: 'abaikan', amount: 1 }] };
  const item = receiptToItem({ ...base, description_preview: 'Toko X', suggestion: { envelope_id: 'e3', confident: true } }, 'k4');
  assert.deepEqual([item.docType, item.description, item.envelopeId, item.suggested, item.receiptItems], ['tidak_dikenali', 'Toko X', 'e3', true, []]);
  assert.equal(receiptToItem({ ...base, description_preview: null }, 'k').description, 'TOKO X');
  assert.equal(receiptToItem({ ...base, description_preview: null, merchant: null }, 'k').description, 'Belanja');
  // Yakin tanpa amplop → tidak dipilihkan dan tidak ditandai "disarankan".
  const noEnv = receiptToItem({ ...base, suggestion: { envelope_id: null, confident: true } }, 'k');
  assert.deepEqual([noEnv.envelopeId, noEnv.suggested], ['', false]);
});

test('receiptToItem: tanggal = result.date dulu, lalu tanggal WIB dari paid_at (UTC di Postgres)', () => {
  const base = { item_id: 'i3', scan_id: 'i3', doc_type: 'transfer', total: 1000, flags: {}, items: [] };
  assert.equal(receiptToItem({ ...base, paid_at: '2026-10-25T17:30:00+00:00' }, 'k').transactionDate, '2026-10-26'); // 00.30 WIB
  assert.equal(receiptToItem({ ...base, paid_at: '2026-10-25T17:30:00+00:00' }, 'k').docDate, '2026-10-26');
  assert.equal(receiptToItem({ ...base, date: '2026-10-24', paid_at: '2026-10-25T17:30:00+00:00' }, 'k').transactionDate, '2026-10-24');
  assert.equal(receiptToItem({ ...base, paid_at: null }, 'k').transactionDate, null);
});

test('proofBlockReason: transaksi gagal / sudah tercatat, untuk SEMUA jenis dokumen', () => {
  assert.equal(proofBlockReason({ blocked: 'transaksi_gagal' }), 'Transaksi ini gagal di bank, jadi tidak bisa dicatat.');
  assert.equal(proofBlockReason({ blocked: 'sudah_tercatat' }), 'Bukti ini sudah tercatat.');
  for (const flags of [null, undefined, {}, { blocked: null }, { blocked: 'lain' }]) assert.equal(proofBlockReason(flags), null);
  for (const doc_type of ['struk_belanja', 'qris', 'transfer', 'tidak_dikenali']) {
    const item = receiptToItem({ item_id: 'x', scan_id: 'x', doc_type, total: 5000, merchant: 'A', confidence: 'tinggi',
      flags: { blocked: 'sudah_tercatat', warnings: [] }, items: [{ name: 'B', amount: 5000 }] }, 'k');
    assert.equal(item.blockedReason, 'Bukti ini sudah tercatat.', doc_type);
  }
});

test('wibDate/wibTime: waktu dari server → tanggal & jam WIB (00.00–07.00 WIB ikut tanggal WIB)', () => {
  const cases = [
    ['2026-10-25T16:59:59+00:00', '2026-10-25', '23.59'],
    ['2026-10-25T17:00:00+00:00', '2026-10-26', '00.00'],   // struk belanja: paid_at = 00.00 WIB
    ['2026-10-25T17:30:00+00:00', '2026-10-26', '00.30'],
    ['2026-10-25T23:59:00Z', '2026-10-26', '06.59'],
    ['2026-10-26T00:00:00Z', '2026-10-26', '07.00'],
    ['2026-10-26T01:12:00+00:00', '2026-10-26', '08.12'],
    ['2026-10-26T08:12:00+07:00', '2026-10-26', '08.12'],
    ['2026-10-25T17:30:00', '2026-10-26', '00.30'],             // tanpa zona = UTC (seperti server)
    ['2026-10-25T17:30:00.123456+00:00', '2026-10-26', '00.30'], // mikrodetik dari Python
  ];
  for (const [iso, day, time] of cases) {
    assert.equal(wibDate(iso), day, iso);
    assert.equal(wibTime(iso), time, iso);
  }
  for (const bad of [null, undefined, '', 'bukan tanggal', 42]) {
    assert.equal(wibDate(bad), null);
    assert.equal(wibTime(bad), null);
  }
  assert.equal(wibDate(new Date('2026-10-25T17:30:00Z')), '2026-10-26');
  assert.equal(wibToday(new Date('2026-10-28T18:00:00Z')), '2026-10-29'); // 01.00 WIB
  assert.equal(wibToday(new Date('2026-10-28T16:59:00Z')), '2026-10-28'); // 23.59 WIB
});

test('wibDate/wibTime: hasilnya tidak bergantung zona waktu perangkat (teks tanpa zona = UTC)', () => {
  const saved = process.env.TZ;
  try {
    for (const tz of ['UTC', 'America/New_York', 'Asia/Makassar', 'Asia/Jayapura']) {
      process.env.TZ = tz;
      assert.deepEqual([wibDate('2026-10-25T17:30:00'), wibTime('2026-10-25T17:30:00')], ['2026-10-26', '00.30'], tz);
      assert.deepEqual([wibDate('2026-10-25T17:30:00+00:00'), wibTime('2026-10-25T17:30:00+00:00')], ['2026-10-26', '00.30'], tz);
    }
  } finally {
    if (saved === undefined) delete process.env.TZ;
    else process.env.TZ = saved;
  }
});

test('shortDate / periodLabel: "30 Sep", dengan tahun bila bukan tahun ini (sama dengan bot)', () => {
  assert.equal(shortDate('2026-09-30', '2026-10-29'), '30 Sep');
  assert.equal(shortDate('2026-08-01', '2026-10-29'), '1 Agu');
  assert.equal(shortDate('2025-12-30', '2026-01-05'), '30 Des 2025');
  assert.equal(periodLabel('2026-10-27', '2026-11-26', '2026-10-29'), '27 Okt–26 Nov');
  assert.equal(periodLabel('2026-12-27', '2027-01-26', '2027-01-05'), '27 Des 2026–26 Jan');
});

test('currentPeriod: periode berjalan dari GET /analytics/periods (terlama dulu); bentuk lain → null', () => {
  assert.deepEqual(currentPeriod([{ period_start: '2026-10-27', period_end: '2026-11-26', label: '27 Oct – 26 Nov 2026' }]),
    { start: '2026-10-27', end: '2026-11-26' });
  assert.deepEqual(currentPeriod([{ period_start: '2026-09-27', period_end: '2026-10-26' }, { period_start: '2026-10-27', period_end: '2026-11-26' }]),
    { start: '2026-10-27', end: '2026-11-26' });
  for (const bad of [[], null, undefined, {}, [{}], [{ period_start: 'x', period_end: '2026-11-26' }], { detail: 'x' }]) {
    assert.equal(currentPeriod(bad), null);
  }
});

test('documentDateKind: cermin period.document_date_kind (batas awal periode dan hari ini)', () => {
  const ctx = { periodStart: '2026-10-27', today: '2026-10-29' };
  assert.equal(documentDateKind('2026-10-26', ctx), 'past');     // sehari sebelum awal periode
  assert.equal(documentDateKind('2026-09-30', ctx), 'past');
  assert.equal(documentDateKind('2026-10-27', ctx), 'current');  // tepat awal periode
  assert.equal(documentDateKind('2026-10-29', ctx), 'current');  // hari ini
  assert.equal(documentDateKind('2026-10-30', ctx), 'future');   // besok
  assert.equal(documentDateKind('2027-01-01', ctx), 'future');
  assert.equal(documentDateKind('2026-10-29', { periodStart: '2026-10-29', today: '2026-10-29' }), 'current'); // hari gajian
  assert.equal(documentDateKind('2026-10-28', { periodStart: '2026-10-29', today: '2026-10-29' }), 'past');
  for (const bad of [null, undefined, '', '30/09/2026', '2026-9-30']) assert.equal(documentDateKind(bad, ctx), null);
  // Periode tidak terbaca → tidak pernah 'past' (tanpa pertanyaan, seperti dulu); masa depan tetap dikenali.
  assert.equal(documentDateKind('2026-09-30', { periodStart: null, today: '2026-10-29' }), 'current');
  assert.equal(documentDateKind('2026-10-30', { periodStart: null, today: '2026-10-29' }), 'future');
});

const PERIOD = { start: '2026-10-27', end: '2026-11-26' };
const TODAY = '2026-10-29';
const scanned = (extra = {}) => receiptToItem({
  item_id: 'i1', scan_id: 'i1', doc_type: 'struk_belanja', merchant: 'Indomaret', total: 9000, confidence: 'tinggi',
  flags: { blocked: null, warnings: [] }, items: [], ...extra,
}, 'k1');

test('applyDocumentDate: periode lalu → belum ada tanggal (ditanya); masa depan → hari ini; selain itu tetap', () => {
  const past = applyDocumentDate(scanned({ date: '2026-09-30' }), { period: PERIOD, today: TODAY });
  assert.deepEqual([past.dateKind, past.transactionDate, past.docDate, past.datePeriod], ['past', null, '2026-09-30', PERIOD]);
  const future = applyDocumentDate(scanned({ date: '2026-11-02' }), { period: PERIOD, today: TODAY });
  assert.deepEqual([future.dateKind, future.transactionDate, future.docDate], ['future', TODAY, '2026-11-02']);
  for (const date of ['2026-10-27', TODAY, null]) {
    const row = scanned({ date });
    assert.deepEqual(applyDocumentDate(row, { period: PERIOD, today: TODAY }), row, String(date));
  }
  // Semua jenis dokumen (saklar mati: setiap bukti terbaca struk_belanja).
  for (const doc_type of ['qris', 'transfer', 'tidak_dikenali']) {
    assert.equal(applyDocumentDate(scanned({ doc_type, date: '2026-09-30' }), { period: PERIOD, today: TODAY }).dateKind, 'past', doc_type);
  }
});

test('applyDocumentDate: periode tak terbaca → tidak bertanya; scan lama / bukti diblokir → tidak berubah', () => {
  const noPeriod = scanned({ date: '2026-09-30' });
  assert.deepEqual(applyDocumentDate(noPeriod, { period: null, today: TODAY }), noPeriod);
  const old = receiptToItem({ scan_id: 's1', merchant: 'Indomaret', total: 9000, date: '2026-09-30', confidence: 'tinggi' }, 'k');
  assert.deepEqual(applyDocumentDate(old, { period: PERIOD, today: TODAY }), old);
  const oldFuture = receiptToItem({ scan_id: 's1', merchant: 'Indomaret', total: 9000, date: '2026-11-02', confidence: 'tinggi' }, 'k');
  assert.deepEqual(applyDocumentDate(oldFuture, { period: PERIOD, today: TODAY }), oldFuture);
  const blocked = scanned({ date: '2026-09-30', flags: { blocked: 'sudah_tercatat', warnings: [] } });
  assert.deepEqual(applyDocumentDate(blocked, { period: PERIOD, today: TODAY }), blocked);
});

test('dateNotice: pertanyaan dan pilihan persis; "bukti" untuk QRIS/transfer, "struk" untuk lainnya', () => {
  const past = applyDocumentDate(scanned({ date: '2026-09-30' }), { period: PERIOD, today: TODAY });
  assert.deepEqual(dateNotice(past, TODAY), {
    kind: 'past',
    text: 'Tanggal di struk: 30 Sep — di luar periode sekarang (27 Okt–26 Nov). Catat untuk tanggal berapa?',
    choices: [{ label: 'Hari ini', date: TODAY }, { label: '30 Sep', date: '2026-09-30' }],
  });
  for (const [doc_type, noun] of [['qris', 'bukti'], ['transfer', 'bukti'], ['tidak_dikenali', 'struk']]) {
    const row = applyDocumentDate(scanned({ doc_type, date: '2026-09-30' }), { period: PERIOD, today: TODAY });
    assert.ok(dateNotice(row, TODAY).text.startsWith(`Tanggal di ${noun}: 30 Sep — `), doc_type);
  }
  const future = applyDocumentDate(scanned({ doc_type: 'transfer', date: '2026-11-02' }), { period: PERIOD, today: TODAY });
  assert.deepEqual(dateNotice(future, TODAY), { kind: 'future', text: 'Tanggal di bukti (2 Nov) belum lewat — dicatat hari ini.' });
  const storeFuture = applyDocumentDate(scanned({ date: '2026-11-02' }), { period: PERIOD, today: TODAY });
  assert.equal(dateNotice(storeFuture, TODAY).text, 'Tanggal di struk (2 Nov) belum lewat — dicatat hari ini.');
  // Tahun lain → dengan tahun (pertanyaan dan pilihan).
  const lastYear = applyDocumentDate(scanned({ date: '2025-12-30' }), { period: { start: '2026-01-01', end: '2026-01-31' }, today: '2026-01-05' });
  const n = dateNotice(lastYear, '2026-01-05');
  assert.equal(n.text, 'Tanggal di struk: 30 Des 2025 — di luar periode sekarang (1 Jan–31 Jan). Catat untuk tanggal berapa?');
  assert.deepEqual(n.choices, [{ label: 'Hari ini', date: '2026-01-05' }, { label: '30 Des 2025', date: '2025-12-30' }]);
  // Tanpa aturan tanggal → null.
  assert.equal(dateNotice(scanned({ date: TODAY }), TODAY), null);
  assert.equal(dateNotice({ origin: 'text', description: 'kopi' }, TODAY), null);
});

test('docNoun / isProofRow: kata benda tanggal dan jenis baris bukti', () => {
  assert.deepEqual(['qris', 'transfer', 'struk_belanja', 'tidak_dikenali', null, undefined].map(docNoun),
    ['bukti', 'bukti', 'struk', 'struk', 'struk', 'struk']);
  assert.deepEqual(['qris', 'transfer', 'tidak_dikenali', 'struk_belanja', null, undefined].map(isProofRow),
    [true, true, true, false, false, false]);
});

test('scanMessage: bukti QRIS/transfer — nama, nominal, satu peringatan (server → duplikat lunak → lewati)', () => {
  const flags = { warnings: [], duplicate_of: null, skip_suggestion: null, blocked: null };
  const qris = { doc_type: 'qris', total: 25000, merchant: 'SITI AMINAH', confidence: 'tinggi', flags };
  assert.deepEqual(scanMessage(qris), { type: 'success', text: 'Bukti QRIS SITI AMINAH terbaca: Rp 25.000. Pilih amplop lalu simpan.' });
  const tf = { ...qris, doc_type: 'transfer', merchant: null, counterparty: { name: 'BUDI SANTOSO' }, total: 152500 };
  assert.equal(scanMessage(tf).text, 'Bukti transfer BUDI SANTOSO terbaca: Rp 152.500. Pilih amplop lalu simpan.');
  assert.equal(scanMessage({ ...tf, counterparty: null }).text, 'Bukti transfer terbaca: Rp 152.500. Pilih amplop lalu simpan.');
  assert.deepEqual(scanMessage({ ...tf, flags: { ...flags, skip_suggestion: 'top_up' } }), {
    type: 'mixed',
    text: 'Bukti transfer BUDI SANTOSO terbaca: Rp 152.500. Pilih amplop lalu simpan. Ini top-up saldo, biasanya bukan pengeluaran.',
  });
  assert.match(scanMessage({ ...tf, flags: { ...flags, skip_suggestion: 'masuk' } }).text, / Ini uang masuk, biasanya bukan pengeluaran\.$/);
  assert.match(scanMessage({ ...tf, flags: { ...flags, skip_suggestion: 'antar_rekening_sendiri' } }).text,
    / Ini transfer ke rekening sendiri, biasanya bukan pengeluaran\.$/);
  // Satu peringatan saja, urutan: peringatan server, duplikat lunak, lalu lewati.
  const all = { ...flags, warnings: ['Transaksi masih diproses bank', 'Bukti ini lebih dari 60 hari lalu'],
    duplicate_of: { kind: 'soft', transaction: { description: 'bakso 25rb' } }, skip_suggestion: 'top_up' };
  assert.equal(scanMessage({ ...qris, flags: all }).text,
    'Bukti QRIS SITI AMINAH terbaca: Rp 25.000. Pilih amplop lalu simpan. Transaksi masih diproses bank.');
  assert.equal(scanMessage({ ...qris, flags: { ...all, warnings: [] } }).text,
    'Bukti QRIS SITI AMINAH terbaca: Rp 25.000. Pilih amplop lalu simpan. Mirip "bakso 25rb" yang sudah dicatat — cek dulu sebelum menyimpan.');
  // Duplikat ref anggota lain: peringatannya sudah ada di warnings (C5); kind 'ref' tidak menambah teks sendiri.
  assert.equal(scanMessage({ ...qris, flags: { ...flags, duplicate_of: { kind: 'ref', recorded: false, by: 'Dewi' } } }).type, 'success');
});

test('scanMessage: dokumen yang diblokir → pesan blokir (semua jenis dokumen)', () => {
  assert.deepEqual(scanMessage({ doc_type: 'transfer', total: 50000, merchant: 'ANDI', flags: { blocked: 'transaksi_gagal', warnings: [] } }),
    { type: 'error', text: 'Transaksi ini gagal di bank, jadi tidak bisa dicatat.' });
  assert.deepEqual(scanMessage({ doc_type: 'struk_belanja', total: 9000, merchant: 'Indomaret', confidence: 'tinggi', flags: { blocked: 'sudah_tercatat' } }),
    { type: 'error', text: 'Bukti ini sudah tercatat.' });
});

test('scanMessage: struk belanja dan tidak dikenali tetap memakai pesan struk lama', () => {
  const flags = { warnings: ['Transaksi masih diproses bank'], duplicate_of: null, skip_suggestion: null, blocked: null };
  assert.deepEqual(scanMessage({ doc_type: 'tidak_dikenali', merchant: null, total: 12000, confidence: 'rendah', flags }),
    { type: 'mixed', text: 'Struk terbaca: Rp 12.000. Mohon cek nominalnya (kurang yakin, mohon dicek). Pilih amplop lalu simpan.' });
  assert.deepEqual(scanMessage({ doc_type: 'struk_belanja', merchant: 'Indomaret', total: 9000, confidence: 'tinggi', flags, items: [{}], reconciliation: { status: 'cocok', diff: 0 } }),
    { type: 'success', text: 'Struk Indomaret terbaca: Rp 9.000. 1 barang cocok dengan total. Pilih amplop lalu simpan.' });
});
