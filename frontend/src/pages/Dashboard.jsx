import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { formatShort, formatCurrency, titleCase } from '../lib/utils';
import ExportButtons from '../components/ExportButtons';
import Onboarding from '../components/Onboarding';
import {
  ComposedChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
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

function buildDailyData(raw, prediction) {
  if (!prediction?.period_start) {
    return raw.map(x => ({ date: new Date(x.date).getDate() + '', total: x.total, isFuture: false }));
  }
  const spendMap = {};
  raw.forEach(d => { spendMap[d.date] = d.total; });

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = new Date(prediction.period_start);
  const end = new Date(prediction.period_end);
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

  const hasDanger = items.some(i => i.level === 'danger');
  const hasWarning = items.some(i => i.level === 'warning');
  const hasReward = !hasDanger && !hasWarning && items.some(i => i.level === 'reward');
  const bg = hasDanger ? '#FEF2F2' : hasWarning ? '#FFFBEB' : hasReward ? '#EFF6FF' : '#F0FDF9';
  const border = hasDanger ? '#FECACA' : hasWarning ? '#FDE68A' : hasReward ? '#BFDBFE' : '#A7F3D0';
  const label = hasDanger ? '🚨 Perlu perhatian sekarang' : hasWarning ? '📊 Status budget hari ini' : hasReward ? '🌟 Kamu lagi on fire!' : '📊 Status budget hari ini';
  const labelColor = hasDanger ? '#991B1B' : hasWarning ? '#92400E' : hasReward ? '#1E40AF' : '#065F46';

  return (
    <div className="rounded-xl p-4" style={{ background: bg, border: `1px solid ${border}` }}>
      <p className="text-xs font-bold mb-2.5 uppercase tracking-wide" style={{ color: labelColor }}>{label}</p>
      <div className="space-y-1.5">
        {items.map((item, i) => (
          <p key={i} className="text-sm" style={{ color: item.level === 'reward' ? '#1E40AF' : item.level === 'safe' ? '#065F46' : item.level === 'danger' ? '#7F1D1D' : '#78350F' }}>
            {item.icon} {item.text}
          </p>
        ))}
      </div>
      {safeDaily > 0 && (
        <p className="text-xs mt-2.5 pt-2.5 border-t" style={{ borderColor: border, color: labelColor }}>
          👉 Batas aman: <strong>{formatCurrency(safeDaily)}/hari</strong> · Sisa {prediction.days_left} hari · Dana bebas {formatCurrency(prediction.free)}
        </p>
      )}
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
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [daily, setDaily] = useState([]);
  const [breakdown, setBreakdown] = useState([]);
  const [prediction, setPrediction] = useState(null);

  useEffect(() => {
    Promise.all([
      api.getEnvelopeSummary(),
      api.getTransactions(null, 10),
      api.request('/analytics/daily-spending').then(r => r.ok ? r.json() : []),
      api.request('/analytics/envelope-breakdown').then(r => r.ok ? r.json() : []),
      api.request('/analytics/prediction').then(r => r.ok ? r.json() : null),
    ]).then(([env, txn, d, b, p]) => {
      setEnvelopes(env);
      setTransactions(txn);
      setDaily(d);
      setBreakdown(b.filter(x => x.spent > 0));
      setPrediction(p);
      setLoading(false);
      if (env.length === 0) setShowOnboarding(true);
    });
  }, []);

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;
  if (showOnboarding) return <Onboarding onDone={() => { setShowOnboarding(false); window.location.reload(); }} />;

  const shared = sortEnvelopes(envelopes.filter(e => !e.is_personal));
  const personal = sortEnvelopes(envelopes.filter(e => e.is_personal));

  const totalAllocated = shared.reduce((s, e) => s + Number(e.allocated), 0);
  const totalSpent = shared.reduce((s, e) => s + Number(e.spent), 0);
  const totalRemaining = shared.reduce((s, e) => s + Number(e.remaining), 0);

  const periodLabel = prediction?.period_start
    ? `${new Date(prediction.period_start).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })} – ${new Date(prediction.period_end).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}`
    : new Date().toLocaleString('id-ID', { month: 'long', year: 'numeric' });
  const daysLeft = prediction?.days_left ?? 0;

  const chartData = buildDailyData(daily, prediction);
  const todayStr = new Date().toISOString().split('T')[0];
  const todaySpent = daily.find(d => d.date === todayStr)?.total || 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold">Hai, {user?.name || 'User'}</h1>
        <p className="text-sm text-gray-500">{periodLabel} · {daysLeft} hari lagi</p>
      </div>

      <ExportButtons />

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card"><p className="text-xs text-gray-400 font-medium">Dana dialokasi</p><p className="font-display text-xl font-bold mt-1">{formatShort(totalAllocated)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Terpakai</p><p className="font-display text-xl font-bold mt-1 text-amber-400">{formatShort(totalSpent)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Sisa</p><p className={`font-display text-xl font-bold mt-1 ${totalRemaining >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>{formatShort(totalRemaining)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Amplop aktif</p><p className="font-display text-xl font-bold mt-1">{envelopes.length}</p></div>
      </div>

      {/* Decision Box */}
      <DecisionBox envelopes={envelopes} prediction={prediction} todaySpent={todaySpent} />

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
              <div className="flex items-center gap-4">
                <ResponsiveContainer width="50%" height={160}>
                  <PieChart>
                    <Pie data={breakdown} dataKey="spent" nameKey="name" cx="50%" cy="50%"
                      outerRadius={65} innerRadius={38} paddingAngle={2}>
                      {breakdown.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                    </Pie>
                    <Tooltip formatter={v => formatCurrency(v)} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex-1 space-y-1.5">
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

      {/* Recent transactions */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display font-bold text-lg">Transaksi terbaru</h2>
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
