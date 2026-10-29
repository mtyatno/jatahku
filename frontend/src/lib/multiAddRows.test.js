import { test } from 'node:test';
import assert from 'node:assert/strict';
import { receiptToItem, applyDocumentDate, dateNotice, feedbackFor } from './receiptScan.js';
import {
  isInsufficientFundsError, isDailyLimitError, hasReceiptItems, receiptPlan, needsDate, isReady, needsEnvelope,
  notReadyMessage, applyRowPatch, withSaveDate, toPayload, toParts, wantsReceiptFeedback, removalCalls,
  wantsKeywordSuggestion, pastDated, fundCandidate, showRaisedLimit, alreadyListed, withSaveError, canUnlockPlan,
} from './multiAddRows.js';
import { toBatchItem } from './offlineSync.js';
import { summarizePlan } from './receiptSplit.js';

const PERIOD = { start: '2026-10-27', end: '2026-11-26' };
const TODAY = '2026-10-29';
const OK_FLAGS = { blocked: null, warnings: [] };

// Baris ketikan ("kopi 15k") seperti dibuat MultiAddTransaction.
const manual = (extra = {}) => ({
  amount: 15000, description: 'kopi', key: 't1', origin: 'text', envelopeId: 'e1',
  suggested: false, touched: false, error: null, saving: false, ...extra,
});
const proof = (extra = {}, flags = OK_FLAGS) => receiptToItem({
  item_id: 'i1', scan_id: 'i1', doc_type: 'qris', total: 25000, merchant: 'SITI AMINAH',
  description_preview: 'Siti Aminah (QRIS)', confidence: 'tinggi', flags, items: [], ...extra,
}, 'k1');
const store = (extra = {}) => receiptToItem({
  item_id: 's1', scan_id: 's1', doc_type: 'struk_belanja', merchant: 'Indomaret', total: 15000, date: '2026-10-28',
  confidence: 'tinggi', flags: OK_FLAGS, items: [{ name: 'ROTI', amount: 10000 }, { name: 'SUSU', amount: 5000 }], ...extra,
}, 'k2');
const dated = row => applyDocumentDate(row, { period: PERIOD, today: TODAY });

test('galat dana / limit harian dikenali dari teks server (create dan batch)', () => {
  for (const msg of ['💸 Dana tidak cukup. Sisa: Rp19,000, diminta: Rp25,000', 'Dana tidak cukup. Sisa: Rp0, diminta: Rp1,000',
    '💸 Amplop Makan belum ada dana. Alokasikan income dulu.', 'Amplop belum didanai']) {
    assert.equal(isInsufficientFundsError(msg), true, msg);
  }
  assert.equal(isDailyLimitError('Melebihi limit harian Makan: Rp50.000'), true);
  for (const msg of [null, '', 'Amplop dikunci. Tidak bisa belanja.', 'Bukti ini sudah tercatat']) {
    assert.equal(isInsufficientFundsError(msg), false);
    assert.equal(isDailyLimitError(msg), false);
  }
});

test('toPayload: baris ketikan tanpa field baru; baris bukti membawa receipt_item_id', () => {
  assert.deepEqual(toPayload(manual({ ref: 'r1' })), {
    envelope_id: 'e1', amount: 15000, description: 'kopi', source: 'webapp', client_ref: 'r1',
  });
  const row = { ...proof({ date: '2026-10-28' }), envelopeId: 'e2', ref: 'r2' };
  assert.deepEqual(toPayload(row), {
    envelope_id: 'e2', amount: 25000, description: 'Siti Aminah (QRIS)', source: 'webapp',
    transaction_date: '2026-10-28', client_ref: 'r2', receipt_item_id: 'i1',
  });
  // Scan lama (tanpa item Kotak Struk): bentuk payload lama.
  const old = { ...receiptToItem({ scan_id: 's', merchant: 'A', total: 1000, date: '2026-10-28', confidence: 'tinggi' }, 'k'), envelopeId: 'e1' };
  assert.equal('receipt_item_id' in toPayload(old), false);
});

