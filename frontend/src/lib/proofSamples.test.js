import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  SAMPLE_TABS, STEP_PARTS, PSEUDONYM_CHOICES, SAMPLE_MAX_LINES, SAMPLE_LINE_MAX, EXPECT_LABEL, STEP_TEXT, sampleCounts, sampleRows,
  periksaCount, editableLines, linesNotice, approveBody, rejectBody, entryFileName, entryDownload, actionOutcome,
  confirmText, nextSampleTab, emptyText,
} from './proofSamples.js';

// Bentuk GET /admin/kotak/samples (app/api/routes/admin_kotak.py ProofSampleOut). Data karangan, tanpa data user.
const sample = over => ({
  id: 's1', doc_type: 'transfer', rule_key: 'gopay', app_label: 'GoPay', trigger: 'nominal',
  lines: [
    { text: 'Transfer Berhasil', periksa: false },
    { text: 'Ke BUDI SANTOSO', periksa: false },
    { text: 'Ref …5678 …1234', periksa: true },
    { text: 'Total Rp 35.000', periksa: false },
  ],
  user_name: 'ANDI PRATAMA',
  truth: { total: 53000, date: '2026-11-03', flow: null, app: null },
  reading: { doc_type: 'transfer', issuer: 'gopay', total: 35000, paid_at: '2026-11-03T10:15:00+07:00',
    counterparty: 'BUDI SANTOSO', status: 'berhasil', flow: 'keluar' },
  today: '2026-11-03', status: 'menunggu', created_at: '2026-11-03T03:20:00Z', decided_at: null,
  decided_by_name: null, note: null, ...over,
});
const RESP = {
  counts: { menunggu: 2, disetujui: 1, ditolak: 0 },
  samples: [
    sample(),
    sample({ id: 's2', trigger: 'arah', app_label: null, rule_key: 'logo:newpay', truth: { flow: 'top_up' }, reading: null }),
    sample({ id: 's3', status: 'disetujui', decided_at: '2026-11-04T02:00:00Z', decided_by_name: 'Admin Satu', note: 'oke' }),
    { id: 's4', status: 'menunggu' },   // rusak: tanpa baris
    null,
  ],
};

test('SAMPLE_TABS: hanya Menunggu dan Disetujui (sampel ditolak tidak pernah ada)', () => {
  assert.deepEqual(SAMPLE_TABS.map(t => [t.key, t.label]), [['menunggu', 'Menunggu'], ['disetujui', 'Disetujui']]);
  assert.deepEqual(sampleCounts(RESP), { menunggu: 2, disetujui: 1 });   // counts.ditolak diabaikan
  assert.deepEqual(sampleCounts({}), { menunggu: 0, disetujui: 0 });
  assert.deepEqual(sampleRows(RESP, 'ditolak'), []);
  assert.equal(nextSampleTab('menunggu', 'ArrowRight'), 'disetujui');
  assert.equal(nextSampleTab('disetujui', 'ArrowRight'), 'menunggu');
  assert.equal(nextSampleTab('menunggu', 'End'), 'disetujui');
  assert.equal(nextSampleTab('ditolak', 'Home'), null);
  assert.equal(nextSampleTab('menunggu', 'a'), null);
});

test('PSEUDONYM_CHOICES: empat nama samaran server + tanpa nama', () => {
  assert.deepEqual(PSEUDONYM_CHOICES.map(c => c.value),
    ['ANDI PRATAMA', 'BUDI SANTOSO', 'SITI AMINAH', 'TOKO CONTOH', '']);
  assert.equal(PSEUDONYM_CHOICES.at(-1).label, 'Tanpa nama');
  assert.equal(SAMPLE_MAX_LINES, 80);
  assert.equal(SAMPLE_LINE_MAX, 200);
});

