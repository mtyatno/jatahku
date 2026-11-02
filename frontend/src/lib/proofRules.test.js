import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  KIND_LABEL, RULE_TABS, NOTE_MAX, RULE_MIN_USERS, THRESHOLD_HINT, WARNING_TEXT, ruleAppLabel, syntheticExample,
  ruleActions, rowActions, actionButtons, ruleSummary, tabCounts, ruleRows, voteRows, noteError, notePayload,
  decisionBody, actionOutcome, pendingBadge, hasRulesSection, emptyText, nextTab,
} from './proofRules.js';

// Bentuk GET /admin/kotak/rules?status=semua (app/api/routes/admin_kotak.py, laporan L4a). Data karangan.
const rule = over => ({
  id: 'r1', kind: 'label_total', rule_key: 'gopay', value: 'total bayar', users: 3, households: 2, status: 'menunggu',
  created_at: '2026-10-20T03:00:00Z', decided_at: null, decided_by: null, decided_by_name: null, note: null,
  example: 'Total bayar Rp##.###', warning: false, ...over,
});
const RESP = {
  counts: { menunggu: 3, disetujui: 1, ditolak: 1, dicabut: 1 },
  rules: [
    rule({ id: 'm-old', users: 2, households: 1, created_at: '2026-10-18T03:00:00Z' }),
    rule({ id: 'm-top', kind: 'label_pihak', rule_key: 'bca_mobile', value: 'nama penerima', users: 5, households: 4 }),
    rule({ id: 'm-new', kind: 'label_tanggal', rule_key: 'logo:jeniuspay', value: 'waktu transaksi', users: 2,
      households: 2, created_at: '2026-10-25T03:00:00Z' }),
    rule({ id: 'ok', status: 'disetujui', decided_at: '2026-10-21T18:30:00Z', decided_by: 'a1', decided_by_name: 'Admin Satu',
      note: 'cocok dengan contoh' }),
    rule({ id: 'no', status: 'ditolak', value: 'status transaksi', warning: true, decided_at: '2026-10-22T03:00:00Z',
      decided_by: 'a1', decided_by_name: 'Admin Satu' }),
    rule({ id: 'rv', status: 'dicabut', rule_key: 'mystery_app', decided_at: '2026-10-23T03:00:00Z', decided_by: 'a1',
      decided_by_name: null }),
  ],
};

test('KIND_LABEL dan tab: jenis tahap 1 dan lima tab berurutan', () => {
  assert.deepEqual(KIND_LABEL, { label_total: 'Nominal', label_pihak: 'Nama penerima', label_tanggal: 'Tanggal' });
  assert.deepEqual(RULE_TABS.map(t => [t.key, t.label]), [
    ['menunggu', 'Menunggu'], ['disetujui', 'Disetujui'], ['ditolak', 'Ditolak'], ['dicabut', 'Dicabut'], ['suara', 'Suara'],
  ]);
  assert.equal(NOTE_MAX, 200);
  assert.equal(RULE_MIN_USERS, 2);
  assert.equal(THRESHOLD_HINT, 'Belum didukung 2 user');
});

test('ruleAppLabel: label penerbit, logo:x → Aplikasi baru, selain itu kunci asli', () => {
  assert.equal(ruleAppLabel('gopay'), 'GoPay');
  assert.equal(ruleAppLabel('livin'), "Livin' by Mandiri");
  assert.equal(ruleAppLabel('logo:jeniuspay'), 'Aplikasi baru: jeniuspay');
  assert.equal(ruleAppLabel('mystery_app'), 'mystery_app');
  assert.equal(ruleAppLabel('toString'), 'toString');   // bukan properti prototipe
  assert.equal(ruleAppLabel('logo:'), 'logo:');
  assert.equal(ruleAppLabel(null), '–');
  assert.equal(ruleAppLabel(''), '–');
});

