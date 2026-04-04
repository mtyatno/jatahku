import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { formatShort, formatCurrency, titleCase } from '../lib/utils';
import ExportButtons from '../components/ExportButtons';
import Onboarding from '../components/Onboarding';
import {
  ComposedChart, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
  PieChart, Pie, Cell,
} from 'recharts';

const COLORS = ['#0F6E56', '#BA7517', '#1D9E75', '#D85A30', '#534AB7', '#993556', '#378ADD', '#639922'];

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-gray-200 rounded-lg px-3 py-2 shadow-sm">
      <p className="text-xs text-gray-400 mb-1">Tgl {label}</p>
      {payload.map((p, i) => p.value > 0 && (
        <p key={i} className="text-sm font-semibold" style={{color: p.color}}>
          {formatCurrency(p.value)}
        </p>
      ))}
    </div>
  );
}

function buildDailyData(raw, prediction, periodDates = null) {
  const pStart = prediction?.period_start || periodDates?.period_start;
  const pEnd = prediction?.period_end || periodDates?.period_end;
  if (!pStart) {
    return raw.map(x => ({ date: new Date(x.date).getDate() + '', total: x.total, isFuture: false }));
  }
  const spendMap = {};
  raw.forEach(d => { spendMap[d.date] = d.total; });

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = new Date(pStart);
  const end = new Date(pEnd);
  const result = [];
  const cur = new Date(start);
  while (cur <= end) {
    const dateStr = cur.toISOString().split('T')[0];
    const isFuture = cur > today;
    result.push({
      date: cur.getDate() + '',
      dateStr,
      total: spendMap[dateStr] || 0,
      isFuture,
    });
    cur.setDate(cur.getDate() + 1);
  }
  return result;
}

