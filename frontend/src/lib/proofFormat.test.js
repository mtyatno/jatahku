import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ISSUER_LABEL, proofHeader, paidLabel, proofWarnings, proofTotal, amountEditable, amountHint, amountFieldText,
  parseAmountInput, saveAmount, proofDate, descriptionFor, envelopeChoices, effectiveEnvelope, skipActions, canSave,
  savePayload, saveOutcome, skipOutcome, createSharedLoader,
} from './proofFormat.js';

// Hari ini dan periode berjalan dipasang tetap (tidak membaca jam): 26 Okt masih di periode 25 Okt–24 Nov.
const TODAY = '2026-10-29';
const PERIOD = { start: '2026-10-25', end: '2026-11-24' };
const FLAGS = { duplicate_of: null, skip_suggestion: null, blocked: null, warnings: [] };
const ITEM = { id: 'i1', status: 'siap', paid_at: '2026-10-26T08:12:00+07:00', description_preview: 'Siti Aminah (QRIS)',
  document: { doc_type: 'qris', issuer: 'bca_mobile', status: 'berhasil', counterparty: { city: 'BANDUNG' }, amounts: { total: 25000 } },
  flags: FLAGS };
const FORM = { envelopeId: 'e1', period: PERIOD, today: TODAY, online: true };
const OLD = '2026-09-30T02:00:00+00:00';   // 30 Sep 09.00 WIB: sebelum awal periode
const withDoc = (patch, item = ITEM) => ({ ...item, document: { ...item.document, ...patch } });
const withFlags = (patch, item = ITEM) => ({ ...item, flags: { ...FLAGS, ...patch } });
const typed = (doc_type, item = ITEM) => ({ ...withDoc({ doc_type }, item), doc_type });

test('proofHeader dan paidLabel (rencana): label penerbit, status, tanggal & jam WIB, kota', () => {
  assert.deepEqual(proofHeader(ITEM), { badge: 'QRIS · BCA mobile', statusText: 'Berhasil', statusTone: 'success' });
  assert.equal(paidLabel(ITEM), '26 Okt 2026, 08.12 · Bandung');
  // Server (Postgres) mengirim UTC: tanggal dan jam tetap WIB, bukan potongan teks ISO.
  assert.equal(paidLabel({ ...ITEM, paid_at: '2026-10-26T01:12:00+00:00' }), '26 Okt 2026, 08.12 · Bandung');
  assert.equal(paidLabel({ ...ITEM, paid_at: '2026-10-25T17:30:00+00:00' }), '26 Okt 2026, 00.30 · Bandung');
});

test('proofHeader: badge untuk setiap jenis dokumen; penerbit hanya untuk QRIS/transfer', () => {
  const badge = (doc_type, issuer = null) => proofHeader({ ...typed(doc_type), document: { ...ITEM.document, doc_type, issuer } }).badge;
  assert.equal(badge('qris'), 'QRIS');
  assert.equal(badge('transfer'), 'Transfer');
  assert.equal(badge('transfer', 'livin'), "Transfer · Livin' by Mandiri");
  assert.equal(badge('struk_belanja'), 'Struk belanja');
  assert.equal(badge('struk_belanja', 'bca_mobile'), 'Struk belanja');
  assert.equal(badge('tidak_dikenali'), 'Bukti bayar');
  assert.equal(badge('tidak_dikenali', 'gopay'), 'Bukti bayar');
  assert.equal(badge('qris', 'bank_baru'), 'QRIS');   // penerbit yang belum dikenal klien
  assert.equal(proofHeader({ id: 'x', status: 'diproses', doc_type: null, document: null }).badge, 'Bukti bayar');
  // Jenis dari kolom item bila dokumen tidak memuatnya.
  assert.equal(proofHeader({ ...ITEM, doc_type: 'transfer', document: { ...ITEM.document, doc_type: undefined, issuer: 'jago' } }).badge,
    'Transfer · Jago');
  const expected = { bca_mobile: 'BCA mobile', livin: "Livin' by Mandiri", brimo: 'BRImo', bni: 'wondr by BNI', bsi: 'BSI',
    jago: 'Jago', seabank: 'SeaBank', blu: 'blu', gopay: 'GoPay', ovo: 'OVO', dana: 'DANA', shopeepay: 'ShopeePay' };
  assert.deepEqual(ISSUER_LABEL, expected);
  for (const [key, label] of Object.entries(expected)) assert.equal(badge('qris', key), `QRIS · ${label}`, key);
});

test('proofHeader: status Berhasil/Pending/Gagal, selain itu kosong', () => {
  const st = status => { const h = proofHeader(withDoc({ status })); return [h.statusText, h.statusTone]; };
  assert.deepEqual(st('berhasil'), ['Berhasil', 'success']);
  assert.deepEqual(st('pending'), ['Pending', 'warning']);
  assert.deepEqual(st('gagal'), ['Gagal', 'danger']);
  for (const s of ['tidak_diketahui', null, undefined, 'lain']) assert.deepEqual(st(s), ['', 'muted'], String(s));
  assert.deepEqual(proofHeader({ id: 'x', status: 'diproses', document: null }).statusText, '');
});