test('syntheticExample: label berhuruf awal kapital + nilai tersamar; tidak pernah angka', () => {
  assert.equal(syntheticExample({ kind: 'label_total', value: 'total bayar' }), 'Total bayar Rp##.###');
  assert.equal(syntheticExample({ kind: 'label_pihak', value: 'nama penerima' }), 'Nama penerima NAMA PENERIMA');
  assert.equal(syntheticExample({ kind: 'label_tanggal', value: 'waktu transaksi' }), 'Waktu transaksi ## Okt ####');
  assert.equal(syntheticExample({ kind: 'arah', value: 'uang keluar' }), 'Uang keluar …');
  // Contoh dibangun dari label dan jenis saja: teks lain dari server (mis. `example` berisi data) tidak pernah dipakai.
  const ex = syntheticExample({ kind: 'label_total', value: 'nominal', example: 'Nominal Rp1.250.000 BUDI 0812345678' });
  assert.equal(ex, 'Nominal Rp##.###');
  // Jenis yang belum punya topeng (tahap 2: arah, logo) juga tidak memakai `example` server.
  assert.equal(syntheticExample({ kind: 'arah', value: 'x', example: 'X 0812345678 BUDI' }), 'X …');
  for (const r of RESP.rules) assert.doesNotMatch(syntheticExample(r), /\d/);
  // Label yang memuat # (digit tersamar) tetap tanpa angka.
  assert.doesNotMatch(syntheticExample({ kind: 'label_total', value: 'total #' }), /\d/);
  assert.equal(syntheticExample(null), null);
  assert.equal(syntheticExample({ kind: 'label_total', value: '' }), null);
  assert.equal(syntheticExample({ kind: 'label_total', value: 12 }), null);
});

test('ruleActions: transisi G5 per status', () => {
  assert.deepEqual(ruleActions('menunggu'), ['setujui', 'tolak']);
  assert.deepEqual(ruleActions('disetujui'), ['cabut']);
  assert.deepEqual(ruleActions('ditolak'), ['setujui']);
  assert.deepEqual(ruleActions('dicabut'), ['setujui']);
  assert.deepEqual(ruleActions('semua'), []);
  assert.deepEqual(ruleActions(undefined), []);
  assert.deepEqual(ruleActions('__proto__'), []);
  // Salinan: mengubah hasil tidak mengubah tabel.
  ruleActions('menunggu').push('cabut');
  assert.deepEqual(ruleActions('menunggu'), ['setujui', 'tolak']);
});

test('rowActions: tanpa Setujui di bawah ambang 2 user (status apa pun); tolak dan cabut tetap', () => {
  assert.deepEqual(rowActions('menunggu', 2), ['setujui', 'tolak']);
  assert.deepEqual(rowActions('menunggu', 1), ['tolak']);
  assert.deepEqual(rowActions('ditolak', 1), []);
  assert.deepEqual(rowActions('dicabut', 0), []);
  assert.deepEqual(rowActions('dicabut', 2), ['setujui']);
  assert.deepEqual(rowActions('disetujui', 1), ['cabut']);
  assert.deepEqual(rowActions('menunggu', 'banyak'), ['tolak']);
  assert.deepEqual(rowActions('aneh', 5), []);
});

test('actionButtons: label Indonesia; semua mati selama ada permintaan berjalan atau catatan tidak sah', () => {
  assert.deepEqual(actionButtons({ actions: ['setujui', 'tolak'] }, false, ''), [
    { action: 'setujui', label: 'Setujui', disabled: false },
    { action: 'tolak', label: 'Tolak', disabled: false },
  ]);
  assert.deepEqual(actionButtons({ actions: ['cabut'] }, true, ''), [{ action: 'cabut', label: 'Cabut', disabled: true }]);
  assert.deepEqual(actionButtons({ actions: ['setujui'] }, false, 'x'.repeat(201)),
    [{ action: 'setujui', label: 'Setujui', disabled: true }]);
  assert.deepEqual(actionButtons({ actions: ['setujui'] }, false, 'a\tb'), [{ action: 'setujui', label: 'Setujui', disabled: true }]);
  assert.deepEqual(actionButtons({ actions: ['setujui'] }, false, 'x'.repeat(200)),
    [{ action: 'setujui', label: 'Setujui', disabled: false }]);
  assert.deepEqual(actionButtons({ actions: ['hapus', '__proto__'] }, false, ''), []);
  assert.deepEqual(actionButtons(null, false, ''), []);
});

