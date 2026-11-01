// Ruang yang sedang dibuka (Plugin R4; docs/plugin/04-kontrak-api.md §1–§2).
//
// Klien hanya MEMILIH ruang: id ruang terpilih dikirim sebagai header `X-Jatahku-Ruang`, dan server
// yang memutuskan boleh atau tidak (keanggotaan, flag `ruang_usaha_users`). Yang disimpan di perangkat
// hanya id ruang (bukan data keuangan), dan hanya untuk ruang selain ruang keluarga: tanpa header =
// ruang keluarga, sama seperti aplikasi sebelum R4. Dikosongkan saat logout.
//
// Server menolak header (403 `ruang_tidak_diizinkan`: ruang dihapus, user dikeluarkan, flag dicabut)
// → klien kembali ke ruang keluarga (`api.js`).

export const RUANG_HEADER = 'X-Jatahku-Ruang';
export const KODE_RUANG_DITOLAK = 'ruang_tidak_diizinkan';
const KEY = 'jatahku_ruang_aktif';
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const store = (storage) => (storage === undefined ? globalThis.localStorage : storage);

export function getRuangAktif(storage) {
  try {
    const v = store(storage)?.getItem(KEY);
    return v && UUID_RE.test(v) ? v : null;
  } catch {
    return null;
  }
}

// `id` kosong atau ruang keluarga (`bawaan`) → dihapus, supaya permintaan tanpa header.
export function setRuangAktif(id, { bawaan = null, storage } = {}) {
  try {
    const s = store(storage);
    if (!id || id === bawaan || !UUID_RE.test(String(id))) s?.removeItem(KEY);
    else s?.setItem(KEY, String(id));
  } catch {}
}

export function withRuangHeader(headers = {}, storage) {
  const id = getRuangAktif(storage);
  return id ? { ...headers, [RUANG_HEADER]: id } : headers;
}

// Cache offline per ruang: data ruang usaha tidak pernah tampil saat ruang keluarga dibuka, dan sebaliknya.
// Ruang keluarga memakai kunci lama (tanpa akhiran), jadi cache yang sudah ada tetap terpakai.
export function ruangCacheSuffix(storage) {
  const id = getRuangAktif(storage);
  return id ? `@${id}` : '';
}

export function isRuangDitolak(status, body) {
  return status === 403 && body?.kode === KODE_RUANG_DITOLAK;
}

// Isi pemilih ruang dari `GET /ruang`. `tampil` false → tampilan sama seperti sebelum R4
// (user di luar flag: hanya ruang keluarga dan tidak bisa membuat ruang usaha).
export function pilihanRuang(daftar, aktifId) {
  const items = Array.isArray(daftar?.items) ? daftar.items : [];
  const bawaan = daftar?.bawaan ?? null;
  const aktif = items.find(r => r.id === aktifId) || items.find(r => r.id === bawaan) || items[0] || null;
  return {
    items,
    bawaan,
    aktif,
    bolehBuat: !!daftar?.boleh_buat_usaha,
    tampil: items.length > 1 || !!daftar?.boleh_buat_usaha,
  };
}

const PERAN_LABEL = { owner: 'Pemilik', admin: 'Admin', member: 'Karyawan' };
export const peranLabel = (peran) => PERAN_LABEL[peran] || '';
export const jenisLabel = (jenis) => (jenis === 'usaha' ? 'Usaha' : 'Rumah tangga');

// ADR-P16: chat selalu ruang keluarga. Di ruang usaha, karyawan tidak melihat tombol chat;
// pemilik dan admin melihatnya berlabel "Ruang keluarga".
export function chatDiRuang(aktif) {
  if (!aktif || aktif.jenis !== 'usaha') return { tampil: true, label: null };
  if (aktif.peran === 'member') return { tampil: false, label: null };
  return { tampil: true, label: 'Ruang keluarga' };
}
