import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';

export default function Allocate() {
  const [envelopes, setEnvelopes] = useState([]);
  const [incomes, setIncomes] = useState([]);
  const [loading, setLoading] = useState(true);

  // Income form
  const [incomeAmount, setIncomeAmount] = useState('');
  const [incomeDesc, setIncomeDesc] = useState('');
  const [savingIncome, setSavingIncome] = useState(false);

  // Allocation state
  const [allocating, setAllocating] = useState(null); // income id
  const [allocations, setAllocations] = useState({});
  const [savingAlloc, setSavingAlloc] = useState(false);

  const load = () => {
    Promise.all([
      api.getEnvelopes(),
      api.getIncomes(),
    ]).then(([env, inc]) => {
      setEnvelopes(env);
      setIncomes(inc);
      setLoading(false);
    });
  };

  useEffect(load, []);

  const handleAddIncome = async (e) => {
    e.preventDefault();
    setSavingIncome(true);
    const result = await api.createIncome({
      amount: Number(incomeAmount),
      description: incomeDesc,
    });
    setSavingIncome(false);
    if (result.ok) {
      setIncomeAmount('');
      setIncomeDesc('');
      load();
    }
  };

  const handleAllocate = async (incomeId) => {
    const items = Object.entries(allocations)
      .filter(([, amt]) => Number(amt) > 0)
      .map(([envId, amt]) => ({ envelope_id: envId, amount: Number(amt) }));

    if (items.length === 0) return;

    setSavingAlloc(true);
    const result = await api.allocateIncome(incomeId, items);
    setSavingAlloc(false);
    if (result.ok) {
      setAllocating(null);
      setAllocations({});
      load();
    }
  };

  const totalAllocated = Object.values(allocations).reduce((s, v) => s + (Number(v) || 0), 0);

  const distributeEvenly = (incomeAmount) => {
    if (envelopes.length === 0) return;
    const perEnvelope = Math.floor(incomeAmount / envelopes.length);
    const newAlloc = {};
    envelopes.forEach((env, i) => {
      newAlloc[env.id] = i === 0
        ? incomeAmount - perEnvelope * (envelopes.length - 1)
        : perEnvelope;
    });
    setAllocations(newAlloc);
  };

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-display font-bold">Alokasi Income</h1>
        <p className="text-sm text-gray-500">Catat income dan distribusikan ke amplop</p>
      </div>

      {/* Add income */}
      <form onSubmit={handleAddIncome} className="card border-brand-200">
        <h3 className="font-semibold text-sm mb-3">Catat income baru</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="label">Jumlah (Rp)</label>
            <input
              type="number"
              className="input font-mono"
              placeholder="8500000"
              value={incomeAmount}
              onChange={e => setIncomeAmount(e.target.value)}
              required
              min="1"
            />
          </div>
          <div>
            <label className="label">Keterangan</label>
            <input
              type="text"
              className="input"
              placeholder="Gaji Maret, Freelance..."
              value={incomeDesc}
              onChange={e => setIncomeDesc(e.target.value)}
              required
            />
          </div>
          <div className="flex items-end">
            <button type="submit" disabled={savingIncome} className="btn-primary w-full disabled:opacity-50">
              {savingIncome ? '...' : 'Catat Income'}
            </button>
          </div>
        </div>
      </form>

      {/* Income list */}
      <div>
        <h2 className="font-display font-bold text-lg mb-3">Riwayat income</h2>
        {incomes.length === 0 ? (
          <div className="card text-center py-8">
            <p className="text-gray-400">Belum ada income tercatat</p>
          </div>
        ) : (
          <div className="space-y-3">
            {incomes.map(inc => (
              <div key={inc.id} className="card">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-semibold">{inc.description}</p>
                    <p className="text-xs text-gray-400">
                      {new Date(inc.income_date).toLocaleDateString('id-ID', {
                        day: 'numeric', month: 'long', year: 'numeric',
                      })}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="font-display font-bold text-lg text-brand-600">
                      +{formatShort(inc.amount)}
                    </p>
                    {allocating !== inc.id && (
                      <button
                        onClick={() => {
                          setAllocating(inc.id);
                          setAllocations({});
                        }}
                        className="text-xs text-brand-600 hover:underline mt-1"
                      >
                        Alokasikan →
                      </button>
                    )}
                  </div>
                </div>

                {/* Allocation form */}
                {allocating === inc.id && (
                  <div className="mt-4 pt-4 border-t border-gray-100">
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="text-sm font-semibold">Distribusikan ke amplop</h4>
                      <button
                        onClick={() => distributeEvenly(Number(inc.amount))}
                        className="text-xs text-brand-600 hover:underline"
                      >
                        Bagi rata
                      </button>
                    </div>

                    <div className="space-y-2">
                      {envelopes.map(env => (
                        <div key={env.id} className="flex items-center gap-3">
                          <span className="text-lg w-8">{env.emoji || '📁'}</span>
                          <span className="text-sm font-medium flex-1">{env.name}</span>
                          <div className="relative w-40">
                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">Rp</span>
                            <input
                              type="number"
                              className="input pl-8 text-right font-mono text-sm"
                              placeholder="0"
                              value={allocations[env.id] || ''}
                              onChange={e => setAllocations(prev => ({
                                ...prev,
                                [env.id]: e.target.value,
                              }))}
                              min="0"
                            />
                          </div>
                        </div>
                      ))}
                    </div>

                    <div className="flex items-center justify-between mt-4 pt-3 border-t border-gray-100">
                      <div className="text-sm">
                        <span className="text-gray-400">Dialokasikan: </span>
                        <span className={`font-display font-bold ${
                          totalAllocated > Number(inc.amount) ? 'text-danger-400' : 'text-brand-600'
                        }`}>
                          {formatCurrency(totalAllocated)}
                        </span>
                        <span className="text-gray-400"> / {formatCurrency(inc.amount)}</span>
                        {totalAllocated < Number(inc.amount) && (
                          <span className="text-xs text-amber-400 ml-2">
                            (sisa {formatShort(Number(inc.amount) - totalAllocated)})
                          </span>
                        )}
                      </div>
                      <div className="flex gap-2">
                        <button
                          onClick={() => { setAllocating(null); setAllocations({}); }}
                          className="btn-outline text-xs"
                        >
                          Batal
                        </button>
                        <button
                          onClick={() => handleAllocate(inc.id)}
                          disabled={savingAlloc || totalAllocated === 0 || totalAllocated > Number(inc.amount)}
                          className="btn-primary text-xs disabled:opacity-50"
                        >
                          {savingAlloc ? '...' : 'Alokasikan'}
                        </button>
                      </div>
                    </div>
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
