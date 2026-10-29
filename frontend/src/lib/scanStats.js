// Rincian Kotak Struk di kartu Admin "Scan Struk" (`GET /admin/receipt-scans/stats`: `by_doc_type`, `unrecognized`,
// `by_issuer`, dihitung server di receipt_scan._kotak_breakdown) — logika murni, diuji dengan node --test; JSX di
// Admin.jsx hanya merender. Server lama tanpa field itu → null: bagiannya tidak dirender.
import { ISSUER_LABEL } from './proofFormat.js';

const DOC_TYPES = [
  ['struk_belanja', 'Struk belanja'],
  ['qris', 'QRIS'],
  ['transfer', 'Transfer'],
  ['tidak_dikenali', 'Tidak dikenali'],
];
const KNOWN_TYPES = new Set(DOC_TYPES.map(([key]) => key));

const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const count = v => (Number.isSafeInteger(v) && v > 0 ? v : 0);
const byName = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

// Jumlah per jenis dokumen, urutan tetap Struk belanja · QRIS · Transfer · Tidak dikenali (kunci yang tidak ada → 0),
// lalu jenis lain yang belum dikenal klien dengan kunci aslinya (urut kunci). `unrecognized` adalah hitungan server
// yang sama dengan `by_doc_type.tidak_dikenali`: angkanya tampil sekali, dari `unrecognized` (cadangan: peta).
// → [{ key, label, count }] atau null tanpa `by_doc_type`.
export function docTypeCounts(stats) {
  const map = stats?.by_doc_type;
  if (!isObj(map)) return null;
  const unrecognized = Number.isSafeInteger(stats.unrecognized) && stats.unrecognized >= 0 ? stats.unrecognized : null;
  const known = DOC_TYPES.map(([key, label]) => ({
    key, label, count: key === 'tidak_dikenali' && unrecognized !== null ? unrecognized : count(map[key]),
  }));
  const extra = Object.keys(map).filter(key => !KNOWN_TYPES.has(key)).sort(byName)
    .map(key => ({ key, label: key, count: count(map[key]) }));
  return [...known, ...extra];
}

// "Struk belanja 12 · QRIS 3 · Transfer 2 · Tidak dikenali 1", atau null tanpa `by_doc_type`.
export function docTypeLine(stats) {
  const rows = docTypeCounts(stats);
  return rows ? rows.map(r => `${r.label} ${r.count}`).join(' · ') : null;
}

// Satu baris per penerbit (`by_issuer`; kunci toko seperti indomaret juga muncul di sini): label ISSUER_LABEL atau
// kunci aslinya, total, tercatat (`recorded`), dikoreksi (`corrected`), dan % dikoreksi = Math.round(100 × dikoreksi /
// tercatat) + "%" ("–" bila belum ada yang tercatat). Urut total terbanyak, lalu label (lalu kunci).
// → [{ key, label, total, recorded, corrected, correctedPct }] atau null tanpa `by_issuer`.
export function issuerRows(stats) {
  const map = stats?.by_issuer;
  if (!isObj(map)) return null;
  return Object.keys(map).map((key) => {
    const v = map[key];
    const total = count(v?.total);
    const recorded = count(v?.recorded);
    const corrected = count(v?.corrected);
    const label = Object.hasOwn(ISSUER_LABEL, key) ? ISSUER_LABEL[key] : key;
    const correctedPct = recorded > 0 ? `${Math.round((100 * corrected) / recorded)}%` : '–';
    return { key, label, total, recorded, corrected, correctedPct };
  }).sort((a, b) => b.total - a.total || a.label.localeCompare(b.label) || byName(a.key, b.key));
}