test('sampleRows menunggu: aplikasi, pemicu, baris PERIKSA, hasil baca vs koreksi user; baris rusak dilewati', () => {
  const rows = sampleRows(RESP, 'menunggu');
  assert.deepEqual(rows.map(r => r.id), ['s1', 's2']);
  const [a, b] = rows;
  assert.equal(a.app, 'GoPay');
  assert.equal(a.trigger, 'Nominal dikoreksi');
  assert.equal(a.periksa, 1);
  assert.equal(a.periksaText, 'PERIKSA baris 3');
  assert.deepEqual(a.lines.map(l => [l.n, l.periksa]), [[1, false], [2, false], [3, true], [4, false]]);
  assert.equal(a.userName, 'ANDI PRATAMA');
  assert.equal(a.date, 'Masuk 3 Nov 2026');
  const total = a.compare.find(c => c.field === 'total');
  assert.deepEqual(total, { field: 'total', label: 'Nominal', read: 'Rp 35.000', fixed: 'Rp 53.000', differs: true });
  const date = a.compare.find(c => c.field === 'date');
  assert.deepEqual([date.read, date.fixed, date.differs], ['3 Nov 2026', '3 Nov 2026', false]);
  const app = a.compare.find(c => c.field === 'app');
  assert.deepEqual([app.read, app.fixed, app.differs], ['GoPay', '–', false]);

  assert.equal(b.app, 'Aplikasi tidak dikenal');
  assert.equal(b.trigger, 'Bukan pengeluaran');
  assert.equal(b.readingMissing, true);
  const flow = b.compare.find(c => c.field === 'flow');
  assert.deepEqual([flow.read, flow.fixed, flow.differs], ['–', 'Top-up', true]);
  // tidak pernah ada id user/item di baris
  for (const r of rows) assert.ok(!('user_id' in r) && !('item_id' in r));
});

test('sampleRows disetujui: tanggal keputusan; respons tanpa daftar → null', () => {
  const [r] = sampleRows(RESP, 'disetujui');
  assert.equal(r.id, 's3');
  assert.equal(r.date, 'Disetujui 4 Nov 2026 oleh Admin Satu');
  assert.equal(r.note, 'oke');
  for (const bad of [null, undefined, {}, { samples: 'x' }]) assert.equal(sampleRows(bad, 'menunggu'), null);
  assert.equal(emptyText('menunggu'), 'Tidak ada sampel yang menunggu.');
});

test('periksaCount dan editableLines: teks per baris; data rusak → null', () => {
  assert.equal(periksaCount(sample()), 1);
  assert.equal(periksaCount(sampleRows(RESP, 'menunggu')[0]), 1);
  assert.equal(periksaCount(sample({ lines: [{ text: 'a' }, { text: 'b', periksa: true }, { text: 'c', periksa: true }] })), 2);
  assert.equal(editableLines(sample()), 'Transfer Berhasil\nKe BUDI SANTOSO\nRef …5678 …1234\nTotal Rp 35.000');
  for (const bad of [null, {}, { lines: 'x' }, { lines: [1] }]) {
    assert.equal(periksaCount(bad), null);
    assert.equal(editableLines(bad), null);
  }
});

