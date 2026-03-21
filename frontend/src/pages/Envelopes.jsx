import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort } from '../lib/utils';

const EMOJIS = ['🍜','🚗','🎬','📱','💰','🏠','📚','🎮','👕','🏥','✈️','🎁','🐱','📁'];

function CreateModal({ onClose, onCreated, editing, envelopes: existingEnvelopes }) {
  const [step, setStep] = useState(editing ? 2 : 1); // 1=basic, 2=controls (editing skips funding)
  const [name, setName] = useState(editing?.name || '');
  const [emoji, setEmoji] = useState(editing?.emoji || '📁');
  const [budget, setBudget] = useState(editing ? String(Math.round(Number(editing.budget_amount))) : '');
  const [rollover, setRollover] = useState(editing?.is_rollover ?? true);
  const [isPersonal, setIsPersonal] = useState(editing?.is_personal ?? false);
  const [isLocked, setIsLocked] = useState(editing?.is_locked ?? false);
  const [dailyLimit, setDailyLimit] = useState(editing?.daily_limit ? String(Math.round(Number(editing.daily_limit))) : '');
  const [coolingThreshold, setCoolingThreshold] = useState(editing?.cooling_threshold ? String(Math.round(Number(editing.cooling_threshold))) : '');
  const [showControls, setShowControls] = useState(!!(editing?.is_locked || editing?.daily_limit || editing?.cooling_threshold));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Funding
  const [fundingSource, setFundingSource] = useState('transfer'); // 'transfer' or 'income'
  const [transferFrom, setTransferFrom] = useState('');
  const [fundAmount, setFundAmount] = useState('');
  const [newIncomeAmount, setNewIncomeAmount] = useState('');
  const [newIncomeDesc, setNewIncomeDesc] = useState('Top-up');

  const fundableEnvelopes = (existingEnvelopes || []).filter(e => Number(e.remaining) > 0);

  const handleSubmit = async () => {
    setSaving(true);
    setError('');

    if (editing) {
      const data = {
        name, emoji, budget_amount: Number(budget), is_rollover: rollover,
        is_personal: isPersonal, is_locked: isLocked,
        daily_limit: dailyLimit ? Number(dailyLimit) : null,
        cooling_threshold: coolingThreshold ? Number(coolingThreshold) : null,
      };
      const result = await api.updateEnvelope(editing.id, data);
      setSaving(false);
      if (result.ok) { onCreated(); onClose(); } else { setError('Gagal update'); }
      return;
    }

    // Create new envelope
    const data = {
      name, emoji, budget_amount: Number(fundAmount || budget || 0), is_rollover: rollover,
      is_personal: isPersonal, is_locked: isLocked,
      daily_limit: dailyLimit ? Number(dailyLimit) : null,
      cooling_threshold: coolingThreshold ? Number(coolingThreshold) : null,
    };
    const createRes = await api.createEnvelope(data);
    if (!createRes.ok) { setSaving(false); setError('Gagal buat amplop'); return; }
    const newEnvId = createRes.data.id;

    // Fund the envelope
    const amt = Number(fundAmount);
    if (amt > 0) {
      if (fundingSource === 'transfer' && transferFrom) {
        // Transfer from existing envelope
        const res = await api.request(
          `/envelopes/transfer?from_id=${transferFrom}&to_id=${newEnvId}&amount=${amt}`,
          { method: 'POST' }
        );
        if (!res.ok) {
          const d = await res.json();
          setSaving(false);
          setError(d.detail || 'Transfer gagal');
          return;
        }
      } else if (fundingSource === 'income') {
        // New income allocation
        const incAmt = Number(newIncomeAmount) || amt;
        const res = await api.request('/incomes/', {
          method: 'POST',
          body: JSON.stringify({
            amount: incAmt,
            source: newIncomeDesc,
            allocations: [{ envelope_id: newEnvId, amount: amt }],
          }),
        });
        if (!res.ok) {
          const d = await res.json();
          setSaving(false);
          setError(d.detail || 'Income gagal');
          return;
        }
      }
    }

    setSaving(false);
    onCreated();
    onClose();
  };

  const selectedSource = fundableEnvelopes.find(e => e.id === transferFrom);
  const maxTransfer = selectedSource ? Number(selectedSource.remaining) : 0;

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-md p-6 shadow-xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-bold text-lg mb-4">{editing ? 'Edit amplop' : 'Amplop baru'}</h3>

        {/* Step 1: Basic info + funding (new only) */}
        <div className="space-y-4">
          <div><label className="label">Emoji</label><div className="flex flex-wrap gap-1.5">{EMOJIS.map(e => (<button key={e} type="button" onClick={() => setEmoji(e)} className={`w-9 h-9 rounded-lg text-lg flex items-center justify-center transition-all ${emoji === e ? 'bg-brand-50 ring-2 ring-brand-400' : 'bg-gray-50 hover:bg-gray-100'}`}>{e}</button>))}</div></div>
          <div><label className="label">Nama amplop</label><input type="text" className="input" placeholder="Darurat, Liburan..." value={name} onChange={e => setName(e.target.value)} required /></div>

          {!editing && (
            <div className="border-t border-gray-100 pt-4">
              <h4 className="font-semibold text-sm mb-3">💰 Sumber dana</h4>
              <div className="flex gap-2 mb-3">
                <button type="button" onClick={() => setFundingSource('transfer')}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${fundingSource === 'transfer' ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500'}`}>
                  ↔️ Transfer dari amplop lain
                </button>
                <button type="button" onClick={() => setFundingSource('income')}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${fundingSource === 'income' ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500'}`}>
                  💵 Income baru
                </button>
              </div>

              {fundingSource === 'transfer' && (
                <div className="space-y-3">
                  <div>
                    <label className="label">Transfer dari</label>
                    <select className="input" value={transferFrom} onChange={e => setTransferFrom(e.target.value)}>
                      <option value="">Pilih amplop sumber</option>
                      {fundableEnvelopes.map(env => (
                        <option key={env.id} value={env.id}>{env.emoji} {env.name} (sisa {formatShort(env.remaining)})</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="label">Jumlah transfer (Rp)</label>
                    <input type="number" className="input font-mono" placeholder="500000" value={fundAmount}
                      onChange={e => setFundAmount(e.target.value)} min="1" max={maxTransfer} />
                    {transferFrom && <p className="text-xs text-gray-400 mt-1">Max: {formatCurrency(maxTransfer)}</p>}
                  </div>
                </div>
              )}

              {fundingSource === 'income' && (
                <div className="space-y-3">
                  <div>
                    <label className="label">Total income baru (Rp)</label>
                    <input type="number" className="input font-mono" placeholder="1000000" value={newIncomeAmount}
                      onChange={e => setNewIncomeAmount(e.target.value)} min="1" />
                  </div>
                  <div>
                    <label className="label">Keterangan</label>
                    <input type="text" className="input" value={newIncomeDesc}
                      onChange={e => setNewIncomeDesc(e.target.value)} placeholder="Bonus, Freelance..." />
                  </div>
                  <div>
                    <label className="label">Alokasi ke amplop ini (Rp)</label>
                    <input type="number" className="input font-mono" placeholder="500000" value={fundAmount}
                      onChange={e => setFundAmount(e.target.value)} min="1"
                      max={Number(newIncomeAmount) || undefined} />
                    {Number(newIncomeAmount) > 0 && Number(fundAmount) > 0 && Number(newIncomeAmount) > Number(fundAmount) && (
                      <p className="text-xs text-brand-600 mt-1">Sisa {formatCurrency(Number(newIncomeAmount) - Number(fundAmount))} → Tabungan</p>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {editing && (
            <div><label className="label">Budget target (Rp)</label><input type="number" className="input font-mono" placeholder="1500000" value={budget} onChange={e => setBudget(e.target.value)} min="0" /></div>
          )}

          <div className="space-y-2">
            <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={rollover} onChange={e => setRollover(e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-brand-600" /><span className="text-sm text-gray-600">Rollover sisa ke bulan depan</span></label>
            <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={isPersonal} onChange={e => setIsPersonal(e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-brand-600" /><span className="text-sm text-gray-600">Personal (hanya kamu)</span></label>
          </div>

          <div className="border-t border-gray-100 pt-3">
            <button type="button" onClick={() => setShowControls(!showControls)}
              className="text-sm font-medium text-brand-600 hover:underline flex items-center gap-1">
              ⚙️ Behavior controls {showControls ? '▲' : '▼'}
            </button>
            {showControls && (
              <div className="mt-3 space-y-3 bg-gray-50 rounded-xl p-4">
                <label className="flex items-center gap-2 cursor-pointer"><input type="checkbox" checked={isLocked} onChange={e => setIsLocked(e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-danger-400" /><span className="text-sm text-gray-600">🔒 Kunci amplop</span></label>
                <div><label className="label">📊 Daily limit (Rp/hari)</label><input type="number" className="input font-mono" placeholder="Kosongkan = no limit" value={dailyLimit} onChange={e => setDailyLimit(e.target.value)} min="0" /></div>
                <div><label className="label">⏳ Cooling threshold (Rp)</label><input type="number" className="input font-mono" placeholder="Kosongkan = no cooling" value={coolingThreshold} onChange={e => setCoolingThreshold(e.target.value)} min="0" /></div>
              </div>
            )}
          </div>

          {error && <div className="bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>{error}</div>}

          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-outline flex-1">Batal</button>
            <button type="button" onClick={handleSubmit} disabled={saving || (!editing && !name)}
              className="btn-primary flex-1 disabled:opacity-50">
              {saving ? '...' : editing ? 'Simpan' : 'Buat & Alokasi'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function ControlBadges({ env }) {
  const badges = [];
  if (env.is_locked) badges.push({ icon: '🔒', label: 'Locked', color: 'bg-red-50 text-danger-400' });
  if (env.daily_limit) badges.push({ icon: '📊', label: `${formatShort(env.daily_limit)}/hari`, color: 'bg-amber-50 text-amber-600' });
  if (env.cooling_threshold) badges.push({ icon: '⏳', label: `>=${formatShort(env.cooling_threshold)}`, color: 'bg-blue-50 text-info-400' });
  if (!badges.length) return null;
  return <div className="flex flex-wrap gap-1 mt-2">{badges.map((b, i) => <span key={i} className={`text-xs font-medium px-2 py-0.5 rounded-md ${b.color}`}>{b.icon} {b.label}</span>)}</div>;
}

function EnvelopeCard({ env, onEdit, onDelete }) {
  const allocated = Number(env.allocated || 0);
  const spent = Number(env.spent || 0);
  const remaining = Number(env.remaining || 0);
  const reserved = Number(env.reserved || 0);
  const free = Number(env.free || remaining);
  const spentRatio = env.spent_ratio || 0;
  const isUnfunded = allocated <= 0 && env.name !== 'Tabungan';
  const status = spentRatio >= 0.9 ? 'danger' : spentRatio >= 0.7 ? 'warning' : 'safe';
  const barColor = status === 'danger' ? 'bg-danger-400' : status === 'warning' ? 'bg-amber-400' : 'bg-brand-400';
  const remainColor = free <= 0 ? 'text-danger-400' : status === 'warning' ? 'text-amber-400' : 'text-brand-600';

  return (
    <div className={`card group hover:border-brand-200 transition-all ${env.is_locked ? 'opacity-60' : ''}`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5"><span className="text-2xl">{env.emoji || '📁'}</span><div><h3 className="font-semibold">{env.name}</h3><p className="text-xs text-gray-400">{env.is_personal ? '🔒 Personal' : '👥 Shared'} · {env.is_rollover ? 'Rollover' : 'Reset'}</p></div></div>
        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
          <button onClick={() => onEdit(env)} className="text-xs text-gray-400 hover:text-brand-600 px-2 py-1 rounded">Edit</button>
          <button onClick={() => onDelete(env.id, env.name)} className="text-xs text-gray-400 hover:text-danger-400 px-2 py-1 rounded">Hapus</button>
        </div>
      </div>
      {isUnfunded ? (
        <div className="bg-amber-50 text-amber-600 text-xs px-3 py-2 rounded-lg">💡 Belum ada dana. Alokasikan income dulu.</div>
      ) : (
        <div className="mb-2">
          <div className="flex justify-between items-end mb-1.5">
            <span className={`font-display text-2xl font-bold ${env.is_locked ? 'text-gray-400' : remainColor}`}>{formatShort(free)}</span>
            <span className="text-xs text-gray-400">Dana {formatShort(allocated)}</span>
          </div>
          <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden"><div className={`h-full rounded-full transition-all duration-700 ${env.is_locked ? 'bg-gray-300' : barColor}`} style={{ width: `${Math.max(spentRatio * 100, 1)}%` }} /></div>
          <p className="text-xs text-gray-400 mt-1">Terpakai {formatCurrency(spent)} dari {formatCurrency(allocated)}</p>
          {reserved > 0 && <p className="text-xs text-amber-500 mt-0.5">🔄 Reserved: {formatCurrency(reserved)}/bulan</p>}
        </div>
      )}
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
      {(showCreate || editing) && <CreateModal editing={editing} envelopes={envelopes} onClose={() => { setShowCreate(false); setEditing(null); }} onCreated={load} />}
    </div>
  );
}
