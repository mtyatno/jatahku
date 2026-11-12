import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  amplopDipakai, amplopPilihan, aturanCatatan, galatCatat, hasilPribadi, hasilTidakPasti, isiFormPlugin, jenisBerikut,
  jenisLain, jenisTerdeteksi, kontakCatatan, labelSumber, perluCekPribadi, pesanAjari, pesanTerkunci, tambahanKontak,
  tawaranPribadi, uraiCatatan,
} from './catatCepat.js';

test('uraiCatatan: nominal dan keterangan dari satu kotak teks, kasus sama dengan bot', () => {
  assert.deepEqual(uraiCatatan('kardus 50 pcs 125rb'), { nominal: 125000, keterangan: 'kardus 50 pcs' });
  assert.deepEqual(uraiCatatan('ayam potong 40kg 1,64jt ud sumber unggas'),
    { nominal: 1640000, keterangan: 'ayam potong 40kg ud sumber unggas' });
  assert.deepEqual(uraiCatatan('125rb'), { nominal: 125000, keterangan: '' });   // bukan "Pengeluaran"
  assert.deepEqual(uraiCatatan('  tisu  '), { nominal: 0, keterangan: 'tisu' });
  assert.deepEqual(uraiCatatan(''), { nominal: 0, keterangan: '' });
  assert.deepEqual(uraiCatatan(null), { nominal: 0, keterangan: '' });
});

test('labelSumber: setiap tebakan menyebut asalnya', () => {
  assert.equal(labelSumber({ jenis: 'kamus_ruang', kali: 4, diajarkan_oleh: 'Bagas', oleh_saya: false }, 'Dapur Nusa'),
    'Kamus Dapur Nusa · diajarkan Bagas · 4×');
  assert.equal(labelSumber({ jenis: 'kamus_ruang', kali: 1, diajarkan_oleh: null, oleh_saya: true }, 'Dapur Nusa'),
    'Kamus Dapur Nusa · diajarkan kamu · 1×');
  assert.equal(labelSumber({ jenis: 'kamus_ruang', kali: 2, diajarkan_oleh: null, oleh_saya: false }),
    'Kamus ruang ini · diajarkan anggota · 2×');   // akun pengajar terhapus
  assert.equal(labelSumber({ jenis: 'kamus_ruang' }, 'Dapur Nusa'), 'Kamus Dapur Nusa');   // karyawan (#191 temuan 2)
  assert.equal(labelSumber({ jenis: 'kata_saya', kali: 3 }), 'Kata yang kamu ajarkan · 3×');
  assert.equal(labelSumber({ jenis: 'kamus_kategori' }), 'Kamus kategori bawaan');
  assert.equal(labelSumber({ jenis: 'kamus_plugin' }), 'Kamus Fitur Tambahan');
  assert.equal(labelSumber({ jenis: 'nama_amplop' }), 'Nama amplop di catatanmu');
  assert.equal(labelSumber(null), '');
  assert.equal(labelSumber({ jenis: 'kontak' }), '');                            // U5: belum dikenal → kosong
});

test('tawaran pribadi: hanya bila kata belum dikenal ruang ini dan ruang keluarga mengenalnya dari kata user', () => {
  const kat = { envelope_id: 'm', confident: true, sumber: { jenis: 'kamus_kategori' } };
  assert.equal(perluCekPribadi({ jenis: 'pengeluaran', keterangan: 'pulsa', saran: kat }), true);
  assert.equal(perluCekPribadi({ jenis: 'pengeluaran', keterangan: 'pulsa', saran: null }), true);
  assert.equal(perluCekPribadi({ jenis: 'pengeluaran', keterangan: 'kardus',
    saran: { envelope_id: 'o', sumber: { jenis: 'kamus_ruang' } } }), false);
  assert.equal(perluCekPribadi({ jenis: 'pengeluaran', keterangan: 'kardus',
    saran: { envelope_id: 'o', sumber: { jenis: 'kata_saya' } } }), false);
  assert.equal(perluCekPribadi({ jenis: 'penjualan', keterangan: 'nasi box', saran: null }), false);
  assert.equal(perluCekPribadi({ jenis: 'pengeluaran', keterangan: ' ', saran: null }), false);

  assert.equal(tawaranPribadi({ envelope_id: 'j', confident: true, sumber: { jenis: 'kata_saya', kali: 7 } }), true);
  assert.equal(tawaranPribadi({ envelope_id: 'j', confident: true, sumber: { jenis: 'kamus_kategori' } }), false);
  assert.equal(tawaranPribadi({ envelope_id: 'j', confident: false, sumber: { jenis: 'kata_saya' } }), false);
  assert.equal(tawaranPribadi({ envelope_id: null, confident: false, sumber: null }), false);
  assert.equal(tawaranPribadi(null), false);
});

