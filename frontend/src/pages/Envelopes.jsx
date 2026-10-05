import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../lib/api';
import { formatCurrency, formatShort, formatShortSigned, titleCase } from '../lib/utils';
import { Icon, EnvelopeIcon, BRAND, SAVING } from '../components/Icon';
import { envelopeInsight } from '../lib/envelopeInsight';
import { fundingState } from '../lib/envelopeFunding';
import { envelopeRow } from '../lib/envelopeRow';
import { errorText } from '../lib/balanceCheck';
import { needsClassification, suggestClassification, PURPOSE_OPTIONS } from '../lib/envelopeClassification';
import ClassificationBackfill from '../components/ClassificationBackfill';

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

const PURPOSE_EXPLANATIONS = {
  'expense': { title: 'Pengeluaran rutin', desc: 'Untuk pengeluaran sehari-hari seperti makan, transport, pulsa, dll.' },
  'debt': { title: 'Cicilan/Utang', desc: 'Untuk cicilan, cicilan kredit, atau hutang yang perlu dibayar berkala.' },
  'saving': { title: 'Target menabung', desc: 'Untuk menabung ke tujuan spesifik seperti liburan, nikah, atau darurat.' },
  'sinking_fund': { title: 'Dana persiapan', desc: 'Untuk mengumpulkan dana untuk pengeluaran tahunan/berkala seperti pajak, asuransi.' },
};

const CLASSIFICATION_EXPLANATIONS = {
  'needs': { title: 'Kebutuhan', desc: 'Pengeluaran yang tidak bisa ditunda' },
  'wants': { title: 'Keinginan', desc: 'Pengeluaran yang bisa dikurangi atau ditunda' },
};

