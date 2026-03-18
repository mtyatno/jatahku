import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { useAuth } from '../hooks/useAuth';
import { formatCurrency, formatShort, spentRatio, budgetStatus, daysLeftInMonth } from '../lib/utils';

function ProgressBar({ ratio, status }) {
  const colors = { safe: 'bg-brand-400', warning: 'bg-amber-400', danger: 'bg-danger-400' };
  return (
    <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
      <div className={`h-full rounded-full transition-all duration-500 ${colors[status]}`}
        style={{ width: `${Math.max(ratio * 100, 1)}%` }} />
    </div>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const [envelopes, setEnvelopes] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [allTxns, setAllTxns] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.getEnvelopes(),
      api.getTransactions(null, 10),
      api.getTransactions(null, 500),
    ]).then(([env, txn, all]) => {
      setEnvelopes(env);
      setTransactions(txn);
      setAllTxns(all);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return <div className="text-center py-12 text-gray-400">Loading...</div>;
  }

  const now = new Date();
  const daysLeft = daysLeftInMonth();
  const month = now.toLocaleString('id-ID', { month: 'long', year: 'numeric' });

  const getSpent = (envId) => {
    return allTxns
      .filter(t => {
        const d = new Date(t.transaction_date);
        return t.envelope_id === envId && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
      })
      .reduce((s, t) => s + Number(t.amount), 0);
  };

  const totalBudget = envelopes.reduce((s, e) => s + Number(e.budget_amount), 0);
  const totalSpent = envelopes.reduce((s, e) => s + getSpent(e.id), 0);
  const totalRemaining = totalBudget - totalSpent;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold">Hai, {user?.name || 'User'}</h1>
        <p className="text-sm text-gray-500">{month} — {daysLeft} hari lagi</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="card">
          <p className="text-xs text-gray-400 font-medium">Total budget</p>
          <p className="font-display text-xl font-bold mt-1">{formatShort(totalBudget)}</p>
        </div>
        <div className="card">
          <p className="text-xs text-gray-400 font-medium">Terpakai</p>
          <p className="font-display text-xl font-bold mt-1 text-amber-400">{formatShort(totalSpent)}</p>
        </div>
        <div className="card">
          <p className="text-xs text-gray-400 font-medium">Sisa</p>
          <p className={`font-display text-xl font-bold mt-1 ${totalRemaining >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>
            {formatShort(totalRemaining)}
          </p>
        </div>
        <div className="card">
          <p className="text-xs text-gray-400 font-medium">Amplop aktif</p>
          <p className="font-display text-xl font-bold mt-1">{envelopes.length}</p>
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-display font-bold text-lg">Amplop</h2>
          <Link to="/envelopes" className="text-sm text-brand-600 font-medium hover:underline">Lihat semua →</Link>
        </div>
        {envelopes.length === 0 ? (
          <div className="card text-center py-8">
            <p className="text-gray-400 mb-3">Belum ada amplop</p>
            <Link to="/envelopes" className="btn-primary inline-block">Buat Amplop</Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {envelopes.map(env => {
              const spent = getSpent(env.id);
              const budget = Number(env.budget_amount);
              const remaining = budget - spent;
              const ratio = spentRatio(spent, budget);
              const status = budgetStatus(spent, budget);
              return (
                <div key={env.id} className="card hover:border-brand-200 transition-colors">
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{env.emoji || '📁'}</span>
                      <span className="font-semibold text-sm">{env.name}</span>
                    </div>
                    <span className={`font-display font-bold text-sm ${
                      status === 'danger' ? 'text-danger-400' : status === 'warning' ? 'text-amber-400' : 'text-brand-600'
                    }`}>{formatShort(remaining)}</span>
                  </div>
                  <ProgressBar ratio={ratio} status={status} />
                  <div className="flex justify-between mt-1.5 text-xs text-gray-400">
                    <span>Terpakai {formatShort(spent)}</span>
                    <span>Budget {formatShort(budget)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

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
                      <p className="text-xs text-gray-400">{env?.name} · {txn.source === 'telegram' ? '📱 Telegram' : '🌐 WebApp'}</p>
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
