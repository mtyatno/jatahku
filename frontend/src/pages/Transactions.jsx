import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';

export default function Transactions() {
  const [transactions, setTransactions] = useState([]);
  const [envelopes, setEnvelopes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [showAdd, setShowAdd] = useState(false);

  // Add form state
  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [envelopeId, setEnvelopeId] = useState('');
  const [saving, setSaving] = useState(false);

  const load = () => {
    Promise.all([
      api.getTransactions(filter === 'all' ? null : filter, 100),
      api.getEnvelopes(),
    ]).then(([txn, env]) => {
      setTransactions(txn);
      setEnvelopes(env);
      setLoading(false);
    });
  };

  useEffect(load, [filter]);

  const handleAdd = async (e) => {
    e.preventDefault();
    setSaving(true);
    const result = await api.createTransaction({
      envelope_id: envelopeId,
      amount: Number(amount),
      description,
      source: 'webapp',
    });
    setSaving(false);
    if (result.ok) {
      setAmount('');
      setDescription('');
      setShowAdd(false);
      load();
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Hapus transaksi ini?')) return;
    await api.deleteTransaction(id);
    load();
  };

  // Group by date
  const grouped = {};
  transactions.forEach(txn => {
    const dateKey = txn.transaction_date;
    if (!grouped[dateKey]) grouped[dateKey] = [];
    grouped[dateKey].push(txn);
  });

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold">Transaksi</h1>
          <p className="text-sm text-gray-500">{transactions.length} transaksi</p>
        </div>
        <button onClick={() => setShowAdd(!showAdd)} className="btn-primary">
          + Tambah
        </button>
      </div>

      {/* Quick add form */}
      {showAdd && (
        <form onSubmit={handleAdd} className="card border-brand-200 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div>
              <label className="label">Jumlah (Rp)</label>
              <input
                type="number"
                className="input font-mono"
                placeholder="35000"
                value={amount}
                onChange={e => setAmount(e.target.value)}
                required
                min="1"
              />
            </div>
            <div>
              <label className="label">Keterangan</label>
              <input
                type="text"
                className="input"
                placeholder="Starbucks, Gojek..."
                value={description}
                onChange={e => setDescription(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="label">Amplop</label>
              <select
                className="input"
                value={envelopeId}
                onChange={e => setEnvelopeId(e.target.value)}
                required
              >
                <option value="">Pilih amplop</option>
                {envelopes.map(env => (
                  <option key={env.id} value={env.id}>
                    {env.emoji} {env.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex items-end gap-2">
              <button type="submit" disabled={saving} className="btn-primary flex-1 disabled:opacity-50">
                {saving ? '...' : 'Simpan'}
              </button>
              <button type="button" onClick={() => setShowAdd(false)} className="btn-outline">
                Batal
              </button>
            </div>
          </div>
        </form>
      )}

      {/* Filter */}
      <div className="flex gap-2 overflow-x-auto pb-1">
        <button
          onClick={() => setFilter('all')}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
            filter === 'all' ? 'bg-brand-50 text-brand-600' : 'text-gray-400 hover:bg-gray-50'
          }`}
        >
          Semua
        </button>
        {envelopes.map(env => (
          <button
            key={env.id}
            onClick={() => setFilter(env.id)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
              filter === env.id ? 'bg-brand-50 text-brand-600' : 'text-gray-400 hover:bg-gray-50'
            }`}
          >
            {env.emoji} {env.name}
          </button>
        ))}
      </div>

      {/* Transaction list */}
      {transactions.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-4xl mb-3">📝</p>
          <p className="text-gray-500">Belum ada transaksi</p>
          <p className="text-sm text-gray-400 mt-1">Kirim "35k starbucks" di Telegram atau tambah di sini</p>
        </div>
      ) : (
        <div className="space-y-4">
          {Object.entries(grouped).map(([dateStr, txns]) => {
            const d = new Date(dateStr);
            const label = d.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long' });
            const dayTotal = txns.reduce((s, t) => s + Number(t.amount), 0);

            return (
              <div key={dateStr}>
                <div className="flex items-center justify-between mb-2 px-1">
                  <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">{label}</h3>
                  <span className="text-xs font-mono text-gray-400">-{formatShort(dayTotal)}</span>
                </div>
                <div className="card divide-y divide-gray-50">
                  {txns.map(txn => {
                    const env = envelopes.find(e => e.id === txn.envelope_id);
                    return (
                      <div key={txn.id} className="flex items-center justify-between py-3 first:pt-0 last:pb-0 group">
                        <div className="flex items-center gap-3">
                          <span className="text-lg">{env?.emoji || '📁'}</span>
                          <div>
                            <p className="text-sm font-medium">{txn.description}</p>
                            <p className="text-xs text-gray-400">
                              {env?.name}
                              <span className="mx-1">·</span>
                              {txn.source === 'telegram' ? '📱' : '🌐'}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <p className="font-display font-bold text-sm">-{formatShort(txn.amount)}</p>
                          <button
                            onClick={() => handleDelete(txn.id)}
                            className="text-xs text-gray-300 hover:text-danger-400 opacity-0 group-hover:opacity-100 transition-all"
                            title="Hapus"
                          >
                            ✕
                          </button>
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
