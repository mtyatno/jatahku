import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BREAKPOINT_DESKTOP, tampilanLaporan, labelStatus, angkaUtama, trenTeks, bannerLaporan, statusEmail, pesanVerifikasi, unduhPdf,
  HALAMAN_LAPORAN, isiHalaman, masihAdaHalaman, gabungLaporan,
} from './laporanView.js';

const res = (status, body, { blob } = {}) => ({
  status,
  ok: status >= 200 && status < 300,
  json: async () => { if (body === undefined) throw new Error('no json'); return body; },
  blob: async () => blob ?? { fake: 'blob' },
});
const laporan = { id: 'x1', nama_file: 'jatahku-laporan-2026-10.pdf' };
const fakeNative = () => { const saved = []; return { saved, files: { save: async (b, n) => { saved.push([b, n]); } } }; };

test('breakpoint dan tampilan', () => {
  assert.equal(BREAKPOINT_DESKTOP, '(min-width: 1024px)');
  assert.equal(tampilanLaporan(true), 'lengkap');
  assert.equal(tampilanLaporan(false), 'ringkas');
});

test('labelStatus: label persis dan kelas', () => {
  assert.equal(labelStatus('aman').label, 'Aman');
  assert.equal(labelStatus('hampir_habis').label, 'Hampir habis');
  assert.equal(labelStatus('lewat_batas').label, 'Lewat batas');
  assert.equal(labelStatus('tabungan').label, 'Tabungan');
  assert.equal(labelStatus('kosong').label, 'Kosong');
  for (const s of ['aman', 'hampir_habis', 'lewat_batas', 'tabungan', 'kosong']) {
    assert.equal(typeof labelStatus(s).kelas, 'string');
    assert.ok(labelStatus(s).kelas.length > 0);
  }
  assert.equal(labelStatus('aneh').label, 'aneh');
  assert.equal(labelStatus(undefined).label, '—');
});

test('angkaUtama: empat angka berurutan, null jadi "—", tidak dihitung ulang', () => {
  const data = { ringkasan: { terpakai: '1500000.00', sisa: '500000.00', dibawa: '200000.00', persen_terpakai: 75, pemasukan: '9', dialokasikan: '2000000.00' } };
  const out = angkaUtama(data);
  assert.deepEqual(out.map(x => x.label), ['Terpakai', 'Sisa', 'Dibawa ke periode berikut', 'Anggaran terpakai']);
  assert.match(out[0].nilai, /1\.500\.000/);
  assert.match(out[1].nilai, /500\.000/);
  assert.match(out[2].nilai, /200\.000/);
  assert.equal(out[3].nilai, '75%');
  const nol = angkaUtama({ ringkasan: { ...data.ringkasan, persen_terpakai: null } });
  assert.equal(nol[3].nilai, '—');
  assert.equal(angkaUtama({ ringkasan: { ...data.ringkasan, persen_terpakai: 0 } })[3].nilai, '0%');
});

test('trenTeks', () => {
  assert.equal(trenTeks(-12), 'Pengeluaran turun 12% dibanding periode lalu');
  assert.equal(trenTeks(5), 'Pengeluaran naik 5% dibanding periode lalu');
  assert.equal(trenTeks(0), 'Pengeluaran sama dengan periode lalu');
  assert.equal(trenTeks(null), '');
  assert.equal(trenTeks(undefined), '');
});

test('daftar laporan per halaman: ukuran sama dengan bawaan API, isi halaman dari daftar atau {items}', () => {
  assert.equal(HALAMAN_LAPORAN, 24);
  const satu = [{ id: 'a' }];
  assert.deepEqual(isiHalaman(satu), satu);
  assert.deepEqual(isiHalaman({ items: satu }), satu);
  assert.deepEqual(isiHalaman(null), []);
  assert.deepEqual(isiHalaman({}), []);
});

