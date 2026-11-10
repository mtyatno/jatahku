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

// ── U2 ──
import {
  amplopBawaanNonPenjualan, barisAlokasi, persenTampil, pesanUsahaGalat, rupiah, totalPersen, validasiAlokasi,
  validasiPenjualan,
} from './bukuUsaha.js';

test('alokasi: saran bila belum tersimpan, aturan bila tersimpan, sisa amplop', () => {
  const amplop = [{ envelope_id: 'a', nama: 'Bahan' }, { envelope_id: 'b', nama: 'Prive' }, { envelope_id: 'c', nama: 'Kas' }];
  const belum = barisAlokasi({ tersimpan: false, aturan: [], saran: [{ envelope_id: 'a', nama: 'Bahan', persen: 45 },
    { envelope_id: 'b', nama: 'Prive', persen: 55 }], amplop });
  assert.deepEqual(belum.baris.map(b => [b.envelope_id, b.persen]), [['a', '45'], ['b', '55']]);
  assert.deepEqual(belum.sisa.map(b => b.envelope_id), ['c']);
  const sudah = barisAlokasi({ tersimpan: true, siap: true, aturan: [{ envelope_id: 'c', nama: 'Kas', persen: '100.00' }],
    saran: [{ envelope_id: 'a' }], amplop });
  assert.deepEqual(sudah.baris.map(b => b.persen), ['100']);
  assert.equal(sudah.siap, true);
  assert.equal(persenTampil('33.50'), '33.5');
});

test('alokasi: total tepat dan validasi seperti server', () => {
  const b = (...p) => p.map((persen, i) => ({ envelope_id: String(i), nama: `A${i}`, persen }));
  assert.equal(totalPersen(b('33.33', '33,33', '33.34')), 100);
  assert.deepEqual(validasiAlokasi(b('45', '30', '15', '9', '1')).body.aturan.map(a => a.persen), ['45', '30', '15', '9', '1']);
  assert.match(validasiAlokasi(b('60', '39')).pesan, /Total harus 100%, sekarang 99%/);
  assert.equal(validasiAlokasi(b('0', '100')).ok, false);
  assert.equal(validasiAlokasi(b('1.234', '98.766')).ok, false);
  assert.equal(validasiAlokasi([]).ok, false);
  assert.equal(validasiAlokasi(b(...Array(11).fill('1'))).ok, false);
});

test('penjualan: body per jenis', () => {
  const ok = validasiPenjualan({ jenis: 'penjualan', jumlah: '1.000.001', kontak_id: 'k1', envelope_id: 'x',
    tanggal: '2026-11-08', keterangan: '  nasi   box ' }, '2026-11-09');
  assert.deepEqual(ok.body, { jumlah: '1000001', jenis: 'penjualan', tanggal: '2026-11-08', keterangan: 'nasi box', kontak_id: 'k1' });
  const modal = validasiPenjualan({ jenis: 'modal', jumlah: '5000000', kontak_id: 'k1', envelope_id: 'e1' }, '2026-11-09');
  assert.deepEqual(modal.body, { jumlah: '5000000', jenis: 'modal', envelope_id: 'e1' });
  assert.ok(validasiPenjualan({ jenis: 'pinjaman', jumlah: '1' }).galat.envelope_id);
  assert.ok(validasiPenjualan({ jumlah: '0' }).galat.jumlah);
  assert.ok(validasiPenjualan({ jumlah: '1', tanggal: '2026-11-10' }, '2026-11-09').galat.tanggal);
  assert.equal(validasiPenjualan({ jenis: 'hibah', jumlah: '1' }).body.jenis, 'penjualan');
});

test('penjualan: amplop bawaan, pesan galat, rupiah', () => {
  assert.equal(amplopBawaanNonPenjualan([{ envelope_id: 'x', nama: 'laba  ditahan' }]), 'x');
  assert.equal(amplopBawaanNonPenjualan([{ envelope_id: 'x', nama: 'Kas' }]), '');
  assert.equal(pesanUsahaGalat(422, { kode: 'alokasi_belum_diatur' }).perlu, 'alokasi');
  assert.equal(pesanUsahaGalat(403, { kode: 'tanpa_izin' }).perlu, 'izin');
  assert.equal(pesanUsahaGalat(422, { kode: 'nilai_tidak_sah', detail: 'Tanggal salah.' }).teks, 'Tanggal salah.');
  assert.equal(rupiah('1000001.00'), 'Rp1.000.001');
});