test('approveBody: hanya lines/user_name/note/from_status; memotong ke batas server; menolak baris kosong', () => {
  const row = sampleRows(RESP, 'menunggu')[0];
  const body = approveBody(row, 'Transfer Berhasil\r\n  \nKe BUDI SANTOSO\n\tTotal Rp 35.000  \n', 'TOKO CONTOH', '  cek  ');
  assert.deepEqual(Object.keys(body).sort(), ['from_status', 'lines', 'note', 'user_name']);
  // baris dengan field lain (data tangan): tetap hanya empat field
  const leaky = approveBody({ ...row, user_id: 'u1', item_id: 'i1', status: 'menunggu', truth: { total: 1 } }, 'a', null, null);
  assert.deepEqual(Object.keys(leaky).sort(), ['from_status', 'lines', 'note', 'user_name']);
  // nama samaran tersimpan dipakai bila dipilih apa adanya (huruf besar/kecil server tidak dibedakan)
  assert.equal(approveBody(row, 'a', 'siti aminah', null).user_name, 'SITI AMINAH');
  assert.deepEqual(body, {
    lines: ['Transfer Berhasil', 'Ke BUDI SANTOSO', '\tTotal Rp 35.000  '],
    user_name: 'TOKO CONTOH', note: 'cek', from_status: 'menunggu',
  });
  // baris dan jumlah baris dipotong ke batas server; karakter kontrol (kecuali tab) dibuang
  const long = approveBody(row, ['x'.repeat(250), ...Array.from({ length: 100 }, (_, i) => `b${i}\u0000`)], '', null);
  assert.equal(long.lines.length, SAMPLE_MAX_LINES);
  assert.equal(long.lines[0].length, SAMPLE_LINE_MAX);
  assert.equal(long.lines[1], 'b0');
  assert.equal(long.user_name, null);
  assert.equal(long.note, null);
  // nama di luar daftar samaran → null (server hanya menerima kata samaran)
  assert.equal(approveBody(row, 'a', 'Siti Rahma', null).user_name, null);
  assert.equal(approveBody(row, 'a', 'ANDI PRATAMA', 'x'.repeat(300)).note.length, 200);
  // tanpa baris berisi, baris yang bukan menunggu, atau data rusak → null
  assert.equal(approveBody(row, ' \n\n', 'ANDI PRATAMA', null), null);
  assert.equal(approveBody(row, [], null, null), null);
  assert.equal(approveBody(sampleRows(RESP, 'disetujui')[0], 'a', null, null), null);
  assert.equal(approveBody(null, 'a', null, null), null);
  assert.equal(approveBody(row, 42, null, null), null);
  assert.deepEqual(rejectBody(row, ' tidak jelas '), { note: 'tidak jelas', from_status: 'menunggu' });
  assert.equal(rejectBody({ status: 'disetujui' }, null), null);
});

test('linesNotice: peringatan bila baris akan dipotong', () => {
  assert.equal(linesNotice('a\nb'), null);
  assert.match(linesNotice('x'.repeat(201)), /baris 1 .*200 karakter/i);
  assert.match(linesNotice(Array.from({ length: 81 }, () => 'a').join('\n')), /80 baris/);
  assert.match(linesNotice(' \n'), /kosong/);
});

const ENTRY = {
  entry: {
    id: 'donasi-transfer-0a1b2c3d', real: true, reviewed: true, today: '2026-11-03', user_name: 'ANDI PRATAMA',
    lines: ['Transfer Berhasil', 'Total Rp 53.000'],
    expect: { doc_type: 'transfer', issuer: 'gopay', total: 53000, paid_at: '2026-11-03T10:15:00+07:00',
      counterparty: null, status: 'berhasil', flow: 'keluar' },
  },
  truth: { total: 53000, date: '2026-11-03', flow: null, app: null },
  gated_diff: ['total'],
};

