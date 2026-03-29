import { useState } from 'react';
import { api } from '../lib/api';
import { formatCurrency } from '../lib/utils';

const EMOJI_OPTIONS = ['🍜','🚗','🏠','📱','🎬','📚','👶','🏥','💊','🎁','👕','🐾','🏋️','✈️','🛒','💡','📦','🔧'];

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
  const [step, setStep] = useState(1);
  const [income, setIncome] = useState('');
  const [paydayDay, setPaydayDay] = useState(1);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [envelopes, setEnvelopes] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newEmoji, setNewEmoji] = useState('📦');
  const [newPct, setNewPct] = useState('');

  const incomeNum = Number(income) || 0;
  const totalAllocated = envelopes.reduce((s, e) => s + (Number(e.amount) || 0), 0);
  const remainder = incomeNum - totalAllocated;

  const handleSelectTemplate = (key) => {
    setSelectedTemplate(key);
    if (key === 'custom') {
      setEnvelopes([]);
      setStep(3);
      return;
    }
    const tpl = TEMPLATES[key];
    setEnvelopes(tpl.envelopes.map(env => ({
      emoji: env.emoji,
      name: env.name,
      pct: env.pct,
      amount: Math.round(incomeNum * env.pct / 100),
      isTemplate: true,
    })));
    setStep(3);
  };

  const updateAmount = (idx, val) => {
    const amount = Number(val) || 0;
    const pct = incomeNum > 0 ? Math.round(amount / incomeNum * 100) : 0;
    setEnvelopes(prev => prev.map((e, i) => i === idx ? { ...e, amount, pct } : e));
  };

  const updatePct = (idx, val) => {
    const pct = Number(val) || 0;
    const amount = Math.round(incomeNum * pct / 100);
    setEnvelopes(prev => prev.map((e, i) => i === idx ? { ...e, pct, amount } : e));
  };

  const addEnvelope = () => {
    if (!newName.trim()) return;
    const pct = Number(newPct) || 0;
    const amount = Math.round(incomeNum * pct / 100);
    setEnvelopes(prev => [...prev, {
      emoji: newEmoji, name: newName.trim(), pct, amount, isTemplate: false,
    }]);
    setNewName('');
    setNewPct('');
    setNewEmoji('📦');
    setShowAddForm(false);
  };

  const removeEnvelope = (idx) => {
    setEnvelopes(prev => prev.filter((_, i) => i !== idx));
  };

  const handleCreate = async () => {
    if (envelopes.length === 0 && selectedTemplate === 'custom') { onDone(); return; }
    if (totalAllocated > incomeNum) {
      setError(`Total alokasi (${formatCurrency(totalAllocated)}) melebihi income (${formatCurrency(incomeNum)})`);
      return;
    }
    if (envelopes.length === 0) {
      setError('Tambahkan minimal 1 amplop.');
      return;
    }
    setSaving(true);
    setError('');

    // Save payday_day
    await api.request('/user/profile', {
      method: 'PUT',
      body: JSON.stringify({ payday_day: paydayDay }),
    });

    const envelopeIds = [];
    for (const env of envelopes) {
      const amount = Number(env.amount) || 0;
      const res = await api.createEnvelope({
        name: env.name, emoji: env.emoji,
        budget_amount: amount,
        is_rollover: true, is_personal: false,
      });
      if (res.ok) {
        envelopeIds.push({ id: res.data.id, amount });
      }
    }

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
    sessionStorage.setItem('just_onboarded', '1');
    sessionStorage.removeItem('tg_prompt_dismissed');
    onDone();
  };

  return (
    <div className="max-w-lg mx-auto py-8 pb-28">
      <div className="text-center mb-6">
        <h1 className="font-display text-3xl font-bold text-brand-600 mb-2">Selamat datang!</h1>
        <div className="flex justify-center gap-2 mb-4">
          {[1,2,3].map(s => (
            <div key={s} className={`w-8 h-1.5 rounded-full transition-all ${s <= step ? 'bg-brand-400' : 'bg-gray-200'}`} />
          ))}
        </div>
      </div>

      {step === 1 && (
        <div className="space-y-4">
          <div className="card space-y-5">
            <div>
              <h3 className="font-semibold text-lg mb-1">💰 Berapa income bulanan kamu?</h3>
              <p className="text-sm text-gray-500 mb-3">Total pemasukan per bulan (gaji, freelance, dll).</p>
              <div className="relative">
                <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 font-medium">Rp</span>
                <input type="number" className="input pl-12 text-right font-mono text-xl" placeholder="8000000"
                  value={income} onChange={e => setIncome(e.target.value)} min="0" autoFocus />
              </div>
              {incomeNum > 0 && <p className="text-sm text-brand-600 mt-2 text-right font-medium">{formatCurrency(incomeNum)}/bulan</p>}
            </div>

            <div className="border-t border-gray-100 pt-4">
              <h3 className="font-semibold text-base mb-1">📅 Tanggal gajian kamu?</h3>
              <p className="text-sm text-gray-500 mb-3">Untuk hitung periode budget yang akurat. Bisa diubah nanti.</p>
              <div className="flex items-center gap-3">
                <input
                  type="number" min="1" max="31"
                  className="input w-20 text-center font-mono text-lg"
                  value={paydayDay}
                  onChange={e => setPaydayDay(Math.min(31, Math.max(1, parseInt(e.target.value) || 1)))}
                />
                <span className="text-sm text-gray-500">setiap bulan</span>
              </div>
              <p className="text-xs text-gray-400 mt-2">
                Contoh: isi 25 jika gajian tiap tanggal 25
              </p>
            </div>
          </div>
          <button onClick={() => setStep(2)} disabled={incomeNum <= 0}
            className="btn-primary w-full disabled:opacity-50">Lanjut →</button>
        </div>
      )}

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

      {step === 3 && (
        <div className="space-y-4">
          <button onClick={() => setStep(2)} className="text-sm text-brand-600 hover:underline">← Pilih template lain</button>
          <div className="card">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-500">Income</span>
              <span className="font-display font-bold">{formatCurrency(incomeNum)}</span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full mt-2 mb-1 overflow-hidden">
              <div className="h-full rounded-full transition-all" style={{
                width: `${incomeNum > 0 ? Math.min(Math.round(totalAllocated / incomeNum * 100), 100) : 0}%`,
                background: remainder < 0 ? '#E24B4A' : '#0F6E56',
              }} />
            </div>
            <div className="flex items-center justify-between text-xs text-gray-400">
              <span>Dialokasi: <b className="text-amber-500">{formatCurrency(totalAllocated)}</b></span>
              <span>Tabungan: <b className={remainder >= 0 ? 'text-brand-600' : 'text-red-500'}>{formatCurrency(Math.abs(remainder))}</b></span>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold mb-4">Sesuaikan alokasi per amplop:</h3>
            <div className="space-y-3">
              {envelopes.map((env, i) => (
                <div key={i} className="group">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-lg w-7">{env.emoji}</span>
                    <span className="text-sm font-medium flex-1">{env.name}</span>
                    <button onClick={() => removeEnvelope(i)}
                      className="text-xs text-gray-300 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity">✕</button>
                  </div>
                  <div className="flex items-center gap-2 ml-9">
                    <div className="relative w-20">
                      <input type="number" className="input text-center text-sm py-1.5 pr-6" placeholder="0"
                        value={env.pct || ''} min="0" max="100"
                        onChange={e => updatePct(i, e.target.value)} />
                      <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400">%</span>
                    </div>
                    <div className="relative flex-1">
                      <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">Rp</span>
                      <input type="number" className="input pl-8 text-right font-mono text-sm py-1.5"
                        value={env.amount || ''} min="0"
                        onChange={e => updateAmount(i, e.target.value)} />
                    </div>
                  </div>
                  <div className="ml-9 mt-1">
                    <div className="h-1.5 bg-gray-100 rounded-full">
                      <div className="h-full bg-brand-400 rounded-full transition-all" style={{width: `${Math.min(env.pct || 0, 100)}%`}} />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Add new envelope */}
            {!showAddForm ? (
              <button onClick={() => setShowAddForm(true)}
                className="mt-4 w-full py-2.5 border-2 border-dashed border-gray-200 rounded-xl text-sm text-gray-400 hover:border-brand-400 hover:text-brand-600 transition-colors">
                + Tambah amplop
              </button>
            ) : (
              <div className="mt-4 p-3 border border-brand-200 rounded-xl bg-brand-50/30 space-y-3">
                <div className="flex gap-2">
                  <select value={newEmoji} onChange={e => setNewEmoji(e.target.value)}
                    className="input w-16 text-center text-lg py-1.5">
                    {EMOJI_OPTIONS.map(em => <option key={em} value={em}>{em}</option>)}
                  </select>
                  <input type="text" className="input flex-1 text-sm py-1.5" placeholder="Nama amplop"
                    value={newName} onChange={e => setNewName(e.target.value)} autoFocus />
                  <div className="relative w-20">
                    <input type="number" className="input text-center text-sm py-1.5 pr-6" placeholder="0"
                      value={newPct} min="0" max="100"
                      onChange={e => setNewPct(e.target.value)} />
                    <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400">%</span>
                  </div>
                </div>
                {newPct && incomeNum > 0 && (
                  <p className="text-xs text-gray-500 ml-1">= {formatCurrency(Math.round(incomeNum * (Number(newPct) || 0) / 100))}</p>
                )}
                <div className="flex gap-2">
                  <button onClick={addEnvelope} disabled={!newName.trim()}
                    className="btn-primary text-sm py-1.5 flex-1 disabled:opacity-50">Tambah</button>
                  <button onClick={() => { setShowAddForm(false); setNewName(''); setNewPct(''); }}
                    className="text-sm text-gray-400 hover:text-gray-600 px-3">Batal</button>
                </div>
              </div>
            )}

            {remainder > 0 && (
              <div className="flex items-center gap-3 mt-4 pt-3 border-t border-gray-100">
                <span className="text-xl w-7">💰</span>
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

          <button onClick={handleCreate} disabled={saving || remainder < 0 || envelopes.length === 0}
            className="btn-primary w-full disabled:opacity-50">
            {saving ? 'Membuat amplop & alokasi...' : `Mulai Budgeting → (${envelopes.length} amplop)`}
          </button>
        </div>
      )}
    </div>
  );
}
