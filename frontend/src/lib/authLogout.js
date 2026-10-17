// Logout mencabut sesi perangkat ini di server (POST /auth/logout, mobile 1.1)
// sebelum token dihapus dari perangkat. Tidak ditunggu dan tidak pernah gagal:
// logout lokal tetap jalan walau offline. `keepalive` supaya request tetap
// terkirim saat halaman langsung pindah ke /login.
export function revokeSession(apiUrl, refreshToken, fetchFn = globalThis.fetch) {
  if (!refreshToken || typeof fetchFn !== 'function') return;
  try {
    const p = fetchFn(`${apiUrl}/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
      keepalive: true,
    });
    if (p && typeof p.catch === 'function') p.catch(() => {});
  } catch {}
}
