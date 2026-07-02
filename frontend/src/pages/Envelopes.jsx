import { useState, useEffect } from 'react';
import { api } from '../lib/api';
import { formatCurrency, formatShort, titleCase } from '../lib/utils';
import { Icon, EnvelopeIcon, BRAND, SAVING } from '../components/Icon';
import { envelopeInsight } from '../lib/envelopeInsight';

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

export function CreateModal({ onClose, onCreated, editing, envelopes: existingEnvelopes, groups = [], goals = [] }) {
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
    } else if (purpose === 'expense' && Number(data.budget_amount) <= 0) {
      data.budget_amount = Number(fundAmount || 500000);
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
          <div><label className="label">Ikon</label><div className="flex flex-wrap gap-1.5">{EMOJIS.map(e => (<button key={e} type="button" onClick={() => setEmoji(e)} className={`w-9 h-9 rounded-lg flex items-center justify-center transition-all ${emoji === e ? 'bg-brand-50 ring-2 ring-brand-400' : 'bg-gray-50 hover:bg-gray-100'}`}><EnvelopeIcon value={e} size={20} color={emoji === e ? BRAND : '#6b7280'} /></button>))}</div></div>
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
                { key: 'expense', icon: 'expense', label: 'Expense', desc: 'Pengeluaran rutin' },
                { key: 'saving', icon: 'target', label: 'Saving', desc: 'Target menabung' },
                { key: 'sinking_fund', icon: 'calendar', label: 'Sinking Fund', desc: 'Dana persiapan' },
              ].map(p => (
                <button key={p.key} type="button" onClick={() => {
                  if (editing && purpose !== p.key) {
                    if (!confirm(`Ubah purpose ke "${p.label}"? Budget atau goal mungkin terpengaruh.`)) return;
                  }
                  setPurpose(p.key);
                }}
                  className={`flex-1 px-2 py-2 rounded-lg text-xs font-medium transition-all text-center leading-tight flex flex-col items-center gap-1 ${
                    purpose === p.key ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                  }`}>
                  <Icon name={p.icon} size={20} color={purpose === p.key ? BRAND : '#6b7280'} />
                  {p.desc}
                </button>
              ))}
            </div>
          </div>

          {/* Goal fields for saving/sinking_fund */}
          {isSavingLike && (
            <div className="border-t border-gray-100 pt-3 space-y-3">
              <h4 className="font-semibold text-sm flex items-center gap-1.5"><Icon name="target" size={16} color={BRAND} /> Target {purpose === 'sinking_fund' ? 'dana persiapan' : 'menabung'}</h4>
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
              <h4 className="font-semibold text-sm mb-3 flex items-center gap-1.5"><Icon name="wallet" size={16} color={BRAND} /> Sumber dana</h4>
              <div className="flex gap-2 mb-3">
                <button type="button" onClick={() => setFundingSource('transfer')}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all inline-flex items-center gap-1.5 ${fundingSource === 'transfer' ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500'}`}>
                  <Icon name="transfer" size={16} /> Transfer dari amplop lain
                </button>
                <button type="button" onClick={() => setFundingSource('income')}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all inline-flex items-center gap-1.5 ${fundingSource === 'income' ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500'}`}>
                  <Icon name="income" size={16} /> Income baru
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
        <p className="text-sm text-gray-400 mb-4 flex items-center gap-1.5">Amplop: <EnvelopeIcon value={env.emoji} size={16} color="currentColor" /> {titleCase(env.name)} (sisa {formatCurrency(Number(env.remaining))})</p>

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

function AdvisorStrip({ insight, leadingIcon }) {
  const TONE = {
    safe:    { box: 'bg-brand-50',  text: 'text-brand-600',  color: BRAND,     glyph: 'check' },
    warning: { box: 'bg-amber-50',  text: 'text-amber-600',  color: '#D97706', glyph: 'warning' },
    danger:  { box: 'bg-red-50',    text: 'text-danger-400', color: '#E24B4A', glyph: 'warning' },
    neutral: { box: 'bg-gray-50',   text: 'text-gray-500',   color: '#9CA3AF', glyph: null },
  };
  const t = TONE[insight.tone] || TONE.neutral;
  return (
    <div className={`mt-3 flex items-center gap-2 rounded-xl px-3 py-2 ${t.box}`}>
      <Icon name={leadingIcon} size={16} color={t.color} />
      <span className={`text-xs font-medium flex-1 ${t.text}`}>{insight.text}</span>
      {t.glyph && <Icon name={t.glyph} size={15} color={t.color} weight="fill" />}
    </div>
  );
}

function EnvelopeCard({ env, goal, onEdit, onDelete, onTransfer, onGoalCreate, onGoalUpdate, onGoalDelete }) {
  const allocated = Number(env.allocated || 0);
  const rollover = Number(env.rollover || 0);
  const spent = Number(env.spent || 0);
  const remaining = Number(env.remaining || 0);
  const reserved = Number(env.reserved || 0);
  const free = Number(env.free ?? remaining);
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

  const [menuOpen, setMenuOpen] = useState(false);
  const accent = isSavingLike ? SAVING : BRAND;
  const iconTint = isSavingLike ? 'rgba(99,102,241,0.10)' : 'rgba(15,110,86,0.08)';
  const pct = Math.round(spentRatio * 100);
  const pctBadgeCls = spentRatio >= 0.9 ? 'bg-red-50 text-danger-400'
    : spentRatio >= 0.7 ? 'bg-amber-50 text-amber-600'
    : 'bg-brand-50 text-brand-600';
  const insight = envelopeInsight(env, goal);

  return (
    <div className={`card group hover:border-brand-200 transition-all relative ${env.is_locked ? 'opacity-60' : ''}`}>
      {/* Header */}
      <div className="flex items-start gap-3 mb-4">
        <div className="w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0" style={{ background: iconTint }}>
          <EnvelopeIcon value={env.emoji} size={26} color={accent} />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="font-display font-bold leading-snug truncate">{titleCase(env.name)}</h3>
          <p className="text-xs text-gray-400 flex items-center gap-1 mt-0.5">
            {env.is_personal ? <><Icon name="lock" size={12} /> Personal</> : <><Icon name="users" size={12} /> Shared</>}
            <span>· {isSavingLike ? (env.purpose === 'sinking_fund' ? 'Sinking Fund' : 'Tabungan') : env.is_rollover ? 'Rollover' : 'Reset'}</span>
          </p>
        </div>
        <button onClick={() => setMenuOpen(v => !v)}
          className="w-8 h-8 -mr-1 -mt-1 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors flex-shrink-0">
          <Icon name="dots" size={18} weight="bold" />
        </button>
        {menuOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
            <div className="absolute right-0 top-10 z-20 w-36 bg-white rounded-xl shadow-lg border border-gray-100 py-1">
              <button onClick={() => { setMenuOpen(false); onTransfer(env); }} className="w-full text-left px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-2"><Icon name="transfer" size={15} /> Geser dana</button>
              <button onClick={() => { setMenuOpen(false); onEdit(env); }} className="w-full text-left px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 flex items-center gap-2"><Icon name="settings" size={15} /> Edit</button>
              <button onClick={() => { setMenuOpen(false); onDelete(env.id, env.name); }} className="w-full text-left px-3 py-2 text-sm text-red-500 hover:bg-red-50 flex items-center gap-2"><Icon name="close" size={15} /> Hapus</button>
            </div>
          </>
        )}
      </div>

      {/* Body */}
      {isUnfunded ? (
        <div className="bg-amber-50 text-amber-600 text-xs px-3 py-3 rounded-xl flex items-center gap-2">
          <Icon name="warning" size={16} color="#D97706" /> Belum ada dana. Alokasikan income dulu.
        </div>
      ) : isSavingLike ? (
        <div>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-[11px] font-semibold tracking-wide text-gray-400 uppercase">Saldo</p>
              <p className="font-display text-3xl font-bold" style={{ color: env.is_locked ? '#9CA3AF' : SAVING }}>{formatShort(goal ? goal.current_balance : free)}</p>
            </div>
            {goal && (
              <span className="text-xs font-semibold px-2.5 py-1 rounded-full whitespace-nowrap flex-shrink-0" style={{ background: 'rgba(99,102,241,0.10)', color: SAVING }}>{Math.round(goal.progress_pct)}% dari target</span>
            )}
          </div>
          {goal ? (
            <>
              <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden mt-3">
                <div className="h-full rounded-full transition-all duration-700" style={{ width: `${Math.max(goal.progress_pct, 2)}%`, background: SAVING }} />
              </div>
              <div className="flex items-stretch gap-3 mt-3">
                <div className="flex items-start gap-2 flex-1 min-w-0">
                  <Icon name="calendar" size={16} className="text-gray-400 mt-0.5 flex-shrink-0" />
                  <div className="text-xs text-gray-500 leading-snug min-w-0">
                    <p className="truncate">{goal.name}</p>
                    {goal.is_achieved ? (
                      <span className="inline-flex items-center gap-1 text-green-600"><Icon name="check" size={12} weight="fill" color="#16A34A" /> Tercapai</span>
                    ) : goal.monthly_needed !== null ? (
                      <p className="text-gray-400">{goal.months_remaining} bulan · {formatShort(goal.monthly_needed)}/bln</p>
                    ) : null}
                  </div>
                </div>
                <div className="w-px bg-gray-100 flex-shrink-0" />
                <div className="text-right flex-shrink-0">
                  <p className="text-[11px] font-semibold tracking-wide text-gray-400 uppercase">Target</p>
                  <p className="text-sm font-semibold text-gray-600 mt-0.5">{formatShort(goal.target_amount)}</p>
                </div>
              </div>
              {env.purpose === 'sinking_fund' && Number(env.budget_amount) > 0 && (
                <p className="text-xs text-gray-400 mt-2">Budget {formatShort(env.budget_amount)}/bulan</p>
              )}
              {reserved > 0 && <p className="text-xs text-amber-500 mt-1 flex items-center gap-1"><Icon name="warning" size={12} /> Reserved {formatShort(reserved)}/bulan</p>}
              {goal.target_date && new Date(goal.target_date) < new Date() && !goal.is_achieved && (
                <span className="inline-flex items-center gap-1 mt-2 text-xs font-medium px-2 py-0.5 rounded-md bg-red-100 text-red-700"><Icon name="warning" size={12} weight="fill" /> Terlambat</span>
              )}
            </>
          ) : (
            <div className="mt-3">
              <button onClick={() => setShowGoalForm(true)} className="text-xs font-medium hover:underline" style={{ color: SAVING }}>+ Buat target</button>
            </div>
          )}
        </div>
      ) : (
        <div>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-[11px] font-semibold tracking-wide text-gray-400 uppercase">Dana Tersedia</p>
              <p className={`font-display text-3xl font-bold ${env.is_locked ? 'text-gray-400' : remainColor}`}>{formatShort(free)}</p>
            </div>
            <span className={`text-xs font-semibold px-2.5 py-1 rounded-full whitespace-nowrap flex-shrink-0 ${pctBadgeCls}`}>{pct}% terpakai</span>
          </div>
          <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden mt-3">
            <div className={`h-full rounded-full transition-all duration-700 ${env.is_locked ? 'bg-gray-300' : barColor}`} style={{ width: `${Math.max(spentRatio * 100, 1)}%` }} />
          </div>
          <div className="flex items-stretch gap-3 mt-3">
            <div className="flex items-start gap-2 flex-1 min-w-0">
              <Icon name="wallet" size={16} className="text-gray-400 mt-0.5 flex-shrink-0" />
              <div className="text-xs text-gray-500 leading-snug min-w-0">
                <p className="truncate">Terpakai {formatCurrency(spent)}</p>
                <p className="text-gray-400 truncate">dari {formatCurrency(allocated)}</p>
              </div>
            </div>
            <div className="w-px bg-gray-100 flex-shrink-0" />
            <div className="text-right flex-shrink-0">
              <p className="text-[11px] font-semibold tracking-wide text-gray-400 uppercase">Dana Awal</p>
              <p className="text-sm font-semibold text-gray-600 mt-0.5">{formatShort(allocated)}</p>
            </div>
          </div>
          {rollover !== 0 && (
            rollover > 0
              ? <p className="text-xs text-brand-500 mt-2 flex items-center gap-1"><Icon name="langganan" size={12} /> Rollover +{formatShort(rollover)} dari bulan lalu</p>
              : <p className="text-xs text-danger-400 mt-2 flex items-center gap-1"><Icon name="langganan" size={12} /> {formatShort(Math.abs(rollover))} minus dari bulan lalu</p>
          )}
          {reserved > 0 && <p className="text-xs text-amber-500 mt-1 flex items-center gap-1"><Icon name="warning" size={12} /> Reserved {formatShort(reserved)}/bulan</p>}
        </div>
      )}

      {/* Goal actions — edit link (badges + add live in the body above) */}
      {isSavingLike && goal && !showGoalForm && (
        <div className="mt-2 pt-2 border-t border-gray-100 text-right">
          <button onClick={() => { setShowGoalForm(true); setGoalName(goal.name); setGoalAmount(String(Math.round(Number(goal.target_amount)))); setGoalDate(goal.target_date || ''); }}
            className="text-xs text-gray-400 hover:text-brand-600">
            Edit target
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

      {!isUnfunded && !showGoalForm && (
        <AdvisorStrip insight={insight} leadingIcon={isSavingLike ? 'target' : 'advisor'} />
      )}
    </div>
  );
}

const FILTERS = [
  { key: 'semua', label: 'Semua', test: () => true },
  { key: 'shared', label: 'Shared', icon: 'users', test: (e) => !e.is_personal },
  { key: 'personal', label: 'Personal', icon: 'lock', test: (e) => e.is_personal },
  { key: 'saving', label: 'Tabungan', icon: 'piggy', test: (e) => e.purpose === 'saving' },
  { key: 'sinking_fund', label: 'Sinking Fund', icon: 'calendar', test: (e) => e.purpose === 'sinking_fund' },
];

const SORTS = [
  { key: 'grup', label: 'Grup' },
  { key: 'nama', label: 'Nama' },
  { key: 'saldo', label: 'Saldo' },
  { key: 'terpakai', label: 'Terpakai' },
];

function envBalance(e) {
  return Number(e.allocated || 0) + Number(e.rollover || 0) - Number(e.spent || 0);
}

function sortEnvelopes(list, sortBy) {
  const arr = [...list];
  if (sortBy === 'nama') arr.sort((a, b) => a.name.localeCompare(b.name));
  else if (sortBy === 'saldo') arr.sort((a, b) => envBalance(b) - envBalance(a));
  else if (sortBy === 'terpakai') arr.sort((a, b) => (b.spent_ratio || 0) - (a.spent_ratio || 0));
  return arr;
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
  const [filter, setFilter] = useState('semua');
  const [sortBy, setSortBy] = useState('grup');
  const [view, setView] = useState('grid');

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

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('new') === '1') setShowCreate(true);
  }, []);

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

  const handleRenameGroup = async (g) => {
    const next = window.prompt('Nama grup baru:', g.name);
    if (!next || !next.trim() || next.trim() === g.name) return;
    await api.renameEnvelopeGroup(g.id, next.trim());
    load();
  };

  const handleDeleteGroup = async (g) => {
    if (!confirm(`Hapus grup "${g.name}"? Amplop di dalamnya pindah ke Lainnya.`)) return;
    await api.deleteEnvelopeGroup(g.id);
    load();
  };

  if (loading) return <div className="text-center py-12 text-gray-400">Loading...</div>;

  const totalSaldo = groupBalance(envelopes);
  const counts = Object.fromEntries(FILTERS.map(f => [f.key, envelopes.filter(f.test).length]));
  const activeFilter = FILTERS.find(f => f.key === filter) || FILTERS[0];
  const filtered = envelopes.filter(activeFilter.test);
  const gridCls = view === 'list' ? 'grid grid-cols-1 gap-3' : 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4';

  const cardOf = (env) => (
    <EnvelopeCard key={env.id} env={env} goal={goals.find(g => g.envelope_id === env.id)}
      onEdit={setEditing} onDelete={handleDelete} onTransfer={setTransferTarget}
      onGoalCreate={handleGoalCreate} onGoalUpdate={handleGoalUpdate} onGoalDelete={handleGoalDelete} />
  );

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-display font-bold">Amplop</h1>
          <p className="text-sm text-gray-500">Kelola semua amplop keuanganmu</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="card !p-3 flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(15,110,86,0.08)' }}><Icon name="envelope" size={18} color={BRAND} /></div>
            <div><p className="font-display font-bold text-base leading-none">{envelopes.length}</p><p className="text-xs text-gray-400 mt-0.5">Amplop aktif</p></div>
          </div>
          <div className="card !p-3 flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(15,110,86,0.08)' }}><Icon name="coins" size={18} color={BRAND} /></div>
            <div><p className="font-display font-bold text-base leading-none">{formatShort(totalSaldo)}</p><p className="text-xs text-gray-400 mt-0.5">Total saldo</p></div>
          </div>
        </div>
      </div>

      {envelopes.length === 0 ? (
        <div className="card text-center py-12"><div className="flex justify-center mb-3"><Icon name="envelope" size={40} color={BRAND} /></div><p className="text-gray-500 mb-4">Belum ada amplop.</p><button onClick={() => setShowCreate(true)} className="btn-primary">Buat Amplop Pertama</button></div>
      ) : (
        <>
          {/* Filter tabs + controls */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 pb-3">
            <div className="flex flex-wrap items-center gap-1.5">
              {FILTERS.map(f => (
                <button key={f.key} onClick={() => setFilter(f.key)}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium inline-flex items-center gap-1.5 transition-colors ${filter === f.key ? 'bg-brand-600 text-white' : 'bg-gray-50 text-gray-500 hover:bg-gray-100'}`}>
                  {f.icon && <Icon name={f.icon} size={14} color={filter === f.key ? '#fff' : '#6b7280'} />}
                  {f.label}
                  <span className={`text-xs px-1.5 py-0.5 rounded-full ${filter === f.key ? 'bg-white/20' : 'bg-gray-200 text-gray-500'}`}>{counts[f.key]}</span>
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <div className="relative">
                <select value={sortBy} onChange={e => setSortBy(e.target.value)}
                  className="appearance-none text-sm border border-gray-200 rounded-lg pl-3 pr-8 py-1.5 text-gray-600 bg-white hover:bg-gray-50 cursor-pointer">
                  {SORTS.map(s => <option key={s.key} value={s.key}>Urutkan: {s.label}</option>)}
                </select>
                <Icon name="chevron" size={14} weight="bold" className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
              </div>
              <div className="flex items-center gap-0.5 border border-gray-200 rounded-lg p-0.5">
                <button onClick={() => setView('grid')} className={`w-8 h-7 rounded-md flex items-center justify-center transition-colors ${view === 'grid' ? 'bg-brand-50 text-brand-600' : 'text-gray-400 hover:bg-gray-50'}`} title="Grid"><Icon name="grid" size={16} /></button>
                <button onClick={() => setView('list')} className={`w-8 h-7 rounded-md flex items-center justify-center transition-colors ${view === 'list' ? 'bg-brand-50 text-brand-600' : 'text-gray-400 hover:bg-gray-50'}`} title="List"><Icon name="rows" size={16} /></button>
              </div>
            </div>
          </div>

          {/* Content */}
          {filtered.length === 0 ? (
            <div className="card text-center py-10 text-gray-400 text-sm">Tidak ada amplop di filter ini.</div>
          ) : sortBy === 'grup' ? (
            (() => {
              const sections = buildGroupSections(filtered, groups);
              const showHeaders = sections.some(s => s.id !== null);
              if (!showHeaders) return <div className={gridCls}>{filtered.map(cardOf)}</div>;
              return (
                <div className="space-y-6">
                  {sections.map(sec => (
                    <div key={sec.id ?? '__none__'}>
                      <div className="group flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <Icon name="group" size={16} color={BRAND} />
                          <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">{sec.name}</h3>
                          <span className="text-xs text-gray-400">· Saldo {formatCurrency(groupBalance(sec.envelopes))}</span>
                        </div>
                        {sec.id && (
                          <div className="opacity-0 group-hover:opacity-100 transition-opacity flex gap-2">
                            <button onClick={() => handleRenameGroup(sec)} className="text-xs text-gray-400 hover:text-brand-600">Rename</button>
                            <button onClick={() => handleDeleteGroup(sec)} className="text-xs text-gray-400 hover:text-danger-400">Hapus</button>
                          </div>
                        )}
                      </div>
                      <div className={gridCls}>{sec.envelopes.map(cardOf)}</div>
                    </div>
                  ))}
                </div>
              );
            })()
          ) : (
            <div className={gridCls}>{sortEnvelopes(filtered, sortBy).map(cardOf)}</div>
          )}
        </>
      )}
      {(showCreate || editing) && <CreateModal editing={editing} envelopes={envelopes} groups={groups} goals={goals} onClose={() => { setShowCreate(false); setEditing(null); }} onCreated={load} />}
      {transferTarget && <TransferModal env={transferTarget} envelopes={envelopes} onClose={() => setTransferTarget(null)} onDone={load} />}
    </div>
  );
}
