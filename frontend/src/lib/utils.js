export function formatCurrency(amount) {
  const val = Math.round(Number(amount));
  return new Intl.NumberFormat('id-ID', {
    style: 'currency', currency: 'IDR',
    minimumFractionDigits: 0, maximumFractionDigits: 0,
  }).format(val);
}

export function formatShort(amount) {
  const val = Math.round(Number(amount));
  if (val >= 1_000_000) {
    const jt = Math.floor(val / 10_000) / 100;
    return jt % 1 === 0 ? `Rp${jt}jt` : `Rp${jt}jt`;
  }
  if (val >= 1_000) {
    const rb = Math.floor(val / 1_000);
    return `Rp${rb}rb`;
  }
  return `Rp${val.toLocaleString('id-ID')}`;
}

export function spentRatio(spent, budget) {
  if (!budget || budget == 0) return 0;
  return Math.min(Number(spent) / Number(budget), 1);
}

export function budgetStatus(spent, budget) {
  const ratio = spentRatio(spent, budget);
  if (ratio >= 0.9) return 'danger';
  if (ratio >= 0.7) return 'warning';
  return 'safe';
}

export function titleCase(str) {
  if (!str) return str;
  return str.replace(/\b\w/g, c => c.toUpperCase());
}

export function daysLeftInMonth() {
  const now = new Date();
  const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  return lastDay - now.getDate();
}
