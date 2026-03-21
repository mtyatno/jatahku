import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { formatShort, formatCurrency, daysLeftInMonth } from '../lib/utils';
import ExportButtons from '../components/ExportButtons';
import Onboarding from '../components/Onboarding';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts';

const COLORS = ['#0F6E56', '#BA7517', '#1D9E75', '#D85A30', '#534AB7', '#993556', '#378ADD', '#639922'];

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

function ProgressBar({ ratio, color }) {
  return (
    <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
      <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${Math.min(Math.max(ratio * 100, 1), 100)}%` }} />
    </div>
  );
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
      setDaily(d.map(x => ({...x, date: new Date(x.date).getDate() + ''})));
      setBreakdown(b.filter(x => x.spent > 0));
      setPrediction(p);
      setLoading(false);
      if (env.length === 0) setShowOnboarding(true);
    });
  }, []);

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;
  if (showOnboarding) return <Onboarding onDone={() => { setShowOnboarding(false); window.location.reload(); }} />;

  const shared = envelopes.filter(e => !e.is_personal);
  const personal = envelopes.filter(e => e.is_personal);
  const daysLeft = daysLeftInMonth();
  const month = new Date().toLocaleString('id-ID', { month: 'long', year: 'numeric' });

  const totalAllocated = shared.reduce((s, e) => s + Number(e.allocated), 0);
  const totalSpent = shared.reduce((s, e) => s + Number(e.spent), 0);
  const totalRemaining = shared.reduce((s, e) => s + Number(e.remaining), 0);

  const renderEnvelopeRow = (env) => {
    const allocated = Number(env.allocated);
    const spent = Number(env.spent);
    const remaining = Number(env.remaining);
    const reserved = Number(env.reserved || 0);
    const free = Number(env.free || remaining);
    const spentRatio = env.spent_ratio;

    const spentColor = spentRatio >= 0.9 ? 'bg-danger-400' : spentRatio >= 0.7 ? 'bg-amber-400' : 'bg-brand-400';
    const remainColor = free <= 0 ? 'text-danger-400' : spentRatio >= 0.7 ? 'text-amber-400' : 'text-brand-600';
    const isUnfunded = allocated <= 0 && env.name !== 'Tabungan';

    return (
      <div key={env.id} className={`card hover:border-brand-200 transition-colors ${env.is_locked ? 'opacity-60' : ''}`}>
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-lg">{env.emoji || '📁'}</span>
            <span className="font-semibold text-sm">{env.name}</span>
          </div>
          <span className={`font-display font-bold text-sm ${remainColor}`}>{formatShort(free)}</span>
        </div>
        {isUnfunded ? (
          <div className="bg-amber-50 text-amber-600 text-xs px-3 py-2 rounded-lg">💡 Belum ada dana.</div>
        ) : (
          <>
            <ProgressBar ratio={spentRatio} color={env.is_locked ? 'bg-gray-300' : spentColor} />
            <div className="flex justify-between mt-1.5 text-xs text-gray-400">
              <span>Terpakai {formatShort(spent)}</span>
              {reserved > 0 && <span>🔄 {formatShort(reserved)}</span>}
              <span>Dana {formatShort(allocated)}</span>
            </div>
          </>
        )}
      </div>
    );
  };

  const pct = prediction && prediction.total_allocated > 0
    ? Math.round((prediction.total_spent / prediction.total_allocated) * 100) : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold">Hai, {user?.name || 'User'}</h1>
        <p className="text-sm text-gray-500">{month} — {daysLeft} hari lagi</p>
      </div>

      <ExportButtons />

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card"><p className="text-xs text-gray-400 font-medium">Dana dialokasi</p><p className="font-display text-xl font-bold mt-1">{formatShort(totalAllocated)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Terpakai</p><p className="font-display text-xl font-bold mt-1 text-amber-400">{formatShort(totalSpent)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Sisa</p><p className={`font-display text-xl font-bold mt-1 ${totalRemaining >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>{formatShort(totalRemaining)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Amplop aktif</p><p className="font-display text-xl font-bold mt-1">{envelopes.length}</p></div>
      </div>

      {/* Prediction */}
      {prediction && prediction.total_allocated > 0 && (
        <div className="flex items-center gap-3 p-4 rounded-xl" style={{background: prediction.on_track ? '#E1F5EE' : '#FCEBEB'}}>
          <span className="text-2xl">{prediction.on_track ? '✅' : '⚠️'}</span>
          <div className="flex-1">
            <p className="text-sm font-semibold" style={{color: prediction.on_track ? '#085041' : '#791F1F'}}>
              {prediction.on_track ? 'On track! Budget cukup sampai akhir bulan.' : 'Hati-hati! Di pace ini, budget bisa habis sebelum akhir bulan.'}
            </p>
            <p className="text-xs mt-0.5" style={{color: prediction.on_track ? '#0F6E56' : '#A32D2D'}}>
              Rata-rata {formatCurrency(prediction.daily_avg)}/hari · Aman max {formatCurrency(prediction.safe_daily)}/hari · {prediction.days_left} hari lagi
            </p>
          </div>
        </div>
      )}

      {/* Charts row */}
      {(daily.length > 0 || breakdown.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {daily.length > 0 && (
            <div className="card">
              <h3 className="font-semibold text-sm mb-3">Pengeluaran harian</h3>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={daily}>
                  <XAxis dataKey="date" tick={{fontSize: 10}} tickLine={false} axisLine={false} />
                  <YAxis tick={{fontSize: 10}} tickLine={false} axisLine={false} width={45}
                    tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="total" name="Pengeluaran" fill="#0F6E56" radius={[3,3,0,0]} />
                </BarChart>
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
                  {breakdown.map((item, i) => (
                    <div key={i} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-1.5">
                        <div className="w-2.5 h-2.5 rounded-sm" style={{background: COLORS[i % COLORS.length]}} />
                        <span>{item.emoji} {item.name}</span>
                      </div>
                      <span className="font-mono font-medium">{formatShort(item.spent)}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Envelopes */}
      {shared.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3"><h2 className="font-display font-bold text-lg">👥 Shared</h2><Link to="/envelopes" className="text-sm text-brand-600 font-medium hover:underline">Lihat semua →</Link></div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">{shared.map(renderEnvelopeRow)}</div>
        </div>
      )}

      {personal.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3"><h2 className="font-display font-bold text-lg">🔒 Personal</h2></div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">{personal.map(renderEnvelopeRow)}</div>
        </div>
      )}

      {/* Recent transactions */}
      <div>
        <div className="flex items-center justify-between mb-3"><h2 className="font-display font-bold text-lg">Transaksi terbaru</h2><Link to="/transactions" className="text-sm text-brand-600 font-medium hover:underline">Lihat semua →</Link></div>
        {transactions.length === 0 ? (
          <div className="card text-center py-8"><p className="text-gray-400">Belum ada transaksi</p></div>
        ) : (
          <div className="card divide-y divide-gray-50">
            {transactions.slice(0, 8).map(txn => {
              const env = envelopes.find(e => e.id === txn.envelope_id);
              return (
                <div key={txn.id} className="flex items-center justify-between py-3 first:pt-0 last:pb-0">
                  <div className="flex items-center gap-3"><span className="text-lg">{env?.emoji || '📁'}</span><div><p className="text-sm font-medium">{txn.description}</p><p className="text-xs text-gray-400">{env?.name} · {txn.source === 'telegram' ? '📱' : '🌐'}</p></div></div>
                  <div className="text-right"><p className="font-display font-bold text-sm text-gray-900">-{formatShort(txn.amount)}</p><p className="text-xs text-gray-400">{new Date(txn.transaction_date).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}</p></div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