test('toParts: setiap bagian rencana struk belanja membawa receipt_item_id dan kuncinya sendiri', () => {
  const entry = { ...store(), envelopeId: 'e1' };
  assert.equal(hasReceiptItems(entry), true);
  const plan = receiptPlan(entry).map((g, i) => ({ ...g, ref: `r${i}` }));
  assert.equal(plan.length, 2);
  const parts = toParts(entry, plan);
  assert.deepEqual(parts.map(p => [p.key, p.gid, p.payload.receipt_item_id, p.payload.client_ref, p.payload.transaction_date, p.payload.amount]),
    [['k2', 'g0', 's1', 'r0', '2026-10-28', 10000], ['k2', 'g1', 's1', 'r1', '2026-10-28', 5000]]);
  // Bagian yang sudah tersimpan tidak dikirim lagi.
  assert.deepEqual(toParts(entry, [{ ...plan[0], saved: true }, plan[1]]).map(p => p.gid), ['g1']);
  // Tanpa rencana: satu bagian, payload baris itu sendiri.
  assert.deepEqual(toParts({ ...manual(), ref: 'x' }, null), [{ key: 't1', gid: null, payload: toPayload({ ...manual(), ref: 'x' }) }]);
});

test('receipt_item_id ikut antrean offline: payload form → item antrean → baris batch', () => {
  const payload = toPayload({ ...proof({ date: '2026-10-28' }), envelopeId: 'e2', ref: 'r2' });
  const queued = { ...payload, id: 7, token: 't', queuedAt: 1 };   // enqueueTransaction menyebar payload
  assert.deepEqual(toBatchItem(queued), {
    envelope_id: 'e2', amount: 25000, description: 'Siti Aminah (QRIS)', source: 'webapp', is_private: false,
    transaction_date: '2026-10-28', client_ref: 'r2', receipt_item_id: 'i1',
  });
  const plan = receiptPlan({ ...store(), envelopeId: 'e1' }).map((g, i) => ({ ...g, ref: `r${i}` }));
  for (const part of toParts({ ...store(), envelopeId: 'e1' }, plan)) {
    assert.equal(toBatchItem({ ...part.payload, id: 9 }).receipt_item_id, 's1');
  }
  assert.equal('receipt_item_id' in toBatchItem({ ...toPayload(manual({ ref: 'r' })), id: 8 }), false);
});

test('isReady: baris diblokir tidak pernah siap, walau sudah ada amplop dan diedit', () => {
  const blocked = proof({}, { blocked: 'transaksi_gagal', warnings: [] });
  const withEnv = applyRowPatch(blocked, { envelopeId: 'e1', touched: true });
  assert.equal(withEnv.blockedReason, 'Transaksi ini gagal di bank, jadi tidak bisa dicatat.');
  assert.equal(isReady(withEnv), false);
  assert.equal(isReady({ ...withEnv, blockedReason: null }), true);
  // Struk belanja dengan rincian (jalur rencana) juga diblokir.
  const recorded = { ...store({ flags: { blocked: 'sudah_tercatat', warnings: [] } }), envelopeId: 'e1' };
  assert.equal(hasReceiptItems(recorded), true);
  assert.equal(isReady(recorded), false);
  assert.equal(isReady({ ...recorded, blockedReason: null }), true);
  // Baris ketikan: seperti dulu (siap bila ada amplop).
  assert.equal(isReady(manual()), true);
  assert.equal(isReady(manual({ envelopeId: '' })), false);
});

