import { useState } from 'react';
import { api } from '../lib/api';
import { formatCurrency } from '../lib/utils';

const TEMPLATES = {
  karyawan: {
    label: '💼 Karyawan', desc: 'Budget standar pekerja kantoran',
    envelopes: [
      { emoji: '🍜', name: 'Makan', pct: 20 },
      { emoji: '🚗', name: 'Transport', pct: 7 },
      { emoji: '🎬', name: 'Hiburan', pct: 5 },
      { emoji: '📱', name: 'Tagihan', pct: 8 },
    ],
  },
  mahasiswa: {
    label: '🎓 Mahasiswa', desc: 'Budget hemat mahasiswa',
    envelopes: [
      { emoji: '🍜', name: 'Makan', pct: 30 },
      { emoji: '🚗', name: 'Transport', pct: 10 },
      { emoji: '🎬', name: 'Hiburan', pct: 10 },
      { emoji: '📚', name: 'Kuliah', pct: 15 },
    ],
  },
  keluarga: {
    label: '👨‍👩‍👧 Keluarga', desc: 'Budget lengkap rumah tangga',
    envelopes: [
      { emoji: '🍜', name: 'Makan', pct: 25 },
      { emoji: '🚗', name: 'Transport', pct: 10 },
      { emoji: '🏠', name: 'Rumah', pct: 20 },
      { emoji: '📱', name: 'Tagihan', pct: 8 },
      { emoji: '🎬', name: 'Hiburan', pct: 5 },
    ],
  },
  custom: {
    label: '✏️ Custom', desc: 'Buat amplop sendiri dari nol',
    envelopes: [],
  },
};

