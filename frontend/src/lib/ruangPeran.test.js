import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  aksesRuang, batasanDariForm, catatKaryawan, formDariBatasan, galatForm, hasilCatat, jenisDariAksi, labelAudit,
  menuUntuk, payloadCatat, ringkasBatasan, ringkasHari, ruteBoleh,
} from './ruangPeran.js';

const KELUARGA = { id: 'k', jenis: 'rumah_tangga', peran: 'owner' };
const USAHA_OWNER = { id: 'u', jenis: 'usaha', peran: 'owner' };
const USAHA_ADMIN = { id: 'u', jenis: 'usaha', peran: 'admin' };
const KARYAWAN = { id: 'u', jenis: 'usaha', peran: 'member', jenis_catatan: ['pengeluaran'] };
const MENU = [
  { to: '/', label: 'Beranda' }, { to: '/envelopes', label: 'Amplop' }, { to: '/transactions', label: 'Transaksi' },
  { to: '/allocate', label: 'Alokasi' }, { to: '/langganan', label: 'Langganan' },
];

test('aksesRuang: karyawan hanya peran member di ruang usaha', () => {
  assert.deepEqual(aksesRuang(KARYAWAN), { usaha: true, karyawan: true, pengelola: false, ruangId: 'u',
    jenisCatatan: ['pengeluaran'] });
  assert.equal(aksesRuang({ ...KELUARGA, peran: 'member' }).karyawan, false);   // anggota household tidak dibatasi
  assert.equal(aksesRuang(USAHA_ADMIN).pengelola, true);
  assert.equal(aksesRuang(null).karyawan, false);
  assert.deepEqual(aksesRuang({ ...KARYAWAN, jenis_catatan: null }).jenisCatatan, ['pengeluaran', 'penjualan']);
});

test('ruteBoleh: karyawan hanya Beranda, Transaksi, Pengaturan; halaman Anggota hanya pengelola', () => {
  const k = aksesRuang(KARYAWAN);
  for (const p of ['/', '/transactions', '/settings', '/settings/']) assert.equal(ruteBoleh(p, k), true, p);
  for (const p of ['/envelopes', '/allocate', '/analytics', '/langganan', '/ruang', '/admin']) {
    assert.equal(ruteBoleh(p, k), false, p);
  }
  assert.equal(ruteBoleh('/ruang', aksesRuang(USAHA_OWNER)), true);
  assert.equal(ruteBoleh('/ruang', aksesRuang(KELUARGA)), false);
  assert.equal(ruteBoleh('/analytics', aksesRuang(USAHA_ADMIN)), true);
});

test('menuUntuk: karyawan menu tersaring, pengelola usaha mendapat Anggota dengan angka antrean', () => {
  assert.deepEqual(menuUntuk(MENU, aksesRuang(KARYAWAN)).map(i => i.to), ['/', '/transactions']);
  const kelola = menuUntuk(MENU, aksesRuang(USAHA_OWNER), { menunggu: 3 });
  assert.deepEqual(kelola.at(-1), { to: '/ruang', label: 'Anggota', icon: 'users', badge: 3, badgeLabel: 'menunggu persetujuan' });
  assert.deepEqual(menuUntuk(MENU, aksesRuang(KELUARGA)), MENU);
  assert.deepEqual(menuUntuk(MENU, aksesRuang(USAHA_OWNER), { kelola: false }), MENU);
});

test('catatKaryawan dan payloadCatat', () => {
  assert.deepEqual(catatKaryawan(aksesRuang(KARYAWAN)).map(o => o.key), ['karyawan-pengeluaran']);
  assert.deepEqual(catatKaryawan(aksesRuang(USAHA_OWNER)), []);
  assert.equal(jenisDariAksi('karyawan-penjualan'), 'penjualan');
  assert.deepEqual(payloadCatat({ jenis: 'pengeluaran', nominal: '125000', keterangan: ' kardus ', amplopId: 'e1',
    clientRef: 'r1' }), { path: '/transactions/', body: { envelope_id: 'e1', amount: 125000, description: 'kardus',
    client_ref: 'r1' } });
  const jual = payloadCatat({ jenis: 'penjualan', nominal: 900000, keterangan: '', amplopId: 'e2', clientRef: 'r2' });
  assert.deepEqual(jual, { path: '/incomes/', body: { amount: 900000, source: 'Penjualan', client_ref: 'r2',
    allocations: [{ envelope_id: 'e2', amount: 900000 }] } });
});