test('paidLabel: struk tanpa jam; tanpa kota / tanpa tanggal; kota dirapikan seperti bot', () => {
  const store = { ...typed('struk_belanja'), paid_at: '2026-10-25T17:00:00+00:00' };   // tengah malam WIB
  assert.equal(paidLabel(withDoc({ counterparty: { name: 'INDOMARET', city: null } }, store)), '26 Okt 2026');
  assert.equal(paidLabel(withDoc({ counterparty: {} }, typed('tidak_dikenali', store))), '26 Okt 2026');
  assert.equal(paidLabel(withDoc({ counterparty: { city: 'JAKARTA SELATAN' } })), '26 Okt 2026, 08.12 · Jakarta Selatan');
  assert.equal(paidLabel(withDoc({ counterparty: { city: '  KAB.  BANDUNG ' } })), '26 Okt 2026, 08.12 · Kab. Bandung');
  assert.equal(paidLabel(withDoc({ counterparty: { city: 'Kota Bandung' } })), '26 Okt 2026, 08.12 · Kota Bandung');
  assert.equal(paidLabel(withDoc({ counterparty: null })), '26 Okt 2026, 08.12');
  assert.equal(paidLabel({ ...ITEM, paid_at: null }), 'Bandung');
  assert.equal(paidLabel({ id: 'x', status: 'diproses', paid_at: null, document: null }), '');
});

test('proofWarnings (rencana): blokir lebih dulu, lalu lewati dan duplikat lunak (jam WIB)', () => {
  const w = proofWarnings({ ...ITEM, flags: { blocked: 'transaksi_gagal', skip_suggestion: 'top_up',
    duplicate_of: { kind: 'soft', transaction: { description: 'bakso 25rb', created_at: '2026-10-26T10:05:00+07:00' } }, warnings: [] } });
  assert.deepEqual(w.map(x => x.tone), ['danger', 'warning', 'warning']);
  assert.equal(w[0].text, 'Transaksi ini gagal di bank, jadi tidak bisa dicatat.');
  assert.equal(w[1].text, 'Ini top-up saldo, biasanya bukan pengeluaran.');
  assert.equal(w[2].text, 'Mirip "bakso 25rb" yang dicatat 10.05. Sudah dicatat?');
  // created_at dari Postgres berbentuk UTC: jamnya WIB.
  const utc = proofWarnings(withFlags({ duplicate_of: { kind: 'soft',
    transaction: { description: 'bakso 25rb', created_at: '2026-10-26T03:05:00.123456+00:00' } } }));
  assert.deepEqual(utc, [{ tone: 'warning', text: 'Mirip "bakso 25rb" yang dicatat 10.05. Sudah dicatat?' }]);
});

test('proofWarnings: teks lewati; peringatan server apa adanya sesudahnya; duplikat ref tanpa teks tambahan', () => {
  assert.deepEqual(proofWarnings(withFlags({ skip_suggestion: 'masuk' })),
    [{ tone: 'warning', text: 'Ini uang masuk, biasanya bukan pengeluaran.' }]);
  assert.deepEqual(proofWarnings(withFlags({ skip_suggestion: 'antar_rekening_sendiri' })),
    [{ tone: 'warning', text: 'Sepertinya transfer ke rekeningmu sendiri.' }]);
  const w = proofWarnings(withFlags({
    skip_suggestion: 'top_up',
    duplicate_of: { kind: 'ref', item_id: 'i9', recorded: false, by: 'Dewi' },
    warnings: ['Transaksi masih diproses bank', 'Bukti ini juga dibagikan Dewi', '  ', null],
  }));
  assert.deepEqual(w, [
    { tone: 'warning', text: 'Ini top-up saldo, biasanya bukan pengeluaran.' },
    { tone: 'warning', text: 'Transaksi masih diproses bank' },
    { tone: 'warning', text: 'Bukti ini juga dibagikan Dewi' },
  ]);
  assert.deepEqual(proofWarnings(ITEM), []);
  assert.deepEqual(proofWarnings({ id: 'x', status: 'diproses', flags: null }), []);
});

test('proofWarnings: alasan blokir dari kartu (409) menggantikan blokir server; duplikat lunak tanpa jam → "tadi"', () => {
  assert.deepEqual(proofWarnings(withFlags({ blocked: 'transaksi_gagal' }), { blockedReason: 'Bukti ini sudah tercatat.' }),
    [{ tone: 'danger', text: 'Bukti ini sudah tercatat.' }]);
  assert.deepEqual(proofWarnings(ITEM, { blockedReason: 'Bukti tidak ditemukan.' }), [{ tone: 'danger', text: 'Bukti tidak ditemukan.' }]);
  assert.equal(proofWarnings(withFlags({ duplicate_of: { kind: 'soft', transaction: { description: 'kopi' } } }))[0].text,
    'Mirip "kopi" yang dicatat tadi. Sudah dicatat?');
});