test('isReady: struk/bukti periode lalu belum siap sampai tanggal dipilih (pilihan atau input tanggal)', () => {
  const row = { ...dated(proof({ date: '2026-09-30' })), envelopeId: 'e1' };
  assert.equal(needsDate(row), true);
  assert.equal(isReady(row), false);
  for (const choice of dateNotice(row, TODAY).choices) {
    const picked = applyRowPatch(row, { transactionDate: choice.date });
    assert.equal(needsDate(picked), false, choice.label);
    assert.equal(isReady(picked), true, choice.label);
    assert.equal(dateNotice(picked, TODAY).kind, 'past');   // pertanyaan tetap terlihat: pilihan bisa diganti
  }
  assert.equal(isReady(applyRowPatch(row, { transactionDate: '2026-10-01' })), true);   // input tanggal
  const cleared = applyRowPatch(applyRowPatch(row, { transactionDate: TODAY }), { transactionDate: null });
  assert.equal(isReady(cleared), false);                                                // dikosongkan lagi
  // Struk belanja dengan rincian juga menunggu tanggal.
  const card = { ...dated(store({ date: '2026-09-30' })), envelopeId: 'e1' };
  assert.equal(isReady(card), false);
  assert.equal(isReady(applyRowPatch(card, { transactionDate: '2026-09-30' })), true);
  // Masa depan, periode berjalan, dan tanpa tanggal dokumen tidak ditanya.
  for (const date of ['2026-11-02', '2026-10-28', '2026-10-27', null]) {
    const r = { ...dated(proof({ date })), envelopeId: 'e1' };
    assert.equal(needsDate(r), false, String(date));
    assert.equal(isReady(r), true, String(date));
  }
  // Periode tidak terbaca: struk lama tetap bisa langsung disimpan (seperti dulu).
  const unknownPeriod = { ...applyDocumentDate(proof({ date: '2026-09-30' }), { period: null, today: TODAY }), envelopeId: 'e1' };
  assert.deepEqual([needsDate(unknownPeriod), isReady(unknownPeriod), unknownPeriod.transactionDate], [false, true, '2026-09-30']);
});

test('applyRowPatch: edit menghapus error, blokir tetap; ganti tanggal menyembunyikan "dicatat hari ini"', () => {
  const row = { ...proof({}, { blocked: 'sudah_tercatat', warnings: [] }), error: 'Bukti ini sudah tercatat' };
  const next = applyRowPatch(row, { description: 'x', blockedReason: null });
  assert.deepEqual([next.description, next.error, next.blockedReason], ['x', null, 'Bukti ini sudah tercatat.']);
  const future = dated(proof({ date: '2026-11-02' }));
  assert.equal(dateNotice(future, TODAY).kind, 'future');
  assert.equal(dateNotice(applyRowPatch(future, { envelopeId: 'e1' }), TODAY).kind, 'future');
  assert.equal(dateNotice(applyRowPatch(future, { transactionDate: '2026-10-20' }), TODAY), null);
  // Baris ketikan: tidak ada field baru yang ditambahkan.
  assert.deepEqual(applyRowPatch(manual({ error: 'Gagal' }), { envelopeId: 'e2', suggested: false, touched: true }),
    manual({ envelopeId: 'e2', touched: true }));
});

test('notReadyMessage: semua diblokir → alasan blokir; perlu tanggal → "Pilih tanggal catat"; selain itu amplop', () => {
  const blocked = proof({}, { blocked: 'transaksi_gagal', warnings: [] });
  assert.equal(notReadyMessage([blocked]), 'Transaksi ini gagal di bank, jadi tidak bisa dicatat.');
  const past = { ...dated(proof({ date: '2026-09-30' })), envelopeId: 'e1' };
  assert.equal(notReadyMessage([blocked, past]), 'Pilih tanggal catat');
  assert.equal(notReadyMessage([blocked, manual({ envelopeId: '' })]), 'Pilih amplop untuk setiap item');
  assert.equal(notReadyMessage([manual({ envelopeId: '' })]), 'Pilih amplop untuk setiap item');
});

test('needsEnvelope: hitungan "perlu amplop" tanpa baris yang diblokir', () => {
  assert.equal(needsEnvelope(manual({ envelopeId: '' })), true);
  assert.equal(needsEnvelope(manual()), false);
  assert.equal(needsEnvelope(proof({}, { blocked: 'transaksi_gagal', warnings: [] })), false);
  assert.equal(needsEnvelope(proof()), true);
  assert.equal(needsEnvelope({ ...store(), envelopeId: '' }), true);
  assert.equal(needsEnvelope({ ...store(), envelopeId: 'e1' }), false);
  assert.equal(needsEnvelope({ ...dated(proof({ date: '2026-09-30' })), envelopeId: 'e1' }), false);   // butuh tanggal, bukan amplop
});