export default function Onboarding({ onDone }) {
  const [step, setStep] = useState(1); // 1=income, 2=template, 3=allocate
  const [income, setIncome] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [allocations, setAllocations] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const incomeNum = Number(income) || 0;
  const totalAllocated = Object.values(allocations).reduce((s, v) => s + (Number(v) || 0), 0);
  const remainder = incomeNum - totalAllocated;

  const handleSelectTemplate = (key) => {
    setSelectedTemplate(key);
    if (key === 'custom') {
      setAllocations({});
      setStep(3);
      return;
    }
    const tpl = TEMPLATES[key];
    const allocs = {};
    tpl.envelopes.forEach((env, i) => {
      allocs[i] = Math.round(incomeNum * env.pct / 100);
    });
    setAllocations(allocs);
    setStep(3);
  };

  const handleCreate = async () => {
    if (selectedTemplate === 'custom') { onDone(); return; }
    if (totalAllocated > incomeNum) {
      setError(`Total alokasi (${formatCurrency(totalAllocated)}) melebihi income (${formatCurrency(incomeNum)})`);
      return;
    }
    setSaving(true);
    setError('');

    const tpl = TEMPLATES[selectedTemplate];

    // 1. Create envelopes
    const envelopeIds = [];
    for (let i = 0; i < tpl.envelopes.length; i++) {
      const env = tpl.envelopes[i];
      const amount = Number(allocations[i]) || 0;
      const res = await api.createEnvelope({
        name: env.name, emoji: env.emoji,
        budget_amount: amount,
        is_rollover: true, is_personal: false,
      });
      if (res.ok) {
        envelopeIds.push({ id: res.data.id, amount });
      }
    }

    // 2. Create income + allocate
    const incomeAllocations = envelopeIds
      .filter(e => e.amount > 0)
      .map(e => ({ envelope_id: e.id, amount: e.amount }));

    await api.request('/incomes/', {
      method: 'POST',
      body: JSON.stringify({
        amount: incomeNum,
        source: 'Gaji',
        allocations: incomeAllocations,
      }),
    });

    setSaving(false);
    onDone();
  };

  return (
    <div className="max-w-lg mx-auto py-8">
      <div className="text-center mb-6">
        <h1 className="font-display text-3xl font-bold text-brand-600 mb-2">Selamat datang!</h1>
        <div className="flex justify-center gap-2 mb-4">
          {[1,2,3].map(s => (
            <div key={s} className={`w-8 h-1.5 rounded-full transition-all ${s <= step ? 'bg-brand-400' : 'bg-gray-200'}`} />
          ))}
        </div>
      </div>

      {/* Step 1: Income */}
      {step === 1 && (
        <div className="space-y-4">
          <div className="card">
            <h3 className="font-semibold text-lg mb-1">💰 Berapa income bulanan kamu?</h3>
            <p className="text-sm text-gray-500 mb-4">Total pemasukan per bulan (gaji, freelance, dll).</p>
            <div className="relative">
              <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 font-medium">Rp</span>
              <input type="number" className="input pl-12 text-right font-mono text-xl" placeholder="8000000"
                value={income} onChange={e => setIncome(e.target.value)} min="0" autoFocus />
            </div>
            {incomeNum > 0 && <p className="text-sm text-brand-600 mt-2 text-right font-medium">{formatCurrency(incomeNum)}/bulan</p>}
          </div>
          <button onClick={() => setStep(2)} disabled={incomeNum <= 0}
            className="btn-primary w-full disabled:opacity-50">
            Lanjut →
          </button>
        </div>
      )}

      {/* Step 2: Template */}
      {step === 2 && (
        <div className="space-y-4">
          <button onClick={() => setStep(1)} className="text-sm text-brand-600 hover:underline">← Ubah income</button>
          <div className="card">
            <p className="text-sm text-gray-400 mb-1">Income bulanan</p>
            <p className="font-display text-xl font-bold text-brand-600">{formatCurrency(incomeNum)}</p>
          </div>
          <h3 className="font-semibold text-lg">Pilih template amplop:</h3>
          <div className="grid grid-cols-1 gap-3">
            {Object.entries(TEMPLATES).map(([key, tpl]) => (
              <button key={key} onClick={() => handleSelectTemplate(key)}
                className="card text-left hover:border-brand-400 transition-all group">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-semibold">{tpl.label}</h3>
                    <p className="text-xs text-gray-500">{tpl.desc}</p>
                    {tpl.envelopes.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-2">
                        {tpl.envelopes.map((e, i) => (
                          <span key={i} className="text-xs bg-gray-50 px-2 py-0.5 rounded-md text-gray-500">
                            {e.emoji} {e.name} ({e.pct}%)
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <span className="text-gray-300 group-hover:text-brand-400 text-xl">→</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Step 3: Allocate */}
      {step === 3 && selectedTemplate !== 'custom' && (
        <div className="space-y-4">
          <button onClick={() => setStep(2)} className="text-sm text-brand-600 hover:underline">← Pilih template lain</button>
          <div className="flex gap-3">
            <div className="card flex-1">
              <p className="text-xs text-gray-400">Income</p>
              <p className="font-display text-lg font-bold">{formatCurrency(incomeNum)}</p>
            </div>
            <div className="card flex-1">
              <p className="text-xs text-gray-400">Dialokasikan</p>
              <p className="font-display text-lg font-bold text-amber-500">{formatCurrency(totalAllocated)}</p>
            </div>
            <div className="card flex-1">
              <p className="text-xs text-gray-400">→ Tabungan</p>
              <p className={`font-display text-lg font-bold ${remainder >= 0 ? 'text-brand-600' : 'text-danger-400'}`}>{formatCurrency(Math.abs(remainder))}</p>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold mb-4">Sesuaikan alokasi per amplop:</h3>
            <div className="space-y-3">
              {TEMPLATES[selectedTemplate].envelopes.map((env, i) => {
                const val = allocations[i] || 0;
                const pct = incomeNum > 0 ? Math.round(val / incomeNum * 100) : 0;
                return (
                  <div key={i} className="flex items-center gap-3">
                    <span className="text-xl w-8">{env.emoji}</span>
                    <div className="flex-1">
                      <div className="flex justify-between">
                        <span className="text-sm font-medium">{env.name}</span>
                        <span className="text-xs text-gray-400">{pct}%</span>
                      </div>
                      <div className="h-1.5 bg-gray-100 rounded-full mt-1">
                        <div className="h-full bg-brand-400 rounded-full transition-all" style={{width: `${Math.min(pct, 100)}%`}} />
                      </div>
                    </div>
                    <div className="relative w-32">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">Rp</span>
                      <input type="number" className="input pl-8 text-right font-mono text-sm"
                        value={val || ''} min="0"
                        onChange={e => setAllocations(prev => ({...prev, [i]: Number(e.target.value) || 0}))} />
                    </div>
                  </div>
                );
              })}
            </div>
            {remainder > 0 && (
              <div className="flex items-center gap-3 mt-4 pt-3 border-t border-gray-100">
                <span className="text-xl w-8">💰</span>
                <span className="text-sm font-medium flex-1">Tabungan <span className="text-xs text-gray-400">(otomatis)</span></span>
                <span className="font-mono text-sm font-bold text-brand-600">{formatCurrency(remainder)}</span>
              </div>
            )}
          </div>

          {error && <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>{error}</div>}

          {remainder < 0 && (
            <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>
              Total alokasi melebihi income sebesar {formatCurrency(Math.abs(remainder))}. Kurangi salah satu amplop.
            </div>
          )}

          <button onClick={handleCreate} disabled={saving || remainder < 0}
            className="btn-primary w-full disabled:opacity-50">
            {saving ? 'Membuat amplop & alokasi...' : `Mulai Budgeting →`}
          </button>
        </div>
      )}

      {step === 3 && selectedTemplate === 'custom' && (
        <div className="space-y-4">
          <button onClick={() => setStep(2)} className="text-sm text-brand-600 hover:underline">← Pilih template lain</button>
          <div className="card text-center py-8">
            <p className="text-4xl mb-3">✏️</p>
            <p className="text-gray-500 mb-2">Buat amplop sendiri di halaman Amplop.</p>
            <p className="text-sm text-gray-400">Jangan lupa alokasikan income ke setiap amplop.</p>
          </div>
          <button onClick={handleCreate} className="btn-primary w-full">Lanjut ke Dashboard →</button>
        </div>
      )}
    </div>
  );
}