test('masihAdaHalaman: hanya bila halaman terakhir penuh', () => {
  const halaman = (n) => Array.from({ length: n }, (_, i) => ({ id: String(i) }));
  assert.equal(masihAdaHalaman(halaman(HALAMAN_LAPORAN)), true);
  assert.equal(masihAdaHalaman(halaman(HALAMAN_LAPORAN - 1)), false);  // halaman pendek: habis
  assert.equal(masihAdaHalaman([]), false);                            // daftar kosong atau halaman kosong
  assert.equal(masihAdaHalaman(halaman(3), 3), true);
  assert.equal(masihAdaHalaman(null), false);
  assert.equal(masihAdaHalaman(undefined), false);
});

test('gabungLaporan: menyambung tanpa mengulang id yang sudah tampil', () => {
  const lama = [{ id: 'a' }, { id: 'b' }];
  // Laporan baru terbit di antara dua muatan: offset bergeser satu, baris terakhir halaman lalu datang lagi.
  assert.deepEqual(gabungLaporan(lama, [{ id: 'b' }, { id: 'c' }]).map((l) => l.id), ['a', 'b', 'c']);
  assert.deepEqual(gabungLaporan(lama, []).map((l) => l.id), ['a', 'b']);
  assert.deepEqual(gabungLaporan(null, [{ id: 'x' }]).map((l) => l.id), ['x']);
  assert.deepEqual(gabungLaporan(lama, null), lama);
  assert.deepEqual(lama.map((l) => l.id), ['a', 'b']);  // masukan tidak diubah
});

test('bannerLaporan', () => {
  assert.deepEqual(bannerLaporan({ kata_sandi_diatur: false }), { teks: 'Atur kata sandi laporan untuk mengunduh PDF.', tautan: '/settings#laporan' });
  assert.equal(bannerLaporan({ kata_sandi_diatur: true }), null);
  assert.equal(bannerLaporan(null), null);
  assert.equal(bannerLaporan(undefined), null);
});

test('bannerLaporan email: kata sandi lebih dulu, lalu verifikasi email', () => {
  const email = { teks: 'Verifikasi email untuk menerima laporan lewat email.', tautan: '/settings#laporan' };
  const dasar = { kata_sandi_diatur: true, email: 'a@b.id', email_terverifikasi: false, email_on: true };
  assert.deepEqual(bannerLaporan(dasar), email);
  assert.equal(bannerLaporan({ ...dasar, email_terverifikasi: true }), null);
  assert.equal(bannerLaporan({ ...dasar, email_on: false }), null);
  assert.equal(bannerLaporan({ ...dasar, email: null }), null);
  assert.equal(bannerLaporan({ ...dasar, kata_sandi_diatur: false }).teks, 'Atur kata sandi laporan untuk mengunduh PDF.');
});

test('statusEmail', () => {
  assert.deepEqual(statusEmail({ email: null }), { teks: 'Belum ada email di akun ini. Laporan tetap terbit di aplikasi dan Telegram.', bisaVerifikasi: false });
  assert.deepEqual(statusEmail({ email: 'a@b.id', email_terverifikasi: false }), { teks: 'Email a@b.id belum terverifikasi.', bisaVerifikasi: true });
  assert.deepEqual(statusEmail({ email: 'a@b.id', email_terverifikasi: true }), { teks: 'Email a@b.id terverifikasi.', bisaVerifikasi: false });
  assert.equal(statusEmail(null).bisaVerifikasi, false);
});

test('pesanVerifikasi', () => {
  assert.deepEqual(pesanVerifikasi('berhasil'), { teks: 'Email terverifikasi. Laporan berikutnya juga dikirim ke email.', jenis: 'sukses' });
  assert.deepEqual(pesanVerifikasi('tidak_berlaku'), { teks: 'Tautan verifikasi tidak berlaku atau sudah kedaluwarsa. Kirim tautan baru.', jenis: 'galat' });
  assert.deepEqual(pesanVerifikasi('berubah'), { teks: 'Alamat email akunmu sudah berubah sejak tautan dikirim. Kirim tautan baru.', jenis: 'galat' });
  assert.equal(pesanVerifikasi('asing'), null);
  assert.equal(pesanVerifikasi(null), null);
  assert.equal(pesanVerifikasi('toString'), null);
});

