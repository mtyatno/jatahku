// Token sekali pakai di URL halaman (`/reset-password?token=`, `/hapus-akun?token=`, `/auth/tg?token=`).
// Halaman membacanya sekali (initializer useState), lalu menghapusnya dari address bar (effect), supaya token
// tidak tertinggal di riwayat peramban, tangkapan layar, atau laporan error. Memuat ulang halaman sesudah itu
// berarti membuka lagi tautan dari email atau bot.
//
// Dibaca di initializer dan dihapus di effect (pola LaporanSettings): StrictMode menjalankan effect dua kali,
// dan jalan kedua tidak boleh kehilangan token.

export const PARAM_TOKEN = 'token';

export function bacaToken(search, nama = PARAM_TOKEN) {
  return new URLSearchParams(search || '').get(nama);
}

// URL yang sama tanpa parameter `nama`; query lain dan hash tetap. null bila parameternya memang tidak ada.
export function urlTanpaParam({ pathname, search, hash }, nama = PARAM_TOKEN) {
  const params = new URLSearchParams(search || '');
  if (!params.has(nama)) return null;
  params.delete(nama);
  const sisa = params.toString();
  return pathname + (sisa ? `?${sisa}` : '') + (hash || '');
}

// Mengganti entri riwayat saat ini dengan URL tanpa token; state riwayat (milik react-router) tetap.
// true bila address bar diubah. Tidak pernah melempar.
export function hapusTokenDariUrl(win, nama = PARAM_TOKEN) {
  try {
    const url = urlTanpaParam(win.location, nama);
    if (url === null) return false;
    win.history.replaceState(win.history.state, '', url);
    return true;
  } catch {
    return false;
  }
}
