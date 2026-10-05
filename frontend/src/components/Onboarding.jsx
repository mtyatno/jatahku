import { useState } from 'react';
import { api } from '../lib/api';
import { formatCurrency } from '../lib/utils';
import { EnvelopeIcon } from './Icon';

const EMOJI_OPTIONS = ['🍜','🚗','🏠','📱','🎬','📚','👶','🏥','💊','🎁','👕','🐾','🏋️','✈️','🛒','💡','📦','🔧'];

const TEMPLATES = {
  driver_ojol: {
    label: '🛵 Driver & Kurir',
    desc: 'Operasional narik harian & perawatan motor',
    envelopes: [
      { emoji: '⛽', name: 'Bensin & Operasional', pct: 25, purpose: 'expense' },
      { emoji: '🍜', name: 'Makan di Jalan', pct: 20, purpose: 'expense' },
      { emoji: '📱', name: 'Pulsa & Kuota Narik', pct: 8, purpose: 'expense' },
      { emoji: '🔧', name: 'Servis & Ganti Oli', pct: 12, purpose: 'sinking_fund' },
      { emoji: '🏠', name: 'Kebutuhan Rumah', pct: 25, purpose: 'expense' },
      { emoji: '💰', name: 'Tabungan / Darurat', pct: 10, purpose: 'saving' },
    ],
  },
  freelance_bisnis: {
    label: '🛠️ Freelance & Usaha Mandiri',
    desc: 'Biaya hidup fleksibel & alat kerja',
    envelopes: [
      { emoji: '💻', name: 'Operasional & Internet', pct: 15, purpose: 'expense' },
      { emoji: '🍜', name: 'Biaya Hidup Harian', pct: 35, purpose: 'expense' },
      { emoji: '🏠', name: 'Sewa / Tagihan', pct: 20, purpose: 'expense' },
      { emoji: '🔧', name: 'Alat Kerja & Maintenance', pct: 10, purpose: 'sinking_fund' },
      { emoji: '💰', name: 'Dana Darurat & Pajak', pct: 20, purpose: 'saving' },
    ],
  },
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
  const [incomeType, setIncomeType] = useState('monthly'); // 'daily' | 'weekly' | 'monthly' | 'irregular'
  const [dailyIncome, setDailyIncome] = useState('');
  const [workingDays, setWorkingDays] = useState(26);
  const [weeklyIncome, setWeeklyIncome] = useState('');
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
  const [newPurpose, setNewPurpose] = useState('expense');
  const [initialCashMode, setInitialCashMode] = useState('zero');
  const [startingCash, setStartingCash] = useState('');

  const handleIncomeTypeChange = (type) => {
    setIncomeType(type);
    setInitialCashMode(type === 'monthly' ? 'full' : 'zero');
    setStartingCash('');
    if (type !== 'monthly') {
      setPaydayDay(1);
    }
  };

  const guessPurpose = (name) => {
    const n = name.toLowerCase();
    const savingKw = ['tabungan','nikah','darurat','liburan','umroh','rumah','mobil','motor','pendidikan','sekolah','kuliah','dp','menikah','haji','investasi','pensiun'];
    const sinkingKw = ['servis','pajak','asuransi','perpanjang','tahunan','semester','langganan','renewal','hosting','domain','stnk','bpjs','service','maintenance','perawatan'];
    if (savingKw.some(kw => n.includes(kw))) return 'saving';
    if (sinkingKw.some(kw => n.includes(kw))) return 'sinking_fund';
    return 'expense';
  };

  const incomeNum = incomeType === 'daily'
    ? (Number(dailyIncome) || 0) * (Number(workingDays) || 0)
    : incomeType === 'weekly'
    ? (Number(weeklyIncome) || 0) * 4
    : (incomeType === 'monthly' || incomeType === 'irregular')
    ? (Number(income) || 0)
    : 0;
  const totalAllocated = envelopes.reduce((s, e) => s + (Number(e.amount) || 0), 0);
  const remainder = incomeNum - totalAllocated;

  const handleSelectTemplate = (key) => {
    setSelectedTemplate(key);
    setInitialCashMode(incomeType === 'monthly' ? 'full' : 'zero');
    setStartingCash('');
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
      purpose: env.purpose || 'expense',
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
      purpose: newPurpose,
    }]);
    setNewName('');
    setNewPct('');
    setNewEmoji('📦');
    setNewPurpose('expense');
    setShowAddForm(false);
  };

  const removeEnvelope = (idx) => {
    setEnvelopes(prev => prev.filter((_, i) => i !== idx));
  };

  const handleCreate = async () => {
    if (envelopes.length === 0 && selectedTemplate === 'custom') {
      sessionStorage.setItem('just_onboarded', '1');
      sessionStorage.setItem('onboarded_income_mode', incomeType);
      onDone();
      return;
    }
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

    try {
      // 1. Save payday_day & income_type: payday 1 for daily/weekly, or chosen paydayDay for monthly
      const finalPayday = incomeType === 'monthly' ? paydayDay : 1;
      await api.request('/user/profile', {
        method: 'PUT',
        body: JSON.stringify({ payday_day: finalPayday, income_type: incomeType }),
      });

      // 2. Create envelopes with target monthly budget_amount
      const envelopeIds = [];
      for (const env of envelopes) {
        const targetAmount = Number(env.amount) || 0;
        const res = await api.createEnvelope({
          name: env.name,
          emoji: env.emoji,
          budget_amount: targetAmount,
          is_rollover: true,
          is_personal: false,
          purpose: env.purpose || 'expense',
        });
        if (res.ok) {
          envelopeIds.push({
            id: res.data.id,
            targetAmount,
            pct: Number(env.pct) || (incomeNum > 0 ? Math.round((targetAmount / incomeNum) * 100) : 0),
          });
        }
      }

      // 3. Conditional Income Record
      const startingCashNum = Number(startingCash) || 0;
      if (incomeType === 'monthly' && initialCashMode === 'full') {
        // Monthly salary full initial allocation
        const incomeAllocations = envelopeIds
          .filter(e => e.targetAmount > 0)
          .map(e => ({ envelope_id: e.id, amount: e.targetAmount }));

        await api.request('/incomes/', {
          method: 'POST',
          body: JSON.stringify({
            amount: incomeNum,
            source: 'Gaji',
            allocations: incomeAllocations,
          }),
        });
      } else if (initialCashMode === 'custom' && startingCashNum > 0) {
        // Prorate starting cash across envelopes according to percentage
        const incomeAllocations = envelopeIds.map(e => ({
          envelope_id: e.id,
          amount: Math.round(startingCashNum * (e.pct / 100)),
        })).filter(e => e.amount > 0);

        const totalAlloc = incomeAllocations.reduce((s, a) => s + a.amount, 0);
        if (totalAlloc > startingCashNum && incomeAllocations.length > 0) {
          incomeAllocations[0].amount = Math.max(0, incomeAllocations[0].amount - (totalAlloc - startingCashNum));
        }

        await api.request('/incomes/', {
          method: 'POST',
          body: JSON.stringify({
            amount: startingCashNum,
            source: 'Saldo Awal',
            allocations: incomeAllocations.filter(e => e.amount > 0),
          }),
        });
      }
      // If initialCashMode === 'zero': NO income is created.

      setSaving(false);
      sessionStorage.setItem('just_onboarded', '1');
      sessionStorage.setItem('onboarded_income_mode', incomeType);
      onDone();
    } catch (err) {
      console.error('Failed to finish onboarding:', err);
      setError('Gagal menyiapkan amplop. Silakan periksa koneksi dan coba lagi.');
      setSaving(false);
    }
  };

  const isCustomInvalid = initialCashMode === 'custom' && !(Number(startingCash) > 0);
  const isSubmitDisabled = saving || remainder < 0 || envelopes.length === 0 || isCustomInvalid;

  const getSubmitButtonLabel = () => {
    if (saving) return 'Membuat amplop & alokasi...';
    if (initialCashMode === 'zero') {
      return 'Mulai Budgeting (Saldo Rp 0) →';
    }
    if (initialCashMode === 'custom') {
      const cash = Number(startingCash) || 0;
      return cash > 0
        ? `Mulai Budgeting (Kas ${formatCurrency(cash)}) →`
        : 'Mulai Budgeting (Saldo Rp 0) →';
    }
    return `Mulai Budgeting → (${envelopes.length} amplop)`;
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
              <p className="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">Pola Pemasukan</p>
              <div className="grid grid-cols-2 gap-1.5 p-1 bg-gray-100 rounded-xl">
                {[
                  { key: 'monthly', label: '💼 Bulanan', desc: 'Gaji/Honorar tetap' },
                  { key: 'weekly', label: '📅 Mingguan', desc: 'Mingguan teratur' },
                  { key: 'daily', label: '🛵 Harian', desc: 'Ojek/Dagang/Harian' },
                  { key: 'irregular', label: '📊 Tidak Tentu', desc: 'Fluktuatif' },
                ].map(tab => (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => handleIncomeTypeChange(tab.key)}
                    className={`py-2.5 px-2 rounded-lg text-sm font-medium transition-all text-center flex flex-col items-center gap-0.5 ${
                      incomeType === tab.key
                        ? 'bg-white text-brand-600 shadow-sm font-semibold'
                        : 'text-gray-500 hover:text-gray-900'
                    }`}
                  >
                    <span>{tab.label}</span>
                    <span className="text-xs text-gray-400 font-normal">{tab.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            {incomeType === 'daily' && (
              <div className="space-y-4">
                <div>
                  <h3 className="font-semibold text-base mb-1">Rata-rata pendapatan bersih per hari</h3>
                  <p className="text-sm text-gray-500 mb-3">Estimasi pemasukan harian setelah operasional/bensin.</p>
                  <div className="relative">
                    <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 font-medium">Rp</span>
                    <input
                      type="number"
                      className="input pl-12 text-right font-mono text-xl"
                      placeholder="150000"
                      value={dailyIncome}
                      onChange={e => setDailyIncome(e.target.value)}
                      min="0"
                      autoFocus
                    />
                  </div>
                </div>

                <div className="border-t border-gray-100 pt-4">
                  <h3 className="font-semibold text-base mb-1">Hari narik/kerja per bulan</h3>
                  <p className="text-sm text-gray-500 mb-3">Jumlah hari kerja aktif dalam sebulan.</p>
                  <div className="flex items-center gap-3">
                    <input
                      type="number"
                      min="1"
                      max="31"
                      className="input w-24 text-center font-mono text-lg"
                      value={workingDays}
                      onChange={e => {
                        const v = e.target.value;
                        if (v === '') { setWorkingDays(''); return; }
                        setWorkingDays(Math.min(31, Math.max(1, parseInt(v) || 1)));
                      }}
                    />
                    <span className="text-sm text-gray-500">hari / bulan (standar 26 hari)</span>
                  </div>
                </div>

                {incomeNum > 0 && (
                  <div className="p-3 bg-brand-50/60 rounded-xl border border-brand-100 flex items-center justify-between">
                    <div>
                      <p className="text-xs text-brand-700 font-medium">Target Budget Bulanan</p>
                      <p className="text-xs text-gray-500">
                        {dailyIncome ? formatCurrency(Number(dailyIncome) || 0) : 'Rp 0'} × {workingDays || 0} hari
                      </p>
                    </div>
                    <p className="font-display text-lg font-bold text-brand-600">
                      {formatCurrency(incomeNum)}<span className="text-xs font-normal text-gray-500">/bulan</span>
                    </p>
                  </div>
                )}

                <div className="text-xs text-gray-500 flex items-center gap-2 bg-gray-50 p-3 rounded-xl border border-gray-100">
                  <span className="text-base">🗓️</span>
                  <span>Siklus evaluasi budget dihitung per tanggal 1 setiap bulan.</span>
                </div>
              </div>
            )}

            {incomeType === 'weekly' && (
              <div className="space-y-4">
                <div>
                  <h3 className="font-semibold text-base mb-1">Rata-rata pemasukan per minggu</h3>
                  <p className="text-sm text-gray-500 mb-3">Estimasi pemasukan mingguan rata-rata.</p>
                  <div className="relative">
                    <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 font-medium">Rp</span>
                    <input
                      type="number"
                      className="input pl-12 text-right font-mono text-xl"
                      placeholder="1500000"
                      value={weeklyIncome}
                      onChange={e => setWeeklyIncome(e.target.value)}
                      min="0"
                      autoFocus
                    />
                  </div>
                </div>

                {incomeNum > 0 && (
                  <div className="p-3 bg-brand-50/60 rounded-xl border border-brand-100 flex items-center justify-between">
                    <div>
                      <p className="text-xs text-brand-700 font-medium">Target Budget Bulanan</p>
                      <p className="text-xs text-gray-500">
                        {weeklyIncome ? formatCurrency(Number(weeklyIncome) || 0) : 'Rp 0'} × 4 minggu
                      </p>
                    </div>
                    <p className="font-display text-lg font-bold text-brand-600">
                      {formatCurrency(incomeNum)}<span className="text-xs font-normal text-gray-500">/bulan</span>
                    </p>
                  </div>
                )}

                <div className="text-xs text-gray-500 flex items-center gap-2 bg-gray-50 p-3 rounded-xl border border-gray-100">
                  <span className="text-base">🗓️</span>
                  <span>Siklus evaluasi budget dihitung per tanggal 1 setiap bulan.</span>
                </div>
              </div>
            )}

            {incomeType === 'monthly' && (
              <div className="space-y-5">
                <div>
                  <h3 className="font-semibold text-lg mb-1">💰 Berapa income bulanan kamu?</h3>
                  <p className="text-sm text-gray-500 mb-3">Total pemasukan per bulan (gaji, freelance, dll).</p>
                  <div className="relative">
                    <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 font-medium">Rp</span>
                    <input
                      type="number"
                      className="input pl-12 text-right font-mono text-xl"
                      placeholder="8000000"
                      value={income}
                      onChange={e => setIncome(e.target.value)}
                      min="0"
                      autoFocus
                    />
                  </div>
                  {incomeNum > 0 && (
                    <p className="text-sm text-brand-600 mt-2 text-right font-medium">
                      {formatCurrency(incomeNum)}/bulan
                    </p>
                  )}
                </div>

                <div className="border-t border-gray-100 pt-4">
                  <h3 className="font-semibold text-base mb-1">📅 Tanggal gajian kamu?</h3>
                  <p className="text-sm text-gray-500 mb-3">Untuk hitung periode budget yang akurat. Bisa diubah nanti.</p>
                  <div className="flex items-center gap-3">
                    <input
                      type="number"
                      min="1"
                      max="31"
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
            )}

            {incomeType === 'irregular' && (
              <div className="space-y-4">
                <div>
                  <h3 className="font-semibold text-base mb-1">📊 Estimasi rata-rata income bulanan</h3>
                  <p className="text-sm text-gray-500 mb-3">Lihat pendapatan 3 bulan lalu, hitung rata-ratanya.</p>
                  <div className="relative">
                    <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 font-medium">Rp</span>
                    <input
                      type="number"
                      className="input pl-12 text-right font-mono text-xl"
                      placeholder="5000000"
                      value={income}
                      onChange={e => setIncome(e.target.value)}
                      min="0"
                      autoFocus
                    />
                  </div>
                </div>

                {incomeNum > 0 && (
                  <div className="p-3 bg-brand-50/60 rounded-xl border border-brand-100 flex items-center justify-between">
                    <div>
                      <p className="text-xs text-brand-700 font-medium">Target Budget Bulanan</p>
                      <p className="text-xs text-gray-500">
                        Rata-rata pendapatan bulan-bulan sebelumnya
                      </p>
                    </div>
                    <p className="font-display text-lg font-bold text-brand-600">
                      {formatCurrency(incomeNum)}<span className="text-xs font-normal text-gray-500">/bulan</span>
                    </p>
                  </div>
                )}

                <div className="text-xs text-gray-500 flex items-center gap-2 bg-gray-50 p-3 rounded-xl border border-gray-100">
                  <span className="text-base">🗓️</span>
                  <span>Siklus evaluasi budget dihitung per tanggal 1 setiap bulan. Bisa diubah nanti di Pengaturan.</span>
                </div>
              </div>
            )}
          </div>
          <button
            onClick={() => setStep(2)}
            disabled={incomeNum <= 0}
            className="btn-primary w-full disabled:opacity-50"
          >
            Lanjut →
          </button>
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
                    <span className="w-7 flex justify-center"><EnvelopeIcon value={env.emoji} size={20} /></span>
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
                    value={newName} onChange={e => { setNewName(e.target.value); setNewPurpose(guessPurpose(e.target.value)); }} autoFocus />
                  <div className="relative w-20">
                    <input type="number" className="input text-center text-sm py-1.5 pr-6" placeholder="0"
                      value={newPct} min="0" max="100"
                      onChange={e => setNewPct(e.target.value)} />
                    <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400">%</span>
                  </div>
                </div>
                <div className="flex gap-1.5">
                  {[
                    { key: 'expense', label: '💰 Expense' },
                    { key: 'saving', label: '🎯 Saving' },
                    { key: 'sinking_fund', label: '📅 Sinking' },
                  ].map(p => (
                    <button key={p.key} type="button" onClick={() => setNewPurpose(p.key)}
                      className={`flex-1 px-2 py-1.5 rounded-lg text-xs font-medium transition-all ${
                        newPurpose === p.key ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                      }`}>
                      {p.label}
                    </button>
                  ))}
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
                <span className="text-sm font-medium flex-1">Tabungan (Saving) <span className="text-xs text-gray-400">(otomatis)</span></span>
                <span className="font-mono text-sm font-bold text-brand-600">{formatCurrency(remainder)}</span>
              </div>
            )}
          </div>

          {/* Initial Balance Selection Card */}
          <div className="card space-y-3">
            <div>
              <h3 className="font-semibold text-base mb-1">
                {incomeType === 'monthly' ? 'Saldo Awal Bulan Ini' : 'Saldo Awal Saat Ini'}
              </h3>
              <p className="text-xs text-gray-500">
                {incomeType === 'monthly'
                  ? 'Pilih apakah gaji bulan ini sudah cair atau ingin mulai dari Rp 0.'
                  : 'Pilih kondisi uang kas yang kamu miliki saat ini.'}
              </p>
            </div>

            <div className="space-y-2">
              {incomeType !== 'monthly' ? (
                <>
                  <label
                    className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                      initialCashMode === 'zero'
                        ? 'border-brand-500 bg-brand-50/40 ring-1 ring-brand-500'
                        : 'border-gray-200 hover:border-gray-300 bg-white'
                    }`}
                  >
                    <input
                      type="radio"
                      name="initialCashMode"
                      value="zero"
                      checked={initialCashMode === 'zero'}
                      onChange={() => setInitialCashMode('zero')}
                      className="mt-0.5 text-brand-600 focus:ring-brand-500"
                    />
                    <div className="flex-1">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-sm font-semibold text-gray-900">Mulai saldo dari Rp 0</span>
                        <span className="text-xs bg-brand-100 text-brand-700 font-medium px-2 py-0.5 rounded-full">Direkomendasikan</span>
                      </div>
                      <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                        Amplop disiapkan dengan target jatah bulanan. Saldo akan diisi setiap kali kamu mencatat pemasukan harian via tombol <strong>+ Pemasukan</strong> di dashboard.
                      </p>
                    </div>
                  </label>

                  <label
                    className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                      initialCashMode === 'custom'
                        ? 'border-brand-500 bg-brand-50/40 ring-1 ring-brand-500'
                        : 'border-gray-200 hover:border-gray-300 bg-white'
                    }`}
                  >
                    <input
                      type="radio"
                      name="initialCashMode"
                      value="custom"
                      checked={initialCashMode === 'custom'}
                      onChange={() => setInitialCashMode('custom')}
                      className="mt-0.5 text-brand-600 focus:ring-brand-500"
                    />
                    <div className="flex-1">
                      <span className="text-sm font-semibold text-gray-900">Ada uang pegangan hari ini</span>
                      <p className="text-xs text-gray-500 mt-0.5">
                        Masukkan uang kas yang ada sekarang untuk langsung dibagi ke amplop.
                      </p>
                    </div>
                  </label>

                  {initialCashMode === 'custom' && (
                    <div className="p-3 bg-gray-50 rounded-xl border border-gray-200 space-y-3 mt-1">
                      <div>
                        <label className="text-xs font-semibold text-gray-700 block mb-1">
                          Uang pegangan saat ini:
                        </label>
                        <div className="relative">
                          <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 font-medium text-sm">Rp</span>
                          <input
                            type="number"
                            className="input pl-10 text-right font-mono text-base py-1.5"
                            placeholder="100000"
                            value={startingCash}
                            onChange={e => setStartingCash(e.target.value)}
                            min="0"
                            autoFocus
                          />
                        </div>
                      </div>

                      {Number(startingCash) > 0 && envelopes.length > 0 && (
                        <div>
                          <p className="text-xs font-semibold text-gray-600 mb-1.5">
                            Simulasi alokasi saldo awal ({formatCurrency(Number(startingCash))}):
                          </p>
                          <div className="space-y-1 bg-white p-2.5 rounded-lg border border-gray-200">
                            {envelopes.map((env, i) => {
                              const alloc = Math.round((Number(startingCash) || 0) * ((Number(env.pct) || 0) / 100));
                              return (
                                <div key={i} className="flex items-center justify-between text-xs py-1 border-b border-gray-50 last:border-0">
                                  <span className="flex items-center gap-1.5 truncate">
                                    <span>{env.emoji}</span>
                                    <span className="truncate">{env.name}</span>
                                    <span className="text-gray-400">({env.pct || 0}%)</span>
                                  </span>
                                  <span className="font-mono font-medium text-brand-600 shrink-0 ml-2">
                                    {formatCurrency(alloc)}
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <label
                    className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                      initialCashMode === 'full'
                        ? 'border-brand-500 bg-brand-50/40 ring-1 ring-brand-500'
                        : 'border-gray-200 hover:border-gray-300 bg-white'
                    }`}
                  >
                    <input
                      type="radio"
                      name="initialCashMode"
                      value="full"
                      checked={initialCashMode === 'full'}
                      onChange={() => setInitialCashMode('full')}
                      className="mt-0.5 text-brand-600 focus:ring-brand-500"
                    />
                    <div className="flex-1">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-sm font-semibold text-gray-900">
                          Isi saldo penuh dari gaji ({formatCurrency(incomeNum)})
                        </span>
                        <span className="text-xs bg-brand-100 text-brand-700 font-medium px-2 py-0.5 rounded-full">Direkomendasikan</span>
                      </div>
                      <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                        Semua amplop langsung terisi sesuai target bulanan untuk memulai budgeting periode ini.
                      </p>
                    </div>
                  </label>

                  <label
                    className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                      initialCashMode === 'zero'
                        ? 'border-brand-500 bg-brand-50/40 ring-1 ring-brand-500'
                        : 'border-gray-200 hover:border-gray-300 bg-white'
                    }`}
                  >
                    <input
                      type="radio"
                      name="initialCashMode"
                      value="zero"
                      checked={initialCashMode === 'zero'}
                      onChange={() => setInitialCashMode('zero')}
                      className="mt-0.5 text-brand-600 focus:ring-brand-500"
                    />
                    <div className="flex-1">
                      <span className="text-sm font-semibold text-gray-900">Mulai saldo dari Rp 0 (Gaji belum cair)</span>
                      <p className="text-xs text-gray-500 mt-1 leading-relaxed">
                        Amplop disiapkan dengan target jatah bulanan. Saldo akan diisi nanti saat gajian lewat tombol <strong>+ Pemasukan</strong> di dashboard.
                      </p>
                    </div>
                  </label>
                </>
              )}
            </div>
          </div>

          {error && <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>{error}</div>}

          {remainder < 0 && (
            <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>
              Total alokasi melebihi income sebesar {formatCurrency(Math.abs(remainder))}. Kurangi salah satu amplop.
            </div>
          )}

          <button onClick={handleCreate} disabled={isSubmitDisabled}
            className="btn-primary w-full disabled:opacity-50">
            {getSubmitButtonLabel()}
          </button>
        </div>
      )}
    </div>
  );
}
