import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';

export default function Langganan() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

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
      <div>
        <h1 className="text-2xl font-display font-bold">Langganan</h1>
        <p className="text-sm text-gray-500">Pembayaran rutin yang tercatat otomatis</p>
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
          <p className="text-sm text-gray-400">Tambah via Telegram: kirim pesan seperti<br/><code className="text-brand-600">langganan netflix 54k</code> atau <code className="text-brand-600">sewa server 250k tiap bulan</code></p>
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
              <div className="flex justify-end mt-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={() => handleDelete(item.id, item.description)}
                  className="text-xs text-danger-400 hover:underline">Hapus langganan</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="card bg-gray-50">
        <p className="text-sm text-gray-500">💡 Tambah langganan lewat Telegram:</p>
        <div className="mt-2 space-y-1">
          <p className="text-xs font-mono text-brand-600">langganan netflix 54k</p>
          <p className="text-xs font-mono text-brand-600">sewa server 250k tiap bulan</p>
          <p className="text-xs font-mono text-brand-600">kontrak rumah 5jt tiap tahun</p>
        </div>
      </div>
    </div>
  );
}
