// Banner "bukti menunggu" (PendingProofsBanner di Layout) dan tips berbagi bukti di Settings — logika murni tanpa
// DOM dan tanpa api.js, supaya bisa dites dengan node --test (komponen hanya menyambungkan API, state, dan router).
//
// Banner menjumlahkan dua hal: bukti yang dibagikan ke PWA tapi belum terkirim (entri kotak share lokal, shareInbox)
// dan item siap di server yang menunggu dicatat (`GET /kotak-struk/count?status=siap`, satu COUNT). Ketuk → /bagikan:
// halaman itu yang mengirim entri lokal dan menampilkan kartunya (banner sendiri tidak mengunggah apa pun).
// Semuanya hanya saat saklar `features.receipt_inbox` menyala: saklar mati = tanpa permintaan, tanpa IndexedDB, dan
// tanpa listener.
import { pendingBannerText } from './proofFormat.js';

// Item Kotak Struk berubah tanpa transaksi baru (baris form Catat dilewati): banner menghitung ulang.
export const KOTAK_CHANGED = 'jatahku:kotak-changed';

// Pemicu hitung ulang di window (selain `visibilitychange` di document dan setiap pindah halaman).
export const REFRESH_EVENTS = Object.freeze(['online', 'jatahku:txn-added', KOTAK_CHANGED]);

export const NO_COUNTS = Object.freeze({ unsent: 0, ready: 0 });

// Tips Settings (tepat sesudah kartu Telegram), juga hanya saat saklar menyala.
export const SHARE_TIP = 'Bagikan bukti bayar ke Jatahku: di Android, pasang Jatahku dari browser lalu pilih Jatahku di '
  + 'menu Bagikan. Di iPhone, bagikan bukti ke bot Telegram Jatahku.';

// Saklar dari useAppConfig(): hanya nilai boolean true. Belum terbaca (DEFAULT_CONFIG) / mati / bentuk lain → false.
export function receiptInboxOn(config) {
  return config?.features?.receipt_inbox === true;
}

// Isi `GET /kotak-struk/count` → jumlah (bilangan bulat ≥ 0), atau null bila bentuknya lain (api.kotakPendingCount
// menjadikannya "gagal": banner memakai angka terakhir).
export function pendingCountOf(data) {
  const n = data?.count;
  return Number.isSafeInteger(n) && n >= 0 ? n : null;
}

// Banner tidak tampil di halaman /bagikan sendiri (juga /bagikan/; besar-kecil huruf diabaikan seperti rute React
// Router): di sana kartunya sudah tampil.
export function bannerHiddenAt(pathname) {
  return /^\/bagikan\/?$/i.test(String(pathname ?? ''));
}

// Yang dirender banner: null (tidak tampil) atau { text, lead, action }. `text` = pendingBannerText apa adanya; `lead`
// dan `action` hanya pemisahan untuk tampilan (kata tindakan digarisbawahi seperti "Tinjau" di banner antrean offline).
export function bannerView({ enabled = false, pathname = '', counts = NO_COUNTS } = {}) {
  if (!enabled || bannerHiddenAt(pathname)) return null;
  const text = pendingBannerText(counts || NO_COUNTS);
  if (!text) return null;
  const cut = text.lastIndexOf(' · ');
  return { text, lead: text.slice(0, cut), action: text.slice(cut + 3) };
}

async function settle(load, fallback) {
  try {
    return await load();
  } catch {
    return fallback;
  }
}

// Penghitung banner. I/O disuntikkan:
//   loadUnsent() → entri kotak share (shareStore().all()); ditolak/melempar (IndexedDB rusak) → 0, tidak pernah lolos;
//   loadReady()  → api.kotakPendingCount(): angka, atau null bila gagal → angka terakhir yang diketahui (awalnya 0);
//   onCounts({ unsent, ready }) → hasil untuk ditampilkan.
// Tiap angka tampil begitu bacaannya sendiri selesai, tanpa menunggu yang lain: COUNT yang lambat atau macet (tidak ada
// batas waktu permintaan) tidak menahan jumlah lokal, dan IndexedDB yang macet tidak menahan angka server. Teksnya bisa
// berganti dua kali berturut-turut. refresh() boleh dipanggil kapan saja dan bertumpuk (hitung ulang baru tidak
// menunggu yang lama); setiap angka berasal dari hitung ulang TERBARU yang membawanya: jawaban yang lebih lama tidak
// pernah menimpa yang lebih baru. stop(): hasil yang masih berjalan diabaikan dan refresh() berikutnya tidak membaca apa
// pun (saklar dimatikan / banner dilepas). → janji yang selesai saat kedua bacaan selesai (macet → tidak pernah).
export function createPendingCounter({ loadUnsent, loadReady, onCounts }) {
  let started = 0;
  let unsentFrom = 0;
  let readyFrom = 0;
  let counts = NO_COUNTS;
  let stopped = false;
  const show = (patch) => {
    counts = { ...counts, ...patch };
    onCounts(counts);
  };
  return {
    async refresh() {
      if (stopped) return;
      const mine = ++started;
      await Promise.all([
        settle(loadUnsent, []).then((entries) => {
          if (stopped || mine <= unsentFrom) return;
          unsentFrom = mine;
          show({ unsent: Array.isArray(entries) ? entries.length : 0 });
        }),
        settle(loadReady, null).then((ready) => {
          if (stopped || !(Number.isSafeInteger(ready) && ready >= 0) || mine <= readyFrom) return;
          readyFrom = mine;
          show({ ready });
        }),
      ]);
    },
    stop() {
      stopped = true;
    },
  };
}

// Pasang pemicu hitung ulang: REFRESH_EVENTS di `win`, `visibilitychange` di `doc` hanya saat halaman terlihat lagi.
// → pelepas yang mencabut semuanya. `refresh` dipanggil tanpa argumen.
export function watchRefreshTriggers(refresh, { win = globalThis.window, doc = globalThis.document } = {}) {
  const run = () => { refresh(); };
  const onVisible = () => { if (doc.visibilityState === 'visible') refresh(); };
  for (const name of REFRESH_EVENTS) win.addEventListener(name, run);
  doc.addEventListener('visibilitychange', onVisible);
  return () => {
    for (const name of REFRESH_EVENTS) win.removeEventListener(name, run);
    doc.removeEventListener('visibilitychange', onVisible);
  };
}

// Sesudah `api.kotakSkip` dari luar /bagikan (baris form Catat dihapus): jawaban 2xx → event KOTAK_CHANGED supaya
// banner langsung menurunkan hitungannya. 409/404/jaringan: item tidak berubah, tanpa event. → true bila dikirim.
export function announceKotakChange(res, target = globalThis) {
  if (res?.ok !== true) return false;
  target.dispatchEvent(new CustomEvent(KOTAK_CHANGED));
  return true;
}
