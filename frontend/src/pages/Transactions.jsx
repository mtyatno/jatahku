import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';
import { enqueueTransaction, flushQueue, getPendingCount } from '../lib/offlineQueue';

export default function Transactions() {
  const [transactions, setTransactions] = useState([]);
  const [envelopes, setEnvelopes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');
  const [showAdd, setShowAdd] = useState(false);
  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [envelopeId, setEnvelopeId] = useState('');
  const [saving, setSaving] = useState(false);
  const [addError, setAddError] = useState('');
  const [pendingCount, setPendingCount] = useState(0);
  const [showMoreFilter, setShowMoreFilter] = useState(false);

  useEffect(() => {
    getPendingCount().then(setPendingCount);
    const syncOnOnline = async () => {
      const results = await flushQueue((item) =>
        api.createTransaction({ envelope_id: item.envelope_id, amount: item.amount, description: item.description, source: item.source })
      );
      if (results.some(r => r.success)) { load(); getPendingCount().then(setPendingCount); }
    };
    window.addEventListener('online', syncOnOnline);
    return () => window.removeEventListener('online', syncOnOnline);
  }, []);

  const load = () => {
    const isSource = filter === 'telegram' || filter === 'webapp';
    const isEnvelope = filter !== 'all' && !isSource;
    Promise.all([
      api.getTransactions(isEnvelope ? filter : null, 100),
      api.getEnvelopes(),
    ]).then(([txn, env]) => {
      let filtered = txn;
      if (isSource) filtered = txn.filter(t => t.source === filter);
      setTransactions(filtered);
      setEnvelopes(env);
      setLoading(false);
    });
  };
  useEffect(load, [filter]);

  const handleAdd = async (e) => {
    e.preventDefault();
    setSaving(true);
    setAddError('');
    const payload = { envelope_id: envelopeId, amount: Number(amount), description, source: 'webapp' };

    if (!navigator.onLine) {
      await enqueueTransaction(payload);
      setSaving(false);
      setAmount(''); setDescription(''); setEnvelopeId(''); setShowAdd(false);
      getPendingCount().then(setPendingCount);
      return;
    }

    const result = await api.createTransaction(payload);
    setSaving(false);
    if (result.ok) {
      setAmount(''); setDescription(''); setEnvelopeId(''); setShowAdd(false); setAddError('');
      load();
    } else {
      setAddError(result.data?.detail || 'Gagal menyimpan transaksi');
    }
  };

  const handleDelete = async (id) => {
    if (!confirm('Hapus transaksi ini?')) return;
    await api.deleteTransaction(id);
    load();
  };

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
        <div className="flex items-center gap-2">
          {pendingCount > 0 && (
            <span style={{ fontSize: '12px', background: '#FEF3C7', color: '#92400E', padding: '4px 10px', borderRadius: '8px', fontWeight: 600 }}>
              ⏳ {pendingCount} pending
            </span>
          )}
          <button onClick={() => { setShowAdd(!showAdd); setAddError(''); }} className="btn-primary">+ Tambah</button>
        </div>
      </div>

      {showAdd && (
        <div className="card border-brand-200 space-y-3">
          <form onSubmit={handleAdd}>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <div>
                <label className="label">Jumlah (Rp)</label>
                <input type="number" className="input font-mono" placeholder="35000" value={amount} onChange={e => setAmount(e.target.value)} required min="1" />
              </div>
              <div>
                <label className="label">Keterangan</label>
                <input type="text" className="input" placeholder="Starbucks, Gojek..." value={description} onChange={e => setDescription(e.target.value)} required />
              </div>
              <div>
                <label className="label">Amplop</label>
                <select className="input" value={envelopeId} onChange={e => setEnvelopeId(e.target.value)} required>
                  <option value="">Pilih amplop</option>
                  {envelopes.map(env => (
                    <option key={env.id} value={env.id}>{env.emoji} {env.name}</option>
                  ))}
                </select>
              </div>
              <div className="flex items-end gap-2">
                <button type="submit" disabled={saving} className="btn-primary flex-1 disabled:opacity-50">{saving ? '...' : 'Simpan'}</button>
                <button type="button" onClick={() => { setShowAdd(false); setAddError(''); }} className="btn-outline">Batal</button>
              </div>
            </div>
          </form>
          {addError && (
            <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>
              {addError}
            </div>
          )}
        </div>
      )}

      {(() => {
        const VISIBLE = 3;
        const visible = envelopes.slice(0, VISIBLE);
        const hidden = envelopes.slice(VISIBLE);
        const activeInHidden = hidden.some(e => e.id === filter);
        const chipCls = (active) => `px-3 py-1.5 rounded-full text-sm font-medium whitespace-nowrap transition-colors ${active ? 'bg-brand-600 text-white shadow-sm' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`;
        return (
          <div className="flex flex-wrap gap-2 items-center">
            <button onClick={() => setFilter('all')} className={chipCls(filter === 'all')}>Semua</button>
            {visible.map(env => (
              <button key={env.id} onClick={() => setFilter(env.id)} className={chipCls(filter === env.id)}>{env.emoji} {env.name}</button>
            ))}
            {hidden.length > 0 && (
              <div className="relative">
                <button onClick={() => setShowMoreFilter(v => !v)} className={chipCls(activeInHidden)}>
                  {activeInHidden ? `${envelopes.find(e => e.id === filter)?.emoji} ${envelopes.find(e => e.id === filter)?.name}` : `+${hidden.length} lainnya`} ▾
                </button>
                {showMoreFilter && (
                  <div className="absolute left-0 top-full mt-1 z-20 bg-white border border-gray-100 rounded-xl shadow-lg py-1 min-w-[160px]">
                    {hidden.map(env => (
                      <button key={env.id} onClick={() => { setFilter(env.id); setShowMoreFilter(false); }}
                        className={`w-full text-left px-4 py-2 text-sm hover:bg-gray-50 ${filter === env.id ? 'text-brand-600 font-medium' : 'text-gray-600'}`}>
                        {env.emoji} {env.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className="w-px h-5 bg-gray-200 mx-1" />
            <button onClick={() => setFilter('telegram')} className={chipCls(filter === 'telegram')}>📱 Telegram</button>
            <button onClick={() => setFilter('webapp')} className={chipCls(filter === 'webapp')}>🌐 WebApp</button>
          </div>
        );
      })()}

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
                            <p className="text-xs text-gray-400">{env?.name}<span className="mx-1">·</span>{txn.source === 'telegram' ? '📱' : '🌐'}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <p className="font-display font-bold text-sm">-{formatShort(txn.amount)}</p>
                          <button onClick={() => handleDelete(txn.id)} className="text-xs text-gray-300 hover:text-danger-400 opacity-0 group-hover:opacity-100 transition-all" title="Hapus">✕</button>
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
