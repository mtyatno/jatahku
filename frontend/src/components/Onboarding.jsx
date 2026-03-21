import { useState } from 'react';
import { api } from '../lib/api';
import { formatCurrency } from '../lib/utils';

const TEMPLATES = {
  karyawan: {
    label: '💼 Karyawan',
    desc: 'Budget standar untuk pekerja kantoran',
    envelopes: [
      { emoji: '🍜', name: 'Makan', budget: 1500000 },
      { emoji: '🚗', name: 'Transport', budget: 500000 },
      { emoji: '🎬', name: 'Hiburan', budget: 300000 },
      { emoji: '📱', name: 'Tagihan', budget: 500000 },
      { emoji: '💰', name: 'Tabungan', budget: 1000000 },
    ],
  },
  mahasiswa: {
    label: '🎓 Mahasiswa',
    desc: 'Budget hemat untuk mahasiswa',
    envelopes: [
      { emoji: '🍜', name: 'Makan', budget: 800000 },
      { emoji: '🚗', name: 'Transport', budget: 200000 },
      { emoji: '🎬', name: 'Hiburan', budget: 200000 },
      { emoji: '📚', name: 'Kuliah', budget: 300000 },
    ],
  },
  keluarga: {
    label: '👨‍👩‍👧 Keluarga',
    desc: 'Budget lengkap untuk rumah tangga',
    envelopes: [
      { emoji: '🍜', name: 'Makan', budget: 3000000 },
      { emoji: '🚗', name: 'Transport', budget: 1000000 },
      { emoji: '🏠', name: 'Rumah', budget: 2000000 },
      { emoji: '📱', name: 'Tagihan', budget: 800000 },
      { emoji: '🎬', name: 'Hiburan', budget: 500000 },
      { emoji: '💰', name: 'Tabungan', budget: 2000000 },
    ],
  },
  custom: {
    label: '✏️ Custom',
    desc: 'Buat amplop sendiri dari nol',
    envelopes: [],
  },
};

export default function Onboarding({ onDone }) {
  const [selected, setSelected] = useState(null);
  const [saving, setSaving] = useState(false);
  const [editAmounts, setEditAmounts] = useState({});

  const handleSelect = (key) => {
    setSelected(key);
    const amounts = {};
    TEMPLATES[key].envelopes.forEach((e, i) => { amounts[i] = e.budget; });
    setEditAmounts(amounts);
  };

  const handleCreate = async () => {
    if (selected === 'custom') {
      onDone();
      return;
    }
    setSaving(true);
    const template = TEMPLATES[selected];
    for (let i = 0; i < template.envelopes.length; i++) {
      const env = template.envelopes[i];
      await api.createEnvelope({
        name: env.name,
        emoji: env.emoji,
        budget_amount: editAmounts[i] || env.budget,
        is_rollover: true,
        is_personal: false,
      });
    }
    setSaving(false);
    onDone();
  };

  const totalBudget = selected && selected !== 'custom'
    ? TEMPLATES[selected].envelopes.reduce((s, e, i) => s + (editAmounts[i] || e.budget), 0)
    : 0;

  return (
    <div className="max-w-lg mx-auto py-8">
      <div className="text-center mb-8">
        <h1 className="font-display text-3xl font-bold text-brand-600 mb-2">Selamat datang!</h1>
        <p className="text-gray-500">Pilih template untuk mulai budgeting.</p>
      </div>

      {!selected ? (
        <div className="grid grid-cols-1 gap-3">
          {Object.entries(TEMPLATES).map(([key, tpl]) => (
            <button key={key} onClick={() => handleSelect(key)}
              className="card text-left hover:border-brand-400 transition-all group">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-semibold text-lg">{tpl.label}</h3>
                  <p className="text-sm text-gray-500">{tpl.desc}</p>
                  {tpl.envelopes.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {tpl.envelopes.map((e, i) => (
                        <span key={i} className="text-xs bg-gray-50 px-2 py-0.5 rounded-md text-gray-500">
                          {e.emoji} {e.name}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <span className="text-gray-300 group-hover:text-brand-400 text-xl transition-colors">→</span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          <button onClick={() => setSelected(null)} className="text-sm text-brand-600 hover:underline">← Pilih template lain</button>

          <div className="card">
            <h3 className="font-semibold text-lg mb-1">{TEMPLATES[selected].label}</h3>
            <p className="text-sm text-gray-500 mb-4">{TEMPLATES[selected].desc}</p>

            {selected === 'custom' ? (
              <p className="text-sm text-gray-400">Kamu bisa buat amplop sendiri di halaman Amplop.</p>
            ) : (
              <div className="space-y-3">
                <p className="text-xs text-gray-400 font-medium uppercase tracking-wider">Sesuaikan budget:</p>
                {TEMPLATES[selected].envelopes.map((env, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="text-xl w-8">{env.emoji}</span>
                    <span className="text-sm font-medium flex-1">{env.name}</span>
                    <div className="relative w-36">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">Rp</span>
                      <input type="number" className="input pl-8 text-right font-mono text-sm"
                        value={editAmounts[i] || ''} min="0"
                        onChange={e => setEditAmounts(prev => ({ ...prev, [i]: Number(e.target.value) }))} />
                    </div>
                  </div>
                ))}
                <div className="pt-3 border-t border-gray-100 flex justify-between text-sm">
                  <span className="text-gray-400">Total budget bulanan:</span>
                  <span className="font-display font-bold text-brand-600">{formatCurrency(totalBudget)}</span>
                </div>
              </div>
            )}
          </div>

          <button onClick={handleCreate} disabled={saving}
            className="btn-primary w-full text-center disabled:opacity-50">
            {saving ? 'Membuat amplop...' : selected === 'custom' ? 'Lanjut ke Dashboard' : `Buat ${TEMPLATES[selected].envelopes.length} Amplop`}
          </button>
        </div>
      )}
    </div>
  );
}