test('withSaveDate: tanggal sesudah hari ini (baris Kotak Struk) jadi hari ini SEBELUM payload dan feedbackFor', () => {
  const row = { ...store({ date: '2026-10-28', items: [] }), envelopeId: 'e1' };
  const typed = applyRowPatch(row, { transactionDate: '2026-11-05' });   // diketik manual ke masa depan
  const saved = withSaveDate(typed, TODAY);
  assert.equal(toPayload(saved).transaction_date, TODAY);
  assert.equal(feedbackFor(saved, true).transaction_date, TODAY);
  for (const d of [TODAY, '2026-10-01', '2026-09-30', null]) {
    const r = applyRowPatch(row, { transactionDate: d });
    assert.equal(withSaveDate(r, TODAY), r, String(d));
  }
  // Tanggal dokumen masa depan sudah jadi hari ini saat baris dibuat → umpan balik juga hari ini.
  assert.equal(feedbackFor(dated(store({ date: '2026-11-02', items: [] })), true).transaction_date, TODAY);
  // Tanpa receipt_item_id (scan lama, baris ketikan): tidak diubah.
  const old = receiptToItem({ scan_id: 's', merchant: 'A', total: 1, date: '2026-11-05', confidence: 'tinggi' }, 'k');
  assert.equal(withSaveDate(old, TODAY), old);
  assert.equal(withSaveDate(manual(), TODAY).transactionDate, undefined);
});

test('umpan balik belajar struk hanya untuk struk belanja (dan scan lama); item Kotak Struk dilewati saat dihapus', () => {
  const mk = doc_type => receiptToItem({ item_id: 'i', scan_id: 'i', doc_type, merchant: 'A', total: 1, confidence: 'tinggi', flags: OK_FLAGS, items: [] }, 'k');
  assert.equal(wantsReceiptFeedback(mk('struk_belanja')), true);
  assert.deepEqual(removalCalls(mk('struk_belanja')), { feedback: 'i', skip: 'i' });
  for (const t of ['qris', 'transfer', 'tidak_dikenali']) {
    assert.equal(wantsReceiptFeedback(mk(t)), false, t);
    assert.deepEqual(removalCalls(mk(t)), { feedback: null, skip: 'i' }, t);
  }
  const old = receiptToItem({ scan_id: 's', merchant: 'A', total: 1, confidence: 'tinggi' }, 'k');
  assert.equal(wantsReceiptFeedback(old), true);
  assert.deepEqual(removalCalls(old), { feedback: 's', skip: null });
  assert.equal(wantsReceiptFeedback(manual()), false);
  assert.deepEqual(removalCalls(manual()), { feedback: null, skip: null });
  assert.deepEqual(removalCalls(undefined), { feedback: null, skip: null });
});

test('saran kata kunci tidak menimpa saran server untuk QRIS/transfer; tidak dikenali seperti struk belanja', () => {
  assert.equal(wantsKeywordSuggestion(manual()), true);
  assert.equal(wantsKeywordSuggestion(store()), true);
  assert.equal(wantsKeywordSuggestion(receiptToItem({ scan_id: 's', merchant: 'A', total: 1, confidence: 'tinggi' }, 'k')), true);
  assert.equal(wantsKeywordSuggestion(proof({ doc_type: 'tidak_dikenali' })), true);
  for (const doc_type of ['qris', 'transfer']) assert.equal(wantsKeywordSuggestion(proof({ doc_type })), false, doc_type);
});

test('satu item Kotak Struk = satu baris: scan yang sama lagi tidak menambah baris', () => {
  const result = { item_id: 'k-same', scan_id: 'k-same', doc_type: 'struk_belanja', merchant: 'Alfamart', total: 45400,
    confidence: 'tinggi', flags: OK_FLAGS, items: [] };
  const first = receiptToItem(result, 'k1');
  assert.deepEqual(alreadyListed(result, [manual(), first]), { type: 'mixed', text: 'Struk ini sudah ada di daftar.' });
  assert.equal(alreadyListed(result, [manual()]), null);
  assert.equal(alreadyListed({ ...result, item_id: 'lain' }, [first]), null);
  assert.equal(alreadyListed({ scan_id: 'lama', merchant: 'A', total: 1, confidence: 'tinggi' }, [first]), null);   // scan lama
  assert.equal(alreadyListed(result, []), null);
  const qris = { ...result, item_id: 'k-q', scan_id: 'k-q', doc_type: 'qris' };
  assert.deepEqual(alreadyListed(qris, [receiptToItem(qris, 'k2')]), { type: 'mixed', text: 'Bukti ini sudah ada di daftar.' });
  const unknown = { ...result, item_id: 'k-u', scan_id: 'k-u', doc_type: 'tidak_dikenali' };
  assert.equal(alreadyListed(unknown, [receiptToItem(unknown, 'k3')]).text, 'Struk ini sudah ada di daftar.');
  const card = { ...result, item_id: 'k-c', scan_id: 'k-c', items: [{ name: 'ROTI', amount: 45400 }] };
  assert.equal(alreadyListed(card, [receiptToItem(card, 'k4')]).text, 'Struk ini sudah ada di daftar.');   // kartu struk
});