test('amountEditable: QRIS/transfer yang yakin hanya dibaca; ragu, tanpa total, atau jenis lain bisa diubah', () => {
  assert.equal(amountEditable(ITEM), false);
  for (const total of ['tinggi', 'sedang']) assert.equal(amountEditable(withDoc({ confidence: { total } })), false, total);
  for (const total of ['rendah', 'gagal']) assert.equal(amountEditable(withDoc({ confidence: { total } })), true, total);
  assert.equal(amountEditable(withDoc({ confidence: { total: 'tinggi' } }, typed('transfer'))), false);
  assert.equal(amountEditable(withDoc({ confidence: { total: 'rendah' } }, typed('transfer'))), true);
  for (const doc_type of ['struk_belanja', 'tidak_dikenali']) {
    assert.equal(amountEditable(withDoc({ confidence: { total: 'tinggi' } }, typed(doc_type))), true, doc_type);
  }
  // Tanpa total: satu-satunya cara mencatat adalah mengisinya.
  assert.equal(amountEditable(withDoc({ amounts: { total: null }, confidence: {} })), true);
  assert.equal(amountEditable(withDoc({ amounts: {} })), true);
});

test('amountHint: label keyakinan di atas isian nominal (sama dengan form Catat); tanpa label bila hanya dibaca', () => {
  assert.equal(amountHint(ITEM), '');
  assert.equal(amountHint(withDoc({ confidence: { total: 'rendah' } })), 'kurang yakin, mohon dicek');
  assert.equal(amountHint(withDoc({ amounts: { total: null }, confidence: {} })), 'total tidak terbaca');
  const store = typed('struk_belanja');
  assert.equal(amountHint(withDoc({ confidence: { total: 'tinggi' } }, store)), '');
  assert.equal(amountHint(withDoc({ confidence: { total: 'sedang' } }, store)), 'cek lagi nominalnya');
  assert.equal(amountHint(withDoc({ confidence: { total: 'rendah' } }, typed('tidak_dikenali'))), 'kurang yakin, mohon dicek');
  assert.equal(amountHint(withDoc({ confidence: {} }, store)), '');
});

test('parseAmountInput: rupiah dengan titik/koma/spasi ribuan, awalan Rp/IDR; selain itu null', () => {
  const cases = [['25000', 25000], ['25.000', 25000], ['Rp 25.000', 25000], ['rp25.000', 25000], ['Rp. 25.000', 25000],
    ['25,000', 25000], ['1.250.000', 1250000], [' 25 000 ', 25000], ['IDR 15.000', 15000], [26000, 26000]];
  for (const [text, n] of cases) assert.equal(parseAmountInput(text), n, String(text));
  for (const bad of ['', '  ', '0', '0.000', 'abc', '25.5', '25.00', '25.000,00', '25,000.00', '1.25.000', '25,5', '-5000',
    '25.000,50', '1.250,000', null, undefined]) {
    assert.equal(parseAmountInput(bad), null, String(bad));
  }
});

test('saveAmount: nominal yang diubah dipakai hanya bila boleh diubah', () => {
  const low = withDoc({ confidence: { total: 'rendah' }, amounts: { total: 261026 } });   // salah baca (Jago)
  assert.equal(saveAmount(low, '26.000'), 26000);
  assert.equal(saveAmount(low, undefined), 261026);   // belum disentuh: total yang terbaca
  assert.equal(saveAmount(low, ''), null);
  assert.equal(saveAmount(ITEM, '99.000'), 25000);    // hanya dibaca: teks isian diabaikan
  assert.equal(proofTotal(ITEM), 25000);
  for (const total of [null, undefined, 0, -5]) assert.equal(proofTotal(withDoc({ amounts: { total } })), null, String(total));
  assert.equal(proofTotal({ id: 'x', document: null }), null);
});

test('amountFieldText: belum disentuh → total dokumen terbaru (bukti yang baru terbaca sesudah kartu dipasang ikut terisi)', () => {
  // Bentuk view.item_detail untuk item yang belum terbaca: tanpa dokumen.
  const pending = { id: 'p1', status: 'diproses', doc_type: null, paid_at: null, document: null, merchant: null,
    suggestion: null, description_preview: null, flags: FLAGS, error: null };
  const store = { ...withDoc({ confidence: { total: 'tinggi' }, amounts: { total: 45400 } }, typed('struk_belanja')), id: 'p1' };
  const low = { ...withDoc({ confidence: { total: 'rendah' }, amounts: { total: 261026 } }, typed('transfer')), id: 'p1' };
  assert.equal(amountFieldText(pending, null), '');
  // Kartu yang sama (id sama) menerima detail siap: kolomnya terisi total, bisa langsung disimpan.
  assert.equal(amountFieldText(store, null), '45400');
  assert.equal(amountFieldText(low, null), '261026');
  assert.deepEqual(canSave(store, { ...FORM, amountText: undefined }), { ok: true, reason: null });
  assert.equal(savePayload(store, { ...FORM, ref: 'r1', amountText: undefined }).amount, 45400);
  assert.equal(saveAmount(store, undefined), 45400);
  // Sudah disentuh: ketikan user tetap, termasuk kolom yang dikosongkan.
  assert.equal(amountFieldText(store, ''), '');
  assert.equal(amountFieldText(store, '26.000'), '26.000');
  assert.equal(amountFieldText(pending, '26.000'), '26.000');
  assert.equal(amountFieldText(withDoc({ amounts: { total: null }, confidence: {} }), undefined), '');
});