test('pesanAjari: koreksi atau kata baru mengajari kamus ruang; tebakan yang dipakai apa adanya tidak', () => {
  const kenal = { envelope_id: 'o', sumber: { jenis: 'kamus_ruang' } };
  assert.equal(pesanAjari({ jenis: 'pengeluaran', keterangan: 'kardus', saran: kenal, amplopId: 'o' }), '');
  assert.match(pesanAjari({ jenis: 'pengeluaran', keterangan: 'kardus', saran: kenal, amplopId: 'b',
    namaRuang: 'Dapur Nusa' }), /kamus Dapur Nusa untuk semua anggota.*tidak dipakai di ruang keluarga/);
  assert.match(pesanAjari({ jenis: 'pengeluaran', keterangan: 'tisu', saran: null, amplopId: 'o' }), /kamus/);
  // Tebakan kamus kategori yang dipakai tetap mengajari (kata itu belum ada di kamus ruang).
  assert.match(pesanAjari({ jenis: 'pengeluaran', keterangan: 'kopi',
    saran: { envelope_id: 'o', sumber: { jenis: 'kamus_kategori' } }, amplopId: 'o' }), /kamus/);
  assert.equal(pesanAjari({ jenis: 'penjualan', keterangan: 'nasi', saran: null, amplopId: 'o' }), '');
  assert.equal(pesanAjari({ jenis: 'pengeluaran', keterangan: '', saran: null, amplopId: 'o' }), '');
  assert.equal(pesanAjari({ jenis: 'pengeluaran', keterangan: 'tisu', saran: null, amplopId: null }), '');
});

test('aturanCatatan: foto nota menahan Simpan dengan alasan; persetujuan hanya memberi tahu', () => {
  const a = aturanCatatan([
    { kode: 'foto_nota', teks: 'Wajib foto nota di atas Rp300.000.' },
    { kode: 'persetujuan', teks: 'Di atas batasmu Rp1.000.000: menunggu persetujuan admin.' },
  ]);
  assert.equal(a.daftar.length, 2);
  assert.match(a.tahan, /Foto nota belum bisa dilampirkan/);
  assert.equal(a.persetujuan, true);
  assert.deepEqual(aturanCatatan([{ kode: 'persetujuan', teks: 'x' }]), { daftar: ['x'], tahan: '', persetujuan: true });
  assert.deepEqual(aturanCatatan(undefined), { daftar: [], tahan: '', persetujuan: false });
});

test('amplopDipakai dan galatCatat', () => {
  assert.equal(amplopDipakai(null, { envelope_id: 'o' }), 'o');
  assert.equal(amplopDipakai('b', { envelope_id: 'o' }), 'b');
  assert.equal(amplopDipakai(null, null), null);
  assert.match(galatCatat({ nominal: 0, amplopId: 'o', tahan: '' }), /nominal/);
  assert.match(galatCatat({ nominal: 1, amplopId: null, tahan: '' }), /amplop/);
  assert.match(galatCatat({ nominal: 1, amplopId: 'o', tahan: 'Foto nota' }), /Foto nota/);
  assert.equal(galatCatat({ nominal: 1, amplopId: 'o', tahan: '' }), null);
});

test('amplopPilihan: tanpa tabungan untuk pengeluaran, tebakan di depan', () => {
  const d = [{ id: 'a', purpose: 'expense' }, { id: 't', purpose: 'saving' }, { id: 'b' }, { id: 's', purpose: 'sinking_fund' }];
  assert.deepEqual(amplopPilihan(d, 'pengeluaran').map(e => e.id), ['a', 'b']);
  assert.deepEqual(amplopPilihan(d, 'pengeluaran', 'b').map(e => e.id), ['b', 'a']);
  assert.deepEqual(amplopPilihan(d, 'penjualan').map(e => e.id), ['a', 't', 'b', 's']);
  assert.deepEqual(amplopPilihan(null, 'pengeluaran'), []);
});

test('hasilTidakPasti: koneksi putus, sedang diproses, dan 5xx belum pasti; bentrok ref dan penolakan pasti', () => {
  assert.equal(hasilTidakPasti(0, null), true);
  assert.equal(hasilTidakPasti(503, {}), true);
  assert.equal(hasilTidakPasti(409, { detail: 'Transaksi ini sedang diproses.' }), true);
  assert.equal(hasilTidakPasti(409, { kode: 'client_ref_bentrok' }), false);
  assert.equal(hasilTidakPasti(403, { detail: 'Dana tidak cukup' }), false);
  assert.equal(hasilTidakPasti(201, {}), false);
  assert.equal(hasilTidakPasti(202, { kode: 'perlu_persetujuan' }), false);
});