test('menghapus satu dari dua baris untuk item yang sama tidak melewati item dan tidak membuang umpan baliknya', () => {
  // Reproduksi review I1: foto yang sama dua kali → dua baris untuk SATU item. Menghapus satu baris dulu
  // melewatinya (dilewati), lalu baris yang tersisa ditolak "Bukti ini belum siap dicatat" selamanya.
  const result = { item_id: 'k-same', scan_id: 'k-same', doc_type: 'struk_belanja', merchant: 'Alfamart', total: 45400,
    confidence: 'tinggi', flags: OK_FLAGS, items: [] };
  const first = receiptToItem(result, 'k1');
  const second = receiptToItem(result, 'k2');
  assert.deepEqual(removalCalls(second, [first, second]), { feedback: null, skip: null });
  assert.deepEqual(removalCalls(first, [first, second, manual()]), { feedback: null, skip: null });
  // Baris terakhir untuk item itu: dilewati dan umpan balik "tidak disimpan" seperti biasa.
  assert.deepEqual(removalCalls(first, [first]), { feedback: 'k-same', skip: 'k-same' });
  assert.deepEqual(removalCalls(first, [first, manual(), store()]), { feedback: 'k-same', skip: 'k-same' });
  // Bukti (tanpa umpan balik struk): hanya skip yang dijaga.
  const qris = proof();
  assert.deepEqual(removalCalls(qris, [qris, { ...qris, key: 'kx' }]), { feedback: null, skip: null });
  assert.deepEqual(removalCalls(qris, [qris]), { feedback: null, skip: 'i1' });
});

test('penolakan bukti saat simpan (409) jadi alasan blokir yang terlihat; galat lain tetap error biasa', () => {
  const row = { ...proof(), envelopeId: 'e1', ref: 'r1' };
  for (const [error, reason] of [
    ['Bukti ini sudah tercatat', 'Bukti ini sudah tercatat.'],
    ['Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya', 'Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya.'],
    ['Bukti ini belum siap dicatat', 'Bukti ini belum siap dicatat.'],
    ['Bukti tidak ditemukan', 'Bukti tidak ditemukan.'],
    ['Transaksi gagal, tidak bisa dicatat', 'Transaksi gagal, tidak bisa dicatat.'],
  ]) {
    const next = withSaveError(row, error);
    assert.deepEqual([next.blockedReason, next.error, isReady(next)], [reason, null, false], error);
    assert.equal(applyRowPatch(next, { envelopeId: 'e2' }).blockedReason, reason, error);   // tetap sesudah diedit
  }
  // Struk belanja dengan rincian (kartu): alasan di tingkat kartu, rencana tidak dikirim lagi.
  const card = { ...store(), envelopeId: 'e1' };
  assert.equal(isReady(withSaveError(card, 'Bukti ini sudah tercatat')), false);
  // Galat lain (dana, limit harian, sedang diproses): tetap `error` (Gagal, Geser, Naikkan limit), baris bisa dicoba lagi.
  for (const error of ['Dana tidak cukup. Sisa: Rp0, diminta: Rp25,000', 'Melebihi limit harian Makan: Rp50.000',
    'Sedang diproses, coba lagi sebentar', 'Amplop dikunci. Tidak bisa belanja.', 'Gagal']) {
    const next = withSaveError(row, error);
    assert.deepEqual([next.blockedReason, next.error, isReady(next)], [null, error, true], error);
  }
  assert.deepEqual([withSaveError(row, null).blockedReason, withSaveError(row, null).error], [null, null]);
  // Baris tanpa item Kotak Struk (ketikan, scan lama): teks yang sama tetap galat biasa.
  const typed = withSaveError(manual(), 'Bukti tidak ditemukan');
  assert.deepEqual([typed.error, 'blockedReason' in typed], ['Bukti tidak ditemukan', false]);
});

