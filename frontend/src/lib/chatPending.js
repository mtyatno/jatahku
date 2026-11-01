// Bukti dari chat yang dibaca lewat batas tunggu bot (10 dtk): server membalas "⏳ Masih dibaca" dengan id item
// Kotak Struk (`item`, `pending` di riwayat lokal, lihat chatHistory.js), dan panel chat menanyakan hasilnya ke
// POST /bot/chat/bukti selagi panel terbuka — padanan "nanti kukabari" di Telegram, tetapi ditarik klien karena
// server tidak menyimpan riwayat chat web. Hasilnya mengganti gelembung yang sama (op "edit") dengan teks dan tombol
// amplop yang sama dengan Telegram.
//
// Dua hal yang ditanyakan:
// - gelembung yang masih `pending` (pendingItems): ditanya berulang dengan jeda POLL_DELAYS_MS sampai server tidak
//   lagi mengembalikannya di `pending`;
// - gelembung hasil yang tombolnya hampir basi (staleItems): sesi tombol bot (`txn:{key}`) hanya 10 menit, jadi saat
//   panel dibuka/kembali tampil, tombol yang dirender ≥ STALE_MS lalu dirender ulang dulu — tanpa itu ketukan sesudah
//   pergi sebentar dijawab "Session expired. Kirim ulang."
// Semua aturannya di sini (murni, diuji); ChatPanel hanya menjalankan timer-nya.

export const POLL_DELAYS_MS = [3000, 5000, 8000, 13000, 20000, 30000];
export const STALE_MS = 9 * 60 * 1000; // TXN_TTL server 600 dtk, dikurangi jeda aman

function pair(m) {
  return { item_id: m.item, message_id: m.id };
}

function isProofBubble(m) {
  return m && m.role === 'bot' && typeof m.item === 'string' && m.item && typeof m.id === 'string';
}

// Gelembung bukti yang masih dibaca.
export function pendingItems(messages) {
  return (messages || []).filter(m => isProofBubble(m) && m.pending === true).map(pair);
}

// Gelembung hasil bertombol yang sesi tombolnya hampir habis.
export function staleItems(messages, now = Date.now()) {
  return (messages || [])
    .filter(m => isProofBubble(m) && m.pending !== true && Array.isArray(m.buttons) && m.buttons.length > 0
      && typeof m.renderedAt === 'number' && now - m.renderedAt >= STALE_MS)
    .map(pair);
}

// Pasangan {item_id, message_id} yang ditanyakan sekarang: yang menunggu selalu; yang basi hanya saat `refresh`
// (panel dibuka atau kembali tampil). Tanpa duplikat pasangan.
export function askItems(messages, now = Date.now(), { refresh = false } = {}) {
  const out = [];
  const seen = new Set();
  for (const p of [...pendingItems(messages), ...(refresh ? staleItems(messages, now) : [])]) {
    const key = `${p.item_id}:${p.message_id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(p);
  }
  return out;
}

// Jeda sebelum tanya ulang ke-`attempt` (0 = yang pertama sesudah jawaban "masih dibaca").
export function pollDelay(attempt) {
  return POLL_DELAYS_MS[Math.min(Math.max(0, attempt | 0), POLL_DELAYS_MS.length - 1)];
}
