import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';

const EMOJIS = ['🍜','🚗','🎬','📱','💰','🏠','📚','🎮','👕','🏥','✈️','🎁','🐱','📁'];

function CreateModal({ onClose, onCreated, editing }) {
  const [name, setName] = useState(editing?.name || '');
  const [emoji, setEmoji] = useState(editing?.emoji || '📁');
  const [budget, setBudget] = useState(editing ? String(Math.round(Number(editing.budget_amount))) : '');
  const [rollover, setRollover] = useState(editing?.is_rollover ?? true);
  const [isPersonal, setIsPersonal] = useState(editing?.is_personal ?? false);
  const [isLocked, setIsLocked] = useState(editing?.is_locked ?? false);
  const [dailyLimit, setDailyLimit] = useState(editing?.daily_limit ? String(Math.round(Number(editing.daily_limit))) : '');
  const [coolingThreshold, setCoolingThreshold] = useState(editing?.cooling_threshold ? String(Math.round(Number(editing.cooling_threshold))) : '');
  const [saving, setSaving] = useState(false);
  const [showControls, setShowControls] = useState(!!(editing?.is_locked || editing?.daily_limit || editing?.cooling_threshold));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    const data = {
      name, emoji,
      budget_amount: Number(budget),
      is_rollover: rollover,
      is_personal: isPersonal,
      is_locked: isLocked,
      daily_limit: dailyLimit ? Number(dailyLimit) : null,
      cooling_threshold: coolingThreshold ? Number(coolingThreshold) : null,
    };
    const result = editing ? await api.updateEnvelope(editing.id, data) : await api.createEnvelope(data);
    setSaving(false);
    if (result.ok) { onCreated(); onClose(); }
  };

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-md p-6 shadow-xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-bold text-lg mb-4">{editing ? 'Edit amplop' : 'Amplop baru'}</h3>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div><label className="label">Emoji</label><div className="flex flex-wrap gap-1.5">{EMOJIS.map(e => (<button key={e} type="button" onClick={() => setEmoji(e)} className={`w-9 h-9 rounded-lg text-lg flex items-center justify-center transition-all ${emoji === e ? 'bg-brand-50 ring-2 ring-brand-400' : 'bg-gray-50 hover:bg-gray-100'}`}>{e}</button>))}</div></div>
          <div><label className="label">Nama amplop</label><input type="text" className="input" placeholder="Makan, Transport..." value={name} onChange={e => setName(e.target.value)} required /></div>
          <div><label className="label">Budget bulanan (Rp)</label><input type="number" className="input font-mono" placeholder="1500000" value={budget} onChange={e => setBudget(e.target.value)} required min="0" />{budget && <p className="text-xs text-gray-400 mt-1">{formatCurrency(budget)}/bulan</p>}</div>

          <div className="space-y-2">
            <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={rollover} onChange={e => setRollover(e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-400" /><span className="text-sm text-gray-600">Rollover sisa ke bulan depan</span></label>
            <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={isPersonal} onChange={e => setIsPersonal(e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-brand-600 focus:ring-brand-400" /><span className="text-sm text-gray-600">Personal (hanya kamu yang lihat)</span></label>
          </div>

          <div className="border-t border-gray-100 pt-3">
            <button type="button" onClick={() => setShowControls(!showControls)}
              className="text-sm font-medium text-brand-600 hover:underline flex items-center gap-1">
              ⚙️ Behavior controls {showControls ? '▲' : '▼'}
            </button>

            {showControls && (
              <div className="mt-3 space-y-3 bg-gray-50 rounded-xl p-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={isLocked} onChange={e => setIsLocked(e.target.checked)}
                    className="w-4 h-4 rounded border-gray-300 text-danger-400 focus:ring-danger-400" />
                  <span className="text-sm text-gray-600">🔒 Kunci amplop (tidak bisa belanja)</span>
                </label>

                <div>
                  <label className="label">📊 Daily limit (Rp/hari)</label>
                  <input type="number" className="input font-mono" placeholder="Kosongkan jika tidak ada limit"
                    value={dailyLimit} onChange={e => setDailyLimit(e.target.value)} min="0" />
                  {dailyLimit && <p className="text-xs text-gray-400 mt-1">Max {formatCurrency(dailyLimit)}/hari</p>}
                </div>

                <div>
                  <label className="label">⏳ Cooling threshold (Rp)</label>
                  <input type="number" className="input font-mono" placeholder="Kosongkan jika tidak ada cooling"
                    value={coolingThreshold} onChange={e => setCoolingThreshold(e.target.value)} min="0" />
                  {coolingThreshold && <p className="text-xs text-gray-400 mt-1">Pembelian &ge; {formatCurrency(coolingThreshold)} harus tunggu 24 jam</p>}
                </div>
              </div>
            )}
          </div>

          <div className="flex gap-2 pt-2"><button type="button" onClick={onClose} className="btn-outline flex-1">Batal</button><button type="submit" disabled={saving} className="btn-primary flex-1 disabled:opacity-50">{saving ? '...' : editing ? 'Simpan' : 'Buat Amplop'}</button></div>
        </form>
      </div>
    </div>
  );
}

function ControlBadges({ env }) {
  const badges = [];
  if (env.is_locked) badges.push({ icon: '🔒', label: 'Locked', color: 'bg-red-50 text-danger-400' });
  if (env.daily_limit) badges.push({ icon: '📊', label: `${formatShort(env.daily_limit)}/hari`, color: 'bg-amber-50 text-amber-600' });
  if (env.cooling_threshold) badges.push({ icon: '⏳', label: `>=${formatShort(env.cooling_threshold)}`, color: 'bg-blue-50 text-info-400' });
  if (badges.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-2">
      {badges.map((b, i) => (
        <span key={i} className={`text-xs font-medium px-2 py-0.5 rounded-md ${b.color}`}>
          {b.icon} {b.label}
        </span>
      ))}
    </div>
  );
}

function EnvelopeCard({ env, onEdit, onDelete }) {
  const status = env.spent_ratio >= 0.9 ? 'danger' : env.spent_ratio >= 0.7 ? 'warning' : 'safe';
  const barColor = status === 'danger' ? 'bg-danger-400' : status === 'warning' ? 'bg-amber-400' : 'bg-brand-400';
  return (
    <div className={`card group hover:border-brand-200 transition-all ${env.is_locked ? 'opacity-60' : ''}`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5"><span className="text-2xl">{env.emoji || '📁'}</span><div><h3 className="font-semibold">{env.name}</h3><p className="text-xs text-gray-400">{env.is_personal ? '🔒 Personal' : '👥 Shared'} · {env.is_rollover ? 'Rollover' : 'Reset'}</p></div></div>
        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
          <button onClick={() => onEdit(env)} className="text-xs text-gray-400 hover:text-brand-600 px-2 py-1 rounded">Edit</button>
          <button onClick={() => onDelete(env.id, env.name)} className="text-xs text-gray-400 hover:text-danger-400 px-2 py-1 rounded">Hapus</button>
        </div>
      </div>
      <div className="mb-2">
        <div className="flex justify-between items-end mb-1.5">
          <span className={`font-display text-2xl font-bold ${env.is_locked ? 'text-gray-400' : status === 'danger' ? 'text-danger-400' : status === 'warning' ? 'text-amber-400' : 'text-brand-600'}`}>{formatShort(env.remaining)}</span>
          <span className="text-xs text-gray-400">/ {formatShort(env.budget_amount)}</span>
        </div>
        <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden"><div className={`h-full rounded-full transition-all duration-700 ${env.is_locked ? 'bg-gray-300' : barColor}`} style={{ width: `${Math.max(env.spent_ratio * 100, 1)}%` }} /></div>
      </div>
      <p className="text-xs text-gray-400">Terpakai {formatCurrency(env.spent)} ({Math.round(env.spent_ratio * 100)}%)</p>
      <ControlBadges env={env} />
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

  const shared = envelopes.filter(e => !e.is_personal);
  const personal = envelopes.filter(e => e.is_personal);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-display font-bold">Amplop</h1><p className="text-sm text-gray-500">{envelopes.length} amplop aktif</p></div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">+ Amplop Baru</button>
      </div>
      {envelopes.length === 0 ? (
        <div className="card text-center py-12"><p className="text-4xl mb-3">✉️</p><p className="text-gray-500 mb-4">Belum ada amplop.</p><button onClick={() => setShowCreate(true)} className="btn-primary">Buat Amplop Pertama</button></div>
      ) : (
        <>
          {shared.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">👥 Shared ({shared.length})</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{shared.map(env => <EnvelopeCard key={env.id} env={env} onEdit={setEditing} onDelete={handleDelete} />)}</div>
            </div>
          )}
          {personal.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">🔒 Personal ({personal.length})</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">{personal.map(env => <EnvelopeCard key={env.id} env={env} onEdit={setEditing} onDelete={handleDelete} />)}</div>
            </div>
          )}
        </>
      )}
      {(showCreate || editing) && <CreateModal editing={editing} onClose={() => { setShowCreate(false); setEditing(null); }} onCreated={load} />}
    </div>
  );
}
