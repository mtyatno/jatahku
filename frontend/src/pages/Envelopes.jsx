import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort, titleCase } from '../lib/utils';

const EMOJIS = ['🍜','🚗','🎬','📱','💰','🏠','📚','🎮','👕','🏥','✈️','🎁','🐱','📁'];

// Balance of a list of envelopes = sum of (allocated + rollover - spent)
function groupBalance(envelopes) {
  return envelopes.reduce(
    (sum, e) => sum + (Number(e.allocated || 0) + Number(e.rollover || 0) - Number(e.spent || 0)),
    0,
  );
}

// Split a section's envelopes into ordered custom groups + a trailing "Lainnya"
// bucket for ungrouped envelopes. Returns [] of { id, name, envelopes }.
function buildGroupSections(envelopes, groups) {
  const groupIds = new Set(groups.map((g) => g.id));
  const byGroup = {};
  envelopes.forEach((e) => {
    const key = e.group_id && groupIds.has(e.group_id) ? e.group_id : '__none__';
    (byGroup[key] = byGroup[key] || []).push(e);
  });
  const sections = [...groups]
    .sort((a, b) => a.sort_order - b.sort_order)
    .filter((g) => byGroup[g.id]?.length)
    .map((g) => ({ id: g.id, name: g.name, envelopes: byGroup[g.id] }));
  if (byGroup['__none__']?.length) {
    sections.push({ id: null, name: 'Lainnya', envelopes: byGroup['__none__'] });
  }
  return sections;
}

