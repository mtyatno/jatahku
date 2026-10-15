// Data untuk grafik "Pengeluaran harian", card "Perlu perhatian", dan "Ke mana uangmu periode ini" di Beranda.
// Murni (tanpa React), supaya bisa dites dengan node --test.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des'];

// 'YYYY-MM-DD' → Date lokal (tanpa geser zona waktu).
export function parseDay(s) {
  const [y, m, d] = String(s).slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function dayStr(date) {
  const p = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
}

export function dayMonth(s) {
  const d = parseDay(s);
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

// Satu baris per hari dalam periode. status: 'future' (belum terjadi), 'empty' (tanpa belanja),
// 'ok' (≤ batas aman), 'over' (> batas aman). Tanpa batas aman (periode lampau), semua belanja 'ok'.
export function buildDailySeries(raw, periodStart, periodEnd, today, safeDaily = 0) {
  const byDay = {};
  (raw || []).forEach(r => { byDay[String(r.date).slice(0, 10)] = Number(r.total) || 0; });
  if (!periodStart || !periodEnd) {
    return (raw || []).map(r => {
      const total = Number(r.total) || 0;
      return { day: String(r.date).slice(0, 10), total, status: total > 0 ? 'ok' : 'empty', isToday: false };
    });
  }
  const out = [];
  const end = parseDay(periodEnd);
  for (let d = parseDay(periodStart); d <= end; d.setDate(d.getDate() + 1)) {
    const s = dayStr(d);
    const total = byDay[s] || 0;
    let status;
    if (s > today) status = 'future';
    else if (total <= 0) status = 'empty';
    else status = safeDaily > 0 && total > safeDaily ? 'over' : 'ok';
    out.push({ day: s, total, status, isToday: s === today });
  }
  return out;
}

// Label sumbu-x: awal periode, tanggal 1 tiap bulan, lalu kelipatan 7 dari tanggal 1 (8, 15, 22, 29),
// dan akhir periode. Label yang terlalu dekat (< 3 hari) dengan awal/akhir dibuang.
export function dailyTicks(series) {
  if (!series.length) return [];
  const first = series[0].day;
  const last = series[series.length - 1].day;
  const idx = (s) => series.findIndex(r => r.day === s);
  const picks = new Set([first, last]);
  series.forEach(r => {
    const dom = parseDay(r.day).getDate();
    if (dom === 1 || (dom - 1) % 7 === 0) picks.add(r.day);
  });
  const lastIdx = series.length - 1;
  return [...picks]
    .filter(s => s === first || s === last || (idx(s) >= 3 && lastIdx - idx(s) >= 3))
    .sort();
}

export function tickLabel(s, series) {
  const d = parseDay(s);
  if (s === series[0]?.day || d.getDate() === 1) return dayMonth(s);
  return String(d.getDate());
}

// Garis bantu sumbu-y: 0, langkah, 2×langkah — langkah dibulatkan ke 1/2/2,5/5 × 10^n.
export function niceStep(max) {
  if (!(max > 0)) return 100_000;
  const raw = max / 2;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const f = raw / pow;
  const m = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return m * pow;
}

export function axisLabel(v) {
  if (v >= 1_000_000) return `${(v / 1_000_000).toLocaleString('id-ID', { maximumFractionDigits: 1 })}jt`;
  if (v >= 1_000) return `${Math.round(v / 1_000)}rb`;
  return String(v);
}

// Transfer internal (Income bernilai 0 berdeskripsi "Transfer: A → B", alokasi −/+) → per amplop tujuan:
// { count, amount, sources: { namaSumber: jumlah } }. Kunci = nama amplop (respons /incomes/ tidak memuat id).
export function transfersInto(incomes) {
  const out = {};
  (incomes || []).forEach(inc => {
    if (Number(inc.amount) !== 0 || !/^Transfer:/i.test(inc.source || '')) return;
    const allocs = inc.allocations || [];
    const from = allocs.find(a => Number(a.amount) < 0)?.envelope;
    allocs.filter(a => Number(a.amount) > 0).forEach(a => {
      const t = (out[a.envelope] = out[a.envelope] || { count: 0, amount: 0, sources: {} });
      t.count += 1;
      t.amount += Number(a.amount);
      if (from) t.sources[from] = (t.sources[from] || 0) + Number(a.amount);
    });
  });
  return out;
}

const fmtRp = (v) => `Rp${Math.round(Math.abs(Number(v) || 0)).toLocaleString('id-ID')}`;

const stripBayar = (desc) => (desc || '').replace(/^bayar\s+/i, '').trim() || desc;

const isSaving = (e) => e.purpose === 'saving' || e.purpose === 'sinking_fund';

// Daftar "Perlu perhatian", urut: tagihan telat → income belum dicatat → amplop minus/habis → peringatan advisor.
// Item: { id, tone: 'danger'|'warning', title, detail, action: { label, kind, value }, primary, envelopeName }.
export function attentionItems({ subscriptions, envelopes, income, isCurrentPeriod, advisorCards, transfers, today }) {
  if (!isCurrentPeriod) return [];
  const items = [];
  const envById = Object.fromEntries((envelopes || []).map(e => [String(e.id), e]));
  const flaggedEnv = new Set();

  (subscriptions || [])
    .filter(s => s.is_active !== false && s.status === 'overdue')
    .sort((a, b) => (a.next_run || '').localeCompare(b.next_run || ''))
    .forEach(s => {
      const env = envById[String(s.envelope_id)];
      const late = Math.max(0, Math.round((parseDay(today) - parseDay(s.next_run)) / 86_400_000));
      const remaining = env ? Number(env.allocated || 0) + Number(env.rollover || 0) - Number(env.spent || 0) : 0;
      const envName = env?.name || s.envelope_name;
      if (env) flaggedEnv.add(String(env.id));
      items.push({
        id: `sub:${s.id}`, tone: 'danger',
        title: late > 0 ? `${stripBayar(s.description)} telat ${late} hari` : `${stripBayar(s.description)} jatuh tempo hari ini`,
        detail: [fmtRp(s.amount), envName && `amplop ${envName}${remaining < 0 ? ' minus' : ''}`].filter(Boolean).join(' · '),
        action: { label: 'Bayar', kind: 'open', value: 'langganan' }, primary: true,
      });
    });

  if (!(Number(income) > 0)) {
    items.push({
      id: 'income', tone: 'warning', title: 'Income belum dicatat', detail: 'Periode ini masih Rp0',
      action: { label: 'Catat', kind: 'open', value: 'income' },
    });
  }

  (envelopes || [])
    .filter(e => !isSaving(e) && !flaggedEnv.has(String(e.id)))
    .map(e => {
      const jatah = Number(e.allocated || 0) + Number(e.rollover || 0);
      const spent = Number(e.spent || 0);
      return { e, jatah, spent, remaining: jatah - spent, free: Number(e.free ?? e.remaining ?? 0) };
    })
    .filter(x => (x.jatah > 0 || x.spent > 0) && (x.remaining < 0 || x.free <= 0))
    .sort((a, b) => a.remaining - b.remaining || b.spent - a.spent)
    .forEach(({ e, jatah, spent, remaining }) => {
      flaggedEnv.add(String(e.id));
      const t = transfers?.[e.name];
      const sources = t ? Object.entries(t.sources).sort((a, b) => b[1] - a[1]).map(([n]) => n) : [];
      const from = sources.length > 1 ? `${sources[0]} & ${sources.length - 1} amplop lain` : sources[0];
      items.push({
        id: `env:${e.id}`, tone: 'danger', envelopeName: e.name,
        title: remaining < 0
          ? `${e.name} minus ${fmtRp(remaining)}${t ? `, ditambal ${t.count}×` : ''}`
          : `${e.name} habis${t ? `, ditambal ${t.count}×` : ''}`,
        detail: t ? `${fmtRp(t.amount)} dari ${from}` : `Terpakai ${fmtRp(spent)} dari jatah ${fmtRp(jatah)}`,
        action: { label: 'Atur', kind: 'route', value: '/allocate' },
      });
    });

  (advisorCards || [])
    .filter(c => ['env_depletion', 'subscription_pressure'].includes(c.type) && ['danger', 'warning'].includes(c.severity))
    .forEach(c => {
      const envId = String(c.id || '').split(':')[1];
      if (envId && flaggedEnv.has(envId)) return;
      if (envId) flaggedEnv.add(envId);
      items.push({
        id: `advisor:${c.id}`, tone: c.severity,
        title: String(c.title || '').replace(/^\p{Extended_Pictographic}️?\s*/u, ''),
        detail: c.evidence?.[0] || c.body || '',
        action: { label: 'Atur', kind: 'route', value: c.primary_action?.route || '/allocate' },
        envelopeName: envById[envId]?.name,
      });
    });

  return items;
}

// Ringkasan item yang tidak muat di card (lebih dari `shown`).
export function attentionOverflow(items, shown = 3) {
  const rest = items.slice(shown);
  if (!rest.length) return null;
  const habis = rest.filter(i => i.id.startsWith('env:'));
  if (habis.length === rest.length) {
    const names = habis.map(i => i.envelopeName);
    const list = names.length > 2 ? `${names.slice(0, -1).join(', ')} & ${names[names.length - 1]}` : names.join(' & ');
    return `${list} juga sudah habis`;
  }
  return `+${rest.length} hal lain perlu dicek`;
}

// Segmen "Ke mana uangmu": 3 amplop terbesar + "Lainnya (N amplop)".
export function breakdownSegments(breakdown, top = 3) {
  const rows = (breakdown || []).filter(b => Number(b.spent) > 0).sort((a, b) => Number(b.spent) - Number(a.spent));
  const total = rows.reduce((s, b) => s + Number(b.spent), 0);
  if (!total) return { total: 0, segments: [] };
  const head = rows.slice(0, rows.length === top + 1 ? top + 1 : top);
  const tail = rows.slice(head.length);
  const segments = head.map(b => ({ key: b.name, name: b.name, amount: Number(b.spent) }));
  if (tail.length) {
    segments.push({ key: '__other__', name: `Lainnya (${tail.length} amplop)`, amount: tail.reduce((s, b) => s + Number(b.spent), 0), other: true });
  }
  return { total, segments: segments.map(s => ({ ...s, share: s.amount / total })) };
}
