import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  amplopDipakai, amplopPilihan, aturanCatatan, galatCatat, labelSumber, perluCekPribadi, pesanAjari, tawaranPribadi,
  uraiCatatan,
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
