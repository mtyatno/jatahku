import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../lib/api';
import { parseMultiExpense, parseAmount } from '../lib/parseAmount';
import { enqueueTransaction } from '../lib/offlineQueue';
import QuickAddTransaction from './QuickAddTransaction';

function formatRupiah(n) {
  return 'Rp ' + Number(n).toLocaleString('id-ID');
}

function ItemRow({ item, index, envelopes, onChangeEnvelope, onRemove }) {
  return (
    <div className={`
      group flex flex-col md:grid md:grid-cols-12 gap-2 md:gap-3 items-start md:items-center
      py-2 md:py-1.5 border-b border-gray-100 last:border-0
      ${!item.envelopeId ? 'bg-amber-50/50 -mx-2 px-2 rounded' : ''}
    `}>
      <div className="flex items-center gap-2 md:col-span-5 min-w-0">
        <button
          type="button"
          onClick={() => onRemove(index)}
          className="shrink-0 text-gray-400 hover:text-red-500 text-sm leading-none p-1"
          title="Hapus item"
        >&times;</button>
        <span className="text-sm text-gray-800 truncate">{item.description}</span>
      </div>
      <div className="md:col-span-2">
        <span className="text-sm font-mono text-gray-700">{formatRupiah(item.amount)}</span>
      </div>
      <div className="md:col-span-4 w-full">
        <select
          className={`input text-sm py-1.5 w-full ${!item.envelopeId ? 'border-amber-400 ring-1 ring-amber-200' : ''}`}
          value={item.envelopeId}
          onChange={e => onChangeEnvelope(index, e.target.value)}
        >
          <option value="">Pilih amplop</option>
          {envelopes.filter(env => env.purpose !== 'saving' && env.purpose !== 'sinking_fund').map(env => (
            <option key={env.id} value={env.id}>{env.emoji} {env.name}</option>
          ))}
        </select>
        {item.suggested && <span className="text-xs text-brand-600">· disarankan</span>}
      </div>
      <div className="md:col-span-1">
        {item.error && <span className="text-xs text-red-500" title={item.error}>Gagal</span>}
        {item.saving && <span className="text-xs text-gray-400">...</span>}
      </div>
    </div>
  );
}

