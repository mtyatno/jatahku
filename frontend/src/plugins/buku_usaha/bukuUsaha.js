// Buku Usaha di web — pembantu murni (Plugin U1; docs/plugin/04-kontrak-api.md §6, 05-desain-buku-usaha.md artboard
// "Halaman Buku Usaha" tab Kontak dan "Fitur Tambahan"). Server yang menyimpan dan memeriksa (`/p/buku_usaha/*`,
// ruang dari header); di sini hanya bentuk, saringan, dan validasi untuk pesan yang sama sebelum dikirim.
// Diuji tanpa browser: node --test src/plugins/buku_usaha/bukuUsaha.test.js

export const PLUGIN_ID = 'buku_usaha';
export const PERAN_KONTAK = Object.freeze([
  { id: 'pelanggan', label: 'Pelanggan', jamak: 'pelanggan' },
  { id: 'pemasok', label: 'Pemasok', jamak: 'pemasok' },
]);
const PERAN_ID = new Set(PERAN_KONTAK.map(p => p.id));
const TELEPON_RE = /^\+?[0-9][0-9 .-]{4,28}$/;        // sama dengan server (`app/plugins/buku_usaha`)
export const MAKS_NAMA = 120;
export const MAKS_CATATAN = 500;

const arr = (v) => (Array.isArray(v) ? v : []);
const teks = (v, maks) => (typeof v === 'string' ? v.slice(0, maks) : '');
export const rapiNama = (v) => String(v ?? '').split(/\s+/).filter(Boolean).join(' ');

/** Jawaban `GET /p/buku_usaha/kontak` → daftar kontak yang aman dipakai UI (entri rusak dibuang). */
export function rapikanKontak(data) {
  return arr(data).filter(k => k && typeof k.id === 'string' && PERAN_ID.has(k.peran)).map(k => ({
    id: k.id,
    nama: teks(k.nama, MAKS_NAMA),
    peran: k.peran,
    telepon: k.telepon ? teks(k.telepon, 30) : '',
    catatan: k.catatan ? teks(k.catatan, MAKS_CATATAN) : '',
    dibuat: typeof k.dibuat === 'string' ? k.dibuat : '',
  }));
}

/** Saringan lokal (daftar sudah dari server untuk ruang ini): peran dan kata di nama/telepon, tanpa peka huruf. */
export function saringKontak(daftar, { peran = '', q = '' } = {}) {
  const kata = rapiNama(q).toLowerCase();
  return arr(daftar).filter(k => (!peran || k.peran === peran)
    && (!kata || k.nama.toLowerCase().includes(kata) || (k.telepon || '').toLowerCase().includes(kata)));
}

/** Urutan tampil: nama (abjad Indonesia), lalu peran. */
export function urutkanKontak(daftar) {
  return [...arr(daftar)].sort((a, b) => a.nama.localeCompare(b.nama, 'id') || a.peran.localeCompare(b.peran));
}

/** Hitungan per peran untuk kepala halaman dan tab. */
export function hitungKontak(daftar) {
  const out = { semua: 0 };
  for (const p of PERAN_KONTAK) out[p.id] = 0;
  for (const k of arr(daftar)) { out.semua += 1; if (k.peran in out) out[k.peran] += 1; }
  return out;
}

/**
 * Validasi form kontak dengan aturan yang sama dengan server; `galat` per kolom kosong = sah.
 * Mengembalikan body yang siap dikirim (nama dirapikan, telepon/catatan kosong → null).
 */
export function validasiKontak(form) {
  const galat = {};
  const nama = rapiNama(form?.nama);
  if (!nama) galat.nama = 'Nama kontak wajib diisi.';
  else if (nama.length > MAKS_NAMA) galat.nama = `Nama kontak paling banyak ${MAKS_NAMA} karakter.`;
  const peran = PERAN_ID.has(form?.peran) ? form.peran : '';
  if (!peran) galat.peran = 'Pilih pelanggan atau pemasok.';
  const telepon = String(form?.telepon ?? '').trim();
  if (telepon && !TELEPON_RE.test(telepon)) galat.telepon = 'Nomor telepon tidak sah (angka, spasi, titik, atau strip).';
  const catatan = String(form?.catatan ?? '').trim();
  if (catatan.length > MAKS_CATATAN) galat.catatan = `Catatan paling banyak ${MAKS_CATATAN} karakter.`;
  return {
    ok: Object.keys(galat).length === 0,
    galat,
    body: { nama, peran, telepon: telepon || null, catatan: catatan || null },
  };
}

