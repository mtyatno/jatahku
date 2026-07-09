// Helper murni untuk section insight di page Analytics.
// Semua input tanggal berupa string ISO 'YYYY-MM-DD' (dari backend).

const DAY_NAMES = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu'];

function parseISO(s) {
  const [y, m, d] = String(s).slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
}

function mondayIndex(d) {
  return (d.getDay() + 6) % 7; // Sen=0 .. Min=6
}

// Grid heatmap minggu x hari. Return { weeks: [[cell|null x7]], max }.
// cell = { date, total, level } — level 0 (nol) s/d 4 (mendekati max);
// null = hari di luar periode (padding awal/akhir).
export function buildWeekHeatmap(daily, periodStart, periodEnd) {
  const byDate = {};
  for (const d of daily || []) byDate[String(d.date).slice(0, 10)] = Number(d.total) || 0;
  const max = Math.max(0, ...Object.values(byDate));

  const level = (total) => {
    if (total <= 0 || max <= 0) return 0;
    const r = total / max;
    return r <= 0.25 ? 1 : r <= 0.5 ? 2 : r <= 0.75 ? 3 : 4;
  };

  const start = parseISO(periodStart);
  const end = parseISO(periodEnd);
  const weeks = [];
  let week = new Array(mondayIndex(start)).fill(null); // padding sebelum periode
  for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const total = byDate[iso] || 0;
    week.push({ date: iso, total, level: level(total) });
    if (week.length === 7) { weeks.push(week); week = []; }
  }
  if (week.length > 0) {
    while (week.length < 7) week.push(null); // padding setelah periode
    weeks.push(week);
  }
  return { weeks, max };
}

// Perbandingan spent per amplop vs periode sebelumnya.
// current/previous: [{ name, emoji, spent }] (bentuk /analytics/envelope-breakdown).
// Return { up, down } — item { name, emoji, prev, cur, pct };
// pct null = amplop baru (prev 0); yang tak berubah di-drop.
// up: baru dulu, lalu pct desc. down: pct paling minus dulu.
export function categoryDelta(current, previous) {
  const prevBy = {};
  for (const p of previous || []) prevBy[p.name] = Number(p.spent) || 0;
  const up = [];
  const down = [];
  for (const c of current || []) {
    const cur = Number(c.spent) || 0;
    const prev = prevBy[c.name] || 0;
    if (cur === prev) continue;
    const pct = prev > 0 ? Math.round(((cur - prev) / prev) * 100) : null;
    const item = { name: c.name, emoji: c.emoji, prev, cur, pct };
    if (cur > prev) up.push(item);
    else down.push(item);
  }
  up.sort((a, b) => (b.pct ?? Infinity) - (a.pct ?? Infinity));
  down.sort((a, b) => (a.pct ?? 0) - (b.pct ?? 0));
  return { up, down };
}

// Hari (nama Indonesia) dengan akumulasi pengeluaran terbesar. null bila kosong.
export function busiestWeekday(daily) {
  if (!daily || daily.length === 0) return null;
  const totals = new Array(7).fill(0);
  for (const d of daily) totals[mondayIndex(parseISO(d.date))] += Number(d.total) || 0;
  let maxIdx = 0;
  for (let i = 1; i < 7; i++) if (totals[i] > totals[maxIdx]) maxIdx = i;
  if (totals[maxIdx] <= 0) return null;
  return { day: DAY_NAMES[maxIdx], total: totals[maxIdx] };
}
