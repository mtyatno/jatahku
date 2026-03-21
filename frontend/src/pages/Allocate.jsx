import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';

export default function Allocate() {
  const [envelopes, setEnvelopes] = useState([]);
  const [incomes, setIncomes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  // Income + allocation form
  const [incomeAmount, setIncomeAmount] = useState('');
  const [incomeDesc, setIncomeDesc] = useState('Gaji');
  const [allocations, setAllocations] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const load = () => {
    Promise.all([api.getEnvelopeSummary(), api.getIncomes()])
      .then(([env, inc]) => { setEnvelopes(env); setIncomes(inc); setLoading(false); });
  };
  useEffect(load, []);

  const incomeNum = Number(incomeAmount) || 0;
  const totalAllocated = Object.values(allocations).reduce((s, v) => s + (Number(v) || 0), 0);
  const remainder = incomeNum - totalAllocated;

  const distributeByBudget = () => {
    if (envelopes.length === 0 || incomeNum <= 0) return;
    const totalBudget = envelopes.reduce((s, e) => s + Number(e.budget_amount), 0);
    const newAlloc = {};
    if (totalBudget > 0) {
      envelopes.forEach(env => {
        const ratio = Number(env.budget_amount) / totalBudget;
        newAlloc[env.id] = Math.round(incomeNum * ratio);
      });
    } else {
      const per = Math.floor(incomeNum / envelopes.length);
      envelopes.forEach((env, i) => {
        newAlloc[env.id] = i === 0 ? incomeNum - per * (envelopes.length - 1) : per;
      });
    }
    setAllocations(newAlloc);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (totalAllocated > incomeNum) {
      setError('Total alokasi melebihi income');
      return;
    }
    setSaving(true);
    setError('');

    const items = Object.entries(allocations)
      .filter(([, amt]) => Number(amt) > 0)
      .map(([envId, amt]) => ({ envelope_id: envId, amount: Number(amt) }));

    const res = await api.request('/incomes/', {
      method: 'POST',
      body: JSON.stringify({
        amount: incomeNum,
        source: incomeDesc,
        allocations: items,
      }),
    });

    setSaving(false);
    if (res.ok) {
      setIncomeAmount('');
      setIncomeDesc('Gaji');
      setAllocations({});
      setShowForm(false);
      load();
    } else {
      const data = await res.json();
      setError(data.detail || 'Gagal menyimpan');
    }
  };

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-display font-bold">Alokasi Income</h1>
          <p className="text-sm text-gray-500">Catat income dan distribusikan ke amplop</p>
        </div>
        {!showForm && (
          <button onClick={() => setShowForm(true)} className="btn-primary">+ Income Baru</button>
        )}
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="card border-brand-200 space-y-4">
          <h3 className="font-semibold">💰 Catat income & alokasi</h3>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="label">Jumlah income (Rp)</label>
              <input type="number" className="input font-mono" placeholder="8000000"
                value={incomeAmount} onChange={e => { setIncomeAmount(e.target.value); setAllocations({}); }} required min="1" />
              {incomeNum > 0 && <p className="text-xs text-brand-600 mt-1">{formatCurrency(incomeNum)}</p>}
            </div>
            <div>
              <label className="label">Keterangan</label>
              <input type="text" className="input" placeholder="Gaji, Freelance, Bonus..."
                value={incomeDesc} onChange={e => setIncomeDesc(e.target.value)} required />
            </div>
          </div>

          {incomeNum > 0 && (
            <>
              <div className="flex gap-3">
                <div className="card flex-1 !p-3"><p className="text-xs text-gray-400">Income</p><p className="font-display font-bold">{formatShort(incomeNum)}</p></div>
                <div className="card flex-1 !p-3"><p className="text-xs text-gray-400">Dialokasikan</p><p className="font-display font-bold text-amber-500">{formatShort(totalAllocated)}</p></div>
                <div className="card flex-1 !p-3"><p className="text-xs text-gray-400">→ Tabungan</p><p className={`font-display font-bold ${remainder >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>{formatShort(Math.abs(remainder))}</p></div>
              </div>

              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold">Distribusikan ke amplop:</p>
                <button type="button" onClick={distributeByBudget} className="text-xs text-brand-600 hover:underline">Bagi proporsional</button>
              </div>

              <div className="space-y-2">
                {envelopes.filter(e => e.name !== 'Tabungan').map(env => {
                  const val = allocations[env.id] || 0;
                  const pct = incomeNum > 0 ? Math.round(Number(val) / incomeNum * 100) : 0;
                  return (
                    <div key={env.id} className="flex items-center gap-3">
                      <span className="text-lg w-8">{env.emoji || '📁'}</span>
                      <div className="flex-1">
                        <div className="flex justify-between">
                          <span className="text-sm font-medium">{env.name}</span>
                          <span className="text-xs text-gray-400">{pct}%</span>
                        </div>
                        <div className="h-1 bg-gray-100 rounded-full mt-1">
                          <div className="h-full bg-brand-400 rounded-full transition-all" style={{width: `${Math.min(pct, 100)}%`}} />
                        </div>
                      </div>
                      <div className="relative w-32">
                        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">Rp</span>
                        <input type="number" className="input pl-8 text-right font-mono text-sm"
                          value={val || ''} min="0"
                          onChange={e => setAllocations(prev => ({...prev, [env.id]: Number(e.target.value) || 0}))} />
                      </div>
                    </div>
                  );
                })}
                {remainder > 0 && (
                  <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
                    <span className="text-lg w-8">💰</span>
                    <span className="text-sm font-medium flex-1">Tabungan <span className="text-xs text-gray-400">(otomatis)</span></span>
                    <span className="font-mono text-sm font-bold text-brand-600">{formatCurrency(remainder)}</span>
                  </div>
                )}
              </div>
            </>
          )}

          {error && <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>{error}</div>}
          {remainder < 0 && <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>Total alokasi melebihi income</div>}

          <div className="flex gap-2">
            <button type="button" onClick={() => { setShowForm(false); setError(''); }} className="btn-outline flex-1">Batal</button>
            <button type="submit" disabled={saving || incomeNum <= 0 || remainder < 0} className="btn-primary flex-1 disabled:opacity-50">
              {saving ? 'Menyimpan...' : 'Simpan Income & Alokasi'}
            </button>
          </div>
        </form>
      )}

      {/* Income history - read only */}
      <div>
        <h2 className="font-display font-bold text-lg mb-3">Riwayat income</h2>
        {incomes.length === 0 ? (
          <div className="card text-center py-8"><p className="text-gray-400">Belum ada income tercatat</p></div>
        ) : (
          <div className="space-y-3">
            {incomes.map(inc => (
              <div key={inc.id} className="card">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <p className="font-semibold">{inc.source}</p>
                    <p className="text-xs text-gray-400">{new Date(inc.date).toLocaleDateString('id-ID', { day: 'numeric', month: 'long', year: 'numeric' })}</p>
                  </div>
                  <p className="font-display font-bold text-lg text-brand-600">+{formatShort(inc.amount)}</p>
                </div>
                {inc.allocations && inc.allocations.length > 0 && (
                  <div className="flex flex-wrap gap-2 pt-2 border-t border-gray-50">
                    {inc.allocations.map((a, i) => (
                      <span key={i} className={`text-xs px-2 py-1 rounded-md ${a.auto ? 'bg-amber-50 text-amber-600' : 'bg-brand-50 text-brand-600'}`}>
                        {a.emoji} {a.envelope} {formatShort(a.amount)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