export function CreateModal({ onClose, onCreated, editing, envelopes: existingEnvelopes, groups = [], goals = [] }) {
  const editingGoal = editing ? goals.find(g => g.envelope_id === editing.id) : null;
  const [step, setStep] = useState(editing ? 1 : 1); // 1=name, 2=purpose, 3=classification, 4=advanced
  const [name, setName] = useState(editing?.name || '');
  const [emoji, setEmoji] = useState(editing?.emoji || '📁');
  const [budget, setBudget] = useState(editing ? String(Math.round(Number(editing.budget_amount))) : '');
  const [rollover, setRollover] = useState(editing?.is_rollover ?? true);
  const [isPersonal, setIsPersonal] = useState(editing?.is_personal ?? false);
  const [isLocked, setIsLocked] = useState(editing?.is_locked ?? false);
  const [dailyLimit, setDailyLimit] = useState(editing?.daily_limit ? String(Math.round(Number(editing.daily_limit))) : '');
  const [coolingThreshold, setCoolingThreshold] = useState(editing?.cooling_threshold ? String(Math.round(Number(editing.cooling_threshold))) : '');
  const [showAdvanced, setShowAdvanced] = useState(!!(editing?.is_locked || editing?.daily_limit || editing?.cooling_threshold || editing?.group_id));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [groupId, setGroupId] = useState(editing?.group_id || '');
  const [newGroupName, setNewGroupName] = useState('');
  const [purpose, setPurpose] = useState(editing?.purpose || 'expense');
  const [classification, setClassification] = useState(editing?.classification || null);
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
    if (needsClassification(purpose) && !classification) {
      setError('Pilih klasifikasi Kebutuhan atau Keinginan dulu');
      return;
    }
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
        classification: needsClassification(purpose) ? classification : null,
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
      classification: needsClassification(purpose) ? classification : null,
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

  const stepReady = {
    1: name.trim().length > 0,
    2: true,
    3: !needsClassification(purpose) || !!classification,
    4: true,
  };

  const canNext = stepReady[step];
  const canFinish = stepReady[1] && stepReady[3] && (!editing || true);

  // Hide scrollbar style
  const scrollbarHideStyle = { scrollbarWidth: 'none', msOverflowStyle: 'none' };

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-md shadow-xl max-h-[90vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-100">
          <h3 className="font-display font-bold text-lg">{editing ? `Edit ${titleCase(editing.name)}` : 'Amplop baru'}</h3>
          {!editing && <p className="text-xs text-gray-400 mt-1">Langkah {step} dari 4</p>}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6" style={scrollbarHideStyle}>
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <label className="label">Pilih ikon</label>
                <div className="grid grid-cols-6 gap-2">
                  {EMOJIS.map(e => (
                    <button key={e} type="button" onClick={() => setEmoji(e)}
                      className={`w-10 h-10 rounded-lg flex items-center justify-center text-lg transition-all ${
                        emoji === e ? 'bg-brand-50 ring-2 ring-brand-400 scale-110' : 'bg-gray-50 hover:bg-gray-100'
                      }`}>
                      <EnvelopeIcon value={e} size={20} color="currentColor" />
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="label">Nama amplop</label>
                <input type="text" className="input" placeholder="Darurat, Liburan..."
                  value={name} onChange={e => {
                    const v = e.target.value;
                    setName(v);
                    const p = guessPurpose(v);
                    setPurpose(p);
                    if (needsClassification(p) && !classification) setClassification(suggestClassification(v));
                  }} autoFocus />
                <p className="text-xs text-gray-400 mt-2">Sebut nama yang deskriptif untuk amplop ini.</p>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-3">
              <label className="label">Jenis amplop</label>
              <div className="space-y-2">
                {PURPOSE_OPTIONS.map(p => {
                  const exp = PURPOSE_EXPLANATIONS[p.key];
                  return (
                    <button key={p.key} type="button"
                      onClick={() => {
                        if (editing && purpose !== p.key) {
                          if (!confirm(`Ubah jenis ke "${exp.title}"? Budget atau goal mungkin terpengaruh.`)) return;
                        }
                        setPurpose(p.key);
                        if (!needsClassification(p.key)) setClassification(null);
                        else if (!classification) setClassification(suggestClassification(name));
                      }}
                      className={`w-full text-left p-3 rounded-lg border-2 transition-all ${
                        purpose === p.key
                          ? 'bg-brand-50 border-brand-400'
                          : 'bg-gray-50 border-gray-100 hover:border-gray-200'
                      }`}>
                      <div className="flex items-start gap-2.5">
                        <Icon name={p.icon} size={20} color={purpose === p.key ? BRAND : '#6b7280'} className="mt-0.5 flex-shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className={`font-semibold text-sm ${purpose === p.key ? 'text-brand-600' : 'text-gray-700'}`}>{exp.title}</p>
                          <p className="text-xs text-gray-500 mt-0.5">{exp.desc}</p>
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {step === 3 && needsClassification(purpose) && (
            <div className="space-y-3">
              <label className="label">Kategori pengeluaran <span className="text-danger-400">*</span></label>
              <div className="space-y-2">
                {[
                  { key: 'needs', exp: CLASSIFICATION_EXPLANATIONS['needs'] },
                  { key: 'wants', exp: CLASSIFICATION_EXPLANATIONS['wants'] },
                ].map(c => (
                  <button key={c.key} type="button" onClick={() => setClassification(c.key)}
                    className={`w-full text-left p-3 rounded-lg border-2 transition-all ${
                      classification === c.key
                        ? 'bg-brand-50 border-brand-400'
                        : 'bg-gray-50 border-gray-100 hover:border-gray-200'
                    }`}>
                    <div className="flex items-start gap-2.5">
                      <Icon name={c.key === 'needs' ? 'check' : 'coffee'} size={20}
                        color={classification === c.key ? BRAND : '#6b7280'} className="mt-0.5 flex-shrink-0" />
                      <div className="flex-1">
                        <p className={`font-semibold text-sm ${classification === c.key ? 'text-brand-600' : 'text-gray-700'}`}>{c.exp.title}</p>
                        <p className="text-xs text-gray-500 mt-0.5">{c.exp.desc}</p>
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {step === 3 && !needsClassification(purpose) && (
            <div className="space-y-4">
              <div>
                <label className="label">Target {purpose === 'sinking_fund' ? 'dana persiapan' : 'menabung'}</label>
                <div>
                  <input type="text" className="input" placeholder={purpose === 'saving' ? 'Nikah, Darurat, Liburan...' : 'Servis tahunan, Pajak...'}
                    value={goalName} onChange={e => setGoalName(e.target.value)} />
                  <p className="text-xs text-gray-400 mt-2">(opsional) Beri nama target untuk amplop ini.</p>
                </div>
              </div>
              {isSavingLike && (
                <>
                  <div>
                    <label className="label">Jumlah target (Rp)</label>
                    <input type="number" className="input font-mono" placeholder="10000000"
                      value={goalAmount} onChange={e => setGoalAmount(e.target.value)} min="1" />
                  </div>
                  <div>
                    <label className="label">Tanggal target</label>
                    <input type="date" className="input" value={goalDate} onChange={e => setGoalDate(e.target.value)} />
                    <p className="text-xs text-gray-400 mt-2">(opsional) Kapan ingin mencapai target ini?</p>
                  </div>
                </>
              )}
            </div>
          )}

          {step === 4 && (
            <div className="space-y-4">
              {/* Advanced settings toggle */}
              <div>
                <button type="button" onClick={() => setShowAdvanced(!showAdvanced)}
                  className="text-sm font-medium text-brand-600 hover:underline flex items-center gap-1.5 w-full">
                  <Icon name={showAdvanced ? 'chevron' : 'chevron'} size={16} weight="bold" className={`transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
                  Pengaturan lainnya
                </button>
              </div>

              {showAdvanced && (
                <div className="space-y-4 bg-brand-50 p-3 rounded-xl">
                  {/* Group */}
                  <div>
                    <label className="label text-xs">Grup</label>
                    <select className="input text-sm" value={groupId} onChange={(e) => setGroupId(e.target.value)}>
                      <option value="">Tanpa grup</option>
                      {groups.map((g) => (
                        <option key={g.id} value={g.id}>{g.name}</option>
                      ))}
                      <option value="__new__">+ Grup baru…</option>
                    </select>
                    {groupId === '__new__' && (
                      <input type="text" className="input text-sm mt-2" placeholder="Nama grup baru (mis. Tabungan)"
                        value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} />
                    )}
                  </div>

                  {/* Rollover & Personal */}
                  <div className="space-y-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={rollover} onChange={e => setRollover(e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-brand-600" />
                      <span className="text-sm text-gray-700">Rollover sisa ke bulan depan</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input type="checkbox" checked={isPersonal} onChange={e => setIsPersonal(e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-brand-600" />
                      <span className="text-sm text-gray-700">Personal (hanya kamu)</span>
                    </label>
                  </div>

                  {/* Behavior Controls */}
                  <div className="border-t border-brand-100 pt-3">
                    <p className="text-xs font-semibold text-gray-600 mb-2">🎯 Behavior controls</p>
                    <div className="space-y-2.5">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked={isLocked} onChange={e => setIsLocked(e.target.checked)} className="w-4 h-4 rounded border-gray-300 text-danger-400" />
                        <span className="text-sm text-gray-700">🔒 Kunci amplop (tidak bisa diubah)</span>
                      </label>
                      <div>
                        <label className="text-xs font-medium text-gray-600">📊 Daily limit (Rp/hari)</label>
                        <input type="number" className="input text-sm font-mono mt-1" placeholder="Kosongkan = no limit"
                          value={dailyLimit} onChange={e => setDailyLimit(e.target.value)} min="0" />
                      </div>
                      <div>
                        <label className="text-xs font-medium text-gray-600">⏳ Cooling threshold (Rp)</label>
                        <input type="number" className="input text-sm font-mono mt-1" placeholder="Kosongkan = no cooling"
                          value={coolingThreshold} onChange={e => setCoolingThreshold(e.target.value)} min="0" />
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Budget for editing */}
              {editing && (
                <div>
                  <label className="label">Budget target (Rp)</label>
                  <input type="number" className="input font-mono" placeholder="1500000" value={budget} onChange={e => setBudget(e.target.value)} min="0" />
                </div>
              )}

              {/* Funding for new envelopes */}
              {!editing && (
                <div className="border-t border-gray-100 pt-4">
                  <h4 className="font-semibold text-sm mb-3 flex items-center gap-1.5"><Icon name="wallet" size={16} color={BRAND} /> Sumber dana</h4>
                  <div className="flex gap-2 mb-3">
                    <button type="button" onClick={() => setFundingSource('transfer')}
                      className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-all inline-flex items-center justify-center gap-1 ${
                        fundingSource === 'transfer' ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500'
                      }`}>
                      <Icon name="transfer" size={16} /> Transfer
                    </button>
                    <button type="button" onClick={() => setFundingSource('income')}
                      className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium transition-all inline-flex items-center justify-center gap-1 ${
                        fundingSource === 'income' ? 'bg-brand-50 text-brand-600 ring-1 ring-brand-400' : 'bg-gray-50 text-gray-500'
                      }`}>
                      <Icon name="income" size={16} /> Income
                    </button>
                  </div>

                  {fundingSource === 'transfer' && (
                    <div className="space-y-3">
                      <div>
                        <label className="label text-sm">Transfer dari amplop</label>
                        <select className="input" value={transferFrom} onChange={e => setTransferFrom(e.target.value)}>
                          <option value="">Pilih amplop sumber</option>
                          {fundableEnvelopes.map(env => (
                            <option key={env.id} value={env.id}>{env.emoji} {env.name} (sisa {formatShort(env.remaining)})</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="label text-sm">Jumlah (Rp)</label>
                        <input type="number" className="input font-mono" placeholder="500000" value={fundAmount}
                          onChange={e => setFundAmount(e.target.value)} min="1" max={maxTransfer} />
                        {transferFrom && <p className="text-xs text-gray-400 mt-1">Max: {formatCurrency(maxTransfer)}</p>}
                      </div>
                    </div>
                  )}

                  {fundingSource === 'income' && (
                    <div className="space-y-3">
                      <div>
                        <label className="label text-sm">Total income (Rp)</label>
                        <input type="number" className="input font-mono" placeholder="1000000" value={newIncomeAmount}
                          onChange={e => setNewIncomeAmount(e.target.value)} min="1" />
                      </div>
                      <div>
                        <label className="label text-sm">Sumber</label>
                        <input type="text" className="input" value={newIncomeDesc}
                          onChange={e => setNewIncomeDesc(e.target.value)} placeholder="Gaji, Bonus, Freelance..." />
                      </div>
                      <div>
                        <label className="label text-sm">Alokasi ke amplop ini (Rp)</label>
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
            </div>
          )}

          {error && <div className="mt-4 bg-red-50 border border-red-200 text-sm px-4 py-3 rounded-xl" style={{color:'#E24B4A'}}>{error}</div>}
        </div>

        {/* Footer */}
        <div className="border-t border-gray-100 px-6 py-4 flex gap-2 bg-gray-50">
          <button type="button" onClick={onClose} className="btn-outline flex-1">Batal</button>
          {step < 4 && (
            <button type="button" onClick={() => setStep(step + 1)} disabled={!canNext}
              className="btn-primary flex-1 disabled:opacity-50">
              Lanjut →
            </button>
          )}
          {step === 4 && (
            <button type="button" onClick={handleSubmit} disabled={saving || !canFinish}
              className="btn-primary flex-1 disabled:opacity-50">
              {saving ? '...' : editing ? 'Simpan' : 'Buat & Alokasi'}
            </button>
          )}
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

function useMediaQuery(query) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);
  return matches;
}

const ROW_AMOUNT_CLS = { safe: 'text-brand-600', warning: 'text-amber-500', danger: 'text-danger-400', muted: 'text-gray-400' };
const ROW_NOTE_CLS = { muted: 'text-gray-500', safe: 'text-brand-600', warning: 'text-amber-600', danger: 'text-danger-400' };

function ActionButton({ icon, onClick, children }) {
  return (
    <button type="button" onClick={onClick}
      className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium border border-gray-200 bg-white text-gray-600 hover:bg-gray-50 transition-colors">
      <Icon name={icon} size={16} /> {children}
    </button>
  );
}

function CompactDetail({ env, goal, onEdit, onDelete, onTransfer, onGoal }) {
  const allocated = Number(env.allocated || 0);
  const rollover = Number(env.rollover || 0);
  const spent = Number(env.spent || 0);
  const remaining = Number(env.remaining || 0);
  const reserved = Number(env.reserved || 0);
  const spentRatio = env.spent_ratio || 0;
  const isSavingLike = env.purpose === 'saving' || env.purpose === 'sinking_fund';
  const isUnfunded = !isSavingLike && allocated <= 0 && rollover === 0;
  const fstate = isSavingLike ? null : fundingState(env);
  const status = spentRatio >= 0.9 ? 'danger' : spentRatio >= 0.7 ? 'warning' : 'safe';
  const barColor = fstate === 'reserve_short' ? 'bg-amber-400' : (fstate === 'overspent' || status === 'danger') ? 'bg-danger-400' : status === 'warning' ? 'bg-amber-400' : 'bg-brand-400';
  const insight = fstate === 'reserve_short'
    ? { text: `Tagihan butuh ${formatShort(reserved)}, sisa ${formatShort(remaining)}`, tone: 'warning' }
    : envelopeInsight(env, goal);

  const lines = [];
  if (isSavingLike) {
    if (goal) {
      lines.push(['Target', formatShort(goal.target_amount)]);
      if (!goal.is_achieved && goal.monthly_needed != null) {
        lines.push(['Perlu per bulan', `${formatShort(goal.monthly_needed)} · ${goal.months_remaining} bln`]);
      }
    }
    if (env.purpose === 'sinking_fund' && Number(env.budget_amount) > 0) lines.push(['Budget bulanan', formatShort(env.budget_amount)]);
  } else if (!isUnfunded) {
    lines.push(['Terpakai', formatShort(spent)]);
    lines.push(['Dana awal', formatShort(allocated)]);
    if (rollover !== 0) {
      lines.push(rollover > 0
        ? ['Rollover', `+${formatShort(rollover)}`, 'text-brand-600']
        : ['Rollover', formatShortSigned(rollover), 'text-danger-400']);
    }
  }
  if (reserved > 0) lines.push(['Disisihkan untuk tagihan', formatShort(reserved), 'text-amber-600']);

  return (
    <div className="px-4 pb-4 sm:pl-[68px]">
      <p className="text-xs text-gray-400 flex items-center gap-1">
        {env.is_personal ? <><Icon name="lock" size={12} /> Personal</> : <><Icon name="users" size={12} /> Shared</>}
        <span>· {isSavingLike ? (env.purpose === 'sinking_fund' ? 'Sinking Fund' : 'Tabungan') : env.is_rollover ? 'Rollover' : 'Reset'}</span>
      </p>

      {isUnfunded ? (
        <div className="mt-3 bg-amber-50 text-amber-600 text-sm px-3 py-3 rounded-xl flex items-center gap-2">
          <Icon name="warning" size={16} color="#D97706" /> Belum ada dana.
          <Link to="/allocate" className="font-semibold hover:underline">Alokasikan</Link>
        </div>
      ) : isSavingLike && goal ? (
        <>
          <p className="mt-3 text-sm text-gray-600 truncate">{goal.name}</p>
          <div className="h-2 bg-gray-100 rounded-full overflow-hidden mt-2">
            <div className="h-full rounded-full" style={{ width: `${Math.max(goal.progress_pct, 2)}%`, background: env.is_locked ? '#D1D5DB' : SAVING }} />
          </div>
        </>
      ) : !isSavingLike ? (
        <div className="h-2 bg-gray-100 rounded-full overflow-hidden mt-3">
          <div className={`h-full rounded-full ${env.is_locked ? 'bg-gray-300' : barColor}`} style={{ width: `${Math.max(Math.min(spentRatio, 1) * 100, 1)}%` }} />
        </div>
      ) : null}

      {lines.length > 0 && (
        <dl className="mt-3 space-y-2 text-sm">
          {lines.map(([label, value, cls]) => (
            <div key={label} className="flex items-baseline justify-between gap-3">
              <dt className="text-gray-500">{label}</dt>
              <dd className={`font-semibold tabular-nums text-right ${cls || 'text-gray-700'}`}>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      <ControlBadges env={env} />
      {!isUnfunded && <AdvisorStrip insight={insight} leadingIcon={isSavingLike ? 'target' : 'advisor'} />}
      {fstate === 'reserve_short' && (
        <Link to="/allocate" className="mt-1.5 inline-block text-xs font-medium text-amber-600 hover:underline">Alokasikan lagi →</Link>
      )}

      <div className="flex flex-wrap items-center gap-2 mt-4">
        {isSavingLike && <ActionButton icon="target" onClick={() => onGoal(env)}>{goal ? 'Ubah target' : 'Buat target'}</ActionButton>}
        <ActionButton icon="transfer" onClick={() => onTransfer(env)}>Geser dana</ActionButton>
        <ActionButton icon="edit" onClick={() => onEdit(env)}>Edit</ActionButton>
        <button type="button" onClick={() => onDelete(env.id, env.name)}
          className="ml-auto inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium text-danger-400 hover:bg-red-50 transition-colors">
          <Icon name="trash" size={16} /> Hapus
        </button>
      </div>
    </div>
  );
}

function CompactRow({ env, goal, open, onToggle, first, ...actions }) {
  const row = envelopeRow(env, goal);
  const isSavingLike = env.purpose === 'saving' || env.purpose === 'sinking_fund';
  const detailRef = useRef(null);

  useEffect(() => {
    if (!open || !detailRef.current) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    detailRef.current.scrollIntoView({ block: 'nearest', behavior: reduce ? 'auto' : 'smooth' });
  }, [open]);

  const amountCls = env.is_locked ? 'text-gray-400' : row.tone === 'saving' ? '' : ROW_AMOUNT_CLS[row.tone];
  const amountStyle = !env.is_locked && row.tone === 'saving' ? { color: SAVING } : undefined;

  return (
    <li className={first ? '' : 'border-t border-gray-100'}>
      <button type="button" onClick={onToggle} aria-expanded={open} aria-controls={open ? `env-detail-${env.id}` : undefined}
        className="w-full flex items-center gap-3 px-4 py-3.5 text-left hover:bg-gray-50 transition-colors">
        {/* Warna ikon lewat currentColor + kelas tema, supaya tetap terbaca di mode gelap. */}
        <span className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${isSavingLike ? '' : 'bg-brand-50 text-brand-600'}`}
          style={isSavingLike ? { background: 'rgba(99,102,241,0.12)', color: SAVING } : undefined}>
          <EnvelopeIcon value={env.emoji} size={22} color="currentColor" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-start gap-1.5">
            <span className="font-semibold text-gray-800 leading-snug line-clamp-2 break-words">{titleCase(env.name)}</span>
            {env.is_locked && <Icon name="lock" size={13} className="text-gray-400 flex-shrink-0 mt-1" />}
          </span>
          <span className={`block text-xs mt-0.5 truncate ${ROW_NOTE_CLS[row.noteTone]}`}>{row.note}</span>
        </span>
        <span className={`font-display font-bold tabular-nums whitespace-nowrap ${amountCls}`} style={amountStyle}>{formatShortSigned(row.amount)}</span>
        <Icon name="chevron" size={14} weight="bold" className={`text-gray-400 flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div id={`env-detail-${env.id}`} ref={detailRef} className="scroll-mb-24">
          <CompactDetail env={env} goal={goal} {...actions} />
        </div>
      )}
    </li>
  );
}

function CompactEnvelopeList({ sections, goals, onRenameGroup, onDeleteGroup, ...actions }) {
  const [openId, setOpenId] = useState(null);
  const wide = useMediaQuery('(min-width: 1024px)');

  const header = (sec) => sec.name && (
    <div className="group flex items-center justify-between gap-2 px-1 mb-2">
      <div className="flex items-center gap-2 min-w-0">
        <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider truncate">{sec.name}</h3>
        {sec.id && (
          <span className="opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity flex gap-2">
            <button onClick={() => onRenameGroup(sec)} className="text-xs text-gray-400 hover:text-brand-600">Rename</button>
            <button onClick={() => onDeleteGroup(sec)} className="text-xs text-gray-400 hover:text-danger-400">Hapus</button>
          </span>
        )}
      </div>
      <span className="text-xs font-semibold text-gray-500 tabular-nums whitespace-nowrap">{formatShortSigned(groupBalance(sec.envelopes))}</span>
    </div>
  );

  const card = (envs, key) => (
    <ul key={key} className="card !p-0 overflow-hidden">
      {envs.map((env, i) => (
        <CompactRow key={env.id} env={env} goal={goals.find(g => g.envelope_id === env.id)} first={i === 0}
          open={openId === env.id} onToggle={() => setOpenId(id => (id === env.id ? null : env.id))} {...actions} />
      ))}
    </ul>
  );

  const section = (sec) => (
    <section key={sec.id ?? '__none__'}>
      {header(sec)}
      {card(sec.envelopes, 'list')}
    </section>
  );

  let content;
  if (!wide) {
    content = <div className="space-y-6">{sections.map(section)}</div>;
  } else if (sections.length === 1) {
    // Desktop: dua kolom yang menumpuk sendiri-sendiri, jadi membuka satu amplop tidak menggeser kolom sebelah.
    const sec = sections[0];
    const half = Math.ceil(sec.envelopes.length / 2);
    content = (
      <section>
        {header(sec)}
        <div className="grid grid-cols-2 gap-6 items-start">
          {card(sec.envelopes.slice(0, half), 'a')}
          {sec.envelopes.length > 1 && card(sec.envelopes.slice(half), 'b')}
        </div>
      </section>
    );
  } else {
    content = (
      <div className="grid grid-cols-2 gap-6 items-start">
        <div className="space-y-6">{sections.filter((_, i) => i % 2 === 0).map(section)}</div>
        <div className="space-y-6">{sections.filter((_, i) => i % 2 === 1).map(section)}</div>
      </div>
    );
  }
  // Ruang bawah supaya angka di baris terakhir tidak tertutup tombol + yang melayang.
  return <div className="pb-20">{content}</div>;
}

function GoalModal({ env, goal, onClose, onSave, onDelete }) {
  const [name, setName] = useState(goal?.name || '');
  const [amount, setAmount] = useState(goal ? String(Math.round(Number(goal.target_amount))) : '');
  const [date, setDate] = useState(goal?.target_date || '');
  const [saving, setSaving] = useState(false);
  const valid = name.trim() && Number(amount) > 0;

  const handleSave = async () => {
    if (!valid) return;
    setSaving(true);
    await onSave({ envelope_id: env.id, name: name.trim(), target_amount: Number(amount), target_date: date || null });
    setSaving(false);
    onClose();
  };

  const handleDelete = async () => {
    if (await onDelete(goal.id)) onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-sm p-6 shadow-xl" onClick={e => e.stopPropagation()}>
        <h3 className="font-display font-bold text-lg mb-1">{goal ? 'Ubah target' : 'Buat target'}</h3>
        <p className="text-sm text-gray-400 mb-4 flex items-center gap-1.5">Amplop: <EnvelopeIcon value={env.emoji} size={16} color="currentColor" /> {titleCase(env.name)}</p>
        <div className="space-y-3">
          <div>
            <label className="label" htmlFor="goal-name">Nama target</label>
            <input id="goal-name" type="text" className="input" placeholder="Nikah, Darurat, Liburan..." value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="goal-amount">Jumlah target (Rp)</label>
            <input id="goal-amount" type="number" className="input font-mono" placeholder="10000000" min="1" value={amount} onChange={e => setAmount(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="goal-date">Tanggal target <span className="normal-case font-normal text-gray-400">(opsional)</span></label>
            <input id="goal-date" type="date" className="input" value={date} onChange={e => setDate(e.target.value)} />
          </div>
        </div>
        <div className="flex gap-2 mt-5">
          {goal && (
            <button type="button" onClick={handleDelete} className="px-3 py-2.5 rounded-xl text-sm font-semibold text-danger-400 hover:bg-red-50 transition-colors">Hapus</button>
          )}
          <button type="button" onClick={onClose} className="btn-outline flex-1">Batal</button>
          <button type="button" onClick={handleSave} disabled={!valid || saving} className="btn-primary flex-1 disabled:opacity-50">{saving ? '...' : 'Simpan'}</button>
        </div>
      </div>
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
  const [goalTarget, setGoalTarget] = useState(null);


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
    if (!confirm(`Hapus amplop "${name}"?\n\nSisa dananya (termasuk bila minus) dipindah ke Tabungan. Riwayat transaksinya tetap tersimpan.`)) return;
    const res = await api.deleteEnvelope(id);
    if (!res.ok) alert(errorText(res.data, 'Gagal menghapus amplop'));
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
    if (!confirm('Hapus target ini?')) return false;
    await api.deleteGoal(id);
    load();
    return true;
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

      <ClassificationBackfill envelopes={envelopes} onDone={load} />

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
            </div>
          </div>

          {/* Content */}
          {filtered.length === 0 ? (
            <div className="card text-center py-10 text-gray-400 text-sm">Tidak ada amplop di filter ini.</div>
          ) : (
            (() => {
              const grouped = sortBy === 'grup' ? buildGroupSections(filtered, groups) : [];
              const sections = grouped.some(s => s.id !== null)
                ? grouped
                : [{ id: null, name: null, envelopes: sortEnvelopes(filtered, sortBy) }];
              return (
                <CompactEnvelopeList sections={sections} goals={goals}
                  onEdit={setEditing} onDelete={handleDelete} onTransfer={setTransferTarget} onGoal={setGoalTarget}
                  onRenameGroup={handleRenameGroup} onDeleteGroup={handleDeleteGroup} />
              );
            })()
          )}
        </>
      )}
      {(showCreate || editing) && <CreateModal editing={editing} envelopes={envelopes} groups={groups} goals={goals} onClose={() => { setShowCreate(false); setEditing(null); }} onCreated={load} />}
      {transferTarget && <TransferModal env={transferTarget} envelopes={envelopes} onClose={() => setTransferTarget(null)} onDone={load} />}
      {goalTarget && (() => {
        const goal = goals.find(g => g.envelope_id === goalTarget.id);
        return (
          <GoalModal env={goalTarget} goal={goal} onClose={() => setGoalTarget(null)}
            onSave={(data) => (goal ? handleGoalUpdate(goal.id, data) : handleGoalCreate(data))}
            onDelete={handleGoalDelete} />
        );
      })()}
    </div>
  );
}