test('hasilPribadi: "di ruang keluargamu" hanya bila transaksinya di amplop ruang keluarga itu (review #191, PoC1/PoC2)', () => {
  const keluarga = { envelope_id: 'jajan', envelope_name: 'Jajan Dewi' };
  const tercatat = { hasil: 'tercatat', pesan: 'Tercatat.' };
  assert.deepEqual(hasilPribadi(tercatat, { envelope_id: 'jajan' }, keluarga),
    { hasil: 'tercatat', pesan: 'Tercatat di ruang keluargamu (Jajan Dewi)' });
  assert.deepEqual(hasilPribadi(tercatat, { envelope_id: 'operasional' }, keluarga), tercatat);   // PoC2
  const draf = { hasil: 'menunggu', pesan: 'Catatan ini menunggu persetujuan admin.' };
  assert.deepEqual(hasilPribadi(draf, { kode: 'perlu_persetujuan', draf_id: 'd' }, keluarga), draf);   // PoC1
  assert.deepEqual(hasilPribadi(tercatat, {}, null), tercatat);
});

test('pesanTerkunci per jalur', () => {
  assert.match(pesanTerkunci('usaha', 'Dapur Nusa'), /Simpan ke Dapur Nusa/);
  assert.match(pesanTerkunci('pribadi'), /Catat di ruang keluarga/);
  assert.equal(pesanTerkunci(null), '');
});

// ── Plugin U5: jenis catatan dan kontak terdeteksi ──
const UNGGAS = { id: 'k1', nama: 'UD Sumber Unggas', peran: 'pemasok', plugin: 'buku_usaha' };
const ARUNIKA = { id: 'k2', nama: 'PT Arunika Data', peran: 'pelanggan', plugin: 'buku_usaha' };

test('jenisTerdeteksi: hanya pindah ke penjualan, dan hanya bila jenis itu boleh untuk user', () => {
  const semua = ['pengeluaran', 'penjualan'];
  assert.equal(jenisTerdeteksi({ jenis_catatan: 'penjualan' }, semua), 'penjualan');
  assert.equal(jenisTerdeteksi({ jenis_catatan: 'penjualan' }, ['pengeluaran']), null);
  assert.equal(jenisTerdeteksi({ jenis_catatan: 'modal' }, semua), null);          // modal bukan jenis Catat cepat
  assert.equal(jenisTerdeteksi({ jenis_catatan: null }, semua), null);
  assert.equal(jenisTerdeteksi(null, semua), null);
  assert.equal(jenisTerdeteksi({ jenis_catatan: 'penjualan' }, null), null);
});

test('jenisBerikut: deteksi memindahkan ke penjualan, dan kembali ke jenis awal saat kata penjualannya hilang', () => {
  const semua = ['pengeluaran', 'penjualan'];
  const dasar = { jenisBoleh: semua, jenisMula: 'pengeluaran', manual: false };
  assert.equal(jenisBerikut({ ...dasar, jenis: 'pengeluaran', saran: { jenis_catatan: 'penjualan' } }), 'penjualan');
  assert.equal(jenisBerikut({ ...dasar, jenis: 'penjualan', saran: { jenis_catatan: 'penjualan' } }), 'penjualan');
  // Teks diganti tanpa dikosongkan ("jual nasi box" → "setor modal" atau "kardus"): jenis yang tadi dipindahkan
  // deteksi tidak boleh tertinggal di Penjualan.
  assert.equal(jenisBerikut({ ...dasar, jenis: 'penjualan', saran: { jenis_catatan: null } }), 'pengeluaran');
  assert.equal(jenisBerikut({ ...dasar, jenis: 'penjualan', saran: { jenis_catatan: 'modal' } }), 'pengeluaran');
  assert.equal(jenisBerikut({ ...dasar, jenis: 'pengeluaran', saran: { jenis_catatan: null } }), 'pengeluaran');
});

test('jenisBerikut: pilihan user, lembar yang dibuka sebagai penjualan, dan saran yang gagal tidak mengubah jenis', () => {
  const semua = ['pengeluaran', 'penjualan'];
  // User memilih sendiri: deteksi tidak memindahkan ke arah mana pun.
  assert.equal(jenisBerikut({ jenisBoleh: semua, jenisMula: 'pengeluaran', manual: true, jenis: 'pengeluaran',
    saran: { jenis_catatan: 'penjualan' } }), 'pengeluaran');
  assert.equal(jenisBerikut({ jenisBoleh: semua, jenisMula: 'pengeluaran', manual: true, jenis: 'penjualan',
    saran: { jenis_catatan: null } }), 'penjualan');
  // Lembar dibuka sebagai Penjualan (karyawan "Catat penjualan"): tanpa kata penjualan pun tetap Penjualan.
  assert.equal(jenisBerikut({ jenisBoleh: semua, jenisMula: 'penjualan', manual: false, jenis: 'penjualan',
    saran: { jenis_catatan: null } }), 'penjualan');
  // Karyawan tanpa izin penjualan: tidak pernah dipindahkan.
  assert.equal(jenisBerikut({ jenisBoleh: ['pengeluaran'], jenisMula: 'pengeluaran', manual: false, jenis: 'pengeluaran',
    saran: { jenis_catatan: 'penjualan' } }), 'pengeluaran');
  // Saran gagal dimuat (null): jangan menebak, biarkan.
  assert.equal(jenisBerikut({ jenisBoleh: semua, jenisMula: 'pengeluaran', manual: false, jenis: 'penjualan',
    saran: null }), 'penjualan');
});

