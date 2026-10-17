// Halaman Transaksi AI Advisor (S13): pembantu murni di atas GET /advisor/page/transaksi
// (04-kontrak-api.md). Banner & penanda sudah dipilih dan dirakit server; di sini hanya
// menyusun query dari filter aktif, menyaring yang baru disembunyikan, dan memilih CTA.

// Filter halaman → query endpoint. Tab "Hari Ini" sama dengan filter tanggal hari ini.
export function advisorQuery({ envelope, date, timeTab, today }) {
  return {
    tanggal: date || (timeTab === 'today' ? today : null),
    amplop: envelope && envelope !== 'all' ? envelope : null,
  };
}

export function pageEnabled(page) {
  return !!(page && page.enabled && page.penanda && typeof page.penanda === 'object');
}

const visible = (insight, hidden) => !!insight && !(hidden || []).includes(insight.dismiss?.kunci || insight.id);

// Penanda baris satu transaksi, tanpa yang baru saja disembunyikan (sebelum muat ulang).
export function rowMarkers(page, txnId, hidden = []) {
  if (!pageEnabled(page)) return [];
  return (page.penanda[txnId] || []).filter(m => visible(m, hidden));
}

export function pageBanner(page, hidden = []) {
  if (!pageEnabled(page)) return null;
  return visible(page.banner, hidden) ? page.banner : null;
}

// Aksi `route` ke halaman Transaksi tanpa filter baru tidak berguna di sini (sudah di halaman ini).
const sameTransactionsPage = (a, search) => {
  if (a.kind !== 'route') return false;
  const path = String(a.payload?.path ?? a.payload?.url ?? '');
  if (!path.startsWith('/transactions')) return false;
  const q = path.slice('/transactions'.length);
  return q === '' || q === search;
};

// Paling banyak 2 CTA (sama dengan popover chip Beranda).
export function markerActions(insight, search = '') {
  return (insight?.aksi || []).filter(a => !sameTransactionsPage(a, search)).slice(0, 2);
}