export default function MultiAddTransaction({ onSaved, onCancel }) {
  const [rawText, setRawText] = useState('');
  const [items, setItems] = useState([]);
  const [envelopes, setEnvelopes] = useState([]);
  const [saving, setSaving] = useState(false);
  const [resultMsg, setResultMsg] = useState(null);
  const [showSingleForm, setShowSingleForm] = useState(false);
  const [singleFormKey, setSingleFormKey] = useState(0);
  const debounceRef = useRef(null);
  const lastParsedRef = useRef('');
  const userTouchedRef = useRef({});

  useEffect(() => { api.getEnvelopes().then(setEnvelopes); }, []);

  const applySuggestions = useCallback((parsedItems) => {
    if (!navigator.onLine || parsedItems.length === 0) return;
    const descriptions = parsedItems.map(i => i.description);
    api.batchSuggestEnvelopes(descriptions).then(res => {
      if (!res || !res.results) return;
      setItems(prev => prev.map((item, i) => {
        if (userTouchedRef.current[i]) return item;
        const match = res.results.find(r => r.index === i);
        if (match && match.confident && match.envelope_id) {
          return { ...item, envelopeId: match.envelope_id, suggested: true };
        }
        return item;
      }));
    });
  }, []);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    const txt = rawText.trim();
    if (txt === lastParsedRef.current) return;

    debounceRef.current = setTimeout(() => {
      lastParsedRef.current = txt;
      if (!txt) {
        setItems([]);
        userTouchedRef.current = {};
        return;
      }

      let parsed = parseMultiExpense(txt);
      if (!parsed) {
        const single = parseAmount(txt);
        if (single) {
          parsed = [single];
        } else {
          setItems([]);
          userTouchedRef.current = {};
          return;
        }
      }

      const newItems = parsed.map((p, i) => ({
        ...p,
        envelopeId: '',
        suggested: false,
        error: null,
        saving: false,
      }));

      setResultMsg(null);
      setItems(newItems);
      userTouchedRef.current = {};
      applySuggestions(newItems);
    }, 300);

    return () => clearTimeout(debounceRef.current);
  }, [rawText, applySuggestions]);

  const handleEnvelopeChange = (index, value) => {
    userTouchedRef.current[index] = true;
    setItems(prev => prev.map((item, i) =>
      i === index ? { ...item, envelopeId: value, suggested: false, error: null } : item
    ));
  };

  const handleRemove = (index) => {
    delete userTouchedRef.current[index];
    setItems(prev => prev.filter((_, i) => i !== index));
  };

  const handleSaveAll = async () => {
    const pending = items.filter(i => i.envelopeId);
    if (pending.length === 0) {
      setResultMsg({ type: 'error', text: 'Pilih amplop untuk setiap item' });
      return;
    }

    const missing = items.length - pending.length;
    setSaving(true);
    setResultMsg(null);

    if (!navigator.onLine) {
      let queued = 0;
      for (const item of items) {
        if (!item.envelopeId) continue;
        await enqueueTransaction({
          envelope_id: item.envelopeId,
          amount: item.amount,
          description: item.description,
          source: 'webapp',
        });
        queued++;
      }
      setSaving(false);
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      setRawText('');
      setItems([]);
      lastParsedRef.current = '';
      userTouchedRef.current = {};
      onSaved?.();
      return;
    }

    const payload = pending.map((item, i) => ({
      envelope_id: item.envelopeId,
      amount: item.amount,
      description: item.description,
      source: 'webapp',
    }));

    const result = await api.batchCreateTransactions(payload);
    setSaving(false);

    if (!result.ok) {
      setResultMsg({ type: 'error', text: 'Gagal menyimpan. Coba lagi.' });
      return;
    }

    const data = result.data || [];
    let successCount = 0;
    const failedIndices = [];

    data.forEach(r => {
      if (r.ok) {
        successCount++;
      } else {
        failedIndices.push(r.index);
      }
    });

    setItems(prev => prev.map((item, i) => {
      const r = data.find(d => d.index === i);
      if (r && !r.ok) {
        return { ...item, error: r.error || 'Gagal' };
      }
      return { ...item, error: null };
    }));

    if (successCount > 0) {
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      const failedCount = data.length - successCount;
      if (failedCount === 0) {
        setResultMsg({ type: 'success', text: `${successCount} transaksi berhasil disimpan` });
        setRawText('');
        setItems([]);
        lastParsedRef.current = '';
        userTouchedRef.current = {};
        onSaved?.();
      } else {
        setResultMsg({
          type: 'mixed',
          text: `${successCount} berhasil, ${failedCount} gagal`,
        });
        setItems(prev => prev.filter((_, i) => {
          const r = data.find(d => d.index === i);
          return r && !r.ok;
        }));
      }
    } else {
      const firstErr = (result.data || []).find(d => d.error)?.error || 'Gagal menyimpan';
      setResultMsg({ type: 'error', text: firstErr });
    }
  };

  const hasItems = items.length > 0;
  const selectedCount = items.filter(i => i.envelopeId).length;
  const unselectedCount = items.length - selectedCount;

  return (
    <div className="space-y-4">
      <div>
        <label className="label text-xs">Ketik beberapa pengeluaran sekaligus — pisahkan dengan koma, baris baru, atau "dan"</label>
        <textarea
          className="input w-full h-24 resize-y font-mono text-sm"
          placeholder={`kopi 15k\nsabun 5.000\nair mineral Rp5.000, gojek 12000\ntelor 1,5`}
          value={rawText}
          onChange={e => setRawText(e.target.value)}
          disabled={saving}
        />
      </div>

      {!hasItems && !saving && (
        <div className="text-center py-4 text-gray-400 text-sm">
          Ketik pengeluaran Anda di atas
        </div>
      )}

      {hasItems && (
        <>
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">
              {items.length} item terdeteksi
              {unselectedCount > 0 && <span className="text-amber-600"> · {unselectedCount} perlu amplop</span>}
            </span>
          </div>

          <div className="max-h-64 overflow-y-auto border border-gray-200 rounded-xl divide-y divide-gray-100">
            <div className="hidden md:grid md:grid-cols-12 gap-3 px-3 py-2 bg-gray-50 rounded-t-xl text-xs font-medium text-gray-500">
              <span className="col-span-5">Keterangan</span>
              <span className="col-span-2">Jumlah</span>
              <span className="col-span-4">Amplop</span>
              <span className="col-span-1"></span>
            </div>
            <div className="px-3">
              {items.map((item, i) => (
                <ItemRow
                  key={i}
                  item={item}
                  index={i}
                  envelopes={envelopes}
                  onChangeEnvelope={handleEnvelopeChange}
                  onRemove={handleRemove}
                />
              ))}
            </div>
          </div>
        </>
      )}

      {resultMsg && (
        <div className={`text-sm px-3 py-2 rounded-xl ${
          resultMsg.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' :
          resultMsg.type === 'mixed' ? 'bg-amber-50 text-amber-700 border border-amber-200' :
          'bg-red-50 border border-red-200'
        }`} style={resultMsg.type === 'error' ? {color:'#E24B4A'} : undefined}>
          {resultMsg.text}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSaveAll}
          disabled={saving || !hasItems}
          className="btn-primary disabled:opacity-50"
        >
          {saving ? 'Menyimpan...' : `Simpan Semua${selectedCount > 0 ? ` (${selectedCount})` : ''}`}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel} className="btn-outline" disabled={saving}>Batal</button>
        )}
      </div>

      <div className="border-t border-gray-100 pt-2">
        <button
          type="button"
          onClick={() => setShowSingleForm(!showSingleForm)}
          className="text-sm text-gray-400 hover:text-gray-600 transition-colors flex items-center gap-1"
        >
          <span>{showSingleForm ? '▲' : '▼'}</span>
          Atau catat satu per satu
        </button>
        {showSingleForm && (
          <div className="mt-3">
            <QuickAddTransaction
              key={singleFormKey}
              onSaved={() => { setSingleFormKey(k => k + 1); }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
