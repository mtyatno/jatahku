import { useState } from 'react';
import { api } from '../lib/api';
import { Icon, EnvelopeIcon, BRAND } from './Icon';
import { titleCase } from '../lib/utils';
import { suggestClassification } from '../lib/envelopeClassification';
import { unclassifiedEnvelopes } from '../lib/classificationBackfill';

export default function ClassificationBackfill({ envelopes, onDone }) {
  const queue = unclassifiedEnvelopes(envelopes);
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(0);
  const [saving, setSaving] = useState(false);

  if (queue.length === 0) return null;

  const current = queue[idx];
  const suggestion = current ? suggestClassification(current.name) : null;

  const save = async (classification) => {
    if (!current) return;
    setSaving(true);
    await api.updateEnvelopeClassification(current, classification);
    setSaving(false);
    if (idx + 1 >= queue.length) {
      setOpen(false);
      setIdx(0);
      onDone?.();
    } else {
      setIdx(idx + 1);
    }
  };

  if (!open) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl px-4 py-3 bg-amber-50 border border-amber-200">
        <span className="text-sm text-amber-700 flex items-center gap-2">
          <Icon name="warning" size={16} color="#D97706" />
          {queue.length} amplop belum terklasifikasi
        </span>
        <button onClick={() => { setIdx(0); setOpen(true); }}
          className="text-sm font-medium text-amber-700 hover:underline shrink-0">Lengkapi →</button>
      </div>
    );
  }

  const btn = (key, label, icon) => {
    const isSuggested = suggestion === key;
    return (
      <button key={key} type="button" disabled={saving} onClick={() => save(key)}
        className={`flex-1 px-3 py-3 rounded-xl text-sm font-medium transition-all inline-flex flex-col items-center gap-1.5 disabled:opacity-50 ${
          isSuggested ? 'bg-brand-50 text-brand-600 ring-2 ring-brand-400' : 'bg-gray-50 text-gray-600 hover:bg-gray-100'
        }`}>
        <Icon name={icon} size={22} color={isSuggested ? BRAND : '#6b7280'} />
        {label}
        {isSuggested && <span className="text-[10px] font-normal text-brand-500">disarankan</span>}
      </button>
    );
  };

  return (
    <div className="rounded-xl px-4 py-4 bg-white border border-amber-200 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-amber-600 uppercase tracking-wide">
          Klasifikasi amplop · {idx + 1}/{queue.length}
        </span>
        <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600"><Icon name="close" size={16} /></button>
      </div>
      <div className="flex items-center gap-2">
        <EnvelopeIcon value={current.emoji} size={24} color={BRAND} />
        <span className="font-display font-bold">{titleCase(current.name)}</span>
      </div>
      <p className="text-xs text-gray-500">Amplop ini kebutuhan atau keinginan?</p>
      <div className="flex gap-2">
        {btn('needs', 'Kebutuhan', 'check')}
        {btn('wants', 'Keinginan', 'coffee')}
      </div>
    </div>
  );
}
