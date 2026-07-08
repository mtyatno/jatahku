import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';
import { flushQueue, getPendingCount } from '../lib/offlineQueue';
import { Icon, EnvelopeIcon, BRAND } from '../components/Icon';
import StatCard from '../components/StatCard';

const TIME_TABS = [
  { key: 'all', label: 'Semua Waktu' },
  { key: 'today', label: 'Hari Ini' },
  { key: 'yesterday', label: 'Kemarin' },
  { key: 'week', label: 'Minggu Ini' },
  { key: 'month', label: 'Bulan Ini' },
];

const SORTS = [
  { key: 'terbaru', label: 'Terbaru' },
  { key: 'terlama', label: 'Terlama' },
  { key: 'terbesar', label: 'Nominal terbesar' },
  { key: 'terkecil', label: 'Nominal terkecil' },
];

function inTimeTab(dateStr, tab) {
  if (tab === 'all') return true;
  const d = new Date(dateStr + 'T00:00:00');
  const today = new Date(); today.setHours(0, 0, 0, 0);
  if (tab === 'today') return d.getTime() === today.getTime();
  if (tab === 'yesterday') { const y = new Date(today); y.setDate(y.getDate() - 1); return d.getTime() === y.getTime(); }
  if (tab === 'week') { const w = new Date(today); w.setDate(w.getDate() - 6); return d >= w && d <= today; }
  if (tab === 'month') return d.getMonth() === today.getMonth() && d.getFullYear() === today.getFullYear();
  return true;
}

function SourceTag({ source }) {
  if (source === 'telegram') return <span className="inline-flex items-center gap-1"><Icon name="telegram" size={12} color="#229ED9" /> Telegram</span>;
  return <span className="inline-flex items-center gap-1"><Icon name="globe" size={12} /> WebApp</span>;
}

function RowMenu({ onDelete }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button onClick={() => setOpen(v => !v)} className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-300 hover:bg-gray-100 hover:text-gray-500 transition-colors"><Icon name="dots" size={16} weight="bold" /></button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-8 z-20 w-28 bg-white rounded-xl shadow-lg border border-gray-100 py-1">
            <button onClick={() => { setOpen(false); onDelete(); }} className="w-full text-left px-3 py-2 text-sm text-red-500 hover:bg-red-50 flex items-center gap-2"><Icon name="close" size={14} /> Hapus</button>
          </div>
        </>
      )}
    </div>
  );
}