test('ruleSummary dan tabCounts: dari counts server; rusak → null / nol', () => {
  assert.equal(ruleSummary(RESP), '3 menunggu · 1 disetujui · 1 ditolak · 1 dicabut');
  assert.equal(ruleSummary({ counts: { menunggu: 2 }, rules: [] }), '2 menunggu · 0 disetujui · 0 ditolak · 0 dicabut');
  assert.equal(ruleSummary({ counts: { menunggu: -1, disetujui: 1.5, ditolak: '2' }, rules: [] }),
    '0 menunggu · 0 disetujui · 0 ditolak · 0 dicabut');
  assert.equal(ruleSummary(null), null);
  assert.equal(ruleSummary({ rules: [] }), null);
  assert.equal(ruleSummary({ counts: [1, 2] }), null);
  assert.deepEqual(tabCounts(RESP), { menunggu: 3, disetujui: 1, ditolak: 1, dicabut: 1 });
  assert.deepEqual(tabCounts(undefined), { menunggu: 0, disetujui: 0, ditolak: 0, dicabut: 0 });
});

test('ruleRows menunggu: pendukung terbanyak dulu, lalu yang lebih dulu masuk; isi baris', () => {
  const rows = ruleRows(RESP, 'menunggu');
  assert.deepEqual(rows.map(r => r.id), ['m-top', 'm-old', 'm-new']);
  assert.deepEqual(rows[0], {
    id: 'm-top', status: 'menunggu', kind: 'Nama penerima', app: 'BCA mobile', label: 'nama penerima',
    example: 'Nama penerima NAMA PENERIMA', support: '5 user · 4 rumah tangga', date: 'Masuk 20 Okt 2026',
    meta: '5 user · 4 rumah tangga · Masuk 20 Okt 2026', note: null, warning: null, threshold: null,
    actions: ['setujui', 'tolak'],
  });
  assert.equal(rows[2].app, 'Aplikasi baru: jeniuspay');
  assert.equal(rows[2].kind, 'Tanggal');
  assert.equal(rows[2].example, 'Waktu transaksi ## Okt ####');
  assert.equal(rows[2].support, '2 user · 2 rumah tangga');
});

test('ruleRows tab keputusan: keputusan terbaru dulu; tanggal, pemutus, catatan, peringatan', () => {
  const resp = {
    counts: RESP.counts,
    rules: [
      rule({ id: 'a', status: 'disetujui', decided_at: '2026-10-01T03:00:00Z', users: 9 }),
      rule({ id: 'b', status: 'disetujui', decided_at: '2026-10-05T03:00:00Z', users: 2 }),
      rule({ id: 'c', status: 'disetujui', decided_at: null, users: 4 }),
    ],
  };
  assert.deepEqual(ruleRows(resp, 'disetujui').map(r => r.id), ['b', 'a', 'c']);
  const [ok] = ruleRows(RESP, 'disetujui');
  // 18.30 UTC = 01.30 WIB tanggal berikutnya.
  assert.equal(ok.date, 'Disetujui 22 Okt 2026 oleh Admin Satu');
  assert.equal(ok.note, 'cocok dengan contoh');
  assert.deepEqual(ok.actions, ['cabut']);
  const [no] = ruleRows(RESP, 'ditolak');
  assert.equal(no.warning, WARNING_TEXT);
  assert.equal(WARNING_TEXT, 'Label ini mirip kata status/metode — periksa contohnya.');
  assert.deepEqual(no.actions, ['setujui']);
  const [rv] = ruleRows(RESP, 'dicabut');
  assert.equal(rv.date, 'Dicabut 23 Okt 2026');
  assert.equal(rv.app, 'mystery_app');
  assert.deepEqual(rv.actions, ['setujui']);
});

