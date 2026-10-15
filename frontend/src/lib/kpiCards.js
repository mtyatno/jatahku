// Angka dan teks kartu KPI Dashboard. Uang yang dihitung aplikasi dibulatkan ke bawah ke Rp100.

export const floorRp100 = (v) => Math.floor((Number(v) || 0) / 100) * 100;

const id = (v, digits = 0) => v.toLocaleString('id-ID', { maximumFractionDigits: digits });

// 297.100 → Rp297.100
export function rpFull(amount) {
  const v = floorRp100(Math.abs(Number(amount) || 0));
  return `${Number(amount) < 0 ? '–' : ''}Rp${id(v)}`;
}

// 1.684.000 → Rp1,68 jt · 490.000 → Rp490 rb · 800 → Rp800
export function rpCompact(amount) {
  const n = Number(amount) || 0;
  const v = Math.abs(n);
  const sign = n < 0 ? '–' : '';
  if (v >= 1_000_000) return `${sign}Rp${id(Math.floor(v / 10_000) / 100, 2)} jt`;
  if (v >= 1_000) return `${sign}Rp${id(Math.floor(v / 1_000))} rb`;
  return `${sign}Rp${id(floorRp100(v))}`;
}

// Bar penuh = yang lebih besar dari belanja hari ini dan batas aman; garis putih = batas aman saat lewat.
export function dailyMeter(todaySpent, safeDaily) {
  const spent = Math.max(Number(todaySpent) || 0, 0);
  const safe = floorRp100(safeDaily);
  if (safe <= 0) return { fill: spent > 0 ? 1 : 0, marker: null, over: false, overBy: 0 };
  const over = spent > safe;
  const scale = Math.max(spent, safe);
  return {
    fill: spent / scale,
    marker: over ? safe / scale : null,
    over,
    overBy: over ? floorRp100(spent - safe) : 0,
  };
}

// Aturan Bapak: prediksi akhir periode di atas alokasi + rollover.
export function predictionOver(prediction) {
  if (!prediction) return false;
  return Number(prediction.predicted_total) > Number(prediction.total_available);
}

export function daysLabel(prediction) {
  if (!prediction) return '';
  return `untuk ${prediction.safe_days} hari`;
}

export function periodDayLabel(prediction) {
  if (!prediction) return '';
  const total = Number(prediction.days_passed) + Number(prediction.days_left);
  return `Hari ke-${prediction.days_passed} dari ${total}`;
}

export function periodProgress(prediction) {
  if (!prediction) return 0;
  const total = Number(prediction.days_passed) + Number(prediction.days_left);
  return total > 0 ? Number(prediction.days_passed) / total : 0;
}

export function savingRateLabel(prediction) {
  return `saving rate ${Math.round(Number(prediction?.saving_rate) || 0)}%`;
}

export function cashFlowLabel(prediction) {
  if (!prediction || prediction.predicted_cash_flow == null) return '';
  return `Arus kas diprediksi ${rpCompact(prediction.predicted_cash_flow)} di akhir periode`;
}

export function billsProgress(stats) {
  const paid = Math.max(Number(stats?.amount_paid) || 0, 0);
  const due = Math.max(Number(stats?.amount_due) || 0, 0);
  const total = paid + due;
  return { paid, due, total, fill: total > 0 ? paid / total : 0 };
}