function DecisionBox({ envelopes, prediction, todaySpent }) {
  if (!prediction || prediction.total_allocated === 0) return null;

  const safeDaily = prediction.safe_daily;
  const items = [];

  // Today vs safe daily
  if (todaySpent > 0 && safeDaily > 0) {
    const ratio = todaySpent / safeDaily;
    const sisa = safeDaily - todaySpent;
    if (ratio >= 1.5) {
      items.push({ icon: '🔴', text: `Hari ini kamu overspend ${ratio.toFixed(1)}x dari batas aman (${formatCurrency(safeDaily)}/hari)`, level: 'danger' });
    } else if (ratio >= 1.0) {
      items.push({ icon: '🟠', text: `Pengeluaran hari ini (${formatCurrency(todaySpent)}) melebihi batas aman ${formatCurrency(safeDaily)}/hari`, level: 'warning' });
    } else if (ratio <= 0.5) {
      items.push({ icon: '🎉', text: `Mantap! Hari ini kamu hemat. Sisa jatah ${formatCurrency(sisa)} bisa ditabung atau carry ke besok.`, level: 'reward' });
    } else {
      items.push({ icon: '✅', text: `Pengeluaran hari ini ${formatCurrency(todaySpent)} — masih aman, sisa ${formatCurrency(sisa)} hari ini.`, level: 'safe' });
    }
  } else if (safeDaily > 0) {
    items.push({ icon: '🎉', text: `Belum ada pengeluaran hari ini. Jatah ${formatCurrency(safeDaily)} masih utuh — mantap!`, level: 'reward' });
  }

  // Envelope warnings — top 3 most urgent
  const urgent = [...envelopes]
    .filter(e => Number(e.allocated) > 0 && e.spent_ratio >= 0.7)
    .sort((a, b) => b.spent_ratio - a.spent_ratio)
    .slice(0, 3);

  urgent.forEach(e => {
    const pct = Math.round(e.spent_ratio * 100);
    if (e.spent_ratio >= 1.0) {
      items.push({ icon: '🔴', text: `${e.emoji} ${titleCase(e.name)} sudah habis (${pct}%)`, level: 'danger' });
    } else if (e.spent_ratio >= 0.9) {
      items.push({ icon: '🔴', text: `${e.emoji} ${titleCase(e.name)} hampir habis (${pct}%)`, level: 'danger' });
    } else {
      items.push({ icon: '⚠️', text: `${e.emoji} ${titleCase(e.name)} mulai menipis (${pct}%)`, level: 'warning' });
    }
  });

  // Safe envelopes summary
  const safeCount = envelopes.filter(e => Number(e.allocated) > 0 && e.spent_ratio < 0.7).length;
  if (safeCount > 0 && urgent.length > 0) {
    items.push({ icon: '✅', text: `${safeCount} amplop lainnya masih aman`, level: 'safe' });
  }

  if (items.length === 0) return null;

  const alertItems = items.filter(i => i.level === 'danger' || i.level === 'warning');
  const positiveItems = items.filter(i => i.level === 'reward' || i.level === 'safe');

  const hasDanger = alertItems.some(i => i.level === 'danger');

  return (
    <div className="space-y-3">
      {alertItems.length > 0 && (
        <div className="rounded-xl p-4" style={{ background: hasDanger ? '#FEF2F2' : '#FFFBEB', border: `1px solid ${hasDanger ? '#FECACA' : '#FDE68A'}` }}>
          <p className="text-xs font-bold mb-2.5 uppercase tracking-wide" style={{ color: hasDanger ? '#991B1B' : '#92400E' }}>
            {hasDanger ? '🚨 Perlu perhatian' : '⚠️ Mulai menipis'}
          </p>
          <div className="space-y-1.5">
            {alertItems.map((item, i) => (
              <p key={i} className="text-sm" style={{ color: item.level === 'danger' ? '#7F1D1D' : '#78350F' }}>
                {item.icon} {item.text}
              </p>
            ))}
          </div>
          {safeDaily > 0 && (
            <p className="text-xs mt-2.5 pt-2.5 border-t" style={{ borderColor: hasDanger ? '#FECACA' : '#FDE68A', color: hasDanger ? '#991B1B' : '#92400E' }}>
              👉 Batas aman: <strong>{formatCurrency(safeDaily)}/hari</strong> · Sisa {prediction.days_left} hari · Dana bebas {formatCurrency(prediction.free)}
            </p>
          )}
        </div>
      )}
      {positiveItems.length > 0 && (
        <div className="rounded-xl p-4" style={{ background: '#F0FDF9', border: '1px solid #A7F3D0' }}>
          <p className="text-xs font-bold mb-2.5 uppercase tracking-wide" style={{ color: '#065F46' }}>
            {positiveItems.some(i => i.level === 'reward') ? '🎉 Kabar baik' : '✅ Status aman'}
          </p>
          <div className="space-y-1.5">
            {positiveItems.map((item, i) => (
              <p key={i} className="text-sm" style={{ color: '#065F46' }}>
                {item.icon} {item.text}
              </p>
            ))}
          </div>
          {alertItems.length === 0 && safeDaily > 0 && (
            <p className="text-xs mt-2.5 pt-2.5 border-t border-green-200" style={{ color: '#065F46' }}>
              👉 Batas aman: <strong>{formatCurrency(safeDaily)}/hari</strong> · Sisa {prediction.days_left} hari · Dana bebas {formatCurrency(prediction.free)}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function buildInsights(monthlyTrend, breakdown) {
  const insights = [];
  const active = (monthlyTrend || []).filter(d => d.spent > 0 || d.allocated > 0);

  // Insight 1: spend trend vs last period
  if (active.length >= 2) {
    const prev = active[active.length - 2];
    const curr = active[active.length - 1];
    if (prev.spent > 0) {
      const pct = Math.round(((curr.spent - prev.spent) / prev.spent) * 100);
      const absPct = Math.abs(pct);
      if (absPct >= 5) {
        const arah = pct > 0 ? 'naik' : 'turun';
        insights.push(`📊 Pengeluaran ${arah} ${absPct}% dibanding periode lalu`);
      } else {
        insights.push(`📊 Pengeluaran stabil dibanding periode lalu`);
      }
    }
  }

  // Insight 2: top envelope this period
  if (breakdown && breakdown.length > 0) {
    const total = breakdown.reduce((s, x) => s + x.spent, 0);
    const top = [...breakdown].sort((a, b) => b.spent - a.spent)[0];
    if (top && total > 0) {
      const pct = Math.round((top.spent / total) * 100);
      insights.push(`${top.emoji || '📁'} Terbanyak: ${titleCase(top.name)} (${pct}% dari total)`);
    }
  }

  return insights;
}

function MonthlyComparison({ data, breakdown }) {
  if (!data || data.length === 0) return null;

  // Only show periods with actual data
  const active = data.filter(d => d.spent > 0 || d.allocated > 0).slice(-6);
  if (active.length === 0) return null;

  const chartData = active.map(d => {
    const parts = d.month.split('–');
    const shortLabel = parts[1]?.trim().slice(0, 6) || parts[0]?.trim().slice(0, 6) || d.month;
    return {
      name: shortLabel,
      fullLabel: d.month,
      spent: d.spent,
      allocated: d.allocated,
      pct: d.allocated > 0 ? Math.round((d.spent / d.allocated) * 100) : 0,
    };
  });

  const insights = buildInsights(data, breakdown);

  return (
    <div className="card">
      <h3 className="font-semibold text-sm mb-3">Perbandingan periode</h3>
      {insights.length > 0 && (
        <div className="mb-3 space-y-1">
          {insights.map((ins, i) => (
            <p key={i} className="text-xs text-gray-500 bg-gray-50 rounded-lg px-3 py-1.5">{ins}</p>
          ))}
        </div>
      )}
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }} barCategoryGap="20%">
          <XAxis dataKey="name" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontSize: 9 }} tickLine={false} axisLine={false} width={42}
            tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(0)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
          <Tooltip
            formatter={(v, n) => [formatCurrency(v), n === 'spent' ? 'Terpakai' : 'Dialokasi']}
            labelFormatter={(_, payload) => payload?.[0]?.payload?.fullLabel || ''}
          />
          <Bar dataKey="allocated" fill="#D1FAE5" radius={[2, 2, 0, 0]} barSize={12} />
          <Bar dataKey="spent" fill="#0F6E56" radius={[2, 2, 0, 0]} barSize={12} />
        </BarChart>
      </ResponsiveContainer>
      <div className="mt-2 space-y-1">
        {chartData.map((d, i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <span className="text-gray-500 truncate mr-2">{d.fullLabel}</span>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-gray-400">{formatShort(d.spent)} / {formatShort(d.allocated)}</span>
              <span className={`font-semibold w-9 text-right ${d.pct >= 90 ? 'text-danger-400' : d.pct >= 70 ? 'text-amber-500' : 'text-brand-600'}`}>
                {d.pct}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function WeeklyPattern({ data }) {
  if (!data || data.length === 0) return null;

  // Reorder: Senin–Sabtu–Minggu (DOW 1,2,3,4,5,6,0)
  const ordered = [1, 2, 3, 4, 5, 6, 0].map(dow => data.find(d => d.dow === dow)).filter(Boolean);
  const hasData = ordered.some(d => d.avg > 0);
  if (!hasData) return null;

  const maxAvg = Math.max(...ordered.map(d => d.avg));
  const chartData = ordered.map(d => ({
    name: d.name.slice(0, 3), // Sen, Sel, Rab, Kam, Jum, Sab, Min
    fullName: d.name,
    avg: d.avg,
    isPeak: d.avg === maxAvg && maxAvg > 0,
  }));

  const peakDay = chartData.find(d => d.isPeak);

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-sm">Pola mingguan</h3>
        {peakDay && (
          <span className="text-xs text-gray-400">
            Paling boros: <span className="font-medium text-amber-500">{peakDay.fullName}</span>
          </span>
        )}
      </div>
      <ResponsiveContainer width="100%" height={120}>
        <BarChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }} barCategoryGap="15%">
          <XAxis dataKey="name" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontSize: 9 }} tickLine={false} axisLine={false} width={42}
            tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
          <Tooltip
            formatter={v => [formatCurrency(v), 'Rata-rata']}
            labelFormatter={(_, payload) => payload?.[0]?.payload?.fullName || ''}
          />
          <Bar dataKey="avg" radius={[3, 3, 0, 0]}
            shape={(props) => {
              const color = props.isPeak ? '#BA7517' : '#1D9E75';
              return <rect {...props} fill={color} rx={3} ry={3} />;
            }}
          />
        </BarChart>
      </ResponsiveContainer>
      <p className="text-xs text-gray-400 mt-2">Rata-rata pengeluaran per hari · 3 periode terakhir</p>
    </div>
  );
}

function EnvelopeRow({ env }) {
  const allocated = Number(env.allocated);
  const spent = Number(env.spent);
  const reserved = Number(env.reserved || 0);
  const free = Number(env.free || env.remaining);
  const ratio = env.spent_ratio;
  const isUnfunded = allocated <= 0 && env.name !== 'Tabungan';

  const barColor = ratio >= 0.9 ? 'bg-danger-400' : ratio >= 0.7 ? 'bg-amber-400' : 'bg-brand-400';
  const freeColor = free <= 0 ? 'text-danger-400' : ratio >= 0.7 ? 'text-amber-400' : 'text-brand-600';

  const badge = ratio >= 1.0
    ? <span className="text-xs px-1.5 py-0.5 rounded-md bg-red-100 text-danger-400 font-semibold">Habis</span>
    : ratio >= 0.9
    ? <span className="text-xs px-1.5 py-0.5 rounded-md bg-red-50 text-danger-400 font-medium">🔴 {Math.round(ratio * 100)}%</span>
    : ratio >= 0.7
    ? <span className="text-xs px-1.5 py-0.5 rounded-md bg-amber-50 text-amber-600 font-medium">🟡 {Math.round(ratio * 100)}%</span>
    : null;

  return (
    <div className={`card hover:border-brand-200 transition-colors ${env.is_locked ? 'opacity-60' : ''}`}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-lg">{env.emoji || '📁'}</span>
          <span className="font-semibold text-sm">{titleCase(env.name)}</span>
          {badge}
        </div>
        <span className={`font-display font-bold text-sm ${freeColor}`}>{formatShort(free)}</span>
      </div>
      {isUnfunded ? (
        <div className="bg-amber-50 text-amber-600 text-xs px-3 py-2 rounded-lg">💡 Belum ada dana.</div>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden flex-1">
              <div className={`h-full rounded-full transition-all duration-500 ${env.is_locked ? 'bg-gray-300' : barColor}`}
                style={{ width: `${Math.min(Math.max(ratio * 100, 1), 100)}%` }} />
            </div>
            <span className={`text-xs font-semibold w-10 text-right ${freeColor}`}>
              {free <= 0 ? '0%' : `Sisa ${Math.round((1 - ratio) * 100)}%`}
            </span>
          </div>
          <div className="flex justify-between mt-1 text-xs text-gray-400">
            <span>Terpakai {formatShort(spent)}</span>
            {reserved > 0 && <span>🔄 {formatShort(reserved)}</span>}
            <span>Dana {formatShort(allocated)}</span>
          </div>
        </>
      )}
    </div>
  );
}

function sortEnvelopes(envs) {
  return [...envs].sort((a, b) => {
    const aFunded = Number(a.allocated) > 0;
    const bFunded = Number(b.allocated) > 0;
    if (aFunded && !bFunded) return -1;
    if (!aFunded && bFunded) return 1;
    return b.spent_ratio - a.spent_ratio;
  });
}

export default function Dashboard() {
  const { user } = useAuth();
  const [envelopes, setEnvelopes] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [periodLoading, setPeriodLoading] = useState(false);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [daily, setDaily] = useState([]);
  const [breakdown, setBreakdown] = useState([]);
  const [prediction, setPrediction] = useState(null);
  const [periods, setPeriods] = useState([]);
  const [periodIdx, setPeriodIdx] = useState(null);
  const [monthlyTrend, setMonthlyTrend] = useState([]);
  const [weeklyPattern, setWeeklyPattern] = useState([]);

  // Load period list, monthly trend, and weekly pattern once on mount
  useEffect(() => {
    Promise.all([
      api.getPeriods(12),
      api.request('/analytics/monthly-trend').then(r => r.ok ? r.json() : []),
      api.getWeeklyPattern(3),
    ]).then(([p, trend, weekly]) => {
      setPeriods(p);
      setMonthlyTrend(trend);
      setWeeklyPattern(weekly);
      setPeriodIdx(p.length - 1); // default = current period
    });
  }, []);

  // Reload data whenever selected period changes
  useEffect(() => {
    if (periods.length === 0 || periodIdx === null) return;
    const isCurrentPeriod = periodIdx === periods.length - 1;
    const period = periods[periodIdx];
    // Pass null for current period so backend uses its own default (handles edge cases)
    const ps = isCurrentPeriod ? null : period.period_start;
    const pe = isCurrentPeriod ? null : period.period_end;

    setPeriodLoading(true);
    Promise.all([
      api.getEnvelopeSummary(ps, pe),
      api.getTransactions(null, 10, period.period_start, period.period_end),
      api.getDailySpending(ps, pe),
      api.getEnvelopeBreakdown(ps, pe),
      isCurrentPeriod
        ? api.request('/analytics/prediction').then(r => r.ok ? r.json() : null)
        : Promise.resolve(null),
    ]).then(([env, txn, d, b, pred]) => {
      setEnvelopes(env);
      setTransactions(txn);
      setDaily(d);
      setBreakdown(b.filter(x => x.spent > 0));
      setPrediction(pred);
      setPeriodLoading(false);
      setLoading(false);
      if (env.length === 0 && isCurrentPeriod) setShowOnboarding(true);
    });
  }, [periodIdx, periods]);

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;
  if (showOnboarding) return <Onboarding onDone={() => { setShowOnboarding(false); window.location.reload(); }} />;

  const isCurrentPeriod = periodIdx === periods.length - 1;
  const selectedPeriod = periods[periodIdx];

  const shared = sortEnvelopes(envelopes.filter(e => !e.is_personal));
  const personal = sortEnvelopes(envelopes.filter(e => e.is_personal));

  const totalAllocated = shared.reduce((s, e) => s + Number(e.allocated), 0);
  const totalSpent = shared.reduce((s, e) => s + Number(e.spent), 0);
  const totalRemaining = shared.reduce((s, e) => s + Number(e.free ?? e.remaining), 0);

  const periodLabel = selectedPeriod?.label
    || (prediction?.period_start
      ? `${new Date(prediction.period_start).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })} – ${new Date(prediction.period_end).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}`
      : new Date().toLocaleString('id-ID', { month: 'long', year: 'numeric' }));
  const daysLeft = prediction?.days_left ?? 0;

  const chartData = buildDailyData(daily, prediction, selectedPeriod);
  const todayStr = new Date().toISOString().split('T')[0];
  const todaySpent = daily.find(d => d.date === todayStr)?.total || 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold">Hai, {user?.name || 'User'}</h1>
        {/* Period Navigator */}
        <div className="flex items-center gap-1 mt-1">
          <button
            onClick={() => setPeriodIdx(i => i - 1)}
            disabled={periodIdx === 0}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-500 text-sm leading-none"
            aria-label="Periode sebelumnya"
          >←</button>
          <span className="text-sm text-gray-500">{periodLabel}{isCurrentPeriod && daysLeft > 0 ? ` · ${daysLeft} hari lagi` : ''}</span>
          {isCurrentPeriod && (
            <span className="text-xs px-1.5 py-0.5 bg-brand-50 text-brand-600 rounded font-medium">Sekarang</span>
          )}
          <button
            onClick={() => setPeriodIdx(i => i + 1)}
            disabled={isCurrentPeriod}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-500 text-sm leading-none"
            aria-label="Periode berikutnya"
          >→</button>
          {periodLoading && <span className="text-xs text-gray-400 ml-1">...</span>}
        </div>
      </div>

      {isCurrentPeriod && <ExportButtons />}

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card"><p className="text-xs text-gray-400 font-medium">Dana dialokasi</p><p className="font-display text-xl font-bold mt-1">{formatShort(totalAllocated)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Terpakai</p><p className="font-display text-xl font-bold mt-1 text-amber-400">{formatShort(totalSpent)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Sisa</p><p className={`font-display text-xl font-bold mt-1 ${totalRemaining >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>{formatShort(totalRemaining)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Amplop aktif</p><p className="font-display text-xl font-bold mt-1">{envelopes.length}</p></div>
      </div>

      {/* Decision Box — only for current period */}
      {isCurrentPeriod && (
        <DecisionBox envelopes={envelopes} prediction={prediction} todaySpent={todaySpent} />
      )}

      {/* Monthly Comparison — always visible */}
      <MonthlyComparison data={monthlyTrend} breakdown={breakdown} />

      {/* Weekly Pattern — always visible */}
      <WeeklyPattern data={weeklyPattern} />

      {/* Charts */}
      {(chartData.length > 0 || breakdown.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {chartData.length > 0 && (
            <div className="card">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold text-sm">Pengeluaran harian</h3>
                {prediction?.safe_daily > 0 && (
                  <span className="text-xs text-gray-400 flex items-center gap-1">
                    <span className="inline-block w-4 border-t-2 border-dashed border-danger-400"></span>
                    Batas aman {formatShort(prediction.safe_daily)}/hari
                  </span>
                )}
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <ComposedChart data={chartData} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
                  <XAxis dataKey="date" tick={{ fontSize: 9 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10 }} tickLine={false} axisLine={false} width={45}
                    tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
                  <Tooltip content={<CustomTooltip />} />
                  {prediction?.safe_daily > 0 && (
                    <ReferenceLine y={prediction.safe_daily} stroke="#E24B4A" strokeDasharray="4 3" strokeWidth={1.5}
                      label={{ value: '', position: 'right' }} />
                  )}
                  <Bar dataKey="total" name="Pengeluaran" radius={[3, 3, 0, 0]}
                    fill="#0F6E56"
                    shape={(props) => {
                      const { isFuture, ...rest } = props;
                      return <rect {...rest} fill={props.isFuture ? '#E5E7EB' : '#0F6E56'} rx={3} ry={3} />;
                    }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}
          {breakdown.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-sm mb-3">Breakdown amplop</h3>
              <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                <div className="mx-auto sm:mx-0" style={{ width: 140, height: 140, flexShrink: 0 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={breakdown} dataKey="spent" nameKey="name" cx="50%" cy="50%"
                        outerRadius={58} innerRadius={34} paddingAngle={2}>
                        {breakdown.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                      </Pie>
                      <Tooltip formatter={v => formatCurrency(v)} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 min-w-0 space-y-1.5">
                  {(() => {
                    const total = breakdown.reduce((s, x) => s + x.spent, 0);
                    return breakdown.map((item, i) => {
                      const pct = total > 0 ? Math.round((item.spent / total) * 100) : 0;
                      return (
                        <div key={i} className="flex items-center justify-between text-xs">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <div className="w-2.5 h-2.5 flex-shrink-0 rounded-sm" style={{ background: COLORS[i % COLORS.length] }} />
                            <span className="truncate">{item.emoji} {titleCase(item.name)}</span>
                          </div>
                          <div className="flex items-center gap-1 ml-2 flex-shrink-0">
                            <span className="font-mono font-medium">{formatShort(item.spent)}</span>
                            <span className="text-gray-400">({pct}%)</span>
                          </div>
                        </div>
                      );
                    });
                  })()}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Envelopes — sorted by urgency */}
      {shared.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display font-bold text-lg">👥 Shared</h2>
            <Link to="/envelopes" className="text-sm text-brand-600 font-medium hover:underline">Lihat semua →</Link>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {shared.map(env => <EnvelopeRow key={env.id} env={env} />)}
          </div>
        </div>
      )}
      {personal.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-display font-bold text-lg">🔒 Personal</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {personal.map(env => <EnvelopeRow key={env.id} env={env} />)}
          </div>
        </div>
      )}

      {/* Transactions for selected period */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display font-bold text-lg">Transaksi{isCurrentPeriod ? ' terbaru' : ''}</h2>
          <Link to="/transactions" className="text-sm text-brand-600 font-medium hover:underline">Lihat semua →</Link>
        </div>
        {transactions.length === 0 ? (
          <div className="card text-center py-8"><p className="text-gray-400">Belum ada transaksi</p></div>
        ) : (
          <div className="card divide-y divide-gray-50">
            {transactions.slice(0, 8).map(txn => {
              const env = envelopes.find(e => e.id === txn.envelope_id);
              return (
                <div key={txn.id} className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
                  <div className="flex items-center gap-3">
                    <span className="text-lg">{env?.emoji || '📁'}</span>
                    <div>
                      <p className="text-sm font-medium">{txn.description}</p>
                      <p className="text-xs text-gray-400">{env?.name} · {txn.source === 'telegram' ? '📱' : '🌐'}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="font-display font-bold text-sm text-gray-900">-{formatShort(txn.amount)}</p>
                    <p className="text-xs text-gray-400">{new Date(txn.transaction_date).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}</p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