test('jenisLain: modal dan pinjaman dicatat lewat form Fitur Tambahan, bukan Catat cepat', () => {
  assert.deepEqual(jenisLain({ jenis_catatan: 'modal' }), { id: 'modal', label: 'Modal pemilik' });
  assert.deepEqual(jenisLain({ jenis_catatan: 'pinjaman' }), { id: 'pinjaman', label: 'Pinjaman' });
  assert.equal(jenisLain({ jenis_catatan: 'penjualan' }), null);
  assert.equal(jenisLain({ jenis_catatan: 'apa saja' }), null);
  assert.equal(jenisLain(null), null);
});

test('kontakCatatan: pemasok untuk pengeluaran, pelanggan untuk penjualan, selain itu tidak ada', () => {
  assert.deepEqual(kontakCatatan('pengeluaran', { kontak: UNGGAS }), UNGGAS);
  assert.deepEqual(kontakCatatan('penjualan', { kontak: ARUNIKA }), ARUNIKA);
  assert.equal(kontakCatatan('penjualan', { kontak: UNGGAS }), null);              // jawaban lama, jenis sudah berganti
  assert.equal(kontakCatatan('pengeluaran', { kontak: ARUNIKA }), null);
  assert.equal(kontakCatatan('pengeluaran', { kontak: null }), null);
  assert.equal(kontakCatatan('pengeluaran', null), null);
  assert.equal(kontakCatatan('pengeluaran', { kontak: { id: '', nama: 'x', peran: 'pemasok' } }), null);
  assert.equal(kontakCatatan('pengeluaran', { kontak: { id: 'k', nama: ' ', peran: 'pemasok' } }), null);
});

test('tambahanKontak: pemasok masuk field reference plugin itu; tanpa field, amplop pribadi, atau plugin lain tidak', () => {
  const fields = [
    { plugin: 'buku_usaha', target: 'transaction', key: 'pemasok', type: 'reference' },
    { plugin: 'buku_usaha', target: 'transaction', key: 'akun', type: 'select', options: ['Gaji'] },
  ];
  const bersama = { id: 'e1', owner_id: null };
  assert.deepEqual(tambahanKontak(fields, UNGGAS, bersama), { buku_usaha: { pemasok: 'k1' } });
  assert.equal(tambahanKontak(fields, UNGGAS, { id: 'e2', owner_id: 'u1' }), null);     // server menolak (review #201)
  assert.equal(tambahanKontak(fields, UNGGAS, { id: 'e3', is_personal: true }), null);
  assert.equal(tambahanKontak([], UNGGAS, bersama), null);
  assert.equal(tambahanKontak(undefined, UNGGAS, bersama), null);
  assert.equal(tambahanKontak(fields, null, bersama), null);
  assert.equal(tambahanKontak(fields, { ...UNGGAS, plugin: 'lain' }, bersama), null);
  assert.equal(tambahanKontak(fields, ARUNIKA, bersama), null);                         // tidak ada field "pelanggan"
  assert.equal(tambahanKontak([{ ...fields[0], type: 'text' }], UNGGAS, bersama), null);
});

test('isiFormPlugin: isian awal form Fitur Tambahan dari yang sudah diketik', () => {
  assert.deepEqual(isiFormPlugin({ jenis: 'penjualan', nominal: 900000, keterangan: 'nasi box 30 pax', kontak: ARUNIKA }),
    { jenis: 'penjualan', jumlah: '900000', keterangan: 'nasi box 30 pax', kontak_id: 'k2' });
  assert.deepEqual(isiFormPlugin({ jenis: 'modal', nominal: 5000000.4, keterangan: ' setor modal ', kontak: ARUNIKA }),
    { jenis: 'modal', jumlah: '5000000', keterangan: 'setor modal' });                 // pelanggan hanya untuk penjualan
  assert.deepEqual(isiFormPlugin({ jenis: 'penjualan', nominal: 0, keterangan: '', kontak: UNGGAS }),
    { jenis: 'penjualan', jumlah: '', keterangan: '' });                               // pemasok bukan pelanggan
});
