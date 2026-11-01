// Beranda registry (Plugin B2): pembantu murni untuk tata letak dan data batch.
// Model "urutan + ukuran" (ADR-P8, 01-kajian.md "Ukuran dan tata letak responsif"): kartu disusun
// baris demi baris sesuai urutan; kartu yang tidak muat pindah ke baris berikutnya, dan kartu
// terakhir di setiap baris melebar mengisi sisa baris. P1 mempertahankan tampilan lama persis:
// pasangan L + S di layar ≥1280 px memakai rasio 1,65 : 1 seperti Beranda sekarang.

export const BREAKPOINTS = ['phone', 'md', 'lg', 'xl'];   // <768, 768–1023, 1024–1279, ≥1280 (Tailwind)

export const SPANS = {
  phone: { S: 12, M: 12, L: 12, XL: 12 },
  md: { S: 6, M: 6, L: 12, XL: 12 },
  lg: { S: 4, M: 6, L: 12, XL: 12 },
  xl: { S: 4, M: 6, L: 8, XL: 12 },
};

export function breakpointOf(width) {
  if (width >= 1280) return 'xl';
  if (width >= 1024) return 'lg';
  if (width >= 768) return 'md';
  return 'phone';
}

// devices: all | wide (≥1024 px) | narrow (<1024 px), 04-kontrak-api.md §4.
export function deviceMatches(devices, bp) {
  if (devices === 'wide') return bp === 'lg' || bp === 'xl';
  if (devices === 'narrow') return bp === 'phone' || bp === 'md';
  return true;
}

/** Instans yang dikirim ke POST /dashboard/data: semua yang tidak disembunyikan (devices disaring saat
 *  menggambar, supaya memutar layar tidak memuat ulang data). */
export function itemsForData(layout, known = () => true) {
  return (layout?.items || [])
    .filter(i => !i.hidden && i.visible !== false && known(i.card))
    .map(i => ({ id: i.id, card: i.card, settings: i.settings || {} }));
}

/** Instans yang tampil di breakpoint ini, berurutan. `known(key)` = kartu ada di registry frontend. */
export function visibleItems(layout, bp, known = () => true) {
  return (layout?.items || []).filter(i => !i.hidden && i.visible !== false && known(i.card)
    && deviceMatches(i.devices || 'all', bp));
}

const fr = (span) => `minmax(0,${span}fr)`;

/**
 * Susun instans menjadi baris untuk satu breakpoint.
 * @param {Array<{id, size}>} items  urutan tampil
 * @param {string} bp                breakpoint
 * @param {object} [opts]
 * @param {(item) => boolean} [opts.ownRow]  kartu yang selalu menempati baris sendiri (tautan Cocokkan saldo)
 * @returns {Array<{cells: Array<{item, span}>, template: string}>}
 */
export function packRows(items, bp, { ownRow = () => false } = {}) {
  const spans = SPANS[bp] || SPANS.phone;
  const rows = [];
  let cur = [];
  let used = 0;
  const tutup = () => {
    if (!cur.length) return;
    // Kartu terakhir di baris melebar mengisi sisa kolom.
    cur[cur.length - 1].span += 12 - used;
    rows.push(cur);
    cur = [];
    used = 0;
  };
  for (const item of items) {
    const span = spans[item.size] || spans.S;
    const sendiri = ownRow(item);
    if (sendiri || used + span > 12) tutup();
    cur.push({ item, span });
    used += span;
    if (sendiri) tutup();
  }
  tutup();
  return rows.map(cells => ({ cells, template: rowTemplate(cells.map(c => c.span), bp) }));
}

export function rowTemplate(spans, bp) {
  if (spans.length === 1) return 'minmax(0,1fr)';
  // P1: L + S di ≥1280 px = 1,65 : 1, sama dengan Beranda lama (xl:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]).
  if (bp === 'xl' && spans.length === 2 && spans[0] === 8 && spans[1] === 4) return 'minmax(0,1.65fr) minmax(0,1fr)';
  return spans.map(fr).join(' ');
}

/**
 * Jarak atas baris (px), meniru Beranda lama (diukur di 390/820/1100/1440 px):
 * - KPI ke KPI 12 (satu grid `gap-3`);
 * - baris yang di layar ≥1280 px sebaris (mis. Pengeluaran harian + AI Advisor) lalu bertumpuk di layar
 *   sempit tetap satu kelompok: 16 (`gap-4` grid lama);
 * - selain itu 24 (`space-y-6`; `-mt-1` di tautan Cocokkan saldo kalah oleh space-y, jadi tetap 24).
 */
export function rowGapAbove(prevKind, kind, sameGroup = false) {
  if (prevKind == null) return 0;
  if (prevKind === 'kpi' && kind === 'kpi') return 12;
  if (sameGroup) return 16;
  return 24;
}

/** id instans → nomor baris di layar ≥1280 px: kelompok yang bertumpuk di layar lebih sempit. */
export function groupsOf(items, opts) {
  const out = {};
  packRows(items, 'xl', opts).forEach((row, i) => row.cells.forEach(c => { out[c.item.id] = i; }));
  return out;
}

/** Jenis baris dari jenis kartunya: semua KPI → 'kpi', semua tautan → 'link', selain itu 'card'. */
export function rowKind(kinds) {
  if (kinds.length && kinds.every(k => k === 'kpi')) return 'kpi';
  if (kinds.length && kinds.every(k => k === 'link')) return 'link';
  return 'card';
}

/** Payload sumber pertama dengan nama itu di respons batch (mis. `ringkasan_amplop`, `prediksi`). */
export function sumberPertama(data, nama) {
  for (const entri of Object.values(data || {})) {
    const s = entri && entri.sumber;
    if (s && Object.prototype.hasOwnProperty.call(s, nama) && s[nama] != null) return s[nama];
  }
  return undefined;
}

export const cacheKeyLayout = (userId) => `beranda_layout:${userId}`;
export const cacheKeyData = (userId) => `beranda_data:${userId}`;

/**
 * Beranda mana yang digambar (Plugin B3). `paksa` dari query `?beranda=lama|registry` dipakai untuk
 * membandingkan kedua Beranda di akun sendiri (alat banding tampilan, uji di perangkat); data dan izin
 * tetap dari server. Tanpa `paksa`: field `enabled` dari GET /dashboard/layout (flag beranda_registry_users).
 * @returns {'lama' | 'registry' | 'memuat'}
 */
export function pilihBeranda(layout, paksa) {
  if (paksa === 'lama') return 'lama';
  if (paksa === 'registry') return layout ? 'registry' : 'memuat';
  return layout?.enabled ? 'registry' : 'lama';
}

export function paksaDariUrl(search) {
  try {
    const v = new URLSearchParams(search || '').get('beranda');
    return v === 'lama' || v === 'registry' ? v : null;
  } catch {
    return null;
  }
}