test('proofDate: tanggal dokumen di periode berjalan → tanggal itu; tanpa paid_at → tanpa tanggal', () => {
  assert.deepEqual(proofDate(ITEM, FORM), { kind: 'current', docDate: '2026-10-26', date: '2026-10-26', notice: null, choices: [] });
  assert.deepEqual(proofDate({ ...ITEM, paid_at: null }, FORM), { kind: null, docDate: null, date: null, notice: null, choices: [] });
  // 00.30 WIB = hari sebelumnya di UTC: tanggalnya WIB.
  assert.equal(proofDate({ ...ITEM, paid_at: '2026-10-25T17:30:00+00:00' }, FORM).date, '2026-10-26');
});

test('proofDate: periode lalu → pertanyaan seperti form Catat, tanggal kosong sampai dipilih', () => {
  const old = { ...ITEM, paid_at: OLD };
  const d = proofDate(old, FORM);
  assert.equal(d.kind, 'past');
  assert.equal(d.date, null);
  assert.equal(d.notice.text, 'Tanggal di bukti: 30 Sep — di luar periode sekarang (25 Okt–24 Nov). Catat untuk tanggal berapa?');
  assert.deepEqual(d.choices.map(c => [c.key, c.label, c.date, c.picked]),
    [['today', 'Hari ini', TODAY, false], ['doc', '30 Sep', '2026-09-30', false]]);
  assert.equal(proofDate(old, { ...FORM, dateChoice: 'today' }).date, TODAY);
  const doc = proofDate(old, { ...FORM, dateChoice: 'doc' });
  assert.equal(doc.date, '2026-09-30');
  assert.deepEqual(doc.choices.map(c => c.picked), [false, true]);
  assert.equal(proofDate(old, { ...FORM, dateChoice: 'lain' }).date, null);
  // "struk" untuk struk belanja (tanggalnya tengah malam WIB).
  const store = { ...typed('struk_belanja'), paid_at: '2026-09-29T17:00:00+00:00' };
  assert.ok(proofDate(store, FORM).notice.text.startsWith('Tanggal di struk: 30 Sep — '));
});

test('proofDate: masa depan → hari ini dengan keterangan; diblokir → tanpa pertanyaan; periode belum ada → tidak bertanya', () => {
  const future = proofDate({ ...ITEM, paid_at: '2026-11-02T01:00:00+00:00' }, FORM);
  assert.deepEqual([future.kind, future.date, future.notice.text],
    ['future', TODAY, 'Tanggal di bukti (2 Nov) belum lewat — dicatat hari ini.']);
  assert.deepEqual(future.choices, []);
  const blocked = proofDate(withFlags({ blocked: 'transaksi_gagal' }, { ...ITEM, paid_at: OLD }), FORM);
  assert.equal(blocked.notice, null);
  assert.equal(proofDate({ ...ITEM, paid_at: OLD }, { ...FORM, blockedReason: 'Bukti ini sudah tercatat.' }).notice, null);
  assert.equal(proofDate({ ...ITEM, paid_at: OLD }, { ...FORM, period: null }).kind, 'current');
});

