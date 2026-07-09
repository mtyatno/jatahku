import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';
import { Icon, EnvelopeIcon } from '../components/Icon';
import ExportButtons from '../components/ExportButtons';
import { useTheme } from '../hooks/useTheme';
import { buildWeekHeatmap, categoryDelta, busiestWeekday } from '../lib/analyticsInsight';
import { monthlyEquivalentTotal, unpaidMonthlyTotal } from '../lib/subscriptionStatus';
import { fundingState } from '../lib/envelopeFunding';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, AreaChart, Area, CartesianGrid, ReferenceLine,
} from 'recharts';

const COLORS = ['#0F6E56', '#BA7517', '#1D9E75', '#D85A30', '#534AB7', '#993556', '#378ADD', '#639922'];
const DAY_HEADS = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min'];

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 shadow-sm">
      <p className="text-xs text-gray-400 mb-1">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-sm font-semibold" style={{color: p.color}}>
          {p.name}: {formatCurrency(p.value)}
        </p>
      ))}
    </div>
  );
}

function SinkingFundAdvisor({ data }) {
  const recommendations = data?.recommendations || [];
  if (recommendations.length === 0) return null;
  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <h3 className="font-semibold text-sm">Sinking fund advisor</h3>
          <p className="text-xs text-gray-400 mt-1">
            Reserve baru {formatShort(data.summary?.new_reserve_needed || 0)} · {recommendations.length} rekomendasi
          </p>
        </div>
        <span className="text-xs px-2 py-1 rounded-lg bg-brand-50 text-brand-600 font-semibold">
          {data.summary?.high_confidence_count || 0} high confidence
        </span>
      </div>
      <div className="space-y-3">
        {recommendations.slice(0, 5).map(item => (
          <div key={item.id} className="rounded-xl border border-gray-100 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold truncate">{item.title}</p>
                <p className="text-xs text-gray-500 mt-1">{item.envelope_name} · {item.frequency} · {item.confidence}</p>
              </div>
              <div className="text-right flex-shrink-0">
                <p className="font-display font-bold text-brand-600">{formatShort(item.monthly_reserve)}</p>
                <p className="text-xs text-gray-400">/periode</p>
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-2">{item.description}</p>
            {item.evidence?.length > 0 && (
              <div className="mt-2 pt-2 border-t border-gray-100 space-y-1">
                {item.evidence.map((evidence, idx) => (
                  <p key={idx} className="text-xs text-gray-500">{evidence}</p>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function MiniStat({ icon, color, value, label, sub }) {
  return (
    <div className="rounded-xl border border-gray-100 p-3 flex items-start gap-2.5">
      <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: `${color}18` }}>
        <Icon name={icon} size={16} color={color} />
      </div>
      <div className="min-w-0">
        <p className="font-display font-bold leading-tight">{value}</p>
        <p className="text-xs text-gray-500">{label}</p>
        {sub && <p className="text-[11px] text-gray-400 mt-0.5 truncate">{sub}</p>}
      </div>
    </div>
  );
}

function DeltaRow({ item, dir }) {
  const up = dir === 'up';
  return (
    <div className="flex items-center gap-2 text-sm py-1">
      <EnvelopeIcon value={item.emoji} size={18} />
      <div className="min-w-0 flex-1">
        <p className="truncate">{item.name}</p>
        <p className="text-[11px] text-gray-400 font-mono">{formatShort(item.prev)} → {formatShort(item.cur)}</p>
      </div>
      <span className={`text-xs font-semibold flex-shrink-0 ${up ? 'text-danger-400' : 'text-brand-600'}`}>
        {item.pct === null ? 'baru' : `${up ? '↑' : '↓'} ${Math.abs(item.pct)}%`}
      </span>
    </div>
  );
}

export default function Analytics() {
  const { mode } = useTheme();
  const isDark = mode === 'dark';
  const [periods, setPeriods] = useState([]);
  const [periodIdx, setPeriodIdx] = useState(null);
  const [d, setD] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getPeriods(12).then(p => { setPeriods(p); setPeriodIdx(p.length > 0 ? p.length - 1 : -1); });
  }, []);

  useEffect(() => {
    if (periodIdx === null || periods.length === 0) { if (periodIdx === -1) setLoading(false); return; }
    const cur = periods[periodIdx];
    const prev = periodIdx > 0 ? periods[periodIdx - 1] : null;
    const ps = cur.period_start, pe = cur.period_end;
    const safeJson = (path) => api.request(path).then(r => (r.ok ? r.json() : null)).catch(() => null);
    setLoading(true);
    Promise.all([
      api.getDailySpending(ps, pe),
      api.getEnvelopeBreakdown(ps, pe),
      prev ? api.getEnvelopeBreakdown(prev.period_start, prev.period_end) : Promise.resolve([]),
      safeJson('/analytics/monthly-trend'),
      safeJson(`/analytics/prediction?period_start=${ps}&period_end=${pe}`),
      api.getAllocationSummary(ps, pe),
      api.getSinkingFundAdvice(),
      api.getRecurring(),
      api.getTransactions(null, 500, ps, pe),
      api.getEnvelopeSummary(),
    ]).then(([daily, breakdown, prevBreakdown, trend, prediction, alloc, sinking, recurring, txns, envelopes]) => {
      setD({
        daily: Array.isArray(daily) ? daily : [],
        breakdown: (Array.isArray(breakdown) ? breakdown : []).filter(x => x.spent > 0),
        prevBreakdown: (Array.isArray(prevBreakdown) ? prevBreakdown : []).filter(x => x.spent > 0),
        trend: Array.isArray(trend) ? trend : [],
        prediction, alloc,
        sinking,
        recurring: Array.isArray(recurring) ? recurring : [],
        txns: Array.isArray(txns) ? txns : [],
        envelopes: Array.isArray(envelopes) ? envelopes : [],
      });
      setLoading(false);
    });
  }, [periodIdx, periods]);

  if (loading || !d) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  const cur = periods[periodIdx] || {};
  const isCurrentPeriod = periodIdx >= periods.length - 1;
  const { daily, breakdown, prevBreakdown, trend, prediction, alloc, sinking, recurring, txns, envelopes } = d;

  // Derived (client-side, pure helpers)
  const dailyChart = daily.map(x => ({ ...x, date: new Date(x.date).getDate() + '' }));
  const heat = buildWeekHeatmap(daily, cur.period_start, cur.period_end);
  const delta = categoryDelta(breakdown, prevBreakdown);
  const boros = busiestWeekday(daily);
  const envById = Object.fromEntries(envelopes.map(e => [e.id, e]));
  const topTxns = [...txns].filter(t => !t.is_deleted)
    .sort((a, b) => Number(b.amount) - Number(a.amount)).slice(0, 5);
  const p = prediction || {};
  const hasPred = p.total_allocated > 0;
  const spentPct = hasPred ? Math.min(Math.round((p.total_spent / p.total_allocated) * 100), 100) : 0;
  const cashflow = hasPred ? p.total_allocated - p.predicted_total : null;
  const perhatian = envelopes.filter(e => (e.purpose || 'expense') === 'expense' && fundingState(e) !== 'ok').length;
  const subsTotal = monthlyEquivalentTotal(recurring);
  const subsUnpaid = unpaidMonthlyTotal(recurring);
  const unpaidCount = recurring.filter(i => i.frequency === 'monthly' && i.status !== 'paid').length;
  const sinkCount = sinking?.recommendations?.length || 0;
  const savingDelta = alloc?.saving_pct_prev != null ? alloc.saving_pct - alloc.saving_pct_prev : null;
  const HEAT_COLORS = isDark
    ? ['#1e293b', '#14532d', '#a16207', '#c2410c', '#dc2626']
    : ['#F1F5F9', '#BBE3D3', '#FDE68A', '#FDBA74', '#EF6A6A'];

  const insights = [];
  if (boros) insights.push({ icon: '📅', text: <>Hari paling boros: <b>{boros.day}</b> (total {formatShort(boros.total)})</> });
  if (p.daily_avg > 0) insights.push({ icon: '💸', text: <>Rata-rata pengeluaran <b>{formatCurrency(p.daily_avg)}/hari</b>{p.safe_daily > 0 && <> — batas aman {formatCurrency(p.safe_daily)}/hari</>}</> });
  if (delta.up[0]) insights.push({ icon: '📈', text: <><b>{delta.up[0].name}</b> {delta.up[0].pct === null ? 'baru muncul periode ini' : <>naik <b className="text-danger-400">{delta.up[0].pct}%</b> dibanding periode lalu</>}</> });
  if (delta.down[0]) insights.push({ icon: '📉', text: <><b>{delta.down[0].name}</b> turun <b className="text-brand-600">{Math.abs(delta.down[0].pct)}%</b> dibanding periode lalu</> });

  return (
    <div className="space-y-6">
      {/* ── Header: judul + period selector + export ── */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-display font-bold">Analytics</h1>
          <div className="flex items-center gap-1 mt-0.5">
            <button onClick={() => setPeriodIdx(i => i - 1)} disabled={periodIdx === 0}
              className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-500 text-sm">←</button>
            <span className="text-sm text-gray-500">{cur.label || '...'}</span>
            {isCurrentPeriod && <span className="text-xs px-1.5 py-0.5 bg-brand-50 text-brand-600 rounded font-medium">Sekarang</span>}
            <button onClick={() => setPeriodIdx(i => i + 1)} disabled={isCurrentPeriod}
              className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-500 text-sm">→</button>
          </div>
          <p className="text-sm text-gray-500 mt-0.5">Memahami pola keuanganmu</p>
        </div>
        <ExportButtons />
      </div>

      {/* ── Financial Health ── */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div className="card">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-gray-400">Prediksi akhir bulan</p>
            {hasPred && (
              <span className={`text-[11px] px-2 py-0.5 rounded-full font-semibold ${p.on_track ? 'bg-brand-50 text-brand-600' : 'bg-red-50 text-danger-400'}`}>
                {p.on_track ? 'On Track' : 'Overspend'}
              </span>
            )}
          </div>
          <p className="font-display text-2xl font-bold">{formatShort(p.total_allocated || 0)}</p>
          <div className="h-2 rounded-full bg-gray-100 overflow-hidden mt-2 mb-3">
            <div className={`h-full rounded-full ${spentPct >= 90 ? 'bg-danger-400' : spentPct >= 70 ? 'bg-amber-400' : 'bg-brand-400'}`} style={{ width: `${spentPct}%` }} />
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div><p className="text-gray-400">Terpakai</p><p className="font-semibold text-amber-500">{formatShort(p.total_spent || 0)}</p><p className="text-gray-400">{spentPct}%</p></div>
            <div><p className="text-gray-400">Reserved</p><p className="font-semibold text-blue-500">{formatShort(p.total_reserved || 0)}</p></div>
            <div><p className="text-gray-400">Bebas</p><p className={`font-semibold ${p.free >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>{formatShort(p.free || 0)}</p></div>
          </div>
        </div>
        <div className="card">
          <div className="flex items-center gap-2 mb-1">
            <Icon name="savings" size={18} color="#0F6E56" />
            <p className="text-xs text-gray-400">Saving Rate</p>
          </div>
          <p className="font-display text-3xl font-bold text-brand-600">{alloc?.saving_pct ?? 0}%</p>
          {savingDelta !== null ? (
            <p className={`text-xs mt-1 ${savingDelta >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>
              {savingDelta >= 0 ? '↑' : '↓'} {Math.abs(savingDelta)}% dari bulan lalu
            </p>
          ) : (
            <p className="text-xs text-gray-400 mt-1">Porsi income yang ditabung</p>
          )}
          <p className="text-xs text-gray-400 mt-2">{formatShort(alloc?.saving_amount || 0)} dari income {formatShort(alloc?.total_income || 0)}</p>
        </div>
        <div className="card">
          <div className="flex items-center gap-2 mb-1">
            <Icon name="wallet" size={18} color="#D97706" />
            <p className="text-xs text-gray-400">Cash Flow</p>
          </div>
          <p className={`font-display text-3xl font-bold ${cashflow === null ? 'text-gray-400' : cashflow >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>
            {cashflow === null ? '—' : `${cashflow >= 0 ? '+' : '−'}${formatShort(Math.abs(cashflow))}`}
          </p>
          <p className="text-xs text-gray-400 mt-1">Sisa akhir periode (prediksi)</p>
          {hasPred && <p className="text-xs text-gray-400 mt-2">Prediksi total belanja {formatShort(p.predicted_total)} · {p.days_left} hari lagi</p>}
        </div>
      </div>

      {/* ── Insight & Pola ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card">
          <div className="flex items-center gap-2 mb-3">
            <Icon name="advisor" size={18} color="#0F6E56" />
            <h3 className="font-semibold text-sm">Insight</h3>
            <span className="text-xs px-2 py-0.5 rounded-full bg-brand-50 text-brand-600">Beta</span>
          </div>
          {insights.length === 0 ? (
            <p className="text-sm text-gray-400">Belum cukup data untuk insight periode ini.</p>
          ) : (
            <div className="space-y-2">
              {insights.map((ins, i) => (
                <p key={i} className="text-sm flex items-start gap-2">
                  <span className="flex-shrink-0">{ins.icon}</span>
                  <span className="text-gray-600">{ins.text}</span>
                </p>
              ))}
            </div>
          )}
        </div>
        <div className="card">
          <h3 className="font-semibold text-sm mb-3">Pola Keuanganmu <span className="text-xs font-normal text-gray-400">(saat ini)</span></h3>
          <div className="grid grid-cols-2 gap-2">
            <MiniStat icon="langganan" color="#0F6E56" value={recurring.length} label="Langganan aktif" sub={`${formatShort(subsTotal)}/bulan`} />
            <MiniStat icon="warning" color="#D97706" value={unpaidCount} label="Belum dibayar" sub={formatShort(subsUnpaid)} />
            <MiniStat icon="target" color="#534AB7" value={sinkCount} label="Sinking fund terdeteksi" sub={sinkCount > 0 ? `${formatShort(sinking?.summary?.new_reserve_needed || 0)} reserve baru` : 'Tidak ada'} />
            <MiniStat icon="card" color="#E24B4A" value={perhatian} label="Amplop perlu perhatian" sub={perhatian > 0 ? 'Overspend / kurang tagihan' : 'Semua sehat'} />
          </div>
        </div>
      </div>

      {/* ── Spending Pattern ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card">
          <h3 className="font-semibold text-sm mb-4">Pengeluaran harian</h3>
          {dailyChart.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">Belum ada data</p>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={dailyChart}>
                  <XAxis dataKey="date" tick={{fontSize: 11}} tickLine={false} axisLine={false} />
                  <YAxis tick={{fontSize: 11}} tickLine={false} axisLine={false}
                    tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
                  <Tooltip content={<CustomTooltip />} />
                  {p.safe_daily > 0 && <ReferenceLine y={p.safe_daily} stroke="#E24B4A" strokeDasharray="4 4" />}
                  <Bar dataKey="total" name="Pengeluaran" fill="#0F6E56" radius={[4,4,0,0]} />
                </BarChart>
              </ResponsiveContainer>
              {p.safe_daily > 0 && (
                <p className="text-xs text-gray-400 mt-2">Rata-rata {formatCurrency(p.daily_avg)}/hari · <span className="text-danger-400">- - batas aman {formatCurrency(p.safe_daily)}/hari</span></p>
              )}
            </>
          )}
        </div>
        <div className="card">
          <h3 className="font-semibold text-sm mb-4">Heatmap mingguan</h3>
          {daily.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">Belum ada data</p>
          ) : (
            <>
              <div className="grid gap-1" style={{ gridTemplateColumns: 'auto repeat(7, minmax(0,1fr))' }}>
                <span />
                {DAY_HEADS.map(h => <span key={h} className="text-[11px] text-gray-400 text-center">{h}</span>)}
                {heat.weeks.map((week, wi) => (
                  [<span key={`w${wi}`} className="text-[11px] text-gray-400 pr-1 self-center whitespace-nowrap">Mg {wi + 1}</span>,
                  ...week.map((cell, di) => (
                    <div key={`${wi}-${di}`} title={cell ? `${cell.date}: ${formatCurrency(cell.total)}` : ''}
                      className="aspect-square rounded-md"
                      style={{ background: cell ? HEAT_COLORS[cell.level] : 'transparent' }} />
                  ))]
                ))}
              </div>
              <div className="flex items-center gap-1.5 mt-3 text-[11px] text-gray-400">
                <span>Rendah</span>
                {HEAT_COLORS.map((c, i) => <span key={i} className="w-3.5 h-3.5 rounded" style={{ background: c }} />)}
                <span>Tinggi</span>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Category Analysis ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card">
          <h3 className="font-semibold text-sm mb-4">Breakdown per amplop</h3>
          {breakdown.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">Belum ada data</p>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={breakdown} dataKey="spent" nameKey="name" cx="50%" cy="50%"
                    outerRadius={80} innerRadius={45} paddingAngle={2} stroke="none">
                    {breakdown.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip formatter={v => formatCurrency(v)} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-2 mt-2">
                {breakdown.map((item, i) => {
                  const total = breakdown.reduce((s, b) => s + b.spent, 0);
                  const pct = total > 0 ? Math.round((item.spent / total) * 100) : 0;
                  return (
                    <div key={i} className="flex items-center gap-2 text-sm">
                      <div className="w-3 h-3 rounded-sm flex-shrink-0" style={{background: COLORS[i % COLORS.length]}} />
                      <span className="inline-flex items-center gap-1.5 flex-1 min-w-0"><EnvelopeIcon value={item.emoji} size={16} color="currentColor" /> <span className="truncate">{item.name}</span></span>
                      <span className="font-mono font-medium">{formatShort(item.spent)}</span>
                      <span className="w-10 text-right text-gray-400 text-xs">{pct}%</span>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
        <div className="card">
          <h3 className="font-semibold text-sm mb-1">Naik vs turun</h3>
          <p className="text-xs text-gray-400 mb-3">Dibanding periode sebelumnya</p>
          {delta.up.length === 0 && delta.down.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">Tidak ada perubahan berarti</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <p className="text-xs font-semibold text-danger-400 mb-1">📈 Naik tertinggi</p>
                {delta.up.slice(0, 3).map((item, i) => <DeltaRow key={i} item={item} dir="up" />)}
                {delta.up.length === 0 && <p className="text-xs text-gray-400">Tidak ada</p>}
              </div>
              <div>
                <p className="text-xs font-semibold text-brand-600 mb-1">📉 Turun tertinggi</p>
                {delta.down.slice(0, 3).map((item, i) => <DeltaRow key={i} item={item} dir="down" />)}
                {delta.down.length === 0 && <p className="text-xs text-gray-400">Tidak ada</p>}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Trend ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="card lg:col-span-2">
          <h3 className="font-semibold text-sm mb-4">Tren 6 bulan</h3>
          {trend.every(t => t.spent === 0 && t.allocated === 0 && !t.income) ? (
            <p className="text-sm text-gray-400 text-center py-8">Belum ada data historis</p>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-tertiary)" />
                  <XAxis dataKey="month" tick={{fontSize: 10}} tickLine={false} axisLine={false} />
                  <YAxis tick={{fontSize: 11}} tickLine={false} axisLine={false}
                    tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
                  <Tooltip content={<CustomTooltip />} />
                  <Area type="monotone" dataKey="income" name="Income" stroke="#378ADD" fill="#378ADD" fillOpacity={0.08} strokeWidth={2} />
                  <Area type="monotone" dataKey="allocated" name="Dana" stroke="#0F6E56" fill="#0F6E56" fillOpacity={0.1} strokeWidth={2} />
                  <Area type="monotone" dataKey="spent" name="Terpakai" stroke="#BA7517" fill="#BA7517" fillOpacity={0.15} strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
              <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                {[['#378ADD', 'Income'], ['#0F6E56', 'Dana'], ['#BA7517', 'Terpakai']].map(([c, l]) => (
                  <span key={l} className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: c }} />{l}</span>
                ))}
              </div>
            </>
          )}
        </div>
        <div className="card">
          <h3 className="font-semibold text-sm mb-4">Income vs Expense</h3>
          {(() => {
            const inc = alloc?.total_income || 0;
            const exp = p.total_spent || 0;
            const maxV = Math.max(inc, exp, 1);
            return (
              <div className="space-y-4">
                <div>
                  <div className="flex justify-between text-xs mb-1"><span className="text-gray-500">Total Income</span><span className="font-mono font-medium">{formatShort(inc)}</span></div>
                  <div className="h-2.5 rounded-full bg-gray-100 overflow-hidden"><div className="h-full rounded-full bg-brand-400" style={{ width: `${(inc / maxV) * 100}%` }} /></div>
                </div>
                <div>
                  <div className="flex justify-between text-xs mb-1"><span className="text-gray-500">Total Expense</span><span className="font-mono font-medium">{formatShort(exp)}</span></div>
                  <div className="h-2.5 rounded-full bg-gray-100 overflow-hidden"><div className="h-full rounded-full bg-amber-400" style={{ width: `${(exp / maxV) * 100}%` }} /></div>
                </div>
                <p className={`text-sm font-semibold ${inc - exp >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>
                  {inc - exp >= 0 ? 'Surplus' : 'Defisit'} {formatShort(Math.abs(inc - exp))}
                </p>
              </div>
            );
          })()}
        </div>
      </div>

      {/* ── Transaksi Terbesar ── */}
      {topTxns.length > 0 && (
        <div className="card">
          <h3 className="font-semibold text-sm mb-3">Transaksi terbesar</h3>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {topTxns.map(t => (
              <div key={t.id} className="rounded-xl border border-gray-100 p-3">
                <EnvelopeIcon value={envById[t.envelope_id]?.emoji} size={20} />
                <p className="text-xs font-medium truncate mt-1.5">{t.description}</p>
                <p className="font-display font-bold text-sm mt-0.5">{formatShort(t.amount)}</p>
                <p className="text-[11px] text-gray-400">{new Date(t.transaction_date).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <SinkingFundAdvisor data={sinking} />
    </div>
  );
}