/** Body PATCH: hanya kolom yang berubah dari kontak lama. */
export function bodyUbahKontak(lama, body) {
  const out = {};
  for (const k of ['nama', 'peran', 'telepon', 'catatan']) {
    const nilaiLama = k === 'telepon' || k === 'catatan' ? (lama?.[k] || null) : lama?.[k];
    if (body[k] !== nilaiLama) out[k] = body[k];
  }
  return out;
}

/** Jawaban server kontak → pesan untuk user (kode §7 dan kode plugin). */
export function pesanKontakGalat(status, body) {
  const detail = typeof body?.detail === 'string' ? body.detail : '';
  if (status === 0) return 'Koneksi terputus. Coba lagi.';
  if (body?.kode === 'plugin_tidak_aktif') return 'Buku Usaha tidak aktif di ruang ini. Buka Fitur Tambahan untuk melanjutkannya.';
  if (body?.kode === 'kontak_ganda') return detail || 'Kontak dengan nama dan peran yang sama sudah ada.';
  if (body?.kode === 'kontak_tidak_ada') return 'Kontak ini sudah tidak ada. Muat ulang daftar.';
  if (body?.kode === 'khusus_admin') return 'Hanya pemilik dan admin ruang yang bisa mengelola kontak.';
  return detail || 'Belum berhasil. Coba lagi sebentar.';
}

// ── wizard pasang: 5 amplop bawaan ──────────────────────────────────────

/**
 * Jawaban `GET /p/buku_usaha/pengaturan` → baris wizard: yang sudah ada tidak dicentang dan dikunci. `tujuan` dari
 * server: `expense` (amplop belanja, butuh anggaran bulanan) atau `saving` (cadangan, tanpa anggaran).
 */
export function barisWizard(pengaturan) {
  return arr(pengaturan?.amplop_bawaan).filter(a => a && typeof a.nama === 'string').map(a => ({
    kunci: a.nama,
    nama: a.nama,
    emoji: teks(a.emoji, 4) || '📁',
    tujuan: a.tujuan === 'saving' ? 'saving' : 'expense',
    keterangan: teks(a.keterangan, 80),
    ada: !!a.ada,
    pilih: !a.ada,
    anggaran: '',            // digit saja; hanya untuk `expense`
  }));
}

export const digitSaja = (t) => String(t ?? '').replace(/[^\d]/g, '').slice(0, 12);

/**
 * Amplop yang akan dibuat dari pilihan wizard: tercentang, belum ada, nama tidak kosong dan tidak kembar (tanpa peka
 * huruf) — juga terhadap amplop yang sudah ada di ruang (`namaAda`). Body untuk `POST /envelopes/` inti: amplop
 * belanja memakai anggaran yang diisi (wajib > 0, aturan inti), cadangan `saving` tanpa anggaran.
 * Mengembalikan { rencana, kurang }: `kurang` = nama amplop belanja tercentang yang anggarannya masih kosong.
 */
export function rencanaAmplop(baris, namaAda = []) {
  const terpakai = new Set(arr(namaAda).map(n => rapiNama(n).toLowerCase()));
  const rencana = [];
  const kurang = [];
  for (const b of arr(baris)) {
    const nama = rapiNama(b?.nama).slice(0, 50);
    const kunci = nama.toLowerCase();
    if (!b?.pilih || b.ada || !nama || terpakai.has(kunci)) continue;
    terpakai.add(kunci);
    const saving = b.tujuan === 'saving';
    const anggaran = saving ? 0 : Number(digitSaja(b.anggaran));
    if (!saving && !(anggaran > 0)) { kurang.push(nama); continue; }
    rencana.push({ name: nama, emoji: b.emoji || '📁', budget_amount: anggaran, is_rollover: true,
      purpose: saving ? 'saving' : 'expense', ...(saving ? { is_emergency: false } : {}) });
  }
  return { rencana, kurang };
}
