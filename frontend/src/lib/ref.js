// Kunci idempotensi per transaksi (client_ref): kirim ulang setelah respons
// hilang tidak mencatat dua kali — server mengembalikan transaksi yang sudah ada.
export function newRef() {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  } catch {
    // lanjut ke cadangan
  }
  return `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}
