// Plugin U1: Buku Usaha di web (pembantu murni). Jalankan: node --test src/plugins/buku_usaha/bukuUsaha.test.js
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  barisWizard, bodyUbahKontak, hitungKontak, pesanKontakGalat, rapikanKontak, rencanaAmplop, saringKontak,
  urutkanKontak, validasiKontak,
} from './bukuUsaha.js';

const SERVER = [
  { id: 'a1', nama: 'UD Sumber Unggas', peran: 'pemasok', telepon: '0812 3456', catatan: 'ayam', dibuat: '2026-11-05T01:00:00+07:00' },
  { id: 'a2', nama: 'Bu Sari', peran: 'pelanggan', telepon: null, catatan: null, dibuat: '2026-11-05T01:00:00+07:00' },
  { id: 'rusak', nama: 'X', peran: 'bos' },
  { nama: 'tanpa id', peran: 'pelanggan' },
  null,
];

test('rapikan kontak membuang entri rusak dan menormalkan kosong', () => {
  const k = rapikanKontak(SERVER);
  assert.deepEqual(k.map(x => x.id), ['a1', 'a2']);
  assert.equal(k[1].telepon, '');
  assert.equal(k[1].catatan, '');
  assert.deepEqual(rapikanKontak(null), []);
  assert.deepEqual(rapikanKontak('x'), []);
});

test('saring, urut, hitung', () => {
  const k = rapikanKontak(SERVER);
  assert.deepEqual(saringKontak(k, { peran: 'pemasok' }).map(x => x.id), ['a1']);
  assert.deepEqual(saringKontak(k, { q: '  SARI ' }).map(x => x.id), ['a2']);
  assert.deepEqual(saringKontak(k, { q: '3456' }).map(x => x.id), ['a1']);
  assert.deepEqual(saringKontak(k, { peran: 'pelanggan', q: 'unggas' }), []);
  assert.deepEqual(urutkanKontak(k).map(x => x.nama), ['Bu Sari', 'UD Sumber Unggas']);
  assert.deepEqual(hitungKontak(k), { semua: 2, pelanggan: 1, pemasok: 1 });
  assert.deepEqual(hitungKontak(null), { semua: 0, pelanggan: 0, pemasok: 0 });
});

test('validasi kontak sama dengan aturan server', () => {
  let v = validasiKontak({ nama: '  Bu   Sari ', peran: 'pelanggan', telepon: ' 0812-3456 ', catatan: '' });
  assert.equal(v.ok, true);
  assert.deepEqual(v.body, { nama: 'Bu Sari', peran: 'pelanggan', telepon: '0812-3456', catatan: null });
  v = validasiKontak({ nama: ' ', peran: 'bos', telepon: 'abc', catatan: 'x'.repeat(501) });
  assert.equal(v.ok, false);
  assert.deepEqual(Object.keys(v.galat).sort(), ['catatan', 'nama', 'peran', 'telepon']);
  assert.equal(validasiKontak({ nama: 'x'.repeat(121), peran: 'pemasok' }).galat.nama.includes('120'), true);
  assert.equal(validasiKontak({ nama: 'A', peran: 'pemasok', telepon: '+62 812 3456' }).ok, true);
  assert.equal(validasiKontak(null).ok, false);
});

test('body ubah hanya kolom yang berubah', () => {
  const lama = { nama: 'Bu Sari', peran: 'pelanggan', telepon: '', catatan: 'lama' };
  const { body } = validasiKontak({ nama: 'Bu Sari', peran: 'pelanggan', telepon: '0812', catatan: 'lama' });
  assert.deepEqual(bodyUbahKontak(lama, body), { telepon: '0812' });
  const sama = validasiKontak({ nama: 'Bu Sari', peran: 'pelanggan', telepon: '', catatan: 'lama' }).body;
  assert.deepEqual(bodyUbahKontak(lama, sama), {});
  const hapusCatatan = validasiKontak({ nama: 'Bu Sari', peran: 'pemasok', telepon: '', catatan: '' }).body;
  assert.deepEqual(bodyUbahKontak(lama, hapusCatatan), { peran: 'pemasok', catatan: null });
});

test('pesan galat kontak', () => {
  assert.equal(pesanKontakGalat(0, null), 'Koneksi terputus. Coba lagi.');
  assert.match(pesanKontakGalat(404, { kode: 'plugin_tidak_aktif', detail: 'x' }), /tidak aktif/);
  assert.equal(pesanKontakGalat(409, { kode: 'kontak_ganda', detail: 'Bu Sari sudah ada sebagai pelanggan.' }),
    'Bu Sari sudah ada sebagai pelanggan.');
  assert.match(pesanKontakGalat(404, { kode: 'kontak_tidak_ada' }), /Muat ulang/);
  assert.match(pesanKontakGalat(403, { kode: 'khusus_admin' }), /pemilik dan admin/);
  assert.equal(pesanKontakGalat(422, { kode: 'nilai_tidak_sah', detail: 'Nomor telepon tidak sah.' }), 'Nomor telepon tidak sah.');
  assert.equal(pesanKontakGalat(500, {}), 'Belum berhasil. Coba lagi sebentar.');
});

test('wizard: baris dari pengaturan dan rencana amplop', () => {
  const peng = { amplop_bawaan: [
    { nama: 'Bahan', emoji: '🥬', tujuan: 'expense', keterangan: 'Bahan baku', ada: true, envelope_id: 'e1' },
    { nama: 'Operasional', emoji: '🔧', tujuan: 'expense', keterangan: 'Biaya harian', ada: false, envelope_id: null },
    { nama: 'Prive', emoji: '👤', tujuan: 'saving', keterangan: '', ada: false, envelope_id: null },
    { nama: 'Pajak', emoji: '🧾', tujuan: 'saving', keterangan: '', ada: false, envelope_id: null },
    null,
  ] };
  const baris = barisWizard(peng);
  assert.deepEqual(baris.map(b => [b.nama, b.tujuan, b.ada, b.pilih]),
    [['Bahan', 'expense', true, false], ['Operasional', 'expense', false, true], ['Prive', 'saving', false, true],
     ['Pajak', 'saving', false, true]]);
  // Nama diubah user, satu dilepas, satu kembar dengan amplop yang sudah ada di ruang; anggaran belanja diisi.
  const pilihan = baris.map(b => ({ ...b }));
  pilihan[1].nama = '  Biaya   Harian ';
  pilihan[1].anggaran = '2.500.000';
  pilihan[2].pilih = false;
  pilihan[3].nama = 'bahan';
  assert.deepEqual(rencanaAmplop(pilihan, ['Bahan', 'Tabungan']), { kurang: [], rencana: [
    { name: 'Biaya Harian', emoji: '🔧', budget_amount: 2500000, is_rollover: true, purpose: 'expense' },
  ] });
  // Cadangan tanpa anggaran; belanja tanpa anggaran masuk `kurang`.
  pilihan[2].pilih = true; pilihan[1].anggaran = '';
  const r = rencanaAmplop(pilihan, ['Bahan']);
  assert.deepEqual(r.kurang, ['Biaya Harian']);
  assert.deepEqual(r.rencana, [{ name: 'Prive', emoji: '👤', budget_amount: 0, is_rollover: true, purpose: 'saving', is_emergency: false }]);
  // Dua baris dengan nama sama → satu.
  pilihan[1].anggaran = '1'; pilihan[2].nama = 'biaya harian';
  assert.equal(rencanaAmplop(pilihan, ['Bahan']).rencana.length, 1);
  assert.deepEqual(barisWizard(null), []);
  assert.deepEqual(rencanaAmplop(null), { rencana: [], kurang: [] });
});
