// Grafik mini kartu KPI Dashboard, hanya dari data yang sudah dimuat halaman.
import { fundingState } from './envelopeFunding.js';

const isSaving = (env) => env.purpose === 'saving' || env.purpose === 'sinking_fund';

export const STATUS_ORDER = ['over', 'low', 'ok', 'saving', 'empty'];

// Mengikuti warna bar amplop di Dashboard: merah habis, kuning hampir habis/kurang tagihan.
export function envelopeStatus(env) {
  if (isSaving(env)) return 'saving';
  if (fundingState(env) === 'overspent') return 'over';
  if (fundingState(env) === 'reserve_short' || Number(env.spent_ratio || 0) >= 0.7) return 'low';
  if (Number(env.allocated || 0) <= 0 && Number(env.rollover || 0) === 0) return 'empty';
  return 'ok';
}

export function envelopeStrip(envelopes) {
  return envelopes
    .map((e) => ({ id: e.id, name: e.name, status: envelopeStatus(e) }))
    .sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status));
}

// Jumlah keempatnya = alokasi + rollover, kecuali kalau total sisa bebas minus.
export function fundsBreakdown(envelopes) {
  let spent = 0;
  let reserved = 0;
  let saving = 0;
  let free = 0;
  envelopes.forEach((e) => {
    spent += Number(e.spent || 0);
    reserved += Number(e.reserved || 0);
    const f = Number(e.free ?? e.remaining ?? 0);
    if (isSaving(e)) saving += Math.max(f, 0);
    else free += f;
  });
  return { spent, reserved, saving, free: Math.max(free, 0) };
}

export function freeShare(envelopes) {
  const spendable = envelopes.filter((e) => !isSaving(e));
  const total = spendable.reduce((s, e) => s + Number(e.allocated || 0) + Number(e.rollover || 0), 0);
  if (total <= 0) return null;
  const free = spendable.reduce((s, e) => s + Number(e.free ?? e.remaining ?? 0), 0);
  return Math.min(Math.max(free / total, 0), 1);
}

// Target yang sudah tercapai tidak menutupi kekurangan target lain.
export function savingsProgress(goals, envelopes, personal) {
  const ids = new Set(envelopes.filter((e) => isSaving(e) && !!e.is_personal === personal).map((e) => e.id));
  const mine = goals.filter((g) => ids.has(g.envelope_id));
  const target = mine.reduce((s, g) => s + Number(g.target_amount || 0), 0);
  if (target <= 0) return null;
  const filled = mine.reduce((s, g) => s + Math.min(Math.max(Number(g.current_balance || 0), 0), Number(g.target_amount || 0)), 0);
  return filled / target;
}

export function localDateStr(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// Hari setelah `today` bernilai null: belum terjadi, bukan nol.
export function dailySeries(raw, periodStart, periodEnd, today) {
  if (!periodStart || !periodEnd) return [];
  const byDate = {};
  (raw || []).forEach((d) => { byDate[d.date] = Number(d.total) || 0; });
  const out = [];
  const cur = new Date(`${periodStart}T00:00:00Z`);
  const end = new Date(`${periodEnd}T00:00:00Z`);
  while (cur <= end && out.length < 62) {
    const date = cur.toISOString().slice(0, 10);
    out.push({ date, total: date <= today ? (byDate[date] || 0) : null });
    cur.setUTCDate(cur.getUTCDate() + 1);
  }
  return out;
}

// Fritsch–Carlson: halus tanpa melampaui data, jadi puncak garis = belanja tertinggi.
export function monotonePath(points) {
  const n = points.length;
  if (n === 0) return '';
  const f = (v) => Math.round(v * 100) / 100;
  if (n === 1) return `M${f(points[0][0])},${f(points[0][1])}`;
  const d = [];
  for (let i = 0; i < n - 1; i++) {
    d.push((points[i + 1][1] - points[i][1]) / (points[i + 1][0] - points[i][0]));
  }
  const m = new Array(n);
  m[0] = d[0];
  m[n - 1] = d[n - 2];
  for (let i = 1; i < n - 1; i++) m[i] = d[i - 1] * d[i] > 0 ? (d[i - 1] + d[i]) / 2 : 0;
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) { m[i] = 0; m[i + 1] = 0; continue; }
    const a = m[i] / d[i];
    const b = m[i + 1] / d[i];
    const h = a * a + b * b;
    if (h > 9) {
      const t = 3 / Math.sqrt(h);
      m[i] = t * a * d[i];
      m[i + 1] = t * b * d[i];
    }
  }
  let path = `M${f(points[0][0])},${f(points[0][1])}`;
  for (let i = 0; i < n - 1; i++) {
    const [x0, y0] = points[i];
    const [x1, y1] = points[i + 1];
    const dx = (x1 - x0) / 3;
    path += `C${f(x0 + dx)},${f(y0 + m[i] * dx)} ${f(x1 - dx)},${f(y1 - m[i + 1] * dx)} ${f(x1)},${f(y1)}`;
  }
  return path;
}