test('hasilCatat: 202 draf, 201 tercatat, galat membawa pesan server', () => {
  assert.deepEqual(hasilCatat(202, { kode: 'perlu_persetujuan', detail: 'Batas catatanmu Rp1.000.000.' }),
    { hasil: 'menunggu', pesan: 'Batas catatanmu Rp1.000.000.' });
  assert.equal(hasilCatat(201, { id: 'x' }).hasil, 'tercatat');
  assert.deepEqual(hasilCatat(403, { kode: 'amplop_tidak_diizinkan', detail: 'Amplop ini tidak termasuk.' }),
    { hasil: 'galat', pesan: 'Amplop ini tidak termasuk.' });
  assert.equal(hasilCatat(0, null).hasil, 'galat');
  assert.match(hasilCatat(422, {}).pesan, /Gagal menyimpan/);
});

test('ringkasBatasan dan ringkasHari', () => {
  assert.equal(ringkasHari([1, 2, 3, 4, 5, 6]), 'Sen–Sab');
  assert.equal(ringkasHari([1, 2, 3, 4, 5, 6, 7]), 'setiap hari');
  assert.equal(ringkasHari([1, 3]), 'Sen, Rab');
  const baris = ringkasBatasan({ jenis_catatan: ['pengeluaran'], batas_nominal: 1000000, foto_nota_di_atas: 300000,
    jendela_ubah: 'hari_sama', lihat_saldo: false, jam_kerja: { mulai: '07:00', selesai: '15:00', hari: [1, 2, 3, 4, 5, 6] } },
  ['Bahan', 'Operasional']);
  assert.deepEqual(baris, [
    'Boleh mencatat pengeluaran saja', 'Amplop: Bahan, Operasional',
    'Di atas Rp1.000.000 per catatan menunggu persetujuan admin', 'Wajib foto nota di atas Rp300.000',
    'Catatan sendiri bisa dihapus di hari yang sama', 'Saldo amplop tidak ditampilkan', 'Jam kerja 07:00–15:00, Sen–Sab',
  ]);
  assert.equal(ringkasBatasan({ jenis_catatan: ['pengeluaran', 'penjualan'] }, null)[1], 'Semua amplop ruang ini');
  assert.deepEqual(ringkasBatasan(null), []);
});

test('form batasan bolak-balik tanpa kehilangan isian', () => {
  const api = { jenis_catatan: ['pengeluaran'], amplop_ids: ['a'], batas_nominal: 1000000, foto_nota_di_atas: null,
    jendela_ubah: 'tidak_boleh', lihat_saldo: true, jam_kerja: { mulai: '22:00', selesai: '06:00', hari: [5, 6], zona: 'Asia/Makassar' } };
  assert.deepEqual(batasanDariForm(formDariBatasan(api)), api);
  const bawaan = formDariBatasan(null);
  assert.deepEqual(batasanDariForm(bawaan), { jenis_catatan: ['pengeluaran', 'penjualan'], amplop_ids: null,
    batas_nominal: null, foto_nota_di_atas: null, jendela_ubah: 'hari_sama', lihat_saldo: false, jam_kerja: null });
  assert.equal(batasanDariForm({ ...bawaan, batas_nominal: 'Rp1.500.000' }).batas_nominal, 1500000);
  assert.equal(galatForm(bawaan), null);
  assert.match(galatForm({ ...bawaan, pakai_jam_kerja: true, hari: [] }), /hari kerja/);
  assert.match(galatForm({ ...bawaan, semua_amplop: false, amplop_ids: [] }), /minimal satu amplop/);
});

test('labelAudit', () => {
  assert.equal(labelAudit({ aksi: 'anggota_diubah', oleh_nama: 'Ani', anggota_nama: 'Dewi',
    rincian: { peran: { dari: 'member', ke: 'admin' } } }), 'Ani mengubah peran Dewi menjadi Admin');
  assert.equal(labelAudit({ aksi: 'draf_disetujui', oleh_nama: 'Ani', anggota_nama: null }),
    'Ani menyetujui catatan Mantan anggota');
  assert.equal(labelAudit({ aksi: 'ruang_diubah', oleh_nama: 'Saya', rincian: { nama: { dari: 'A', ke: 'B' } } }),
    'Saya mengganti nama ruang menjadi B');
  assert.equal(labelAudit({ aksi: 'undangan_dicabut', oleh_nama: 'Saya', rincian: { peran: 'admin' } }),
    'Saya mencabut undangan Admin');
});
