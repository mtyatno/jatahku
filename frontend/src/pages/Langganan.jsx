import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';

function RecurringModal({ onClose, onSaved, item }) {
  const isEdit = !!item;
  const [envelopes, setEnvelopes] = useState([]);
  const [desc, setDesc] = useState(item?.description || '');
  const [amount, setAmount] = useState(item?.amount ? String(item.amount) : '');
  const [frequency, setFrequency] = useState(item?.frequency || 'monthly');
  const [envelopeId, setEnvelopeId] = useState(item?.envelope_id || '');
  const [nextRun, setNextRun] = useState(item?.next_run || (() => {
    const d = new Date();
    d.setMonth(d.getMonth() + 1);
    return d.toISOString().split('T')[0];
  })());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.getEnvelopeSummary().then(envs => {
      setEnvelopes(envs || []);
      if (!isEdit && envs?.length) setEnvelopeId(envs[0].id);
    });
  }, []);

  const handleSubmit = async () => {
    if (!desc || !amount || !envelopeId) { setError('Lengkapi semua field'); return; }
    setSaving(true);
    setError('');
    const res = await api.request(isEdit ? `/recurring/${item.id}` : '/recurring/', {
      method: isEdit ? 'PUT' : 'POST',
      body: JSON.stringify({
        description: desc,
        amount: Number(amount),
        frequency,
        envelope_id: envelopeId,
        next_run: nextRun,
      }),
    });
    setSaving(false);
    if (res.ok) { onSaved(); onClose(); }
    else { const d = await res.json(); setError(d.detail || 'Gagal menyimpan'); }
  };

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-sm p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-bold text-lg mb-4">{isEdit ? 'Edit Langganan' : 'Tambah Langganan'}</h3>
        <div className="space-y-3">
          <div>
            <label className="label">Nama langganan</label>
            <input type="text" className="input" placeholder="Netflix, Sewa server..." value={desc} onChange={e => setDesc(e.target.value)} />
          </div>
          <div>
            <label className="label">Jumlah (Rp)</label>
            <input type="number" className="input font-mono" placeholder="54000" value={amount} onChange={e => setAmount(e.target.value)} min="1" />
          </div>
          <div>
            <label className="label">Frekuensi</label>
            <select className="input" value={frequency} onChange={e => setFrequency(e.target.value)}>
              <option value="weekly">Mingguan</option>
              <option value="monthly">Bulanan</option>
              <option value="yearly">Tahunan</option>
            </select>
          </div>
          <div>
            <label className="label">Amplop</label>
            <select className="input" value={envelopeId} onChange={e => setEnvelopeId(e.target.value)}>
              {envelopes.map(e => <option key={e.id} value={e.id}>{e.emoji} {e.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Jatuh tempo pertama</label>
            <input type="date" className="input" value={nextRun} onChange={e => setNextRun(e.target.value)} />
          </div>
        </div>
        {error && <div className="mt-3 bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>{error}</div>}
        <div className="flex gap-2 mt-4">
          <button type="button" onClick={onClose} className="btn-outline flex-1">Batal</button>
          <button type="button" onClick={handleSubmit} disabled={saving} className="btn-primary flex-1 disabled:opacity-50">
            {saving ? '...' : 'Simpan'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function Langganan() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editItem, setEditItem] = useState(null);

  const load = () => {
    api.request('/recurring/').then(r => r.ok ? r.json() : []).then(d => { setItems(d); setLoading(false); });
  };
  useEffect(load, []);

  const handleDelete = async (id, name) => {
    if (!confirm(`Hapus langganan "${name}"?`)) return;
    await api.request(`/recurring/${id}`, { method: 'DELETE' });
    load();
  };

  const freqLabel = (f) => {
    const map = { weekly: 'Mingguan', monthly: 'Bulanan', yearly: 'Tahunan' };
    return map[f] || f;
  };

  const totalMonthly = items.reduce((s, i) => {
    const amt = Number(i.amount);
    if (i.frequency === 'monthly') return s + amt;
    if (i.frequency === 'weekly') return s + amt * 4;
    if (i.frequency === 'yearly') return s + amt / 12;
    return s + amt;
  }, 0);

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold">Langganan</h1>
          <p className="text-sm text-gray-500">Pembayaran rutin yang tercatat otomatis</p>
        </div>
        <button onClick={() => setShowAdd(true)} className="btn-primary">+ Tambah</button>
      </div>

      {items.length > 0 && (
        <div className="card">
          <p className="text-xs text-gray-400">Estimasi pengeluaran bulanan</p>
          <p className="font-display text-2xl font-bold text-amber-500">{formatCurrency(totalMonthly)}<span className="text-sm font-normal text-gray-400">/bulan</span></p>
        </div>
      )}

      {items.length === 0 ? (
        <div className="card text-center py-12">
          <p className="text-4xl mb-3">🔄</p>
          <p className="text-gray-500 mb-2">Belum ada langganan</p>
          <p className="text-sm text-gray-400 mb-4">Tambah lewat tombol di atas atau via Telegram</p>
          <button onClick={() => setShowAdd(true)} className="btn-primary">+ Tambah Langganan</button>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map(item => (
            <div key={item.id} className="card group hover:border-brand-200 transition-all">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{item.envelope_emoji || '📁'}</span>
                  <div>
                    <h3 className="font-semibold">{item.description}</h3>
                    <p className="text-xs text-gray-400">
                      {item.envelope_name} · {freqLabel(item.frequency)}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="font-display font-bold text-lg">{formatShort(item.amount)}</p>
                  <p className="text-xs text-gray-400">Next: {new Date(item.next_run).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' })}</p>
                </div>
              </div>
              <div className="flex justify-end gap-3 mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={() => setEditItem(item)}
                  className="text-xs text-brand-500 hover:underline">Edit</button>
                <button onClick={() => handleDelete(item.id, item.description)}
                  className="text-xs text-danger-400 hover:underline">Hapus</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showAdd && <RecurringModal onClose={() => setShowAdd(false)} onSaved={load} />}
      {editItem && <RecurringModal onClose={() => setEditItem(null)} onSaved={load} item={editItem} />}
    </div>
  );
}
