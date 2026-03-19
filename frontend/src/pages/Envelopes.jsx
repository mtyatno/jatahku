import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';

const EMOJIS = ['🍜','🚗','🎬','📱','💰','🏠','📚','🎮','👕','🏥','✈️','🎁','🐱','📁'];

function CreateModal({ onClose, onCreated, editing }) {
  const [name, setName] = useState(editing?.name || '');
  const [emoji, setEmoji] = useState(editing?.emoji || '📁');
  const [budget, setBudget] = useState(editing ? String(Math.round(Number(editing.budget_amount))) : '');
  const [rollover, setRollover] = useState(editing?.is_rollover ?? true);
  const [saving, setSaving] = useState(false);
  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    const data = { name, emoji, budget_amount: Number(budget), is_rollover: rollover };
    const result = editing ? await api.updateEnvelope(editing.id, data) : await api.createEnvelope(data);
    setSaving(false);
    if (result.ok) { onCreated(); onClose(); }
  };
  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-md p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-bold text-lg mb-4">{editing ? 'Edit amplop' : 'Amplop baru'}</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="label">Emoji</label>
            <div className="flex flex-wrap gap-1.5">
              {EMOJIS.map(e => (<button key={e} type="button" onClick={() => setEmoji(e)} className={`w-9 h-9 rounded-lg text-lg flex items-center justify-center transition-all ${emoji === e ? 'bg-brand-50 ring-2 ring-brand-400' : 'bg-gray-50 hover:bg-gray-100'}`}>{e}</button>))}
            </div>
          </div>
          <div><label className="label">Nama amplop</label><input type="text" className="input" placeholder="Makan, Transport..." value={name} onChange={e => setName(e.target.value)} required /></div>
          <div><label className="label">Budget bulanan (Rp)</label><input type="number" className="input font-mono" placeholder="1500000" value={budget} onChange={e => setBudget(e.target.value)} required min="0" />{budget && <p className="text-xs text-gray-400 mt-1">{formatCurrency(budget)}/bulan</p>}</div>
          <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={rollover} onChange={e => setRollover(e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-400" /><span className="text-sm text-gray-600">Rollover sisa ke bulan depan</span></label>
          <div className="flex gap-2 pt-2"><button type="button" onClick={onClose} className="btn-outline flex-1">Batal</button><button type="submit" disabled={saving} className="btn-primary flex-1 disabled:opacity-50">{saving ? '...' : editing ? 'Simpan' : 'Buat Amplop'}</button></div>
        </form>
      </div>
    </div>
  );
}

export default function Envelopes() {
  const [envelopes, setEnvelopes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState(null);

  const load = () => { api.getEnvelopeSummary().then(env => { setEnvelopes(env); setLoading(false); }); };
  useEffect(load, []);

  const handleDelete = async (id, name) => {
    if (!confirm(`Hapus amplop "${name}"?`)) return;
    await api.deleteEnvelope(id);
    load();
  };

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-display font-bold">Amplop</h1><p className="text-sm text-gray-500">{envelopes.length} amplop aktif</p></div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">+ Amplop Baru</button>
      </div>
      {envelopes.length === 0 ? (
        <div className="card text-center py-12"><p className="text-4xl mb-3">✉️</p><p className="text-gray-500 mb-4">Belum ada amplop.</p><button onClick={() => setShowCreate(true)} className="btn-primary">Buat Amplop Pertama</button></div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {envelopes.map(env => {
            const status = env.spent_ratio >= 0.9 ? 'danger' : env.spent_ratio >= 0.7 ? 'warning' : 'safe';
            const barColor = status === 'danger' ? 'bg-danger-400' : status === 'warning' ? 'bg-amber-400' : 'bg-brand-400';
            return (
              <div key={env.id} className="card group hover:border-brand-200 transition-all">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2.5"><span className="text-2xl">{env.emoji || '📁'}</span><div><h3 className="font-semibold">{env.name}</h3><p className="text-xs text-gray-400">{env.is_rollover ? 'Rollover aktif' : 'Reset tiap bulan'}</p></div></div>
                  <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
                    <button onClick={() => setEditing(env)} className="text-xs text-gray-400 hover:text-brand-600 px-2 py-1 rounded">Edit</button>
                    <button onClick={() => handleDelete(env.id, env.name)} className="text-xs text-gray-400 hover:text-danger-400 px-2 py-1 rounded">Hapus</button>
                  </div>
                </div>
                <div className="mb-2">
                  <div className="flex justify-between items-end mb-1.5">
                    <span className={`font-display text-2xl font-bold ${status === 'danger' ? 'text-danger-400' : status === 'warning' ? 'text-amber-400' : 'text-brand-600'}`}>{formatShort(env.remaining)}</span>
                    <span className="text-xs text-gray-400">/ {formatShort(env.budget_amount)}</span>
                  </div>
                  <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden"><div className={`h-full rounded-full transition-all duration-700 ${barColor}`} style={{ width: `${Math.max(env.spent_ratio * 100, 1)}%` }} /></div>
                </div>
                <p className="text-xs text-gray-400">Terpakai {formatCurrency(env.spent)} ({Math.round(env.spent_ratio * 100)}%)</p>
              </div>
            );
          })}
        </div>
      )}
      {(showCreate || editing) && <CreateModal editing={editing} onClose={() => { setShowCreate(false); setEditing(null); }} onCreated={load} />}
    </div>
  );
}