test('tanggal sebelum awal periode: tanpa tawaran Geser / "limit ↑" dari dugaan; jawaban server tetap tampil', () => {
  const row = { ...dated(proof({ date: '2026-09-30' })), envelopeId: 'e1' };
  const docDated = applyRowPatch(row, { transactionDate: '2026-09-30', raiseDailyLimit: true });
  const todayDated = applyRowPatch(row, { transactionDate: TODAY, raiseDailyLimit: true });
  assert.equal(pastDated(docDated, PERIOD.start), true);
  assert.equal(pastDated(todayDated, PERIOD.start), false);
  assert.equal(pastDated(applyRowPatch(row, { transactionDate: PERIOD.start }), PERIOD.start), false);   // hari pertama periode
  assert.equal(pastDated(applyRowPatch(row, { transactionDate: '2026-10-26' }), PERIOD.start), true);   // sehari sebelumnya
  assert.equal(showRaisedLimit(docDated, PERIOD.start), false);   // server tidak menaikkan limit untuk baris ini
  assert.equal(showRaisedLimit(todayDated, PERIOD.start), true);
  // Pesan "Dana tidak cukup" sisa percobaan "Hari ini": sesudah pindah ke tanggal dokumen, baris ini bukan target Geser.
  assert.equal(fundCandidate([docDated], PERIOD.start), null);
  assert.equal(fundCandidate([todayDated], PERIOD.start), todayDated);
  // Server tetap menjawab dana kurang (gajian berubah, sinkron offline sesudah gajian) → Geser seperti biasa.
  const answered = { ...docDated, error: 'Dana tidak cukup. Sisa: Rp0, diminta: Rp25,000' };
  assert.equal(fundCandidate([todayDated, answered], PERIOD.start), answered);
  // Periode tidak diketahui, baris ketikan: seperti dulu.
  assert.equal(pastDated(docDated, null), false);
  assert.equal(pastDated(manual(), PERIOD.start), false);
  assert.equal(fundCandidate([manual()], PERIOD.start).key, 't1');
  assert.equal(showRaisedLimit(manual({ raiseDailyLimit: true }), PERIOD.start), true);
  assert.equal(showRaisedLimit(manual({ raiseDailyLimit: true, error: 'Gagal' }), PERIOD.start), false);
});

// ── Review akhir Bagian B: R3 (antrean offline) dan R4 (kartu terblokir) ───────────────────────────────────────

test('alreadyListed: item yang sudah disimpan offline (antrean, menunggu atau ditolak) tidak menambah baris; teks lama tetap', () => {
  const queued = new Set(['s1', 'q1', 't1', 'u1']);
  const QUEUED = ' ini sudah disimpan offline dan menunggu dikirim. Cek pemberitahuan antrean offline.';
  // Sudah ada di daftar: teks lama, persis sama, juga bila item itu ada di antrean.
  assert.deepEqual(alreadyListed({ item_id: 's1', doc_type: 'struk_belanja' }, [{ receiptItemId: 's1' }], queued),
    { type: 'mixed', text: 'Struk ini sudah ada di daftar.' });
  assert.deepEqual(alreadyListed({ item_id: 'q1', doc_type: 'qris' }, [{ receiptItemId: 'q1' }], queued),
    { type: 'mixed', text: 'Bukti ini sudah ada di daftar.' });
  // Di antrean offline: kata benda sama dengan teks lama (bukti untuk QRIS/transfer, struk untuk lainnya).
  assert.deepEqual(alreadyListed({ item_id: 's1', doc_type: 'struk_belanja' }, [], queued), { type: 'mixed', text: `Struk${QUEUED}` });
  assert.deepEqual(alreadyListed({ item_id: 'u1', doc_type: 'tidak_dikenali' }, [manual()], queued), { type: 'mixed', text: `Struk${QUEUED}` });
  assert.deepEqual(alreadyListed({ item_id: 'q1', doc_type: 'qris' }, [], queued), { type: 'mixed', text: `Bukti${QUEUED}` });
  assert.deepEqual(alreadyListed({ item_id: 't1', doc_type: 'transfer' }, [], queued), { type: 'mixed', text: `Bukti${QUEUED}` });
  // Bukan di daftar dan bukan di antrean; tanpa antrean (null / tidak diberikan / bukan Set); scan lama tanpa item.
  assert.equal(alreadyListed({ item_id: 's1', doc_type: 'struk_belanja' }, [], new Set(['lain'])), null);
  assert.equal(alreadyListed({ item_id: 's1', doc_type: 'struk_belanja' }, [], null), null);
  assert.equal(alreadyListed({ item_id: 's1', doc_type: 'struk_belanja' }, []), null);
  assert.equal(alreadyListed({ item_id: 's1', doc_type: 'struk_belanja' }, [], ['s1']), null);
  assert.equal(alreadyListed({ scan_id: 'lama', merchant: 'A', total: 1 }, [], new Set([undefined, null, 'lama'])), null);
});

