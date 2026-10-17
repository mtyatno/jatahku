// Halaman Analitik — AI Advisor v2 (S15, 02-aturan.md §7 "Halaman lain: Analitik").
// Isi dari GET /advisor/page/analitik: ringkasan ≤ 3 poin (pilihan & teks dari server),
// deret grafik metrics.harian (sama dengan Beranda), dan baris analisa grafik. Di sini hanya
// memetakan bentuk; tidak ada hitungan angka periode. User di luar flag / gagal muat / periode
// lama → jalur lama (analyticsInsight.js + /analytics/daily-spending, dihapus di S10b).
import { ACTION_KINDS } from './advisorAction.js';

const TONES = ['danger', 'warn', 'info', 'ok'];

// Ringkasan v2 hanya untuk periode berjalan yang sama dengan respons server.
export function analitikAktif(page, periodStart) {
  return !!(page && page.enabled === true && Array.isArray(page.ringkasan)
    && (!periodStart || page.period_start === periodStart));
}

const tombol = (aksi, max) => (Array.isArray(aksi) ? aksi : [])
  .filter(a => a && ACTION_KINDS.includes(a.kind) && a.label)
  .slice(0, max);

// Poin ringkasan → { key, tone, judul, isi, actions, dismissKey }.
export function ringkasanPoin(page, maxActions = 2) {
  return (page?.ringkasan || []).slice(0, 3).map((r, i) => ({
    key: r.id || `poin-${i}`,
    tone: TONES.includes(r.tone) ? r.tone : 'info',
    judul: r.judul || r.chip || '',
    isi: r.isi || '',
    actions: tombol(r.aksi, maxActions),
    dismissKey: r.dismiss?.kunci || null,
  }));
}

// Deret `harian` (metrics) → bentuk /analytics/daily-spending untuk heatmap: total = belanja
// variabel (batang grafik), supaya heatmap dan grafik menunjuk angka yang sama.
export function harianKeDaily(harian) {
  return (Array.isArray(harian) ? harian : [])
    .map(h => ({ date: String(h.tanggal).slice(0, 10), total: Number(h.variabel) || 0 }))
    .filter(h => h.total > 0);
}

// Tombol rekomendasi sinking fund dari `actions[]` server (kind pipa CTA, S8).
export function sinkingButtons(item, maxActions = 2) {
  return tombol(item?.actions, maxActions);
}