test('ruleRows: warning hanya bila true; tanggal rusak → tanpa tanggal; catatan kosong → null', () => {
  const resp = { counts: {}, rules: [
    rule({ id: 'w1', warning: 'true' }), rule({ id: 'w2', warning: 1 }), rule({ id: 'w3', warning: true }),
    rule({ id: 'd1', created_at: 'kemarin', note: '   ' }),
  ] };
  const rows = ruleRows(resp, 'menunggu');
  assert.deepEqual(rows.map(r => [r.id, r.warning]), [['w1', null], ['w2', null], ['w3', WARNING_TEXT], ['d1', null]]);
  assert.equal(rows[3].date, null);
  assert.equal(rows[3].meta, '3 user · 2 rumah tangga');
  assert.equal(rows[3].note, null);
});

test('ruleRows: data rusak tidak melempar; baris tanpa id/status/jenis/label dilewati', () => {
  assert.equal(ruleRows(null, 'menunggu'), null);
  assert.equal(ruleRows({}, 'menunggu'), null);
  assert.equal(ruleRows({ rules: 'x' }, 'menunggu'), null);
  assert.deepEqual(ruleRows(RESP, 'suara'), []);
  assert.deepEqual(ruleRows(RESP, 'semua'), []);
  const resp = { rules: [
    null, 7, 'x', [], { id: 'a' }, rule({ id: '' }), rule({ id: 'b', value: '' }), rule({ id: 'c', kind: null }),
    rule({ id: 'd', status: 'MENUNGGU' }), rule({ id: 'e', users: 'banyak', households: null }),
  ] };
  const rows = ruleRows(resp, 'menunggu');
  assert.deepEqual(rows.map(r => r.id), ['e']);
  assert.equal(rows[0].support, '0 user · 0 rumah tangga');
  assert.deepEqual(rows[0].actions, ['tolak']);
  // Jenis yang belum dikenal klien: kunci asli.
  assert.equal(ruleRows({ rules: [rule({ kind: 'arah' })] }, 'menunggu')[0].kind, 'arah');
});

test('ruleRows di bawah ambang: petunjuk di semua status, tanpa Setujui; yang disetujui disarankan dicabut', () => {
  const resp = { rules: [
    rule({ id: 'm1', users: 1 }), rule({ id: 'm2', users: 2 }),
    rule({ id: 'd1', status: 'disetujui', users: 1, decided_at: '2026-10-21T03:00:00Z' }),
    rule({ id: 't1', status: 'ditolak', users: 1, decided_at: '2026-10-21T03:00:00Z' }),
    rule({ id: 'c1', status: 'dicabut', users: 0, decided_at: '2026-10-21T03:00:00Z' }),
    rule({ id: 'c2', status: 'dicabut', users: 4, decided_at: '2026-10-21T03:00:00Z' }),
  ] };
  const [m2, m1] = ruleRows(resp, 'menunggu');
  assert.equal(m1.id, 'm1');
  assert.equal(m1.threshold, 'Belum didukung 2 user, jadi belum bisa disetujui.');
  assert.deepEqual(m1.actions, ['tolak']);
  assert.equal(m2.threshold, null);
  assert.deepEqual(m2.actions, ['setujui', 'tolak']);
  const [d1] = ruleRows(resp, 'disetujui');
  assert.equal(d1.threshold, 'Belum didukung 2 user — masih dipakai pembaca; pertimbangkan Cabut.');
  assert.deepEqual(d1.actions, ['cabut']);
  const [t1] = ruleRows(resp, 'ditolak');
  assert.equal(t1.threshold, 'Belum didukung 2 user, jadi belum bisa disetujui.');
  assert.deepEqual(t1.actions, []);
  const cab = ruleRows(resp, 'dicabut');
  assert.deepEqual(cab.map(r => [r.id, r.actions, !!r.threshold]), [['c2', ['setujui'], false], ['c1', [], true]]);
  for (const r of [m1, d1, t1]) assert.ok(r.threshold.startsWith(THRESHOLD_HINT));
});

