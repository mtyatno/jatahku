// Pure helpers for envelope purpose/classification UX (Plan C2 §8.1).
// classification ("needs"/"wants") is only meaningful for expense & debt.

export const PURPOSE_OPTIONS = [
  { key: 'expense', icon: 'expense', desc: 'Pengeluaran rutin' },
  { key: 'debt', icon: 'card', desc: 'Cicilan/Utang' },
  { key: 'saving', icon: 'target', desc: 'Target menabung' },
  { key: 'sinking_fund', icon: 'calendar', desc: 'Dana persiapan' },
];

export function needsClassification(purpose) {
  return purpose === 'expense' || purpose === 'debt';
}

const NEEDS_KW = [
  'listrik', 'air', 'pln', 'pdam', 'sembako', 'makan', 'makanan', 'dapur',
  'sewa', 'kontrakan', 'kos', 'transport', 'bensin', 'pulsa', 'internet',
  'sekolah', 'kuliah', 'spp', 'kesehatan', 'obat', 'bpjs', 'cicilan', 'utang',
  'kredit', 'angsuran', 'pajak', 'gas', 'tagihan',
];
const WANTS_KW = [
  'kopi', 'jajan', 'game', 'hiburan', 'nonton', 'netflix', 'spotify',
  'langganan', 'streaming', 'liburan', 'shopping', 'belanja online', 'gadget',
  'skincare', 'hobi', 'rokok', 'nongkrong', 'cafe', 'kafe', 'boba',
];

export function suggestClassification(name) {
  const n = String(name || '').toLowerCase();
  if (!n) return null;
  if (NEEDS_KW.some(kw => n.includes(kw))) return 'needs';
  if (WANTS_KW.some(kw => n.includes(kw))) return 'wants';
  return null;
}
