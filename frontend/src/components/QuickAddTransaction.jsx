import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../lib/api';
import { enqueueTransaction } from '../lib/offlineQueue';
import { shouldShowPrivateToggle } from '../lib/privateToggle';
import { parseAmount } from '../lib/parseAmount';
import { Icon } from './Icon';
import VoiceInput from './VoiceInput';
import FundEnvelopeModal from './FundEnvelopeModal';

function isInsufficientFundsError(errMsg) {
  if (!errMsg) return false;
  const lower = String(errMsg).toLowerCase();
  return lower.includes('dana tidak cukup') || lower.includes('belum ada dana') || lower.includes('belum didanai');
}

export default function QuickAddTransaction({ onSaved, onCancel }) {
  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [envelopeId, setEnvelopeId] = useState('');
  const [envelopes, setEnvelopes] = useState([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [suggested, setSuggested] = useState(false);
  const [isPrivate, setIsPrivate] = useState(false);
  const [memberCount, setMemberCount] = useState(1);
  const [showFundModal, setShowFundModal] = useState(false);
  const userTouchedRef = useRef(false);
  const debounceRef = useRef(null);

  const loadEnvelopes = useCallback(async () => {
    try {
      const data = await api.getEnvelopeSummary();
      setEnvelopes(Array.isArray(data) ? data : []);
    } catch {
      const fallback = await api.getEnvelopes();
      setEnvelopes(Array.isArray(fallback) ? fallback : []);
    }
  }, []);

  useEffect(() => { loadEnvelopes(); }, [loadEnvelopes]);
  useEffect(() => { api.getHouseholdMembers().then(m => setMemberCount(m.length)); }, []);

  // Debounced envelope suggestion as the user types the description.
  useEffect(() => {
    if (userTouchedRef.current) return;
    const desc = description.trim();
    if (desc.length < 2) return;
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      const res = await api.suggestEnvelope(desc);
      if (res && res.confident && res.envelope_id && !userTouchedRef.current) {
        setEnvelopeId(res.envelope_id);
        setSuggested(true);
      }
    }, 400);
    return () => clearTimeout(debounceRef.current);
  }, [description]);

  const handleDescChange = (e) => {
    const v = e.target.value;
    setDescription(v);
    if (v.trim().length === 0) { userTouchedRef.current = false; setSuggested(false); }
  };

  const handleEnvelopeChange = (e) => {
    userTouchedRef.current = true;
    setSuggested(false);
    setEnvelopeId(e.target.value);
  };

  const handleVoiceTranscript = (text) => {
    userTouchedRef.current = false;
    setSuggested(false);
    const parsed = parseAmount(text);
    if (parsed) {
      setAmount(String(parsed.amount));
      setDescription(parsed.description);
    } else {
      setDescription(text);
    }
  };

  const reset = () => {
    setAmount(''); setDescription(''); setEnvelopeId('');
    setSuggested(false); userTouchedRef.current = false; setError(''); setIsPrivate(false);
  };

  const selectedEnv = envelopes.find(e => e.id === envelopeId);
  const showPrivate = shouldShowPrivateToggle(memberCount, selectedEnv);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!envelopeId || !amount || Number(amount) <= 0) { setError('Lengkapi jumlah & amplop'); return; }
    setSaving(true); setError('');
    const payload = { envelope_id: envelopeId, amount: Number(amount), description, source: 'webapp', is_private: showPrivate ? isPrivate : false };

    if (!navigator.onLine) {
      await enqueueTransaction(payload);
      setSaving(false);
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      reset();
      onSaved?.();
      return;
    }

    const result = await api.createTransaction(payload);
    setSaving(false);
    if (result.ok) {
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      reset();
      onSaved?.();
    } else {
      setError(result.data?.detail || 'Gagal menyimpan transaksi');
    }
  };

  const handleFundSuccess = async () => {
    await loadEnvelopes();
    setError('');
  };

  const neededAmount = selectedEnv
    ? Math.max(0, Number(amount || 0) - Number(selectedEnv.remaining || 0)) || Number(amount || 0)
    : Number(amount || 0);

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div>
          <label className="label">Jumlah (Rp)</label>
          <input type="number" className="input font-mono" placeholder="35000" value={amount} onChange={e => setAmount(e.target.value)} required min="1" />
        </div>
        <div>
          <label className="label">Keterangan</label>
          <div className="flex items-center gap-2">
            <input type="text" className="input" placeholder="Starbucks, Gojek..." value={description} onChange={handleDescChange} required />
            <VoiceInput
              onTranscript={handleVoiceTranscript}
              onError={msg => setError(msg)}
              disabled={saving}
            />
          </div>
        </div>
        <div>
          <label className="label">Amplop {suggested && <span className="text-xs text-brand-600">· disarankan</span>}</label>
          <select className="input" value={envelopeId} onChange={handleEnvelopeChange} required>
            <option value="">Pilih amplop</option>
            {envelopes.filter(env => env.purpose !== 'saving' && env.purpose !== 'sinking_fund').map(env => (<option key={env.id} value={env.id}>{env.emoji} {env.name}</option>))}
          </select>
        </div>
        <div className="flex items-end gap-2">
          <button type="submit" disabled={saving} className="btn-primary flex-1 disabled:opacity-50">{saving ? '...' : 'Simpan'}</button>
          {onCancel && <button type="button" onClick={onCancel} className="btn-outline">Batal</button>}
        </div>
      </div>
      {showPrivate && (
        <label className="flex items-start gap-2 cursor-pointer">
          <input type="checkbox" checked={isPrivate} onChange={e => setIsPrivate(e.target.checked)}
            className="w-4 h-4 mt-0.5 rounded border-gray-300 text-brand-600" />
          <span className="text-xs text-gray-600">
            <span className="inline-flex items-center gap-1 font-medium"><Icon name="lock" size={13} /> Sembunyikan deskripsi dari anggota lain</span>
            <span className="block text-gray-400">Nominal, tanggal, amplop, dan pencatat tetap terlihat. Catatan/deskripsi disembunyikan.</span>
          </span>
        </label>
      )}
      {error && (
        <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>
          <div>{error}</div>
          {isInsufficientFundsError(error) && selectedEnv && (
            <div className="mt-2.5 pt-2 border-t border-red-200/60 flex items-center justify-between flex-wrap gap-2 text-xs">
              <span className="text-red-700">Amplop <strong>{selectedEnv.name}</strong> butuh tambahan dana.</span>
              <button
                type="button"
                onClick={() => setShowFundModal(true)}
                className="bg-brand-600 hover:bg-brand-700 text-white rounded-lg px-2.5 py-1 text-xs font-medium flex items-center gap-1.5 shadow-sm transition-all"
              >
                <Icon name="transfer" size={13} />
                Geser / Isi Dana ({selectedEnv.name})
              </button>
            </div>
          )}
        </div>
      )}

      {showFundModal && selectedEnv && (
        <FundEnvelopeModal
          isOpen={showFundModal}
          onClose={() => setShowFundModal(false)}
          targetEnvelope={selectedEnv}
          neededAmount={neededAmount}
          envelopes={envelopes}
          onSuccess={handleFundSuccess}
        />
      )}
    </form>
  );
}