function CreateModal({ onClose, onCreated, editing, envelopes: existingEnvelopes, groups = [], goals = [] }) {
  const editingGoal = editing ? goals.find(g => g.envelope_id === editing.id) : null;
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
  const [groupId, setGroupId] = useState(editing?.group_id || '');
  const [newGroupName, setNewGroupName] = useState('');
  const [purpose, setPurpose] = useState(editing?.purpose || 'expense');
  const [goalName, setGoalName] = useState(editingGoal?.name || '');
  const [goalAmount, setGoalAmount] = useState(editingGoal ? String(Math.round(Number(editingGoal.target_amount))) : '');
  const [goalDate, setGoalDate] = useState(editingGoal?.target_date || '');

  const guessPurpose = (name) => {
    const n = name.toLowerCase();
    const savingKw = ['tabungan','nikah','darurat','liburan','umroh','rumah','mobil','motor','pendidikan','sekolah','kuliah','dp','menikah','haji','investasi','pensiun'];
    const sinkingKw = ['servis','pajak','asuransi','perpanjang','tahunan','semester','langganan','renewal','hosting','domain','stnk','bpjs','service','maintenance','perawatan'];
    if (savingKw.some(kw => n.includes(kw))) return 'saving';
    if (sinkingKw.some(kw => n.includes(kw))) return 'sinking_fund';
    return 'expense';
  };

  const isSavingLike = purpose === 'saving' || purpose === 'sinking_fund';

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

    // Resolve group: '__new__' means create from the typed name first.
    let resolvedGroupId = groupId || null;
    if (groupId === '__new__' && newGroupName.trim()) {
      const gres = await api.createEnvelopeGroup(newGroupName.trim());
      if (!gres.ok) { setSaving(false); setError('Gagal buat grup'); return; }
      resolvedGroupId = gres.data.id;
    } else if (groupId === '__new__') {
      resolvedGroupId = null;
    }

    if (editing) {
      const data = {
        name, emoji, budget_amount: Number(budget), is_rollover: rollover,
        is_personal: isPersonal, is_locked: isLocked,
        daily_limit: dailyLimit ? Number(dailyLimit) : null,
        cooling_threshold: coolingThreshold ? Number(coolingThreshold) : null,
        group_id: resolvedGroupId,
        purpose,
      };
      if (isSavingLike) {
        data.budget_amount = purpose === 'saving' ? 0 : Number(budget || 0);
        data.is_rollover = true;
      }
      const result = await api.updateEnvelope(editing.id, data);
      if (!result.ok) { setSaving(false); setError('Gagal update'); return; }

      // Handle goal for saving/sinking_fund during edit
      if (isSavingLike && goalName.trim() && Number(goalAmount) > 0) {
        const goalData = {
          name: goalName.trim(),
          target_amount: Number(goalAmount),
          target_date: goalDate || null,
        };
        if (editingGoal) {
          await api.updateGoal(editingGoal.id, goalData);
        } else {
          await api.createGoal({ envelope_id: editing.id, ...goalData });
        }
      }
      setSaving(false);
      onCreated();
      onClose();
      return;
    }

    // Create new envelope
    const data = {
      name, emoji, budget_amount: Number(fundAmount || budget || 0), is_rollover: rollover,
      is_personal: isPersonal, is_locked: isLocked,
      daily_limit: dailyLimit ? Number(dailyLimit) : null,
      cooling_threshold: coolingThreshold ? Number(coolingThreshold) : null,
      group_id: resolvedGroupId,
      purpose,
    };
    if (isSavingLike) {
      data.budget_amount = purpose === 'saving' ? 0 : Number(budget || 0);
      data.is_rollover = true;
    }
    const createRes = await api.createEnvelope(data);
    if (!createRes.ok) { setSaving(false); setError('Gagal buat amplop'); return; }
    const newEnvId = createRes.data.id;

    // Create goal for saving/sinking_fund
    if (isSavingLike && goalName.trim() && Number(goalAmount) > 0) {
      const goalRes = await api.createGoal({
        envelope_id: newEnvId, name: goalName.trim(),
        target_amount: Number(goalAmount),
        target_date: goalDate || null,
      });
      if (!goalRes.ok) { setSaving(false); setError('Goal gagal dibuat'); return; }
    }

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
        <h3 className="font-display font-bold text-lg mb-4">{editing ? `Edit ${titleCase(editing.name)}` : 'Amplop baru'}</h3>

        {/* Step 1: Basic info + funding (new only) */}
        <div className="space-y-4">
          <div><label className="label">Emoji</label><div className="flex flex-wrap gap-1.5">{EMOJIS.map(e => (<button key={e} type="button" onClick={() => setEmoji(e)} className={`w-9 h-9 rounded-lg text-lg flex items-center justify-center transition-all ${emoji === e ? 'bg-brand-50 ring-2 ring-brand-400' : 'bg-gray-50 hover:bg-gray-100'}`}>{e}</button>))}</div></div>
          <div><label className="label">Nama amplop</label><input type="text" className="input" placeholder="Darurat, Liburan..." value={name} onChange={e => { setName(e.target.value); setPurpose(guessPurpose(e.target.value)); }} required /></div>

          <div>
            <label className="label">Grup</label>
            <select className="input" value={groupId} onChange={(e) => setGroupId(e.target.value)}>
              <option value="">Tanpa grup</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
              <option value="__new__">+ Grup baru…</option>
            </select>
            {groupId === '__new__' && (
              <input type="text" className="input mt-2" placeholder="Nama grup baru (mis. Tabungan)"
                value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} />
            )}
          </div>

          <div>
            <label className="label">Purpose</label>
            <div className="flex gap-1.5">
              {[
                { key: 'expense', label: '💰 Expense', desc: 'Pengeluaran rutin' },
                { key: 'saving', label: '🎯 Saving', desc: 'Target menabung' },
                { key: 'sinking_fund', label: '📅 Sinking Fund', desc: 'Dana persiapan' },
              ].map(p => (
                <button key={p.key} type="button" onClick={() => {
                  if (editing && purpose !== p.key) {
                    if (!confirm(`Ubah purpose ke "${p.label.split(' ')[1]}"? Budget atau goal mungkin terpengaruh.`)) return;
                  }
                  setPurpose(p.key);
                }}
                  className={`flex-1 px-2 py-2 rounded-lg text-xs font-medium transition-all text-center leading-tight ${
                    purpose === p.key ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                  }`}>
                  <span className="block text-base mb-0.5">{p.label.split(' ')[0]}</span>
                  {p.desc}
                </button>
              ))}
            </div>
          </div>

          {/* Goal fields for saving/sinking_fund */}
          {isSavingLike && (
            <div className="border-t border-gray-100 pt-3 space-y-3">
              <h4 className="font-semibold text-sm">🎯 Target {purpose === 'sinking_fund' ? 'dana persiapan' : 'menabung'}</h4>
              <div>
                <label className="label">Nama target</label>
                <input type="text" className="input" placeholder={purpose === 'saving' ? 'Nikah, Darurat, Liburan...' : 'Servis tahunan, Pajak...'}
                  value={goalName} onChange={e => setGoalName(e.target.value)} />
              </div>
              <div>
                <label className="label">Jumlah target (Rp)</label>
                <input type="number" className="input font-mono" placeholder="10000000"
                  value={goalAmount} onChange={e => setGoalAmount(e.target.value)} min="1" />
              </div>
              <div>
                <label className="label">Tanggal target <span className="text-xs text-gray-400">(opsional)</span></label>
                <input type="date" className="input"
                  value={goalDate} onChange={e => setGoalDate(e.target.value)} />
              </div>
              {purpose === 'sinking_fund' && (
                <div>
                  <label className="label">Budget bulanan <span className="text-xs text-gray-400">(opsional)</span></label>
                  <input type="number" className="input font-mono" placeholder="Kosongkan = hanya target"
                    value={budget} onChange={e => setBudget(e.target.value)} min="0" />
                </div>
              )}
            </div>
          )}

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