test('voteRows: hanya angka per aplikasi dan jenis; tanpa teks label; urut user terbanyak', () => {
  const resp = { rows: [
    { rule_key: 'ovo', kind: 'label_total', users: 1, values: 1, value: 'RAHASIA', label: 'total bayar' },
    { rule_key: 'gopay', kind: 'label_pihak', users: 3, values: 2 },
    { rule_key: 'gopay', kind: 'label_total', users: 3, values: 1 },
    { rule_key: 'logo:jeniuspay', kind: 'label_tanggal', users: 2, values: 4 },
  ] };
  const rows = voteRows(resp);
  assert.deepEqual(rows, [
    { key: 'gopay|label_total', app: 'GoPay', kind: 'Nominal', users: 3, values: 1, text: '3 user · 1 label' },
    { key: 'gopay|label_pihak', app: 'GoPay', kind: 'Nama penerima', users: 3, values: 2, text: '3 user · 2 label' },
    { key: 'logo:jeniuspay|label_tanggal', app: 'Aplikasi baru: jeniuspay', kind: 'Tanggal', users: 2, values: 4,
      text: '2 user · 4 label' },
    { key: 'ovo|label_total', app: 'OVO', kind: 'Nominal', users: 1, values: 1, text: '1 user · 1 label' },
  ]);
  assert.doesNotMatch(JSON.stringify(rows), /RAHASIA|total bayar/);
  // User sama banyak → urut NAMA aplikasi (bukan kunci: bni = "wondr by BNI", logo:x = "Aplikasi baru: x").
  assert.deepEqual(voteRows({ rows: [
    { rule_key: 'bni', kind: 'label_total', users: 2, values: 1 }, { rule_key: 'dana', kind: 'label_total', users: 2, values: 1 },
    { rule_key: 'livin', kind: 'label_total', users: 2, values: 1 }, { rule_key: 'logo:abc', kind: 'label_total', users: 2, values: 1 },
  ] }).map(r => r.app), ['Aplikasi baru: abc', 'DANA', "Livin' by Mandiri", 'wondr by BNI']);
  assert.equal(voteRows(null), null);
  assert.equal(voteRows({ rows: {} }), null);
  assert.deepEqual(voteRows({ rows: [null, 3, { kind: 'label_total', users: 2 }, { rule_key: 'ovo', kind: 5 }] }), []);
  assert.deepEqual(voteRows({ rows: [{ rule_key: 'ovo', kind: 'label_total', users: -2, values: 'x' }] }),
    [{ key: 'ovo|label_total', app: 'OVO', kind: 'Nominal', users: 0, values: 0, text: '0 user · 0 label' }]);
});

test('noteError dan notePayload: maks 200 karakter sesudah dirapikan (code point, seperti server)', () => {
  assert.equal(noteError(''), null);
  assert.equal(noteError(null), null);
  assert.equal(noteError(undefined), null);
  assert.equal(noteError('a'.repeat(200)), null);
  assert.equal(noteError(`  ${'a'.repeat(200)}  `), null);
  assert.equal(noteError('a'.repeat(201)), 'Catatan maksimal 200 karakter (sekarang 201).');
  // Emoji = 1 karakter di server (Python), 2 unit di JS.
  assert.equal(noteError('😀'.repeat(200)), null);
  assert.equal(noteError('😀'.repeat(201)), 'Catatan maksimal 200 karakter (sekarang 201).');
  assert.equal(notePayload('  cocok  '), 'cocok');
  assert.equal(notePayload('   '), null);
  assert.equal(notePayload(null), null);
  assert.equal(notePayload(42), null);
});

test('noteError: karakter kontrol dan U+FEFF ditolak dengan pesan netral; spasi dirapikan seperti Python strip()', () => {
  const ctrl = 'Catatan tidak boleh memuat tab, baris baru, atau karakter khusus lain.';
  for (const bad of ['a\tb', 'baris\nbaru', 'nul\u0000', 'del\u007f', 'c1\u0085x', 'bom\uFEFF', '\uFEFFdepan', 'x\u001by']) {
    assert.equal(noteError(bad), ctrl, JSON.stringify(bad));
  }
  // Server merapikan spasi Python di kedua ujung (termasuk baris baru, U+001C–U+001F, U+0085) sebelum memeriksa.
  for (const ok of ['\n cocok \n', '\tcocok\t', '\u001fcocok\u0085', '\u3000cocok\u00a0']) {
    assert.equal(noteError(ok), null, JSON.stringify(ok));
    assert.equal(notePayload(ok), 'cocok');
  }
  // U+FEFF bukan spasi Python: tidak dirapikan, jadi 200 karakter + BOM ditolak (tidak lolos lalu 422 di server).
  assert.equal(notePayload('\uFEFFcocok'), '\uFEFFcocok');
  assert.equal(noteError(`${'a'.repeat(200)}\uFEFF`), ctrl);
  // Kontrol didahulukan dari panjang.
  assert.equal(noteError(`${'a'.repeat(250)}\tb`), ctrl);
});