test('entryDownload: seluruh {entry, truth, gated_diff}, nama <entry.id>.json, expect = hasil koreksi user', () => {
  const d = entryDownload({ ...ENTRY, extra: 'x' });
  assert.equal(d.fileName, 'donasi-transfer-0a1b2c3d.json');
  assert.deepEqual(JSON.parse(d.text), ENTRY);
  assert.deepEqual(Object.keys(JSON.parse(d.text)), ['entry', 'truth', 'gated_diff']);
  assert.equal(EXPECT_LABEL, 'Koreksi user (sudah diterapkan)');
  assert.deepEqual(d.expect.find(e => e.field === 'total'), { field: 'total', label: 'Nominal', value: 'Rp 53.000' });
  assert.deepEqual(d.expect.find(e => e.field === 'app'), { field: 'app', label: 'Aplikasi', value: 'GoPay' });
  assert.equal(d.diffText, 'Pembaca masih berbeda dari koreksi user di: Nominal');
  assert.equal(entryDownload({ ...ENTRY, gated_diff: [] }).diffText, null);
  assert.equal(entryDownload({ ...ENTRY, truth: null }).text, JSON.stringify({ ...ENTRY, truth: null }, null, 2));
  assert.equal(STEP_TEXT, 'Simpan berkas, lalu jalankan `python -m app.scripts.kotak_corpus add --dari-donasi <berkas>` '
    + 'di checkout lokal dan buka PR. Bila pembaca berbeda dari koreksi user, perintah berhenti (exit 3); pakai '
    + '`--tahan` untuk menulis `reviewed: false`.');
  // bagian teks/kode untuk dirender (<code>), gabungannya = kalimat utuh di atas
  assert.deepEqual(STEP_PARTS.filter(p => p.code).map(p => p.text),
    ['python -m app.scripts.kotak_corpus add --dari-donasi <berkas>', '--tahan', 'reviewed: false']);
  assert.equal(STEP_PARTS.map(p => (p.code ? `\`${p.text}\`` : p.text)).join(''), STEP_TEXT);
  for (const bad of [null, {}, { entry: {} }, { ...ENTRY, gated_diff: 'x' }, { ...ENTRY, entry: { ...ENTRY.entry, id: '../x' } }]) {
    assert.equal(entryDownload(bad), null);
  }
});

test('entryFileName: <id>.json hanya untuk id yang aman', () => {
  assert.equal(entryFileName(ENTRY.entry), 'donasi-transfer-0a1b2c3d.json');
  assert.equal(entryFileName(ENTRY), 'donasi-transfer-0a1b2c3d.json');
  for (const bad of [null, {}, { id: '' }, { id: '../etc' }, { id: 'a/b' }, { id: '.x' }, { id: 5 }]) {
    assert.equal(entryFileName(bad), null);
  }
});

test('actionOutcome: ok / 409 / 404 / 422 (teks server) / galat', () => {
  assert.deepEqual(actionOutcome('setujui', { ok: true, status: 200, data: {} }),
    { kind: 'ok', text: 'Sampel disetujui.', reload: true });
  assert.equal(actionOutcome('tolak', { ok: true, status: 200 }).text, 'Sampel ditolak dan dihapus.');
  assert.equal(actionOutcome('hapus', { ok: true, status: 204 }).text, 'Sampel dihapus.');
  const c = actionOutcome('setujui', { ok: false, status: 409, data: { detail: 'Sampel sudah diputuskan' } });
  assert.deepEqual(c, { kind: 'conflict', text: 'Sampel sudah diputuskan. Daftar dimuat ulang.', reload: true });
  assert.equal(actionOutcome('setujui', { ok: false, status: 404, data: {} }).kind, 'conflict');
  const inv = actionOutcome('setujui', { ok: false, status: 422, data: { detail: 'Masih ada nomor panjang di baris 3' } });
  assert.deepEqual(inv, { kind: 'invalid', text: 'Masih ada nomor panjang di baris 3.', reload: false });
  const pyd = actionOutcome('setujui', { ok: false, status: 422,
    data: { detail: [{ msg: 'Value error, Baris 2 lebih dari 200 karakter' }] } });
  assert.equal(pyd.text, 'Baris 2 lebih dari 200 karakter.');
  assert.equal(actionOutcome('setujui', { ok: false, status: 422, data: {} }).text, 'Isian tidak diterima.');
  assert.equal(actionOutcome('setujui', { ok: false, status: 0, data: {} }).text, 'Koneksi gagal, coba lagi.');
  for (const bad of [null, undefined, 'x']) assert.equal(actionOutcome('setujui', bad).kind, 'error');
  assert.match(confirmText('tolak'), /dihapus/);
  assert.match(confirmText('hapus'), /disalin/);
  assert.equal(confirmText('setujui'), null);
});
