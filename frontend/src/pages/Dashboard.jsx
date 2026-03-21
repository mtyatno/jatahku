import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { formatShort, formatCurrency, daysLeftInMonth } from '../lib/utils';
import ExportButtons from '../components/ExportButtons';
import Onboarding from '../components/Onboarding';

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

  useEffect(() => {
    Promise.all([api.getEnvelopeSummary(), api.getTransactions(null, 10)])
      .then(([env, txn]) => { setEnvelopes(env); setTransactions(txn); setLoading(false); if (env.length === 0) setShowOnboarding(true); });
  }, []);

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  if (showOnboarding) {
    return <Onboarding onDone={() => { setShowOnboarding(false); window.location.reload(); }} />;
  }

  const shared = envelopes.filter(e => !e.is_personal);
  const personal = envelopes.filter(e => e.is_personal);
  const daysLeft = daysLeftInMonth();
  const month = new Date().toLocaleString('id-ID', { month: 'long', year: 'numeric' });

  const totalAllocated = shared.reduce((s, e) => s + Number(e.allocated), 0);
  const totalSpent = shared.reduce((s, e) => s + Number(e.spent), 0);
  const totalRemaining = shared.reduce((s, e) => s + Number(e.remaining), 0);
  const totalBudget = shared.reduce((s, e) => s + Number(e.budget_amount), 0);

  const renderEnvelopeRow = (env) => {
    const allocated = Number(env.allocated);
    const spent = Number(env.spent);
    const remaining = Number(env.remaining);
    const reserved = Number(env.reserved || 0);
    const free = Number(env.free || remaining);
    const spentRatio = env.spent_ratio;
    const fundedRatio = env.funded_ratio;

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
          <div className="bg-amber-50 text-amber-600 text-xs px-3 py-2 rounded-lg">
            💡 Belum ada dana. Alokasikan income dulu.
          </div>
        ) : (
          <>
            <ProgressBar ratio={spentRatio} color={env.is_locked ? 'bg-gray-300' : spentColor} />
            <div className="flex justify-between mt-1.5 text-xs text-gray-400">
              <span>Terpakai {formatShort(spent)}</span>
              {reserved > 0 ? <span>🔄 {formatShort(reserved)} reserved</span> : null}
              <span>Dana {formatShort(allocated)}</span>
            </div>
          </>
        )}
        {env.is_locked && <span className="text-xs text-danger-400 mt-1 inline-block">🔒 Locked</span>}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold">Hai, {user?.name || 'User'}</h1>
        <p className="text-sm text-gray-500">{month} — {daysLeft} hari lagi</p>
      </div>

      <ExportButtons />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card"><p className="text-xs text-gray-400 font-medium">Dana dialokasi</p><p className="font-display text-xl font-bold mt-1">{formatShort(totalAllocated)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Terpakai</p><p className="font-display text-xl font-bold mt-1 text-amber-400">{formatShort(totalSpent)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Sisa</p><p className={`font-display text-xl font-bold mt-1 ${totalRemaining >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>{formatShort(totalRemaining)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Amplop aktif</p><p className="font-display text-xl font-bold mt-1">{envelopes.length}</p></div>
      </div>

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
