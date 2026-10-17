// Chip pertanyaan cepat di ChatPanel (02-aturan.md §6H CHAT, S17): per halaman yang sedang
// dibuka, hanya pertanyaan yang pasti terjawab bot (intent di app/bot/nlp_cmd.py). Tidak ada
// angka di sini — angka datang dari jawaban bot (metrics + render di server). Chip dari insight
// yang menyala (CTA "Tanya di chat", payload `chat`) tetap didahulukan (draftChips).

const Q = {
  sisa: { label: 'Sisa jatah', text: 'sisa' },
  hariIni: { label: 'Hari ini', text: 'pengeluaran hari ini' },
  harian: { label: 'Limit harian', text: 'limit harian' },
  habis: { label: 'Kapan habis?', text: 'kapan habis' },
  boros: { label: 'Kenapa boros?', text: 'kenapa boros?' },
  tagihan: { label: 'Tagihan bulan ini', text: 'tagihan bulan ini' },
  target: { label: 'Target tabungan', text: 'target' },
  // SIM-01 butuh nominal & barang: chip hanya mengisi kotak ketik, tidak langsung terkirim.
  amanBeli: { label: 'Aman beli…?', text: 'aman gak beli ', fill: true },
};

const UMUM = [
  { label: '/status', text: '/status' },
  { label: '/amplop', text: '/amplop' },
  { label: 'Panduan', text: '/help' },
];

const PER_HALAMAN = {
  '/': [Q.boros, Q.habis, Q.harian, Q.amanBeli, Q.hariIni, Q.sisa, Q.tagihan],
  '/envelopes': [Q.sisa, Q.boros, Q.target, Q.harian, Q.amanBeli],
  '/transactions': [Q.hariIni, Q.boros, Q.habis, Q.amanBeli],
  '/allocate': [Q.sisa, Q.tagihan, Q.target, Q.habis],
  '/langganan': [Q.tagihan, Q.sisa, Q.habis],
  '/analytics': [Q.boros, Q.habis, Q.hariIni, Q.target],
};

const BAWAAN = [Q.sisa, Q.hariIni, Q.harian, Q.habis, Q.boros, Q.tagihan];

export function pageChips(pathname) {
  const path = String(pathname || '/').replace(/\/+$/, '') || '/';
  return PER_HALAMAN[path] || BAWAAN;
}

// Urutan chip di bawah chat: chip dari insight (draft) → chip halaman → perintah umum,
// tanpa duplikat teks (huruf besar/kecil & spasi diabaikan).
export function quickChips(pathname, draftChips = []) {
  const seen = new Set();
  const out = [];
  const add = (chip, draft) => {
    const key = String(chip?.text || '').trim().toLowerCase();
    if (!key || seen.has(key)) return;
    seen.add(key);
    out.push({ ...chip, draft });
  };
  (draftChips || []).forEach(c => add(c, true));
  pageChips(pathname).forEach(c => add(c, false));
  UMUM.forEach(c => add(c, false));
  return out;
}