test('descriptionFor: QRIS/transfer dari server; catatan baru sebelum saran kembali → disusun sama dengan server', () => {
  assert.equal(descriptionFor(ITEM, {}), 'Siti Aminah (QRIS)');
  const merchant = { id: 'm1', name: 'Siti Aminah', display_name: null };
  const item = { ...ITEM, merchant };
  assert.equal(descriptionFor(item, { note: '  ' }), 'Siti Aminah (QRIS)');
  // Saran untuk catatan yang sama sudah kembali → teks server.
  assert.equal(descriptionFor(item, { note: 'bakso 2', preview: { note: 'bakso 2', name: 'Siti Aminah', text: 'bakso 2 (Siti Aminah)' } }),
    'bakso 2 (Siti Aminah)');
  // Belum kembali (atau gagal): disusun di sini, catatannya tidak hilang.
  assert.equal(descriptionFor(item, { note: ' bakso 2, es teh ', preview: { note: 'bakso', name: 'Siti Aminah', text: 'bakso (Siti Aminah)' } }),
    'bakso 2, es teh (Siti Aminah)');
  // Nama panggilan baru (Ubah nama) menggantikan nama.
  const renamed = { ...merchant, display_name: 'Bu Siti' };
  assert.equal(descriptionFor(item, { merchant: renamed }), 'Bu Siti (QRIS)');
  assert.equal(descriptionFor(item, { merchant: renamed, note: 'bakso' }), 'bakso (Bu Siti)');
  const transfer = { ...typed('transfer', item), description_preview: 'Transfer ke Budi Santoso',
    merchant: { id: 'm2', name: 'Budi Santoso', display_name: null } };
  assert.equal(descriptionFor(transfer, {}), 'Transfer ke Budi Santoso');
  assert.equal(descriptionFor(transfer, { merchant: { ...transfer.merchant, display_name: 'Pak Budi' } }), 'Transfer ke Pak Budi');
  // Tanpa nama sama sekali: keterangan cadangan server.
  assert.equal(descriptionFor({ ...item, merchant: null, description_preview: null }, {}), 'Pembayaran QRIS');
  assert.equal(descriptionFor({ ...transfer, merchant: null, description_preview: null }, {}), 'Transfer');
  assert.equal(descriptionFor({ ...item, merchant: null }, { note: 'parkir' }), 'parkir');
});

test('descriptionFor: struk belanja dan tidak dikenali → nama toko atau "Belanja" (sama dengan form Catat)', () => {
  const store = { ...typed('struk_belanja'), description_preview: 'Indomaret', merchant: { id: null, name: 'Indomaret', display_name: null } };
  assert.equal(descriptionFor(store, {}), 'Indomaret');
  assert.equal(descriptionFor({ ...store, merchant: null, description_preview: 'Bukti bayar' }, {}), 'Belanja');
  assert.equal(descriptionFor({ ...typed('tidak_dikenali', store), merchant: null, description_preview: 'Bukti bayar' }, {}), 'Belanja');
  assert.equal(descriptionFor({ ...typed('tidak_dikenali', store), merchant: { id: 'm3', name: 'Warung Ani', display_name: null } }, {}),
    'Warung Ani');
  assert.equal(descriptionFor(store, { note: 'sabun' }), 'sabun (Indomaret)');
});

const ENVS = [
  { id: 'e1', name: 'Makan', emoji: '🍜', purpose: 'expense' },
  { id: 'e2', name: 'Jajan', emoji: '☕', purpose: 'expense' },
  { id: 'e3', name: 'Tabungan', emoji: '🐷', purpose: 'saving' },
  { id: 'e4', name: 'Langganan', emoji: '🔄', purpose: 'sinking_fund' },
  { id: 'e5', name: 'Cicilan', emoji: '💳', purpose: 'debt' },
  { id: 'e6', name: 'Lama', emoji: '📁', purpose: 'expense', is_active: false },
  { id: 'e7', name: 'Lain', emoji: '📁', purpose: null },
];

test('envelopeChoices: daftar yang sama dengan form Catat; saran teratas, "disarankan" hanya bila yakin', () => {
  assert.deepEqual(envelopeChoices(ENVS, null).map(c => c.id), ['e1', 'e2', 'e5', 'e7']);
  const sure = envelopeChoices(ENVS, { envelope_id: 'e2', confident: true });
  assert.deepEqual(sure.map(c => [c.id, c.suggested]), [['e2', true], ['e1', false], ['e5', false], ['e7', false]]);
  assert.deepEqual(sure[0], { id: 'e2', name: 'Jajan', emoji: '☕', suggested: true });
  const unsure = envelopeChoices(ENVS, { envelope_id: 'e2', confident: false });
  assert.deepEqual(unsure.map(c => [c.id, c.suggested]), [['e2', false], ['e1', false], ['e5', false], ['e7', false]]);
  // Urutan tetap dari saran awal (tombol tidak berpindah di bawah jari); tanda mengikuti saran terbaru.
  const later = envelopeChoices(ENVS, { envelope_id: 'e5', confident: true }, { first: 'e2' });
  assert.deepEqual(later.map(c => [c.id, c.suggested]), [['e2', false], ['e1', false], ['e5', true], ['e7', false]]);
  assert.deepEqual(envelopeChoices(ENVS, { envelope_id: 'e3', confident: true }).map(c => c.id), ['e1', 'e2', 'e5', 'e7']);
  assert.deepEqual(envelopeChoices(undefined, null), []);
});

test('effectiveEnvelope: pilihan user menang; saran yakin dipilihkan hanya bila ada di daftar', () => {
  const choices = envelopeChoices(ENVS, null);
  assert.equal(effectiveEnvelope(choices, { suggestion: { envelope_id: 'e1', confident: true } }), 'e1');
  assert.equal(effectiveEnvelope(choices, { suggestion: { envelope_id: 'e1', confident: false } }), '');
  assert.equal(effectiveEnvelope(choices, { suggestion: { envelope_id: 'e3', confident: true } }), '');   // tabungan
  assert.equal(effectiveEnvelope([], { suggestion: { envelope_id: 'e1', confident: true } }), '');        // amplop belum dimuat
  assert.equal(effectiveEnvelope(choices, { picked: 'e2', suggestion: { envelope_id: 'e1', confident: true } }), 'e2');
  assert.equal(effectiveEnvelope(choices, { picked: 'e9', suggestion: { envelope_id: 'e1', confident: true } }), '');
  assert.equal(effectiveEnvelope(choices, {}), '');
});

