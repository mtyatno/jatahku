import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';
import { Icon, EnvelopeIcon } from './Icon';

export default function FundEnvelopeModal({
  isOpen,
  onClose,
  targetEnvelope,
  neededAmount = 0,
  envelopes = [],
  onSuccess,
}) {
  const [tab, setTab] = useState('transfer'); // 'transfer' | 'income'
  const [transferFrom, setTransferFrom] = useState('');
  const [transferAmount, setTransferAmount] = useState('');
  const [incomeDesc, setIncomeDesc] = useState('');
  const [incomeAmount, setIncomeAmount] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Settle initial amounts whenever modal opens or target changes
  useEffect(() => {
    if (!isOpen || !targetEnvelope) return;
    setError('');
    setSaving(false);

    const initialAmt = neededAmount > 0 ? String(Math.round(neededAmount)) : '';
    setTransferAmount(initialAmt);
    setIncomeAmount(initialAmt);
    setIncomeDesc(`Top-up ${targetEnvelope.name}`);

    // Preselect the first available envelope with highest remaining balance
    const available = (envelopes || []).filter(
      e => e.id !== targetEnvelope.id && Number(e.remaining || 0) > 0
    );
    if (available.length > 0) {
      // Pick the envelope with the largest remaining balance
      const sorted = [...available].sort((a, b) => Number(b.remaining || 0) - Number(a.remaining || 0));
      setTransferFrom(sorted[0].id);
    } else {
      setTransferFrom('');
      // If no envelope has remaining funds, switch directly to income tab
      setTab('income');
    }
  }, [isOpen, targetEnvelope, neededAmount, envelopes]);

  if (!isOpen || !targetEnvelope) return null;

  const fundableEnvelopes = (envelopes || []).filter(
    e => e.id !== targetEnvelope.id && Number(e.remaining || 0) > 0
  );

  const selectedSource = fundableEnvelopes.find(e => e.id === transferFrom);
  const maxTransfer = selectedSource ? Math.max(0, Number(selectedSource.remaining || 0)) : 0;
  const currentRemaining = Math.max(0, Number(targetEnvelope.remaining || 0));

  const handleTransfer = async (e) => {
    e.preventDefault();
    if (!transferFrom) {
      setError('Pilih amplop sumber dana');
      return;
    }
    const amt = Number(transferAmount);
    if (!amt || amt <= 0) {
      setError('Jumlah harus lebih dari 0');
      return;
    }
    if (amt > maxTransfer) {
      setError(`Maksimal transfer dari ${selectedSource?.name}: ${formatCurrency(maxTransfer)}`);
      return;
    }

    setSaving(true);
    setError('');

    const res = await api.transferEnvelope(transferFrom, targetEnvelope.id, amt);
    setSaving(false);

    if (res.ok) {
      window.dispatchEvent(new CustomEvent('jatahku:envelope-updated'));
      onSuccess?.({
        type: 'transfer',
        amount: amt,
        fromName: selectedSource?.name || 'Amplop lain',
        targetEnvelope,
      });
      onClose();
    } else {
      setError(res.data?.detail || 'Gagal menggeser dana. Coba lagi.');
    }
  };

  const handleIncome = async (e) => {
    e.preventDefault();
    const amt = Number(incomeAmount);
    if (!amt || amt <= 0) {
      setError('Jumlah pemasukan harus lebih dari 0');
      return;
    }

    setSaving(true);
    setError('');

    const payload = {
      amount: amt,
      source: incomeDesc.trim() || `Top-up ${targetEnvelope.name}`,
      allocations: [{ envelope_id: targetEnvelope.id, amount: amt }],
    };

    const res = await api.createIncome(payload);
    setSaving(false);

    if (res.ok) {
      window.dispatchEvent(new CustomEvent('jatahku:envelope-updated'));
      onSuccess?.({
        type: 'income',
        amount: amt,
        targetEnvelope,
      });
      onClose();
    } else {
      setError(res.data?.detail || 'Gagal menambah pemasukan. Coba lagi.');
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[60] flex items-center justify-center p-4 animate-in fade-in duration-150"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl w-full max-w-md p-5 shadow-2xl space-y-4 max-h-[92vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-gray-100 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-brand-50 flex items-center justify-center shrink-0">
              <EnvelopeIcon emoji={targetEnvelope.emoji} size={20} />
            </div>
            <div>
              <h3 className="font-display font-bold text-base text-gray-900 leading-tight">
                Isi Dana Amplop
              </h3>
              <p className="text-xs text-gray-500 mt-0.5 font-medium">
                {targetEnvelope.name}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <Icon name="close" size={18} />
          </button>
        </div>

        {/* Shortage indicator */}
        <div className="bg-amber-50/80 border border-amber-200/80 rounded-xl p-3 text-xs text-amber-900 space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-amber-700">Sisa dana saat ini:</span>
            <span className="font-mono font-medium">{formatCurrency(currentRemaining)}</span>
          </div>
          {neededAmount > 0 && (
            <div className="flex items-center justify-between pt-1 border-t border-amber-200/60 font-semibold text-amber-800">
              <span>Kurang dana untuk transaksi:</span>
              <span className="font-mono text-sm text-red-600">{formatCurrency(neededAmount)}</span>
            </div>
          )}
        </div>

        {/* Tab switcher */}
        <div className="grid grid-cols-2 gap-1 p-1 bg-gray-100 rounded-xl text-xs font-medium">
          <button
            type="button"
            onClick={() => { setTab('transfer'); setError(''); }}
            className={`py-1.5 px-3 rounded-lg flex items-center justify-center gap-1.5 transition-all ${
              tab === 'transfer'
                ? 'bg-white text-brand-700 shadow-sm font-semibold'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <Icon name="transfer" size={14} />
            Geser Amplop
          </button>
          <button
            type="button"
            onClick={() => { setTab('income'); setError(''); }}
            className={`py-1.5 px-3 rounded-lg flex items-center justify-center gap-1.5 transition-all ${
              tab === 'income'
                ? 'bg-white text-brand-700 shadow-sm font-semibold'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <Icon name="income" size={14} />
            Top-up Pemasukan
          </button>
        </div>

        {/* Error notice */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-xs px-3 py-2 rounded-xl text-red-600 font-medium">
            {error}
          </div>
        )}

        {/* Tab 1: Transfer from another envelope */}
        {tab === 'transfer' && (
          <form onSubmit={handleTransfer} className="space-y-3.5">
            {fundableEnvelopes.length === 0 ? (
              <div className="text-center py-4 px-2 space-y-2">
                <p className="text-xs text-gray-500">
                  Tidak ada amplop lain yang memiliki sisa dana saat ini.
                </p>
                <button
                  type="button"
                  onClick={() => setTab('income')}
                  className="btn-sm btn-outline text-xs"
                >
                  Beralih ke Top-up Pemasukan
                </button>
              </div>
            ) : (
              <>
                <div>
                  <label className="label text-xs mb-1">Ambil dana dari amplop:</label>
                  <select
                    className="input text-sm py-2 w-full"
                    value={transferFrom}
                    onChange={e => {
                      setTransferFrom(e.target.value);
                      setError('');
                    }}
                    required
                  >
                    <option value="">Pilih amplop sumber</option>
                    {fundableEnvelopes.map(env => (
                      <option key={env.id} value={env.id}>
                        {env.emoji} {env.name} (sisa {formatCurrency(env.remaining)})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="label text-xs">Jumlah yang digeser (Rp):</label>
                    {selectedSource && (
                      <span className="text-[11px] text-gray-400">
                        Maks: <span className="font-mono font-medium text-gray-600">{formatShort(maxTransfer)}</span>
                      </span>
                    )}
                  </div>
                  <input
                    type="number"
                    className="input font-mono text-sm py-2 w-full"
                    placeholder="Contoh: 50000"
                    value={transferAmount}
                    onChange={e => setTransferAmount(e.target.value)}
                    min="1"
                    max={maxTransfer || undefined}
                    required
                  />

                  {/* Quick buttons */}
                  {neededAmount > 0 && selectedSource && (
                    <div className="flex items-center gap-1.5 mt-1.5">
                      <button
                        type="button"
                        onClick={() => setTransferAmount(String(Math.min(neededAmount, maxTransfer)))}
                        className="text-[11px] text-brand-600 hover:text-brand-700 bg-brand-50 hover:bg-brand-100/70 px-2 py-0.5 rounded transition-colors"
                      >
                        Pas kekurangan ({formatShort(Math.min(neededAmount, maxTransfer))})
                      </button>
                      <button
                        type="button"
                        onClick={() => setTransferAmount(String(maxTransfer))}
                        className="text-[11px] text-gray-600 hover:text-gray-800 bg-gray-100 hover:bg-gray-200 px-2 py-0.5 rounded transition-colors"
                      >
                        Semua sisa ({formatShort(maxTransfer)})
                      </button>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100">
                  <button
                    type="button"
                    onClick={onClose}
                    className="btn-outline text-xs py-2 px-3"
                    disabled={saving}
                  >
                    Batal
                  </button>
                  <button
                    type="submit"
                    disabled={saving || !transferFrom || !Number(transferAmount)}
                    className="btn-primary text-xs py-2 px-4 disabled:opacity-50 flex items-center gap-1.5"
                  >
                    <Icon name="transfer" size={14} />
                    {saving ? 'Menggeser...' : 'Geser Dana Sekarang'}
                  </button>
                </div>
              </>
            )}
          </form>
        )}

        {/* Tab 2: Top-up / New Income */}
        {tab === 'income' && (
          <form onSubmit={handleIncome} className="space-y-3.5">
            <div>
              <label className="label text-xs mb-1">Keterangan pemasukan:</label>
              <input
                type="text"
                className="input text-sm py-2 w-full"
                placeholder="Contoh: Top-up saldo, Uang saku..."
                value={incomeDesc}
                onChange={e => setIncomeDesc(e.target.value)}
                required
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="label text-xs">Nominal pemasukan (Rp):</label>
                {neededAmount > 0 && (
                  <button
                    type="button"
                    onClick={() => setIncomeAmount(String(Math.round(neededAmount)))}
                    className="text-[11px] text-brand-600 hover:underline"
                  >
                    Isi Rp{formatShort(neededAmount)}
                  </button>
                )}
              </div>
              <input
                type="number"
                className="input font-mono text-sm py-2 w-full"
                placeholder="Contoh: 100000"
                value={incomeAmount}
                onChange={e => setIncomeAmount(e.target.value)}
                min="1"
                required
              />
              <p className="text-[11px] text-gray-400 mt-1">
                Dana pemasukan ini akan langsung dialokasikan 100% ke amplop {targetEnvelope.name}.
              </p>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100">
              <button
                type="button"
                onClick={onClose}
                className="btn-outline text-xs py-2 px-3"
                disabled={saving}
              >
                Batal
              </button>
              <button
                type="submit"
                disabled={saving || !Number(incomeAmount)}
                className="btn-primary text-xs py-2 px-4 disabled:opacity-50 flex items-center gap-1.5"
              >
                <Icon name="income" size={14} />
                {saving ? 'Menyimpan...' : 'Tambah Dana'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
