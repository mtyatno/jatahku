// Pengolahan status langganan untuk UI Bayar Langganan (status berasal dari backend).
const RANK = { overdue: 0, due: 1, upcoming: 2, paid: 3 };
const META = {
  overdue: { label: 'Jatuh tempo', tone: 'danger' },
  due: { label: 'Belum bayar', tone: 'warning' },
  paid: { label: 'Sudah bayar', tone: 'safe' },
  upcoming: { label: 'Belum jatuh tempo', tone: 'neutral' },
};

export function unpaidMonthlyTotal(items) {
  return (items || []).reduce(
    (s, i) => (i.frequency === 'monthly' && i.status !== 'paid' ? s + Number(i.amount || 0) : s),
    0,
  );
}

export function monthlyEquivalentTotal(items) {
  // Estimasi setara-bulanan semua langganan — rumus sama dengan reserved backend
  // (weekly *52/12, yearly /12), bukan weekly *4.
  return (items || []).reduce((s, i) => {
    const amt = Number(i.amount || 0);
    if (i.frequency === 'weekly') return s + (amt * 52) / 12;
    if (i.frequency === 'yearly') return s + amt / 12;
    return s + amt;
  }, 0);
}

export function paidMonthlyTotal(items) {
  return (items || []).reduce(
    (s, i) => (i.frequency === 'monthly' && i.status === 'paid' ? s + Number(i.amount || 0) : s),
    0,
  );
}

export function nearestDue(items) {
  // Item belum dibayar dengan next_run terdekat (ISO date string — aman dibanding leksikal).
  const unpaid = (items || []).filter(i => i.status !== 'paid' && i.next_run);
  if (!unpaid.length) return null;
  return unpaid.reduce((a, b) => (a.next_run <= b.next_run ? a : b));
}

export function sortForPayment(items) {
  return [...(items || [])].sort((a, b) => (RANK[a.status] ?? 9) - (RANK[b.status] ?? 9));
}

export function statusMeta(status) {
  return META[status] || META.upcoming;
}

export function searchSubscriptions(items, q) {
  const s = (q || '').trim().toLowerCase();
  if (!s) return items || [];
  return (items || []).filter(i =>
    (i.description || '').toLowerCase().includes(s) ||
    (i.envelope_name || '').toLowerCase().includes(s),
  );
}

export function sortSubscriptions(items, mode) {
  const arr = [...(items || [])];
  if (mode === 'expensive') return arr.sort((a, b) => Number(b.amount) - Number(a.amount));
  if (mode === 'cheap') return arr.sort((a, b) => Number(a.amount) - Number(b.amount));
  if (mode === 'due') return arr.sort((a, b) => (a.next_run || '').localeCompare(b.next_run || ''));
  if (mode === 'name') return arr.sort((a, b) => (a.description || '').localeCompare(b.description || '', 'id'));
  return sortForPayment(arr); // 'priority' (default)
}