test('skipActions: Bukan pengeluaran; Sama, lewati untuk duplikat; tidak ada sesudah blokir dari kartu', () => {
  const r = acts => acts.map(a => [a.label, a.reason]);
  assert.deepEqual(r(skipActions(ITEM)), [['Bukan pengeluaran', 'bukan_pengeluaran']]);
  const soft = withFlags({ duplicate_of: { kind: 'soft', transaction: { description: 'x' } } });
  assert.deepEqual(r(skipActions(soft)), [['Sama, lewati', 'duplikat'], ['Bukan pengeluaran', 'bukan_pengeluaran']]);
  assert.deepEqual(r(skipActions(withFlags({ blocked: 'sudah_tercatat', duplicate_of: { kind: 'ref', item_id: 'i0', recorded: true } }))),
    [['Sama, lewati', 'duplikat']]);
  assert.deepEqual(r(skipActions(withFlags({ blocked: 'transaksi_gagal' }, soft))), [['Bukan pengeluaran', 'bukan_pengeluaran']]);
  assert.deepEqual(skipActions(ITEM, { blockedReason: 'Bukti ini sudah tercatat.' }), []);
  assert.deepEqual(skipActions({ ...ITEM, status: 'diproses' }), []);
});

test('canSave (rencana): tanpa amplop; blokir', () => {
  assert.deepEqual(canSave(ITEM, { ...FORM, envelopeId: '' }), { ok: false, reason: 'Pilih amplop dulu' });
  assert.equal(canSave(withFlags({ blocked: 'sudah_tercatat' }), FORM).reason, 'Bukti ini sudah tercatat.');
  assert.deepEqual(canSave(ITEM, FORM), { ok: true, reason: null });
});

test('canSave: urutan alasan — blokir, belum siap, nominal, tanggal, amplop, koneksi', () => {
  const noTotal = withDoc({ amounts: { total: null }, confidence: {} }, { ...ITEM, paid_at: OLD });
  const reading = { ...noTotal, status: 'diproses' };
  const none = { ...FORM, envelopeId: '', online: false };
  assert.equal(canSave(withFlags({ blocked: 'transaksi_gagal' }, reading), none).reason, 'Transaksi ini gagal di bank, jadi tidak bisa dicatat.');
  assert.equal(canSave(reading, { ...none, blockedReason: 'Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya.' }).reason,
    'Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya.');
  assert.equal(canSave(reading, none).reason, 'Bukti belum siap');
  assert.equal(canSave(noTotal, none).reason, 'Nominal tidak terbaca');
  assert.equal(canSave(noTotal, { ...none, amountText: '25.000' }).reason, 'Pilih tanggal catat');
  assert.equal(canSave(noTotal, { ...none, amountText: '25.000', dateChoice: 'doc' }).reason, 'Pilih amplop dulu');
  assert.equal(canSave(noTotal, { ...none, amountText: '25.000', dateChoice: 'doc', envelopeId: 'e1' }).reason, 'Butuh koneksi internet');
  assert.deepEqual(canSave(noTotal, { ...FORM, amountText: '25.000', dateChoice: 'today' }), { ok: true, reason: null });
  // Nominal yang boleh diubah lalu dikosongkan / tidak masuk akal.
  assert.equal(canSave(withDoc({ confidence: { total: 'rendah' } }), { ...FORM, amountText: '' }).reason, 'Nominal tidak terbaca');
  assert.equal(canSave(withDoc({ confidence: { total: 'rendah' } }), { ...FORM, amountText: '25.5' }).reason, 'Nominal tidak terbaca');
  // Hanya dibaca dan ada total: isian diabaikan.
  assert.deepEqual(canSave(ITEM, { ...FORM, amountText: '' }), { ok: true, reason: null });
  // Masa depan → hari ini, tanpa pertanyaan.
  assert.deepEqual(canSave({ ...ITEM, paid_at: '2026-11-02T01:00:00+00:00' }, FORM), { ok: true, reason: null });
});

