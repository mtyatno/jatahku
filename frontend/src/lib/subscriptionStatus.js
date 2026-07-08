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

export function sortForPayment(items) {
  return [...(items || [])].sort((a, b) => (RANK[a.status] ?? 9) - (RANK[b.status] ?? 9));
}

export function statusMeta(status) {
  return META[status] || META.upcoming;
}