test('unduhPdf 200: simpan dengan nama_file dari JSON', async () => {
  const native = fakeNative();
  const api = { unduhLaporanPdf: async () => res(200, undefined, { blob: 'BLOB' }) };
  const r = await unduhPdf({ api, native, laporan, mintaKataSandi: async () => assert.fail('tak dipanggil') });
  assert.equal(r, 'tersimpan');
  assert.deepEqual(native.saved, [['BLOB', laporan.nama_file]]);
});

test('unduhPdf 409 lalu setuju: ulangi sekali dan simpan', async () => {
  const native = fakeNative();
  const balasan = [res(409, { detail: 'x', kode: 'kata_sandi_belum_diatur' }), res(200, undefined, { blob: 'B2' })];
  let panggil = 0, minta = 0;
  const api = { unduhLaporanPdf: async () => { panggil += 1; return balasan.shift(); } };
  const r = await unduhPdf({ api, native, laporan, mintaKataSandi: async () => { minta += 1; return true; } });
  assert.equal(r, 'tersimpan');
  assert.equal(panggil, 2);
  assert.equal(minta, 1);
  assert.deepEqual(native.saved, [['B2', laporan.nama_file]]);
});

test('unduhPdf 409 lalu batal: dibatalkan, tak ada simpan, tak ada ulangan', async () => {
  const native = fakeNative();
  let panggil = 0;
  const api = { unduhLaporanPdf: async () => { panggil += 1; return res(409, { detail: 'x', kode: 'kata_sandi_belum_diatur' }); } };
  const r = await unduhPdf({ api, native, laporan, mintaKataSandi: async () => false });
  assert.equal(r, 'dibatalkan');
  assert.equal(panggil, 1);
  assert.equal(native.saved.length, 0);
});

test('unduhPdf 409 lagi setelah diulang: melempar detail, tidak berputar', async () => {
  const native = fakeNative();
  let panggil = 0;
  const api = { unduhLaporanPdf: async () => { panggil += 1; return res(409, { detail: 'Atur dulu.', kode: 'kata_sandi_belum_diatur' }); } };
  await assert.rejects(unduhPdf({ api, native, laporan, mintaKataSandi: async () => true }), { message: 'Atur dulu.' });
  assert.equal(panggil, 2);
});

test('unduhPdf: 404, 503, 429, dan badan tak terbaca', async () => {
  const native = fakeNative();
  const coba = (r) => unduhPdf({ api: { unduhLaporanPdf: async () => r }, native, laporan, mintaKataSandi: async () => true });
  await assert.rejects(coba(res(404, { detail: 'Laporan tidak ditemukan' })), { message: 'Laporan tidak ditemukan' });
  await assert.rejects(coba(res(503, { detail: 'Kata sandi laporan belum bisa dipakai di server. Coba lagi nanti.', kode: 'kunci_belum_diatur' })),
    { message: 'Kata sandi laporan belum bisa dipakai di server. Coba lagi nanti.' });
  await assert.rejects(coba(res(429, { error: 'Rate limit exceeded: 10 per 1 minute' })),
    { message: 'Terlalu sering mengunduh. Coba lagi sebentar lagi.' });
  await assert.rejects(coba(res(500)), { message: 'Gagal mengunduh PDF. Coba lagi nanti.' });
  assert.equal(native.saved.length, 0);
});

test('unduhPdf 409 dengan kode lain: dilempar, tidak meminta kata sandi', async () => {
  const native = fakeNative();
  const api = { unduhLaporanPdf: async () => res(409, { detail: 'Bentrok', kode: 'lain' }) };
  await assert.rejects(unduhPdf({ api, native, laporan, mintaKataSandi: async () => assert.fail('x') }), { message: 'Bentrok' });
});