test('canSave: status selesai punya alasannya sendiri; status lain yang belum siap → "Bukti belum siap"', () => {
  const store = withDoc({ confidence: { total: 'tinggi' } }, typed('struk_belanja'));
  // Struk belanja tercatat tidak membawa blocked (boleh dicatat lagi di form Catat): alasannya dari status.
  assert.equal(canSave({ ...store, status: 'tercatat' }, FORM).reason, 'Bukti ini sudah tercatat.');
  assert.equal(canSave({ ...ITEM, status: 'dilewati' }, FORM).reason, 'Bukti ini sudah dilewati.');
  assert.equal(canSave({ ...ITEM, status: 'kedaluwarsa' }, FORM).reason, 'Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya.');
  for (const status of ['diterima', 'diproses', 'gagal', undefined]) {
    assert.equal(canSave({ ...ITEM, status }, FORM).reason, 'Bukti belum siap', String(status));
  }
  // Blokir tetap lebih dulu (bukti tercatat membawa blocked dari server).
  assert.equal(canSave(withFlags({ blocked: 'transaksi_gagal' }, { ...ITEM, status: 'dilewati' }), FORM).reason,
    'Transaksi ini gagal di bank, jadi tidak bisa dicatat.');
});

test('savePayload (rencana): satu transaksi dengan receipt_item_id, client_ref, tanggal WIB', () => {
  assert.deepEqual(savePayload(ITEM, { ...FORM, description: 'Siti Aminah (QRIS)', ref: 'r1' }), {
    envelope_id: 'e1', amount: 25000, description: 'Siti Aminah (QRIS)', source: 'webapp',
    transaction_date: '2026-10-26', receipt_item_id: 'i1', client_ref: 'r1' });
});

test('savePayload: tanggal WIB (bukan potongan ISO), tanggal yang dipilih, masa depan → hari ini, tanpa tanggal', () => {
  const p = (item, extra = {}) => savePayload(item, { ...FORM, description: 'x', ref: 'r1', ...extra });
  assert.equal(p({ ...ITEM, paid_at: '2026-10-25T17:30:00+00:00' }).transaction_date, '2026-10-26');   // 00.30 WIB
  assert.equal(p({ ...ITEM, paid_at: OLD }, { dateChoice: 'today' }).transaction_date, TODAY);
  assert.equal(p({ ...ITEM, paid_at: OLD }, { dateChoice: 'doc' }).transaction_date, '2026-09-30');
  assert.equal(p({ ...ITEM, paid_at: '2026-11-02T01:00:00+00:00' }).transaction_date, TODAY);
  assert.equal('transaction_date' in p({ ...ITEM, paid_at: null }), false);
});

test('savePayload: nominal yang diubah (bila boleh), naikkan limit, keterangan dari catatan', () => {
  const low = withDoc({ confidence: { total: 'rendah' }, amounts: { total: 261026 } });
  const payload = savePayload(low, { ...FORM, description: 'x', ref: 'r1', amountText: '26.000', raiseLimit: true });
  assert.deepEqual([payload.amount, payload.raise_daily_limit, payload.client_ref, payload.receipt_item_id], [26000, true, 'r1', 'i1']);
  assert.equal(savePayload(ITEM, { ...FORM, description: 'x', ref: 'r1', amountText: '99.000' }).amount, 25000);
  const store = withDoc({ confidence: { total: 'tinggi' } }, typed('struk_belanja'));
  assert.equal(savePayload(store, { ...FORM, description: 'x', ref: 'r1', amountText: '24.500' }).amount, 24500);
  assert.equal('raise_daily_limit' in savePayload(ITEM, { ...FORM, description: 'x', ref: 'r1' }), false);
  const named = { ...ITEM, merchant: { id: 'm1', name: 'Siti Aminah', display_name: null } };
  assert.equal(savePayload(named, { ...FORM, ref: 'r1', note: 'bakso' }).description, 'bakso (Siti Aminah)');
  // Keterangan yang diberikan kartu (yang tampil sebagai "Keterangan: …") dikirim apa adanya.
  assert.equal(savePayload(named, { ...FORM, ref: 'r1', note: 'bakso', description: 'bakso 2, es teh (Siti Aminah)' }).description,
    'bakso 2, es teh (Siti Aminah)');
});

