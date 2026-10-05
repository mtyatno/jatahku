// Baris "Hari ini" di kartu AI Advisor Dashboard, dari GET /analytics/prediction.
// `free` sudah dipotong belanja hari ini; safe_daily = free ÷ safe_days.
// - daily: sisa bebas harus cukup sampai income besok, jadi baru lewat kalau minus.
// - weekly: lewat kalau belanja hari ini melebihi safe_daily.
// - monthly/irregular (juga respons tanpa income_type): kapan lewat persis seperti main.
// `jatah` = jatah harian yang tampil (Dashboard membulatkan safe_daily ke bawah ke Rp100).
// Selisih "sudah lewat" dihitung dari angka itu supaya cocok dengan rinciannya;
// pemicunya tetap safe_daily asli. Dashboard membulatkan selisihnya ke bawah ke Rp100.
export function todayAdvice(prediction, todaySpent = 0, jatah) {
  const p = prediction || {};
  const safe = p.safe_daily || 0;
  const free = Number(p.free) || 0;
  const funded = (p.total_available ?? p.total_allocated) > 0;
  const daily = p.income_type === 'daily';
  const perIncome = daily || p.income_type === 'weekly';
  const over = daily ? free < 0 : todaySpent > safe;
  return {
    show: !!prediction && funded && (safe > 0 || (daily && over)),
    over,
    overBy: !over ? 0 : daily ? -free : todaySpent - (jatah ?? safe),
    perIncome,
    days: perIncome ? p.safe_days : p.days_left,
  };
}