test('withSaveError: penolakan bukti pada struk berencana → hanya alasan kartu; bagian yang belum tersimpan tanpa galat', () => {
  const item = { key: 'k', receiptItemId: 'i1', plan: [
    { id: 'g1', envelopeId: 'e1', amount: 10, saved: true, error: null },
    { id: 'g2', envelopeId: 'e1', amount: 5, saved: false, error: 'Bukti ini sudah tercatat' },
    { id: 'g3', envelopeId: 'e2', amount: 7, saved: false, error: 'Bukti ini sudah tercatat' } ] };
  const out = withSaveError(item, 'Bukti ini sudah tercatat');
  assert.equal(out.blockedReason, 'Bukti ini sudah tercatat.');
  assert.equal(out.error, null);
  assert.deepEqual(out.plan.map(g => [g.id, g.saved, g.error]), [['g1', true, null], ['g2', false, null], ['g3', false, null]]);
  assert.equal(out.plan[0], item.plan[0], 'bagian yang sudah tersimpan tidak disentuh');
  assert.equal(item.plan[1].error, 'Bukti ini sudah tercatat', 'baris asal tidak diubah');
  // Kartu tidak lagi menampilkan "Gagal: …" per amplop, jadi juga tanpa pindah amplop / Geser / Naikkan limit.
  assert.ok(summarizePlan(out.plan).every(r => r.error === null && r.failed.length === 0));
  // Tanpa rencana: bentuk lama (tidak ada kunci `plan` baru); galat lain tidak menyentuh rencana.
  assert.equal('plan' in withSaveError({ key: 'r', receiptItemId: 'i2' }, 'Bukti ini sudah tercatat'), false);
  assert.equal(withSaveError({ key: 'r', receiptItemId: 'i2', plan: null }, 'Bukti ini belum siap dicatat').plan, null);
  const other = withSaveError(item, 'Dana tidak cukup. Sisa: Rp0, diminta: Rp5');
  assert.equal(other.plan, item.plan);
  assert.equal(other.error, 'Dana tidak cukup. Sisa: Rp0, diminta: Rp5');
});

test('canUnlockPlan: "Ubah rincian" hanya untuk rencana beku tanpa bagian tersimpan, tidak belum pasti, dan tidak diblokir', () => {
  const plan = [{ id: 'g1', saved: false, error: 'Dana tidak cukup' }, { id: 'g2', saved: false, error: null }];
  const card = { ...store(), plan };
  assert.equal(canUnlockPlan(card), true);
  assert.equal(canUnlockPlan({ ...card, plan: null }), false, 'belum pernah disimpan: rincian memang belum dikunci');
  assert.equal(canUnlockPlan({ ...card, plan: [{ ...plan[0], saved: true }, plan[1]] }), false, 'sebagian sudah tercatat');
  assert.equal(canUnlockPlan({ ...card, uncertain: true }), false, 'hasil simpan belum pasti');
  assert.equal(canUnlockPlan(withSaveError(card, 'Bukti ini belum siap dicatat')), false, 'kartu yang ditolak server');
  assert.equal(canUnlockPlan({ ...card, blockedReason: 'Bukti ini sudah tercatat.' }), false);
  assert.equal(canUnlockPlan(withSaveError(card, 'Dana tidak cukup. Sisa: Rp0, diminta: Rp5')), true, 'galat biasa tetap bisa diubah');
});
