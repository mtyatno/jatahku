import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { formatShort, daysLeftInMonth } from '../lib/utils';

function ProgressBar({ ratio, status }) {
  const colors = { safe: 'bg-brand-400', warning: 'bg-amber-400', danger: 'bg-danger-400' };
  return (
    <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
      <div className={`h-full rounded-full transition-all duration-500 ${colors[status]}`} style={{ width: `${Math.max(ratio * 100, 1)}%` }} />
    </div>
  );
}
function getStatus(r) { return r >= 0.9 ? 'danger' : r >= 0.7 ? 'warning' : 'safe'; }

export default function Dashboard() {
  const { user } = useAuth();
  const [envelopes, setEnvelopes] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api.getEnvelopeSummary(), api.getTransactions(null, 10)])
      .then(([env, txn]) => { setEnvelopes(env); setTransactions(txn); setLoading(false); });
  }, []);

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  const shared = envelopes.filter(e => !e.is_personal);
  const personal = envelopes.filter(e => e.is_personal);
  const daysLeft = daysLeftInMonth();
  const month = new Date().toLocaleString('id-ID', { month: 'long', year: 'numeric' });
  const sharedBudget = shared.reduce((s, e) => s + Number(e.budget_amount), 0);
  const sharedSpent = shared.reduce((s, e) => s + Number(e.spent), 0);
  const sharedRemaining = sharedBudget - sharedSpent;
  const personalBudget = personal.reduce((s, e) => s + Number(e.budget_amount), 0);
  const personalSpent = personal.reduce((s, e) => s + Number(e.spent), 0);
  const personalRemaining = personalBudget - personalSpent;

  const renderEnvelopeRow = (env) => {
    const status = getStatus(env.spent_ratio);
    return (
      <div key={env.id} className="card hover:border-brand-200 transition-colors">
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-lg">{env.emoji || '📁'}</span>
            <span className="font-semibold text-sm">{env.name}</span>
          </div>
          <span className={`font-display font-bold text-sm ${status === 'danger' ? 'text-danger-400' : status === 'warning' ? 'text-amber-400' : 'text-brand-600'}`}>{formatShort(env.remaining)}</span>
        </div>
        <ProgressBar ratio={env.spent_ratio} status={status} />
        <div className="flex justify-between mt-1.5 text-xs text-gray-400"><span>Terpakai {formatShort(env.spent)}</span><span>Budget {formatShort(env.budget_amount)}</span></div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div><h1 className="text-2xl font-display font-bold">Hai, {user?.name || 'User'}</h1><p className="text-sm text-gray-500">{month} — {daysLeft} hari lagi</p></div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card"><p className="text-xs text-gray-400 font-medium">Budget shared</p><p className="font-display text-xl font-bold mt-1">{formatShort(sharedBudget)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Terpakai</p><p className="font-display text-xl font-bold mt-1 text-amber-400">{formatShort(sharedSpent)}</p></div>
        <div className="card"><p className="text-xs text-gray-400 font-medium">Sisa shared</p><p className={`font-display text-xl font-bold mt-1 ${sharedRemaining >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>{formatShort(sharedRemaining)}</p></div>
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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
            <div className="card"><p className="text-xs text-gray-400 font-medium">Budget personal</p><p className="font-display text-lg font-bold mt-1">{formatShort(personalBudget)}</p></div>
            <div className="card"><p className="text-xs text-gray-400 font-medium">Sisa</p><p className="font-display text-lg font-bold mt-1 text-brand-600">{formatShort(personalRemaining)}</p></div>
          </div>
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
                  <div className="flex items-center gap-3"><span className="text-lg">{env?.emoji || '📁'}</span><div><p className="text-sm font-medium">{txn.description}</p><p className="text-xs text-gray-400">{env?.name} · {txn.source === 'telegram' ? '📱 Telegram' : '🌐 WebApp'}</p></div></div>
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