function TransferModal({ env, envelopes, onClose, onDone }) {
  const [direction, setDirection] = useState('to'); // 'to' = add dana ke env ini, 'from' = ambil dana dari env ini
  const [otherId, setOtherId] = useState('');
  const [amount, setAmount] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const others = envelopes.filter(e => e.id !== env.id);
  const otherEnv = others.find(e => e.id === otherId);

  const fromEnv = direction === 'to' ? otherEnv : env;
  const maxAmount = fromEnv ? Number(fromEnv.remaining) : 0;

  const handleSubmit = async () => {
    if (!otherId || !amount || Number(amount) <= 0) { setError('Lengkapi semua field'); return; }
    if (Number(amount) > maxAmount) { setError(`Melebihi sisa ${direction === 'to' ? 'amplop sumber' : 'amplop ini'}`); return; }
    setSaving(true);
    setError('');
    const fromId = direction === 'to' ? otherId : env.id;
    const toId = direction === 'to' ? env.id : otherId;
    const res = await api.request(
      `/envelopes/transfer?from_id=${fromId}&to_id=${toId}&amount=${amount}`,
      { method: 'POST' }
    );
    setSaving(false);
    if (res.ok) { onDone(); onClose(); }
    else { const d = await res.json(); setError(d.detail || 'Transfer gagal'); }
  };

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-sm p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-bold text-lg mb-1">Geser Dana</h3>
        <p className="text-sm text-gray-400 mb-4">Amplop: {env.emoji} {titleCase(env.name)} (sisa {formatCurrency(Number(env.remaining))})</p>

        <div className="flex gap-2 mb-4">
          <button type="button" onClick={() => { setDirection('to'); setOtherId(''); setAmount(''); }}
            className={`flex-1 py-2 rounded-xl text-sm font-medium transition-all ${direction === 'to' ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500'}`}>
            Tambah dana kesini
          </button>
          <button type="button" onClick={() => { setDirection('from'); setOtherId(''); setAmount(''); }}
            className={`flex-1 py-2 rounded-xl text-sm font-medium transition-all ${direction === 'from' ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500'}`}>
            Kirim dana ke amplop lain
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="label">{direction === 'to' ? 'Ambil dari amplop' : 'Kirim ke amplop'}</label>
            <select className="input" value={otherId} onChange={e => { setOtherId(e.target.value); setAmount(''); }}>
              <option value="">Pilih amplop...</option>
              {others.map(e => (
                <option key={e.id} value={e.id}>
                  {e.emoji} {e.name}
                  {direction === 'to' ? ` (sisa ${formatShort(e.remaining)})` : ''}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Jumlah (Rp)</label>
            <input type="number" className="input font-mono" placeholder="500000"
              value={amount} onChange={e => setAmount(e.target.value)} min="1" max={maxAmount} />
            {otherId && <p className="text-xs text-gray-400 mt-1">Max: {formatCurrency(maxAmount)}</p>}
          </div>
        </div>

        {error && <div className="mt-3 bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>{error}</div>}

        <div className="flex gap-2 mt-4">
          <button type="button" onClick={onClose} className="btn-outline flex-1">Batal</button>
          <button type="button" onClick={handleSubmit} disabled={saving}
            className="btn-primary flex-1 disabled:opacity-50">{saving ? '...' : 'Geser'}</button>
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

function EnvelopeCard({ env, goal, onEdit, onDelete, onTransfer, onGoalCreate, onGoalUpdate, onGoalDelete }) {
  const allocated = Number(env.allocated || 0);
  const rollover = Number(env.rollover || 0);
  const spent = Number(env.spent || 0);
  const remaining = Number(env.remaining || 0);
  const reserved = Number(env.reserved || 0);
  const free = Number(env.free || remaining);
  const spentRatio = env.spent_ratio || 0;
  const isSavingLike = env.purpose === 'saving' || env.purpose === 'sinking_fund';
  const isUnfunded = !isSavingLike && allocated <= 0 && rollover === 0;
  const status = spentRatio >= 0.9 ? 'danger' : spentRatio >= 0.7 ? 'warning' : 'safe';
  const barColor = status === 'danger' ? 'bg-danger-400' : status === 'warning' ? 'bg-amber-400' : 'bg-brand-400';
  const remainColor = free <= 0 ? 'text-danger-400' : status === 'warning' ? 'text-amber-400' : 'text-brand-600';

  const [showGoalForm, setShowGoalForm] = useState(false);
  const [goalName, setGoalName] = useState(goal?.name || '');
  const [goalAmount, setGoalAmount] = useState(goal ? String(Math.round(Number(goal.target_amount))) : '');
  const [goalDate, setGoalDate] = useState(goal?.target_date || '');
  const [goalSaving, setGoalSaving] = useState(false);

  const handleGoalSubmit = async () => {
    if (!goalName.trim() || !goalAmount || Number(goalAmount) <= 0) return;
    setGoalSaving(true);
    const data = {
      envelope_id: env.id,
      name: goalName.trim(),
      target_amount: Number(goalAmount),
      target_date: goalDate || null,
    };
    if (goal) {
      await onGoalUpdate(goal.id, data);
    } else {
      await onGoalCreate(data);
    }
    setGoalSaving(false);
    setShowGoalForm(false);
  };

  const handleGoalDeleteClick = async () => {
    if (goal) {
      await onGoalDelete(goal.id);
      setShowGoalForm(false);
      setGoalName('');
      setGoalAmount('');
      setGoalDate('');
    }
  };

  return (
    <div className={`card group hover:border-brand-200 transition-all ${env.is_locked ? 'opacity-60' : ''}`}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5"><span className="text-2xl">{env.emoji || '📁'}</span><div><h3 className="font-semibold">{titleCase(env.name)}</h3><p className="text-xs text-gray-400">{env.is_personal ? '🔒 Personal' : '👥 Shared'} · {isSavingLike ? (env.purpose === 'sinking_fund' ? 'Sinking Fund' : 'Tabungan') : env.is_rollover ? 'Rollover' : 'Reset'}</p></div></div>
        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-1">
          <button onClick={() => onTransfer(env)} className="text-xs text-gray-400 hover:text-brand-600 px-2 py-1 rounded">Geser</button>
          <button onClick={() => onEdit(env)} className="text-xs text-gray-400 hover:text-brand-600 px-2 py-1 rounded">Edit</button>
          <button onClick={() => onDelete(env.id, env.name)} className="text-xs text-gray-400 hover:text-danger-400 px-2 py-1 rounded">Hapus</button>
        </div>
      </div>
      {isUnfunded ? (
        <div className="bg-amber-50 text-amber-600 text-xs px-3 py-2 rounded-lg">💡 Belum ada dana. Alokasikan income dulu.</div>
      ) : isSavingLike ? (
        <div className="mb-2">
          {goal && (
            <div>
              <div className="flex justify-between items-end mb-1.5">
                <span className={`font-display text-2xl font-bold ${remainColor}`}>{formatShort(free)}</span>
                <span className="text-xs text-gray-400">Saldo</span>
              </div>
              <div className="flex justify-between items-end mb-1">
                <span className="text-xs text-gray-400">🎯 {goal.name}</span>
                <span className="text-xs font-medium text-amber-600">{Math.round(goal.progress_pct)}%</span>
              </div>
              <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-amber-400 rounded-full transition-all duration-700"
                  style={{ width: `${Math.max(goal.progress_pct, 2)}%` }} />
              </div>
              <p className="text-xs text-gray-400 mt-1">{formatShort(goal.current_balance)} / {formatShort(goal.target_amount)}</p>
              {goal.monthly_needed !== null && (
                <p className="text-xs text-gray-400 mt-0.5">📅 {goal.months_remaining} bulan · {formatShort(goal.monthly_needed)}/bln</p>
              )}
              {goal.is_achieved && (
                <span className="inline-block mt-1 text-xs font-medium px-2 py-0.5 rounded-md bg-green-100 text-green-700">✅ Tercapai</span>
              )}
              {goal.target_date && new Date(goal.target_date) < new Date() && !goal.is_achieved && (
                <span className="inline-block mt-0.5 text-xs font-medium px-2 py-0.5 rounded-md bg-red-100 text-red-700">⚠️ Terlambat</span>
              )}
            </div>
          )}
          {!goal && (
            <div className="text-center py-3">
              <p className="text-xs text-gray-400 mb-2">Belum ada target</p>
              <button onClick={() => setShowGoalForm(true)} className="text-xs text-brand-600 hover:underline">+ Buat target</button>
            </div>
          )}
          {env.purpose === 'sinking_fund' && Number(env.budget_amount) > 0 && (
            <p className="text-xs text-gray-400 mt-2 pt-2 border-t border-gray-100">
              Budget: {formatShort(env.budget_amount)}/bulan
            </p>
          )}
          {rollover !== 0 && (
            rollover > 0
              ? <p className="text-xs text-brand-500 mt-1">🔄 Rollover +{formatShort(rollover)} dari bulan lalu</p>
              : <p className="text-xs text-danger-400 mt-1">🔄 {formatShort(Math.abs(rollover))} minus dari bulan lalu</p>
          )}
        </div>
      ) : (
        <div className="mb-2">
          <div className="flex justify-between items-end mb-1.5">
            <span className={`font-display text-2xl font-bold ${env.is_locked ? 'text-gray-400' : remainColor}`}>{formatShort(free)}</span>
            <span className="text-xs text-gray-400">Dana {formatShort(allocated)}</span>
          </div>
          <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden"><div className={`h-full rounded-full transition-all duration-700 ${env.is_locked ? 'bg-gray-300' : barColor}`} style={{ width: `${Math.max(spentRatio * 100, 1)}%` }} /></div>
          <p className="text-xs text-gray-400 mt-1">Terpakai {formatCurrency(spent)} dari {formatCurrency(allocated)}</p>
          {rollover !== 0 && (
            rollover > 0
              ? <p className="text-xs text-brand-500 mt-0.5">🔄 Rollover +{formatShort(rollover)} dari bulan lalu</p>
              : <p className="text-xs text-danger-400 mt-0.5">🔄 {formatShort(Math.abs(rollover))} minus dari bulan lalu</p>
          )}
          {reserved > 0 && <p className="text-xs text-amber-500 mt-0.5">⏳ Reserved: {formatCurrency(reserved)}/bulan</p>}
        </div>
      )}

      {/* Goal actions — only for saving/sinking_fund */}
      {isSavingLike && goal && !showGoalForm && (
        <div className="mt-2 pt-2 border-t border-gray-100">
          <div className="flex items-center gap-2">
            {goal.is_achieved && (
              <span className="text-xs font-medium px-2 py-0.5 rounded-md bg-green-100 text-green-700">✅ Tercapai</span>
            )}
            {goal.target_date && new Date(goal.target_date) < new Date() && !goal.is_achieved && (
              <span className="text-xs font-medium px-2 py-0.5 rounded-md bg-red-100 text-red-700">⚠️ Terlambat</span>
            )}
            <button onClick={() => { setShowGoalForm(true); setGoalName(goal.name); setGoalAmount(String(Math.round(Number(goal.target_amount)))); setGoalDate(goal.target_date || ''); }}
              className="text-xs text-gray-400 hover:text-brand-600 ml-auto">
              Edit target
            </button>
          </div>
        </div>
      )}

      {isSavingLike && !goal && !showGoalForm && (
        <div className="mt-2 pt-2 border-t border-gray-100">
          <button onClick={() => setShowGoalForm(true)}
            className="text-xs text-gray-400 hover:text-amber-600 transition-colors">
            + 🎯 Tambah target tabungan
          </button>
        </div>
      )}

      {isSavingLike && showGoalForm && (
        <div className="mt-2 pt-2 border-t border-gray-100 space-y-2">
          <input type="text" className="input text-sm py-1.5" placeholder="Nama target (Nikah, Darurat...)"
            value={goalName} onChange={e => setGoalName(e.target.value)} />
          <input type="number" className="input text-sm py-1.5 font-mono" placeholder="Jumlah target (Rp)"
            value={goalAmount} onChange={e => setGoalAmount(e.target.value)} min="1" />
          <input type="date" className="input text-sm py-1.5"
            value={goalDate} onChange={e => setGoalDate(e.target.value)} />
          <div className="flex gap-2">
            <button onClick={handleGoalSubmit} disabled={goalSaving}
              className="text-xs px-3 py-1.5 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50">
              {goalSaving ? '...' : goal ? 'Simpan' : 'Buat Target'}
            </button>
            <button onClick={() => setShowGoalForm(false)} className="text-xs px-3 py-1.5 rounded-lg text-gray-400 hover:text-gray-600">Batal</button>
            {goal && (
              <button onClick={handleGoalDeleteClick} className="text-xs px-3 py-1.5 rounded-lg text-red-400 hover:text-red-600 ml-auto">Hapus</button>
            )}
          </div>
        </div>
      )}

      <ControlBadges env={env} />
    </div>
  );
}

function EnvelopeSection({ title, envelopes, groups, goals, onEdit, onDelete, onTransfer, onGroupChanged, onGoalCreate, onGoalUpdate, onGoalDelete }) {
  const hasGroups = envelopes.some((e) => e.group_id);

  const renderGrid = (items) => (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {items.map((env) => {
        const goal = goals?.find(g => g.envelope_id === env.id);
        return (
          <EnvelopeCard key={env.id} env={env} goal={goal}
            onEdit={onEdit} onDelete={onDelete} onTransfer={onTransfer}
            onGoalCreate={onGoalCreate} onGoalUpdate={onGoalUpdate} onGoalDelete={onGoalDelete} />
        );
      })}
    </div>
  );

  if (!hasGroups) {
    return (
      <div>
        <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">{title} ({envelopes.length})</h2>
        {renderGrid(envelopes)}
      </div>
    );
  }

  const sections = buildGroupSections(envelopes, groups);

  const handleRename = async (g) => {
    const next = window.prompt('Nama grup baru:', g.name);
    if (!next || !next.trim() || next.trim() === g.name) return;
    await api.renameEnvelopeGroup(g.id, next.trim());
    onGroupChanged();
  };

  const handleDeleteGroup = async (g) => {
    if (!confirm(`Hapus grup "${g.name}"? Amplop di dalamnya pindah ke Lainnya.`)) return;
    await api.deleteEnvelopeGroup(g.id);
    onGroupChanged();
  };

  return (
    <div>
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">{title} ({envelopes.length})</h2>
      <div className="space-y-5">
        {sections.map((sec) => (
          <div key={sec.id ?? '__none__'}>
            <div className="group flex items-center justify-between mb-2">
              <div className="flex items-baseline gap-2">
                <h3 className="text-sm font-semibold text-gray-600">{sec.name}</h3>
                <span className="text-xs text-gray-400">· saldo {formatCurrency(groupBalance(sec.envelopes))}</span>
              </div>
              {sec.id && (
                <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-2">
                  <button onClick={() => handleRename(sec)} className="text-xs text-gray-400 hover:text-brand-600">✏️ Rename</button>
                  <button onClick={() => handleDeleteGroup(sec)} className="text-xs text-gray-400 hover:text-danger-400">🗑 Hapus</button>
                </div>
              )}
            </div>
            {renderGrid(sec.envelopes)}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Envelopes() {
  const [envelopes, setEnvelopes] = useState([]);
  const [groups, setGroups] = useState([]);
  const [goals, setGoals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState(null);
  const [transferTarget, setTransferTarget] = useState(null);
  const [refreshTick, setRefreshTick] = useState(0);

  const load = () => {
    Promise.all([api.getEnvelopeSummary(), api.getEnvelopeGroups(), api.getGoals()]).then(([env, grp, gls]) => {
      setEnvelopes(env);
      setGroups(grp);
      setGoals(gls);
      setLoading(false);
    });
  };

  useEffect(() => {
    const onAdded = () => setRefreshTick(t => t + 1);
    window.addEventListener('jatahku:txn-added', onAdded);
    return () => window.removeEventListener('jatahku:txn-added', onAdded);
  }, []);

  useEffect(load, [refreshTick]);

  const handleDelete = async (id, name) => {
    if (!confirm(`Hapus amplop "${name}"?`)) return;
    await api.deleteEnvelope(id);
    load();
  };

  const handleGoalCreate = async (data) => {
    const res = await api.createGoal(data);
    if (res.ok) load();
    else alert(res.data?.detail || 'Gagal membuat target');
  };

  const handleGoalUpdate = async (id, data) => {
    const res = await api.updateGoal(id, data);
    if (res.ok) load();
  };

  const handleGoalDelete = async (id) => {
    if (!confirm('Hapus target ini?')) return;
    await api.deleteGoal(id);
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
            <EnvelopeSection title="👥 Shared" envelopes={shared} groups={groups} goals={goals}
              onEdit={setEditing} onDelete={handleDelete} onTransfer={setTransferTarget} onGroupChanged={load}
              onGoalCreate={handleGoalCreate} onGoalUpdate={handleGoalUpdate} onGoalDelete={handleGoalDelete} />
          )}
          {personal.length > 0 && (
            <EnvelopeSection title="🔒 Personal" envelopes={personal} groups={groups} goals={goals}
              onEdit={setEditing} onDelete={handleDelete} onTransfer={setTransferTarget} onGroupChanged={load}
              onGoalCreate={handleGoalCreate} onGoalUpdate={handleGoalUpdate} onGoalDelete={handleGoalDelete} />
          )}
        </>
      )}
      {(showCreate || editing) && <CreateModal editing={editing} envelopes={envelopes} groups={groups} goals={goals} onClose={() => { setShowCreate(false); setEditing(null); }} onCreated={load} />}
      {transferTarget && <TransferModal env={transferTarget} envelopes={envelopes} onClose={() => setTransferTarget(null)} onDone={load} />}
    </div>
  );
}
