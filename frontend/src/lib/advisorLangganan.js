// Halaman Langganan AI Advisor (S12): pembantu murni di atas GET /advisor/page/langganan
// (04-kontrak-api.md). Pilihan insight per baris, teks, dan CTA sudah dari server
// (halaman.py, render.py); di sini hanya memilih yang tampil dan memetakan CTA yang
// menuju halaman ini sendiri ke aksi lokal (aturan kerja #2 & #4).

export const pageEnabled = (page) => !!page?.enabled;

// Insight strip untuk satu baris langganan, tanpa yang baru saja disembunyikan.
export function rowInsight(page, recurringId, hidden = []) {
  const ins = page?.per_langganan?.[recurringId];
  if (!ins || hidden.includes(ins.dismiss?.kunci || ins.id)) return null;
  return ins;
}

// CTA `route` ke /langganan tidak berguna di halaman ini: untuk baris (TAG-04 Atur sisihan,
// TAG-06 Perbarui nominal) → buka form edit langganan itu; untuk ringkasan (TAG-05 Tinjau
// langganan) → urutkan termahal; untuk TAG-08 (Lihat keduanya) → saring ke baris-barisnya.
const isSelfRoute = (aksi) => aksi?.kind === 'route'
  && typeof aksi.payload?.path === 'string' && aksi.payload.path.split('?')[0].replace(/\/+$/, '') === '/langganan';

export function localAction(aksi, ctx = {}) {
  if (!isSelfRoute(aksi)) return null;
  if (ctx.recurringId) return { type: 'edit', recurringId: ctx.recurringId };
  if (Array.isArray(ctx.recurringIds) && ctx.recurringIds.length) return { type: 'focus', recurringIds: ctx.recurringIds };
  return { type: 'sort', mode: 'expensive' };
}

// Ringkasan beban tagihan (K4): angka sudah dihitung server; null bila belum ada dana belanja.
export function summaryLine(ringkasan, fmt) {
  if (!ringkasan || ringkasan.beban_bulanan == null) return null;
  const pct = ringkasan.beban_persen;
  return pct == null
    ? `Tagihan rutin ${fmt(ringkasan.beban_bulanan)}/bulan`
    : `Tagihan rutin ${fmt(ringkasan.beban_bulanan)}/bulan · ${pct}% dari dana belanja`;
}

// Saring daftar langganan ke id tertentu (TAG-08 "Lihat keduanya"); kosong → semua.
export function focusItems(items, ids) {
  if (!Array.isArray(ids) || !ids.length) return items;
  const set = new Set(ids.map(String));
  return (items || []).filter(i => set.has(String(i.id)));
}