test('saveOutcome: tercatat; belum pasti (jaringan, 5xx, sedang diproses); 409 → blokir; limit harian; dana kurang; lainnya', () => {
  assert.deepEqual(saveOutcome({ ok: true, status: 201, data: { id: 't1', quota_notice: 'Kuota habis' } }),
    { kind: 'saved', transaction: { id: 't1', quota_notice: 'Kuota habis' }, quotaNotice: 'Kuota habis' });
  assert.equal(saveOutcome({ ok: true, status: 201, data: { id: 't1' } }).quotaNotice, null);
  for (const res of [null, undefined, { ok: false, status: 0, data: {} }]) {
    assert.deepEqual(saveOutcome(res), { kind: 'uncertain', text: 'Koneksi terputus. Coba lagi — tidak akan tercatat dua kali.' });
  }
  // 500 = bisa jadi sudah ter-commit lalu gagal (efek sesudah commit): belum pasti, isian dikunci, kirim ulang sama.
  for (const status of [500, 502]) {
    assert.deepEqual(saveOutcome({ ok: false, status, data: {} }),
      { kind: 'uncertain', text: 'Hasil simpan belum pasti. Tekan Simpan lagi — tidak akan tercatat dua kali.' }, String(status));
  }
  assert.deepEqual(saveOutcome({ ok: false, status: 503, data: { detail: 'Gagal menaikkan limit harian. Coba lagi sebentar.' } }),
    { kind: 'uncertain', text: 'Gagal menaikkan limit harian. Coba lagi sebentar. Tekan Simpan lagi — tidak akan tercatat dua kali.' });
  assert.equal(saveOutcome({ ok: false, status: 409, data: { detail: 'Transaksi ini sedang diproses. Coba lagi sebentar.' } }).kind,
    'uncertain');
  for (const detail of ['Bukti ini sudah tercatat', 'Bukti ini sudah kedaluwarsa, bagikan lagi untuk mencatatnya',
    'Bukti ini belum siap dicatat', 'Bukti tidak ditemukan', 'Transaksi gagal, tidak bisa dicatat']) {
    assert.deepEqual(saveOutcome({ ok: false, status: 409, data: { detail } }), { kind: 'blocked', text: `${detail}.` });
  }
  assert.deepEqual(saveOutcome({ ok: false, status: 409, data: {} }), { kind: 'blocked', text: 'Bukti ini tidak bisa dicatat.' });
  const limit = 'Melebihi limit harian Makan: limit Rp50.000/hari, terpakai Rp40.000, diminta Rp25.000.';
  assert.deepEqual(saveOutcome({ ok: false, status: 403, data: { detail: limit } }), { kind: 'limit', text: limit });
  for (const detail of ['💸 Dana tidak cukup. Sisa: Rp19,000, diminta: Rp25,000', '💸 Amplop Makan belum ada dana. Alokasikan income dulu.']) {
    assert.deepEqual(saveOutcome({ ok: false, status: 403, data: { detail } }), { kind: 'funds', text: detail });
  }
  assert.deepEqual(saveOutcome({ ok: false, status: 403, data: { detail: 'Amplop dikunci. Tidak bisa belanja.' } }),
    { kind: 'error', text: 'Amplop dikunci. Tidak bisa belanja.' });
  assert.deepEqual(saveOutcome({ ok: false, status: 422, data: { detail: [{ msg: 'x' }] } }), { kind: 'error', text: 'Gagal menyimpan. Coba lagi.' });
});

test('skipOutcome: dilewati; 409/404 → alasan blokir kartu; jaringan → pesan, kartu tetap', () => {
  assert.deepEqual(skipOutcome({ ok: true, status: 200, data: { id: 'i1', status: 'dilewati' } }),
    { kind: 'skipped', item: { id: 'i1', status: 'dilewati' } });
  assert.deepEqual(skipOutcome({ ok: false, status: 409, data: { detail: 'Bukti ini tidak bisa dilewati' } }),
    { kind: 'blocked', text: 'Bukti ini tidak bisa dilewati.' });
  assert.deepEqual(skipOutcome({ ok: false, status: 404, data: { detail: 'Bukti tidak ditemukan' } }),
    { kind: 'blocked', text: 'Bukti tidak ditemukan.' });
  assert.deepEqual(skipOutcome({ ok: false, status: 409, data: {} }), { kind: 'blocked', text: 'Bukti ini tidak bisa dilewati.' });
  assert.deepEqual(skipOutcome({ ok: false, status: 0, data: { detail: 'Koneksi gagal, coba lagi' } }),
    { kind: 'error', text: 'Koneksi gagal, coba lagi' });
  assert.deepEqual(skipOutcome({ ok: false, status: 500, data: {} }), { kind: 'error', text: 'Koneksi gagal, coba lagi' });
  assert.deepEqual(skipOutcome(null), { kind: 'error', text: 'Koneksi gagal, coba lagi' });
});

test('createSharedLoader: satu permintaan untuk banyak kartu, disimpan sebentar, gagal dicoba lagi', async () => {
  let t = 0;
  let calls = 0;
  let fail = false;
  const load = createSharedLoader(async () => { calls++; if (fail) throw new Error('x'); return { start: 's' }; }, { ttlMs: 1000, now: () => t });
  const [a, b] = await Promise.all([load(), load()]);
  assert.deepEqual([a, b, calls], [{ start: 's' }, { start: 's' }, 1]);
  t = 999;
  await load();
  assert.equal(calls, 1);
  t = 1000;
  await load();
  assert.equal(calls, 2);
  fail = true;
  t = 5000;
  assert.equal(await load(), null);
  assert.equal(await load(), null);
  assert.equal(calls, 4);   // gagal tidak disimpan
  fail = false;
  assert.deepEqual(await load(), { start: 's' });
  assert.equal(calls, 5);
  // null dari pemuat (mis. periode tidak terbaca) juga tidak disimpan.
  let empty = 0;
  const none = createSharedLoader(async () => { empty++; return null; }, { ttlMs: 1000, now: () => 0 });
  await none();
  await none();
  assert.equal(empty, 2);
});