export default function Transactions() {
  const [transactions, setTransactions] = useState([]);
  const [envelopes, setEnvelopes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');      // envelope id or 'all'
  const [source, setSource] = useState('all');       // 'all' | 'telegram' | 'webapp'
  const [search, setSearch] = useState('');
  const [timeTab, setTimeTab] = useState('all');
  const [sortBy, setSortBy] = useState('terbaru');
  const [pendingCount, setPendingCount] = useState(0);
  const [refreshTick, setRefreshTick] = useState(0);
  const [showMoreFilter, setShowMoreFilter] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [periods, setPeriods] = useState([]);
  const [periodIdx, setPeriodIdx] = useState(null);

  useEffect(() => {
    api.getPeriods(12).then(p => { setPeriods(p); setPeriodIdx(p.length - 1); });
    getPendingCount().then(setPendingCount);
    const syncOnOnline = async () => {
      const results = await flushQueue((item) =>
        api.createTransaction({ envelope_id: item.envelope_id, amount: item.amount, description: item.description, source: item.source, is_private: item.is_private ?? false })
      );
      if (results.some(r => r.success)) { load(); getPendingCount().then(setPendingCount); }
    };
    window.addEventListener('online', syncOnOnline);
    return () => window.removeEventListener('online', syncOnOnline);
  }, []);

  useEffect(() => {
    const onAdded = () => { setRefreshTick(t => t + 1); getPendingCount().then(setPendingCount); };
    window.addEventListener('jatahku:txn-added', onAdded);
    return () => window.removeEventListener('jatahku:txn-added', onAdded);
  }, []);

  const selectedPeriod = periodIdx !== null ? periods[periodIdx] : null;
  const isCurrentPeriod = periodIdx === periods.length - 1;

  const load = () => {
    if (!selectedPeriod) return;
    Promise.all([
      api.getTransactions(null, 500, selectedPeriod.period_start, selectedPeriod.period_end),
      api.getEnvelopes(),
    ]).then(([txn, env]) => { setTransactions(txn); setEnvelopes(env); setLoading(false); });
  };
  useEffect(load, [periodIdx, periods, refreshTick]);

  const handleDelete = async (id) => {
    if (!confirm('Hapus transaksi ini?')) return;
    await api.deleteTransaction(id);
    load();
  };

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  const envById = Object.fromEntries(envelopes.map(e => [e.id, e]));

  const displayed = transactions
    .filter(t => filter === 'all' || t.envelope_id === filter)
    .filter(t => source === 'all' || t.source === source)
    .filter(t => inTimeTab(t.transaction_date, timeTab))
    .filter(t => {
      if (!search.trim()) return true;
      const q = search.toLowerCase();
      return (t.description || '').toLowerCase().includes(q) || (envById[t.envelope_id]?.name || '').toLowerCase().includes(q);
    });

  // Stats from the current view
  const total = displayed.reduce((s, t) => s + Number(t.amount), 0);
  const count = displayed.length;
  const distinctDays = new Set(displayed.map(t => t.transaction_date)).size || 1;
  const avgPerDay = total / distinctDays;
  const largest = displayed.reduce((m, t) => (Number(t.amount) > Number(m?.amount || 0) ? t : m), null);

  // Envelope chip counts from the full period set
  const chipEnvs = envelopes
    .map(e => ({ ...e, _c: transactions.filter(t => t.envelope_id === e.id).length }))
    .filter(e => e._c > 0)
    .sort((a, b) => b._c - a._c);
  const VISIBLE = 5;
  const visibleEnvs = chipEnvs.slice(0, VISIBLE);
  const hiddenEnvs = chipEnvs.slice(VISIBLE);
  const activeInHidden = hiddenEnvs.some(e => e.id === filter);

  // Group by date (desc), sort within each day by sortBy
  const sortWithin = (arr) => [...arr].sort((a, b) => {
    if (sortBy === 'terbesar') return Number(b.amount) - Number(a.amount);
    if (sortBy === 'terkecil') return Number(a.amount) - Number(b.amount);
    const da = new Date(a.created_at || a.transaction_date).getTime();
    const db = new Date(b.created_at || b.transaction_date).getTime();
    return sortBy === 'terlama' ? da - db : db - da;
  });
  const byDate = {};
  displayed.forEach(t => { (byDate[t.transaction_date] = byDate[t.transaction_date] || []).push(t); });
  const dateKeys = Object.keys(byDate).sort((a, b) => b.localeCompare(a));

  const chipCls = (active) => `px-3 py-1.5 rounded-full text-sm font-medium whitespace-nowrap inline-flex items-center gap-1.5 transition-colors ${active ? 'bg-brand-600 text-white' : 'bg-gray-50 text-gray-500 hover:bg-gray-100'}`;
  const countBadge = (active) => `text-xs px-1.5 py-0.5 rounded-full ${active ? 'bg-white/20' : 'bg-gray-200 text-gray-500'}`;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-display font-bold">Transaksi</h1>
          <div className="flex items-center gap-1 mt-0.5">
            <button onClick={() => setPeriodIdx(i => i - 1)} disabled={periodIdx === 0}
              className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-500 text-sm">←</button>
            <span className="text-sm text-gray-500">{selectedPeriod?.label || '...'}</span>
            {isCurrentPeriod && <span className="text-xs px-1.5 py-0.5 bg-brand-50 text-brand-600 rounded font-medium">Sekarang</span>}
            <button onClick={() => setPeriodIdx(i => i + 1)} disabled={isCurrentPeriod}
              className="p-0.5 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-500 text-sm">→</button>
          </div>
          <p className="text-sm text-gray-500 mt-0.5">{transactions.length} transaksi</p>
        </div>
        {pendingCount > 0 && (
          <span style={{ fontSize: '12px', background: '#FEF3C7', color: '#92400E', padding: '4px 10px', borderRadius: '8px', fontWeight: 600 }} className="flex-shrink-0 self-start">⏳ {pendingCount} pending</span>
        )}
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard icon="expense" tone="red" label="Pengeluaran" value={formatShort(total)} sub="Total keluar" />
        <StatCard icon="transaksi" tone="indigo" label="Jumlah Transaksi" value={count} sub="Transaksi" />
        <StatCard icon="users" tone="purple" label="Rata-rata / Hari" value={formatShort(avgPerDay)} sub="Rata-rata per hari" />
        <StatCard icon="wallet" tone="orange" label="Transaksi Terbesar" value={formatShort(largest?.amount || 0)}
          sub={largest ? `${largest.description} · ${new Date(largest.transaction_date).toLocaleDateString('id-ID', { day: 'numeric', month: 'short' })}` : '—'} />
      </div>

      {/* Search + sort */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Icon name="search" size={18} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari transaksi, merchant, atau catatan..."
            className="input !pl-11" />
        </div>
        <div className="relative flex-shrink-0">
          <button onClick={() => setMoreOpen(v => !v)} className="text-sm border border-gray-200 rounded-xl px-3 py-2.5 text-gray-600 bg-white hover:bg-gray-50 inline-flex items-center gap-2">
            Filter Lainnya <Icon name="chevron" size={14} weight="bold" className="text-gray-400" />
          </button>
          {moreOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMoreOpen(false)} />
              <div className="absolute right-0 top-12 z-20 w-48 bg-white rounded-xl shadow-lg border border-gray-100 py-1">
                <p className="px-3 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide">Urutkan</p>
                {SORTS.map(s => (
                  <button key={s.key} onClick={() => { setSortBy(s.key); setMoreOpen(false); }}
                    className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 ${sortBy === s.key ? 'text-brand-600 font-medium' : 'text-gray-600'}`}>{s.label}</button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Envelope + source chips */}
      <div className="flex flex-wrap gap-2 items-center">
        <button onClick={() => setFilter('all')} className={chipCls(filter === 'all')}>Semua <span className={countBadge(filter === 'all')}>{transactions.length}</span></button>
        {visibleEnvs.map(env => (
          <button key={env.id} onClick={() => setFilter(env.id)} className={chipCls(filter === env.id)}>
            <EnvelopeIcon value={env.emoji} size={15} color="currentColor" /> {env.name} <span className={countBadge(filter === env.id)}>{env._c}</span>
          </button>
        ))}
        {hiddenEnvs.length > 0 && (
          <div className="relative">
            <button onClick={() => setShowMoreFilter(v => !v)} className={chipCls(activeInHidden)}>
              {activeInHidden ? <><EnvelopeIcon value={envById[filter]?.emoji} size={15} color="currentColor" /> {envById[filter]?.name}</> : <>+{hiddenEnvs.length} lainnya</>}
              <Icon name="chevron" size={13} weight="bold" />
            </button>
            {showMoreFilter && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowMoreFilter(false)} />
                <div className="absolute left-0 top-full mt-1 z-20 bg-white border border-gray-100 rounded-xl shadow-lg py-1 min-w-[200px] max-h-64 overflow-y-auto">
                  {hiddenEnvs.map(env => (
                    <button key={env.id} onClick={() => { setFilter(env.id); setShowMoreFilter(false); }}
                      className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-50 flex items-center justify-between ${filter === env.id ? 'text-brand-600 font-medium' : 'text-gray-600'}`}>
                      <span className="inline-flex items-center gap-1.5"><EnvelopeIcon value={env.emoji} size={15} color="currentColor" /> {env.name}</span>
                      <span className="text-xs text-gray-400">{env._c}</span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
        <div className="w-px h-5 bg-gray-200 mx-1" />
        <button onClick={() => setSource(source === 'telegram' ? 'all' : 'telegram')} className={chipCls(source === 'telegram')}><Icon name="telegram" size={14} color={source === 'telegram' ? '#fff' : '#229ED9'} /> Telegram</button>
        <button onClick={() => setSource(source === 'webapp' ? 'all' : 'webapp')} className={chipCls(source === 'webapp')}><Icon name="globe" size={14} color={source === 'webapp' ? '#fff' : '#6b7280'} /> WebApp</button>
      </div>

      {/* Time tabs */}
      <div className="flex items-center justify-between gap-2 flex-wrap border-b border-gray-100 pb-2">
        <div className="flex items-center gap-1 flex-wrap">
          {TIME_TABS.map(t => (
            <button key={t.key} onClick={() => setTimeTab(t.key)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${timeTab === t.key ? 'bg-brand-50 text-brand-600' : 'text-gray-500 hover:bg-gray-50'}`}>{t.label}</button>
          ))}
        </div>
        <span className="text-sm text-gray-400 inline-flex items-center gap-1.5"><Icon name="calendar" size={15} /> {selectedPeriod?.label}</span>
      </div>

      {/* List */}
      {displayed.length === 0 ? (
        <div className="card text-center py-12">
          <div className="flex justify-center mb-3"><Icon name="transaksi" size={40} color={BRAND} /></div>
          <p className="text-gray-500">Belum ada transaksi</p>
          <p className="text-sm text-gray-400 mt-1">Kirim "35k starbucks" di Telegram atau tambah di sini</p>
        </div>
      ) : (
        <div className="space-y-4">
          {dateKeys.map(dateStr => {
            const txns = sortWithin(byDate[dateStr]);
            const d = new Date(dateStr + 'T00:00:00');
            const label = d.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long' });
            const dayTotal = txns.reduce((s, t) => s + Number(t.amount), 0);
            return (
              <div key={dateStr}>
                <div className="flex items-center justify-between mb-2 px-1">
                  <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">{label}</h3>
                  <span className="text-xs text-gray-400">{txns.length} transaksi · <span className="text-danger-400 font-medium">-{formatShort(dayTotal)}</span></span>
                </div>
                <div className="card divide-y divide-gray-50 !py-1">
                  {txns.map(txn => {
                    const env = envById[txn.envelope_id];
                    return (
                      <div key={txn.id} className="flex items-center justify-between py-2.5 group">
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(15,110,86,0.07)' }}>
                            <EnvelopeIcon value={env?.emoji} size={20} color={BRAND} />
                          </div>
                          <div className="min-w-0">
                            <p className="text-sm font-semibold truncate">{txn.description}</p>
                            <p className="text-xs text-gray-400 flex items-center gap-1.5 flex-wrap">
                              <span>{env?.name}</span>
                              {txn.created_at && <><span>·</span><span>{new Date(txn.created_at).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' })}</span></>}
                              <span>·</span><SourceTag source={txn.source} />
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          <p className="font-display font-bold text-sm text-danger-400">-{formatShort(txn.amount)}</p>
                          <RowMenu onDelete={() => handleDelete(txn.id)} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