test('decisionBody: catatan rapi + from_status = status baris yang dilihat admin', () => {
  assert.deepEqual(decisionBody({ id: 'r1', status: 'menunggu' }, '  sesuai contoh  '), { note: 'sesuai contoh', from_status: 'menunggu' });
  assert.deepEqual(decisionBody({ status: 'disetujui' }, ''), { note: null, from_status: 'disetujui' });
  assert.deepEqual(decisionBody({ status: 'ditolak' }, undefined), { note: null, from_status: 'ditolak' });
  assert.deepEqual(decisionBody({ status: 'dicabut' }, null), { note: null, from_status: 'dicabut' });
  assert.deepEqual(decisionBody({ status: 'semua' }, 'x'), { note: 'x', from_status: null });
  assert.deepEqual(decisionBody(null, 'x'), { note: 'x', from_status: null });
  // Baris hasil ruleRows membawa statusnya.
  const [row] = ruleRows(RESP, 'disetujui');
  assert.equal(decisionBody(row, '').from_status, 'disetujui');
});

test('nextTab: panah melingkar, Home/End; tombol lain → null', () => {
  assert.equal(nextTab('menunggu', 'ArrowRight'), 'disetujui');
  assert.equal(nextTab('suara', 'ArrowRight'), 'menunggu');
  assert.equal(nextTab('menunggu', 'ArrowLeft'), 'suara');
  assert.equal(nextTab('ditolak', 'ArrowLeft'), 'disetujui');
  assert.equal(nextTab('ditolak', 'Home'), 'menunggu');
  assert.equal(nextTab('ditolak', 'End'), 'suara');
  assert.equal(nextTab('ditolak', 'Enter'), null);
  assert.equal(nextTab('aneh', 'ArrowRight'), null);
});

