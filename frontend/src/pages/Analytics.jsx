import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';
import { Icon, EnvelopeIcon } from '../components/Icon';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
  AreaChart, Area, CartesianGrid,
} from 'recharts';

const COLORS = ['#0F6E56', '#BA7517', '#1D9E75', '#D85A30', '#534AB7', '#993556', '#378ADD', '#639922'];

function PredictionCard({ data }) {
  if (!data || !data.total_allocated) return null;
  const pct = Math.round((data.total_spent / data.total_allocated) * 100);
  return (
    <div className="card">
      <h3 className="font-semibold text-sm mb-3">Prediksi akhir bulan</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <div><p className="text-xs text-gray-400">Dana</p><p className="font-display font-bold">{formatShort(data.total_allocated)}</p></div>
        <div><p className="text-xs text-gray-400">Terpakai ({pct}%)</p><p className="font-display font-bold text-amber-500">{formatShort(data.total_spent)}</p></div>
        <div><p className="text-xs text-gray-400">Reserved</p><p className="font-display font-bold text-blue-500">{formatShort(data.total_reserved)}</p></div>
        <div><p className="text-xs text-gray-400">Bebas</p><p className={`font-display font-bold ${data.free > 0 ? 'text-brand-600' : 'text-danger-400'}`}>{formatShort(data.free)}</p></div>
      </div>
      <div className="flex items-center gap-3 p-3 rounded-xl" style={{background: data.on_track ? '#E1F5EE' : '#FCEBEB'}}>
        <Icon name={data.on_track ? 'check' : 'warning'} size={26} weight="fill" color={data.on_track ? '#085041' : '#791F1F'} />
        <div>
          <p className="text-sm font-semibold" style={{color: data.on_track ? '#085041' : '#791F1F'}}>
            {data.on_track ? 'On track! Budget cukup sampai akhir bulan.' : 'Overspend! Kurangi pengeluaran.'}
          </p>
          <p className="text-xs" style={{color: data.on_track ? '#0F6E56' : '#A32D2D'}}>
            Rata-rata {formatCurrency(data.daily_avg)}/hari · Aman max {formatCurrency(data.safe_daily)}/hari · {data.days_left} hari lagi
          </p>
        </div>
      </div>
    </div>
  );
}

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
            Reserve baru {formatShort(data.summary?.new_reserve_needed || 0)} � {recommendations.length} rekomendasi
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
                <p className="text-xs text-gray-500 mt-1">{item.envelope_name} � {item.frequency} � {item.confidence}</p>
              </div>
              <div className="text-right flex-shrink-0">
                <p className="font-display font-bold text-brand-600">{formatShort(item.monthly_reserve)}</p>
                <p className="text-xs text-gray-400">/periode</p>
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-2">{item.description}</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2 mt-3 text-xs">
              <div className="bg-gray-50 rounded-lg px-2 py-1.5">
                <p className="text-gray-400">Nominal</p>
                <p className="font-semibold">{formatCurrency(item.suggested_amount)}</p>
              </div>
              <div className="bg-gray-50 rounded-lg px-2 py-1.5">
                <p className="text-gray-400">Estimasi berikut</p>
                <p className="font-semibold">{item.next_expected_date || '-'}</p>
              </div>
              <div className="bg-gray-50 rounded-lg px-2 py-1.5">
                <p className="text-gray-400">Tipe</p>
                <p className="font-semibold">{item.type}</p>
              </div>
            </div>
            {item.evidence?.length > 0 && (
              <div className="mt-3 pt-3 border-t border-gray-100 space-y-1">
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

export default function Analytics() {
  const [daily, setDaily] = useState([]);
  const [breakdown, setBreakdown] = useState([]);
  const [trend, setTrend] = useState([]);
  const [prediction, setPrediction] = useState(null);
  const [sinkingAdvice, setSinkingAdvice] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Satu endpoint gagal tidak boleh membuat halaman stuck "Loading..." —
    // fallback per-request, bagian lain tetap tampil.
    const safe = (path, fallback) =>
      api.request(path).then(r => (r.ok ? r.json() : fallback)).catch(() => fallback);
    Promise.all([
      safe('/analytics/daily-spending', []),
      safe('/analytics/envelope-breakdown', []),
      safe('/analytics/monthly-trend', []),
      safe('/analytics/prediction', null),
      api.getSinkingFundAdvice(),
    ]).then(([d, b, t, p, sfa]) => {
      setDaily((Array.isArray(d) ? d : []).map(x => ({...x, date: new Date(x.date).getDate() + ''})));
      setBreakdown((Array.isArray(b) ? b : []).filter(x => x.spent > 0));
      setTrend(Array.isArray(t) ? t : []);
      setPrediction(p);
      setSinkingAdvice(sfa);
      setLoading(false);
    });
  }, []);

  const month = new Date().toLocaleString('id-ID', { month: 'long', year: 'numeric' });

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold">Analytics</h1>
        <p className="text-sm text-gray-500">{month}</p>
      </div>

      <PredictionCard data={prediction} />

      <SinkingFundAdvisor data={sinkingAdvice} />

      {/* Daily spending */}
      <div className="card">
        <h3 className="font-semibold text-sm mb-4">Pengeluaran harian</h3>
        {daily.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-8">Belum ada data</p>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={daily}>
              <XAxis dataKey="date" tick={{fontSize: 11}} tickLine={false} axisLine={false} />
              <YAxis tick={{fontSize: 11}} tickLine={false} axisLine={false}
                tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="total" name="Pengeluaran" fill="#0F6E56" radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Envelope breakdown */}
        <div className="card">
          <h3 className="font-semibold text-sm mb-4">Breakdown per amplop</h3>
          {breakdown.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-8">Belum ada data</p>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <PieChart>
                  <Pie data={breakdown} dataKey="spent" nameKey="name" cx="50%" cy="50%"
                    outerRadius={80} innerRadius={45} paddingAngle={2}>
                    {breakdown.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip formatter={v => formatCurrency(v)} />
                </PieChart>
              </ResponsiveContainer>
              <div className="space-y-2 mt-2">
                {breakdown.map((item, i) => (
                  <div key={i} className="flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-sm" style={{background: COLORS[i % COLORS.length]}} />
                      <span className="inline-flex items-center gap-1.5"><EnvelopeIcon value={item.emoji} size={16} color="currentColor" /> {item.name}</span>
                    </div>
                    <span className="font-mono font-medium">{formatShort(item.spent)}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Monthly trend */}
        <div className="card">
          <h3 className="font-semibold text-sm mb-4">Tren 6 bulan</h3>
          {trend.every(t => t.spent === 0 && t.allocated === 0) ? (
            <p className="text-sm text-gray-400 text-center py-8">Belum ada data historis</p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-tertiary)" />
                <XAxis dataKey="month" tick={{fontSize: 10}} tickLine={false} axisLine={false} />
                <YAxis tick={{fontSize: 11}} tickLine={false} axisLine={false}
                  tickFormatter={v => v >= 1000000 ? `${(v/1000000).toFixed(1)}jt` : v >= 1000 ? `${Math.round(v/1000)}k` : v} />
                <Tooltip content={<CustomTooltip />} />
                <Area type="monotone" dataKey="allocated" name="Dana" stroke="#0F6E56" fill="#0F6E56" fillOpacity={0.1} strokeWidth={2} />
                <Area type="monotone" dataKey="spent" name="Terpakai" stroke="#BA7517" fill="#BA7517" fillOpacity={0.15} strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  );
}
