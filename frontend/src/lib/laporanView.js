// Tampilan laporan berkala: logika murni (tes di laporanView.test.js); komponen hanya merender.
// Angka laporan beku di server (`data` v1): frontend hanya memformat, tidak pernah menghitung ulang
// (termasuk `ringkasan.persen_terpakai`, yang tanpa tabungan dan bisa null).
import { formatCurrency } from './utils.js';

export const BREAKPOINT_DESKTOP = '(min-width: 1024px)';

const STRIP = '—';
const PESAN_TERLALU_SERING = 'Terlalu sering mengunduh. Coba lagi sebentar lagi.';
const PESAN_GAGAL = 'Gagal mengunduh PDF. Coba lagi nanti.';
const KODE_BELUM_ADA_SANDI = 'kata_sandi_belum_diatur';

export function tampilanLaporan(isDesktop) {
  return isDesktop ? 'lengkap' : 'ringkas';
}

const STATUS = {
  aman: { label: 'Aman', kelas: 'text-brand-600 bg-brand-50' },
  hampir_habis: { label: 'Hampir habis', kelas: 'text-amber-600 bg-amber-50' },
  lewat_batas: { label: 'Lewat batas', kelas: 'text-danger-600 bg-red-50' },
  tabungan: { label: 'Tabungan', kelas: 'text-gray-700 bg-gray-100' },
  kosong: { label: 'Kosong', kelas: 'text-gray-500 bg-gray-100' },
};

export function labelStatus(status) {
  return STATUS[status] || { label: status ? String(status) : STRIP, kelas: 'text-gray-500 bg-gray-100' };
}

const uang = (v) => (v === null || v === undefined || v === '' ? STRIP : formatCurrency(v));

export function angkaUtama(data) {
  const r = data?.ringkasan || {};
  const persen = r.persen_terpakai;
  return [
    { label: 'Terpakai', nilai: uang(r.terpakai) },
    { label: 'Sisa', nilai: uang(r.sisa) },
    { label: 'Dibawa ke periode berikut', nilai: uang(r.dibawa) },
    { label: 'Anggaran terpakai', nilai: persen === null || persen === undefined ? STRIP : `${persen}%` },
  ];
}

export function trenTeks(persen) {
  if (persen === null || persen === undefined) return '';
  if (persen < 0) return `Pengeluaran turun ${Math.abs(persen)}% dibanding periode lalu`;
  if (persen > 0) return `Pengeluaran naik ${persen}% dibanding periode lalu`;
  return 'Pengeluaran sama dengan periode lalu';
}

// Daftar `/laporan` dimuat per halaman (`GET /laporan?limit&offset`, terbaru dulu); sama dengan bawaan `limit` API.
export const HALAMAN_LAPORAN = 24;

// Isi satu halaman dari jawaban API: daftar, atau `{items}` bila bentuknya kelak dibungkus.
export function isiHalaman(jawaban) {
  return Array.isArray(jawaban) ? jawaban : (jawaban?.items || []);
}

// Halaman berikutnya mungkin ada hanya bila halaman terakhir penuh; halaman pendek (atau kosong) = sudah habis.
export function masihAdaHalaman(halaman, ukuran = HALAMAN_LAPORAN) {
  return Array.isArray(halaman) && halaman.length >= ukuran;
}

// Sambungkan halaman berikutnya tanpa mengulang laporan yang sudah tampil: laporan yang terbit di antara dua muatan
// menggeser offset, jadi baris terakhir halaman sebelumnya bisa datang lagi (id ganda = kunci React ganda).
export function gabungLaporan(lama, baru) {
  const sebelumnya = lama || [];
  const ada = new Set(sebelumnya.map((l) => l.id));
  return [...sebelumnya, ...(baru || []).filter((l) => !ada.has(l.id))];
}

// null = tidak ada banner (kata sandi sudah diatur, atau pengaturan belum termuat).
export function bannerLaporan(pengaturan) {
  if (!pengaturan || pengaturan.kata_sandi_diatur) return null;
  return { teks: 'Atur kata sandi laporan untuk mengunduh PDF.', tautan: '/settings#laporan' };
}

async function bacaJson(res) {
  try { return await res.json(); } catch { return null; }
}

// Pesan galat dari balasan non-200. 429 (slowapi) berbadan {error}, bukan {detail}.
async function galat(res) {
  if (res.status === 429) return new Error(PESAN_TERLALU_SERING);
  const body = await bacaJson(res);
  const detail = typeof body?.detail === 'string' && body.detail ? body.detail : PESAN_GAGAL;
  return new Error(detail);
}

// Nama berkas selalu dari `laporan.nama_file` (JSON): CORS tidak membuka Content-Disposition.
export async function unduhPdf({ api, native, laporan, mintaKataSandi }) {
  let res = await api.unduhLaporanPdf(laporan.id);
  if (res.status === 409) {
    const body = await bacaJson(res);
    if (body?.kode !== KODE_BELUM_ADA_SANDI) {
      throw new Error(typeof body?.detail === 'string' && body.detail ? body.detail : PESAN_GAGAL);
    }
    if (!(await mintaKataSandi())) return 'dibatalkan';
    res = await api.unduhLaporanPdf(laporan.id); // diulang sekali; 409 lagi = galat biasa
  }
  if (res.status !== 200) throw await galat(res);
  await native.files.save(await res.blob(), laporan.nama_file);
  return 'tersimpan';
}