test('actionOutcome: ok, 409 teks server, 404, 403, 422, jaringan, lainnya; tidak pernah JSON mentah', () => {
  assert.deepEqual(actionOutcome('setujui', { ok: true, status: 200, data: rule({ status: 'disetujui' }) }),
    { kind: 'ok', text: 'Aturan disetujui.', reload: true });
  assert.deepEqual(actionOutcome('tolak', { ok: true, status: 200, data: {} }),
    { kind: 'ok', text: 'Aturan ditolak.', reload: true });
  assert.deepEqual(actionOutcome('cabut', { ok: true, status: 200, data: {} }),
    { kind: 'ok', text: 'Aturan dicabut.', reload: true });
  assert.deepEqual(actionOutcome('cabut', { ok: false, status: 409, data: { detail: 'Aturan ini tidak bisa diubah ke status itu' } }),
    { kind: 'conflict', text: 'Aturan ini tidak bisa diubah ke status itu. Daftar dimuat ulang.', reload: true });
  // Teks ambang L4a fix 1; titik penutup server tidak digandakan.
  assert.deepEqual(actionOutcome('setujui', { ok: false, status: 409, data: { detail: 'Aturan belum didukung 2 user' } }),
    { kind: 'conflict', text: 'Aturan belum didukung 2 user. Daftar dimuat ulang.', reload: true });
  assert.equal(actionOutcome('setujui', { ok: false, status: 409, data: { detail: 'Aturan ini sudah berubah.' } }).text,
    'Aturan ini sudah berubah. Daftar dimuat ulang.');
  // 409 tanpa teks yang layak → teks klien.
  for (const data of [{}, { detail: { msg: 'x' } }, { detail: '' }, { detail: '{"detail":"x"}' }, { detail: '["x"]' }, { detail: 'x'.repeat(201) }, null]) {
    assert.deepEqual(actionOutcome('tolak', { ok: false, status: 409, data }),
      { kind: 'conflict', text: 'Status aturan ini sudah berubah. Daftar dimuat ulang.', reload: true });
  }
  assert.deepEqual(actionOutcome('setujui', { ok: false, status: 404, data: { detail: 'Aturan tidak ditemukan' } }),
    { kind: 'conflict', text: 'Aturan tidak ditemukan lagi. Daftar dimuat ulang.', reload: true });
  assert.deepEqual(actionOutcome('setujui', { ok: false, status: 403, data: { detail: 'Admin access required' } }),
    { kind: 'error', text: 'Hanya admin yang bisa memutuskan aturan.', reload: false });
  assert.deepEqual(actionOutcome('setujui', { ok: false, status: 422, data: { detail: [{ loc: ['body', 'note'] }] } }),
    { kind: 'error', text: 'Catatan tidak diterima.', reload: false });
  assert.deepEqual(actionOutcome('setujui', { ok: false, status: 0, data: { detail: 'x' } }),
    { kind: 'error', text: 'Koneksi gagal, coba lagi.', reload: false });
  assert.deepEqual(actionOutcome('setujui', { ok: false, status: 500, data: { detail: 'Internal' } }),
    { kind: 'error', text: 'Keputusan belum tersimpan (kode 500). Coba lagi.', reload: false });
  assert.deepEqual(actionOutcome('setujui', null), { kind: 'error', text: 'Koneksi gagal, coba lagi.', reload: false });
  assert.deepEqual(actionOutcome('setujui', undefined), { kind: 'error', text: 'Koneksi gagal, coba lagi.', reload: false });
  const out = actionOutcome('setujui', { ok: false, status: 500, data: { detail: { a: 1 } } });
  assert.doesNotMatch(out.text, /[{}[\]]/);
});

test('pendingBadge dan hasRulesSection: "N aturan menunggu" dari rules_pending; daftar terbaru menang', () => {
  assert.equal(pendingBadge({ rules_pending: 3 }), '3 aturan menunggu');
  assert.equal(pendingBadge({ rules_pending: 1 }), '1 aturan menunggu');
  assert.equal(pendingBadge({ rules_pending: 0 }), null);
  assert.equal(pendingBadge({}), null);
  assert.equal(pendingBadge(null), null);
  assert.equal(pendingBadge({ rules_pending: '3' }), null);
  assert.equal(pendingBadge({ rules_pending: -1 }), null);
  // Sesudah keputusan, hitungan dari daftar yang baru dimuat menggantikan angka stats yang sudah basi.
  assert.equal(pendingBadge({ rules_pending: 3 }, RESP), '3 aturan menunggu');
  assert.equal(pendingBadge({ rules_pending: 3 }, { counts: { menunggu: 2 }, rules: [] }), '2 aturan menunggu');
  assert.equal(pendingBadge({ rules_pending: 3 }, { counts: { menunggu: 0 }, rules: [] }), null);
  assert.equal(pendingBadge({ rules_pending: 3 }, null), '3 aturan menunggu');
  assert.equal(pendingBadge({ rules_pending: 3 }, { counts: { menunggu: 'x' } }), '3 aturan menunggu');
  assert.equal(hasRulesSection({ rules_pending: 0 }), true);
  assert.equal(hasRulesSection({ total: 4 }), false);
  assert.equal(hasRulesSection(null), false);
});

test('emptyText per tab', () => {
  assert.equal(emptyText('menunggu'), 'Tidak ada aturan yang menunggu.');
  assert.equal(emptyText('disetujui'), 'Belum ada aturan yang disetujui.');
  assert.equal(emptyText('ditolak'), 'Belum ada aturan yang ditolak.');
  assert.equal(emptyText('dicabut'), 'Belum ada aturan yang dicabut.');
  assert.equal(emptyText('suara'), 'Belum ada suara.');
});
