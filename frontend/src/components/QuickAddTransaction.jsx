import { useState, useEffect, useRef } from 'react';
import { api } from '../lib/api';
import { enqueueTransaction } from '../lib/offlineQueue';
import { shouldShowPrivateToggle } from '../lib/privateToggle';
import { Icon } from './Icon';

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
  const userTouchedRef = useRef(false);
  const debounceRef = useRef(null);

  useEffect(() => { api.getEnvelopes().then(setEnvelopes); }, []);
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

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div>
          <label className="label">Jumlah (Rp)</label>
          <input type="number" className="input font-mono" placeholder="35000" value={amount} onChange={e => setAmount(e.target.value)} required min="1" />
        </div>
        <div>
          <label className="label">Keterangan</label>
          <input type="text" className="input" placeholder="Starbucks, Gojek..." value={description} onChange={handleDescChange} required />
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
      {error && <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>{error}</div>}
    </form>
  );
}
