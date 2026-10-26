import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../lib/api';
import { parseMultiExpense, parseAmount } from '../lib/parseAmount';
import { enqueueTransaction } from '../lib/offlineQueue';
import QuickAddTransaction from './QuickAddTransaction';
import VoiceInput from './VoiceInput';
import ReceiptInput, { pickReceiptPhoto } from './ReceiptInput';
import ReceiptStatusCard from './ReceiptStatusCard';
import { useReceiptScan } from '../hooks/useReceiptScan';
import { STAGE } from '../lib/receiptProgress';
import ReceiptCard from './ReceiptCard';
import { receiptToItem, scanMessage, feedbackFor, confidenceLabel } from '../lib/receiptScan';
import { buildPlan, applyItemSuggestions } from '../lib/receiptSplit';
import { newRef } from '../lib/ref';
import FundEnvelopeModal from './FundEnvelopeModal';
import { Icon } from './Icon';

function formatRupiah(n) {
  return 'Rp ' + Number(n).toLocaleString('id-ID');
}

// Tanggal hari ini di zona waktu perangkat (toISOString memakai UTC → salah sebelum 07:00 WIB).
function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Ditolak karena limit harian → tawarkan "naikkan limit hari ini" (sama dengan bot).
function isDailyLimitError(errMsg) {
  return !!errMsg && String(errMsg).toLowerCase().includes('limit harian');
}

function isInsufficientFundsError(errMsg) {
  if (!errMsg) return false;
  const lower = String(errMsg).toLowerCase();
  return lower.includes('dana tidak cukup') || lower.includes('belum ada dana') || lower.includes('belum didanai');
}

// Struk dengan rincian barang → disimpan lewat rencana (1 transaksi per barang).
function hasReceiptItems(item) {
  return item.origin === 'receipt' && (item.receiptItems || []).length > 0;
}

// Rencana yang dibekukan (sesudah percobaan simpan) atau dihitung dari isian sekarang.
function receiptPlan(item) {
  return item.plan || buildPlan(item);
}

// Siap disimpan: punya amplop (struk: setiap bagian yang belum tersimpan punya amplop).
function isReady(item) {
  if (hasReceiptItems(item)) {
    const left = receiptPlan(item).filter(g => !g.saved);
    return left.length > 0 && left.every(g => g.envelopeId);
  }
  return !!item.envelopeId;
}

// Struk dicatat per barang, jadi masalah amplop (dana kurang, limit harian,
// pindah amplop) berlaku untuk SEMUA barang yang belum tersimpan di amplop itu.
const patchPlanEnvelope = (item, envelopeId, patch) => ({
  ...item,
  plan: (item.plan || []).map(g => (!g.saved && g.envelopeId === envelopeId ? { ...g, ...patch } : g)),
});

const groupEnvelope = (item, gid) => (item.plan || []).find(g => g.id === gid)?.envelopeId;

function ItemRow({ item, envelopes, onChangeEnvelope, onChangeField, onRemove, onFundEnvelope, onRaiseLimit }) {
  const isShortage = isInsufficientFundsError(item.error);
  const isOverDailyLimit = isDailyLimitError(item.error);
  const isReceipt = item.origin === 'receipt';
  const doubtful = isReceipt && item.confidence !== 'tinggi';

  // Hasil simpan belum pasti: isian dikunci supaya kirim ulang (kunci yang sama)
  // tidak membawa nilai berbeda dari yang mungkin sudah tercatat.
  return (
    <fieldset disabled={!!item.uncertain} className={`
      group flex flex-col md:grid md:grid-cols-12 gap-2 md:gap-3 items-start md:items-center
      py-2 md:py-1.5 border-b border-gray-100 last:border-0
      ${!item.envelopeId ? 'bg-amber-50/50 -mx-2 px-2 rounded' : ''}
    `}>
      {item.uncertain && (
        <span className="md:col-span-12 text-xs text-amber-700">
          Hasil simpan belum pasti — tekan Simpan Semua lagi (tidak akan tercatat dua kali).
        </span>
      )}
      <div className="flex items-center gap-2 md:col-span-5 min-w-0">
        <button
          type="button"
          onClick={() => onRemove(item.key)}
          className="shrink-0 text-gray-400 hover:text-red-500 text-sm leading-none p-1"
          title="Hapus item"
        >&times;</button>
        {isReceipt ? (
          <div className="flex flex-col gap-1 min-w-0 w-full">
            <span className="text-xs text-brand-600 inline-flex items-center gap-1">
              <Icon name="camera" size={12} /> Dari struk{doubtful && <span className="text-amber-600"> · {confidenceLabel(item.confidence)}</span>}
            </span>
            <input
              className="input text-sm py-1 w-full"
              value={item.description}
              onChange={e => onChangeField(item.key, 'description', e.target.value)}
              aria-label="Keterangan struk"
            />
            <input
              type="date"
              className="input text-xs py-1 w-full md:w-40"
              value={item.transactionDate || ''}
              max={localToday()}
              onChange={e => onChangeField(item.key, 'transactionDate', e.target.value || null)}
              aria-label="Tanggal struk"
            />
          </div>
        ) : (
          <span className="text-sm text-gray-800 truncate">{item.description}</span>
        )}
      </div>
      <div className="md:col-span-2 w-full">
        {isReceipt ? (
          <input
            type="number"
            inputMode="numeric"
            min="0"
            className={`input text-sm py-1 font-mono w-full ${doubtful || !item.amount ? 'border-amber-400 ring-1 ring-amber-200' : ''}`}
            value={item.amount || ''}
            placeholder="Nominal"
            onChange={e => onChangeField(item.key, 'amount', Number(e.target.value) || 0)}
            aria-label="Total struk"
          />
        ) : (
          <span className="text-sm font-mono text-gray-700">{formatRupiah(item.amount)}</span>
        )}
      </div>
      <div className="md:col-span-4 w-full">
        <select
          className={`input text-sm py-1.5 w-full ${!item.envelopeId ? 'border-amber-400 ring-1 ring-amber-200' : ''}`}
          value={item.envelopeId}
          onChange={e => onChangeEnvelope(item.key, e.target.value)}
        >
          <option value="">Pilih amplop</option>
          {envelopes.filter(env => env.purpose !== 'saving' && env.purpose !== 'sinking_fund').map(env => (
            <option key={env.id} value={env.id}>{env.emoji} {env.name}</option>
          ))}
        </select>
        {item.suggested && <span className="text-xs text-brand-600">· disarankan</span>}
      </div>
      <div className="md:col-span-1 flex items-center gap-1.5 flex-wrap">
        {item.error && (
          <span className="text-xs text-red-500 font-medium" title={item.error}>
            Gagal
          </span>
        )}
        {isShortage && item.envelopeId && (
          <button
            type="button"
            onClick={() => onFundEnvelope(item.key)}
            className="text-xs text-brand-600 hover:text-brand-700 underline font-medium hover:bg-brand-50 px-1 py-0.5 rounded transition-colors"
            title="Geser dana dari amplop lain atau top-up"
          >
            Geser
          </button>
        )}
        {isOverDailyLimit && item.envelopeId && (
          <button
            type="button"
            onClick={() => onRaiseLimit(item.key)}
            className="text-xs text-brand-600 hover:text-brand-700 underline font-medium hover:bg-brand-50 px-1 py-0.5 rounded transition-colors"
            title="Catat dan naikkan limit harian amplop ini sampai tengah malam"
          >
            Naikkan limit
          </button>
        )}
        {item.raiseDailyLimit && !item.error && (
          <span className="text-xs text-brand-600" title="Limit harian dinaikkan sementara saat disimpan">limit ↑</span>
        )}
        {item.saving && <span className="text-xs text-gray-400">...</span>}
      </div>
    </fieldset>
  );
}

// initialPhoto: File dari pintu masuk "Foto struk" (FAB / pemulihan) → dibaca sekali saat dibuka.
// photoMode 'ready': dibuka dari shortcut PWA → tombol besar "Ambil foto struk" di atas isian.
export default function MultiAddTransaction({ onSaved, onCancel, initialPhoto = null, photoMode = null }) {
  const [rawText, setRawText] = useState('');
  const [items, setItems] = useState([]);
  const [envelopes, setEnvelopes] = useState([]);
  const [saving, setSaving] = useState(false);
  const [resultMsg, setResultMsg] = useState(null);
  const [showSingleForm, setShowSingleForm] = useState(false);
  const [singleFormKey, setSingleFormKey] = useState(0);
  const [fundingTarget, setFundingTarget] = useState(null);
  const debounceRef = useRef(null);
  const lastParsedRef = useRef('');
  const keySeq = useRef(0);
  const nextKey = () => `i${++keySeq.current}`;
  const itemsRef = useRef(items);
  useEffect(() => { itemsRef.current = items; }, [items]);
  // Transkrip suara yang selesai saat menyimpan ditahan dulu: kalau langsung
  // ditambahkan ke kotak teks yang masih berisi baris yang sedang disimpan,
  // baris itu di-parse ulang jadi salinan tanpa kunci idempotensi.
  const savingRef = useRef(false);
  const heldTranscripts = useRef([]);
  // Suara/struk yang masih diproses: Simpan Semua ditahan sampai hasilnya masuk,
  // supaya hasilnya tidak tiba di tengah penyimpanan atau hilang saat panel ditutup.
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [scanBusy, setScanBusy] = useState(false);
  // Versi ref untuk dibaca di akhir penyimpanan (closure handleSaveAll sudah basi).
  const inputBusyRef = useRef({ voice: false, scan: false });
  const handleVoiceBusy = useCallback((b) => { inputBusyRef.current.voice = b; setVoiceBusy(b); }, []);
  const handleScanBusy = useCallback((b) => { inputBusyRef.current.scan = b; setScanBusy(b); }, []);
  const inputBusy = () => inputBusyRef.current.voice || inputBusyRef.current.scan;

  const loadEnvelopes = useCallback(async () => {
    try {
      const data = await api.getEnvelopeSummary();
      setEnvelopes(Array.isArray(data) ? data : []);
    } catch {
      const fallback = await api.getEnvelopes();
      setEnvelopes(Array.isArray(fallback) ? fallback : []);
    }
  }, []);

  useEffect(() => {
    loadEnvelopes();
  }, [loadEnvelopes]);

  // Bagian struk yang gagal karena dana kurang (untuk banner & tombol Geser).
  const insufficientGroup = (item) => (item.plan || []).find(g => !g.saved && isInsufficientFundsError(g.error));

  // envId/amount/gid opsional: bagian struk tertentu.
  const handleOpenFundModal = (key, envId = null, amount = null, gid = null) => {
    const item = items.find(i => i.key === key);
    if (!item) return;
    let targetEnv = envId;
    let targetAmount = amount;
    let targetGid = gid;
    if (!targetEnv && hasReceiptItems(item)) {
      const failed = insufficientGroup(item);
      if (failed) {
        targetEnv = failed.envelopeId;
        targetGid = failed.id;
        // Semua barang di amplop itu yang gagal karena dana kurang.
        targetAmount = (item.plan || [])
          .filter(g => !g.saved && g.envelopeId === failed.envelopeId && isInsufficientFundsError(g.error))
          .reduce((sum, g) => sum + g.amount, 0);
      }
    }
    targetEnv = targetEnv || item.envelopeId;
    targetAmount = targetAmount ?? item.amount;
    if (!targetEnv) return;
    const env = envelopes.find(e => e.id === targetEnv);
    if (!env) return;
    const remaining = Number(env.remaining || 0);
    const needed = Math.max(0, targetAmount - remaining);
    setFundingTarget({
      envelope: env,
      neededAmount: needed > 0 ? needed : targetAmount,
      itemKey: key,
      groupId: targetGid,
    });
  };

  // User mengonfirmasi: item ini dicatat dan limit harian amplopnya dinaikkan
  // sampai tengah malam saat disimpan (backend: raise_daily_limit, sama dengan bot).
  const handleRaiseLimit = (key, gid = null) => {
    const item = items.find(i => i.key === key);
    if (!item) return;
    if (gid && item.plan) {
      const envId = groupEnvelope(item, gid);
      const env = envelopes.find(e => e.id === envId);
      setItems(prev => prev.map(i => (i.key === key
        ? { ...patchPlanEnvelope(i, envId, { raiseLimit: true, error: null }), error: null } : i)));
      setResultMsg({
        type: 'mixed',
        text: `Limit harian ${env ? env.name : 'amplop'} akan dinaikkan sementara (kembali normal besok). Klik Simpan Semua untuk melanjutkan.`,
      });
      return;
    }
    const env = envelopes.find(e => e.id === item.envelopeId);
    setItems(prev => prev.map(i => (i.key === key ? { ...i, raiseDailyLimit: true, error: null } : i)));
    setResultMsg({
      type: 'mixed',
      text: `Limit harian ${env ? env.name : 'amplop'} akan dinaikkan sementara (kembali normal besok). Klik Simpan Semua untuk melanjutkan.`,
    });
  };

  const handleFundSuccess = async ({ type, amount, fromName, targetEnvelope }) => {
    await loadEnvelopes();
    if (fundingTarget && fundingTarget.itemKey != null) {
      setItems(prev => prev.map(item => {
        if (item.key !== fundingTarget.itemKey) return item;
        if (fundingTarget.groupId && item.plan) {
          return { ...patchPlanEnvelope(item, fundingTarget.envelope.id, { error: null }), error: null };
        }
        return { ...item, error: null };
      }));
    }
    const actionDesc = type === 'transfer'
      ? `Berhasil menggeser ${formatRupiah(amount)} dari ${fromName || 'amplop lain'} ke ${targetEnvelope.name}.`
      : `Berhasil menambah dana ${formatRupiah(amount)} ke ${targetEnvelope.name}.`;

    setResultMsg({
      type: 'mixed',
      text: `${actionDesc} Silakan klik Simpan Semua untuk melanjutkan.`,
    });
    setFundingTarget(null);
  };

  // Saran amplop untuk item tertentu; dicocokkan lewat key (bukan indeks)
  // supaya aman walau ada item struk di daftar yang sama.
  const applySuggestions = useCallback((targetItems) => {
    if (!navigator.onLine || targetItems.length === 0) return;
    const descriptions = targetItems.map(i => i.description);
    api.batchSuggestEnvelopes(descriptions).then(res => {
      if (!res || !res.results) return;
      const byKey = {};
      res.results.forEach(r => {
        const target = targetItems[r.index];
        if (target && r.confident && r.envelope_id) byKey[target.key] = r.envelope_id;
      });
      setItems(prev => prev.map(item => (
        !item.touched && byKey[item.key]
          ? { ...item, envelopeId: byKey[item.key], suggested: true }
          : item
      )));
    });
  }, []);

  useEffect(() => {
    clearTimeout(debounceRef.current);
    const txt = rawText.trim();
    if (txt === lastParsedRef.current) return;

    debounceRef.current = setTimeout(() => {
      lastParsedRef.current = txt;
      // Baris dari struk & baris yang tertahan setelah simpan sebagian tidak ikut
      // terhapus saat teks diketik ulang (hanya baris hasil teks yang diganti).
      const keepReceipts = prev => prev.filter(i => i.origin !== 'text');
      if (!txt) {
        setItems(keepReceipts);
        return;
      }

      let parsed = parseMultiExpense(txt);
      if (!parsed) {
        const single = parseAmount(txt);
        if (single) {
          parsed = [single];
        } else {
          setItems(keepReceipts);
          return;
        }
      }

      const newItems = parsed.map(p => ({
        ...p,
        key: nextKey(),
        origin: 'text',
        envelopeId: '',
        suggested: false,
        touched: false,
        error: null,
        saving: false,
      }));

      setResultMsg(null);
      setItems(prev => [...keepReceipts(prev), ...newItems]);
      applySuggestions(newItems);
    }, 300);

    return () => clearTimeout(debounceRef.current);
  }, [rawText, applySuggestions]);

  const handleEnvelopeChange = (key, value) => {
    setItems(prev => prev.map(item =>
      item.key === key ? { ...item, envelopeId: value, suggested: false, touched: true, error: null } : item
    ));
  };

  const handleFieldChange = (key, field, value) => {
    setItems(prev => prev.map(item => (item.key === key ? { ...item, [field]: value, error: null } : item)));
  };

  const handleReceiptChange = (key, patch) => {
    setItems(prev => prev.map(item => (item.key === key ? { ...item, ...patch, error: null } : item)));
  };

  // Bagian yang gagal dipindah ke amplop lain (nominal tetap).
  // Barang yang belum tersimpan di amplop bagian `gid` dipindah ke amplop lain.
  const handleRetargetGroup = (key, gid, envelopeId) => {
    setItems(prev => prev.map(item => (item.key === key
      ? patchPlanEnvelope(item, groupEnvelope(item, gid), { envelopeId, error: null, raiseLimit: false }) : item)));
  };

  // Belum ada bagian tersimpan → rincian boleh diubah lagi (rencana dihitung ulang).
  const handleUnlockReceipt = (key) => {
    setItems(prev => prev.map(item => (item.key === key && !item.uncertain && !(item.plan || []).some(g => g.saved)
      ? { ...item, plan: null, error: null } : item)));
  };

  // Sebagian sudah tercatat; sisanya dilewati (struk keluar dari daftar).
  const handleSkipRest = (key) => {
    const item = items.find(i => i.key === key);
    if (item?.scanId) api.receiptFeedback(item.scanId, feedbackFor(item, false));
    setItems(prev => prev.filter(i => i.key !== key));
  };

  const handleRemove = (key) => {
    const removed = items.find(i => i.key === key);
    if (removed?.origin === 'receipt' && removed.scanId) {
      api.receiptFeedback(removed.scanId, feedbackFor(removed, false));
    }
    setItems(prev => prev.filter(i => i.key !== key));
  };

  // Saran amplop per barang dari kata kunci yang sudah dipelajari (mis. "sabun"
  // pernah dicatat ke Kebutuhan Rumah). Hanya mengisi barang yang amplopnya belum
  // dipilih user, dan tidak menyentuh struk yang sedang/sudah disimpan.
  const suggestReceiptItems = useCallback((entry) => {
    const targets = (entry.receiptItems || []).filter(it => !it.removed && String(it.name || '').trim().length >= 3);
    if (!navigator.onLine || targets.length === 0) return;
    api.batchSuggestEnvelopes(targets.map(it => it.name)).then(res => {
      if (!res || !res.results) return;
      const byItem = {};
      res.results.forEach(r => {
        const t = targets[r.index];
        if (t && r.confident && r.envelope_id) byItem[t.id] = r.envelope_id;
      });
      if (Object.keys(byItem).length === 0 || savingRef.current) return;
      setItems(prev => prev.map(i => (i.key === entry.key && !i.plan && !i.uncertain
        ? { ...i, receiptItems: applyItemSuggestions(i.receiptItems, byItem) } : i)));
    });
  }, []);

  const handleReceiptResult = (result) => {
    const item = receiptToItem(result, nextKey());
    setItems(prev => [item, ...prev]);
    setResultMsg(scanMessage(result));
    applySuggestions([item]);
    suggestReceiptItems(item);
  };

  // Baca struk: tahap prosesnya tampil di ReceiptStatusCard; Simpan ditahan selama berjalan.
  const scan = useReceiptScan({ onResult: handleReceiptResult, onBusyChange: handleScanBusy });

  // Foto dari pintu masuk lain langsung dibaca begitu form terbuka. Hanya saat dipasang:
  // foto baru dari Layout memasang ulang form (kunci actionSeq), bukan mengganti prop.
  useEffect(() => {
    if (initialPhoto) scan.scanFile(initialPhoto);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleVoiceTranscript = (text) => {
    if (savingRef.current) {
      heldTranscripts.current.push(text);
      return;
    }
    setRawText(prev => (prev ? prev + '\n' + text : text));
  };

  // Selesai menyimpan: lepas status & tambahkan transkrip yang tertahan.
  // Mengembalikan jumlah transkrip yang baru masuk ke kotak teks.
  const endSaving = () => {
    savingRef.current = false;
    setSaving(false);
    const queued = heldTranscripts.current.splice(0);
    if (queued.length) setRawText(prev => [prev, ...queued].filter(Boolean).join('\n'));
    return queued.length;
  };

  const handleVoiceError = (msg) => {
    setResultMsg({ type: 'error', text: msg });
  };

  const toPayload = (item) => ({
    envelope_id: item.envelopeId,
    amount: item.amount,
    description: (item.description || '').trim() || 'Belanja',
    source: 'webapp',
    ...(item.transactionDate ? { transaction_date: item.transactionDate } : {}),
    ...(item.raiseDailyLimit ? { raise_daily_limit: true } : {}),
    ...(item.ref ? { client_ref: item.ref } : {}),
  });

  // Satu entri → satu atau beberapa transaksi. Struk dengan rincian memakai
  // rencana (1 transaksi per barang); bagian yang sudah tersimpan tidak dikirim ulang.
  const toParts = (item, plan) => {
    if (plan) {
      return plan.filter(g => !g.saved).map(g => ({
        key: item.key,
        gid: g.id,
        payload: toPayload({
          ...item,
          envelopeId: g.envelopeId,
          amount: g.amount,
          description: g.description,
          raiseDailyLimit: g.raiseLimit,
          ref: g.ref,
        }),
      }));
    }
    return [{ key: item.key, gid: null, payload: toPayload(item) }];
  };

  const handleSaveAll = async () => {
    if (savingRef.current || voiceBusy || scanBusy) return;
    // Teks yang baru diketik belum dibaca (jeda 300 ms). Kalau disimpan sekarang,
    // pembacaan yang tertunda mengganti baris yang sedang disimpan dengan salinan
    // tanpa kunci idempotensi → bisa tercatat dua kali.
    if (rawText.trim() !== lastParsedRef.current) {
      setResultMsg({ type: 'error', text: 'Teks baru masih dibaca — cek barisnya, lalu tekan Simpan Semua lagi.' });
      return;
    }
    if (items.some(i => isReady(i) && !(Number(i.amount) > 0))) {
      setResultMsg({ type: 'error', text: 'Isi nominal struk dulu sebelum menyimpan' });
      return;
    }
    if (!items.some(isReady)) {
      setResultMsg({ type: 'error', text: 'Pilih amplop untuk setiap item' });
      return;
    }
    // Setiap transaksi diberi kunci idempotensi sekali, lalu dipakai ulang di
    // percobaan berikutnya; rencana struk dibekukan bersama kuncinya.
    const plans = {};
    const snapshot = items.map(item => {
      if (!isReady(item)) return item;
      if (hasReceiptItems(item)) {
        plans[item.key] = receiptPlan(item).map(g => (g.ref ? g : { ...g, ref: newRef() }));
        return { ...item, plan: plans[item.key] };
      }
      return item.ref ? item : { ...item, ref: newRef() };
    });
    const snapshotKeys = new Set(snapshot.map(i => i.key));
    const pending = snapshot.filter(isReady);
    const parts = pending.flatMap(item => toParts(item, plans[item.key]));

    savingRef.current = true;
    setSaving(true);
    setResultMsg(null);

    // Terapkan hasil ke daftar TERBARU: entri yang masuk selama menyimpan (mis.
    // scan struk yang baru selesai) tetap ada. Baris teks yang tersisa jadi baris
    // "tertahan" dan kotak teks dikosongkan, supaya mengetik ulang tidak mem-parse
    // ulang baris yang mungkin sudah tercatat.
    // holdText=false: tidak ada yang tercatat & tidak ada yang belum pasti → baris
    // teks tetap bisa diedit lewat kotak teks seperti biasa.
    const applyResult = (updatedByKey, removeKeys, holdText = true) => {
      const hold = i => (holdText && i.origin === 'text' ? { ...i, origin: 'held' } : i);
      setItems(prev => prev
        .filter(i => !removeKeys.has(i.key))
        .map(i => (updatedByKey[i.key] ? hold(updatedByKey[i.key]) : (snapshotKeys.has(i.key) ? hold(i) : i))));
      if (holdText) {
        setRawText('');
        lastParsedRef.current = '';
      }
      const arrivals = itemsRef.current.filter(i => !snapshotKeys.has(i.key));
      const leftover = snapshot.filter(i => !removeKeys.has(i.key));
      return leftover.length === 0 && arrivals.length === 0;
    };

    if (!navigator.onLine) {
      for (const part of parts) {
        await enqueueTransaction(part.payload);
      }
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      const done = applyResult({}, new Set(pending.map(i => i.key)));
      const heldCount = endSaving();
      if (done && heldCount === 0 && !inputBusy()) onSaved?.();
      return;
    }

    const result = await api.batchCreateTransactions(parts.map(p => p.payload));

    if (!result.ok && result.status >= 400 && result.status < 500 && result.status !== 409) {
      // Ditolak utuh (mis. 401/422): tidak ada yang tercatat → baris tetap bisa diedit.
      endSaving();
      const detail = typeof result.data?.detail === 'string' ? result.data.detail : '';
      setResultMsg({ type: 'error', text: detail || 'Gagal menyimpan. Periksa isian lalu coba lagi.' });
      return;
    }

    if (!result.ok) {
      // Respons gagal/hilang: sebagian mungkin sudah tercatat di server. Baris yang
      // dikirim ditandai "belum pasti" & dikunci; kunci idempotensinya dipertahankan,
      // jadi Simpan Semua lagi tidak mencatat dua kali.
      const updated = {};
      pending.forEach(item => {
        updated[item.key] = {
          ...item,
          uncertain: true,
          error: null,
          ...(plans[item.key] ? { plan: plans[item.key].map(g => ({ ...g, error: null })) } : {}),
        };
      });
      applyResult(updated, new Set());
      endSaving();
      setResultMsg({ type: 'error', text: 'Koneksi terputus saat menyimpan. Tekan Simpan Semua lagi — tidak akan tercatat dua kali.' });
      return;
    }

    // Hasil batch berindeks sesuai `parts` → petakan ke entri (key) & bagiannya.
    const data = result.data || [];
    const okKeys = new Set();
    const errByKey = {};
    const pendingKeys = new Set();
    const groupResult = {}; // key → gid → { ok, error, pending }
    let successCount = 0;
    data.forEach(r => {
      const part = parts[r.index];
      if (!part) return;
      if (r.ok) successCount++;
      if (r.pending) pendingKeys.add(part.key);
      if (part.gid) {
        (groupResult[part.key] = groupResult[part.key] || {})[part.gid] = {
          ok: r.ok, pending: !!r.pending, error: r.ok ? null : (r.error || 'Gagal'),
        };
      } else if (r.ok) okKeys.add(part.key);
      else errByKey[part.key] = r.error || 'Gagal';
    });
    const nextPlans = {};
    Object.entries(plans).forEach(([key, plan]) => {
      const res = groupResult[key] || {};
      nextPlans[key] = plan.map(g => (res[g.id]
        ? { ...g, saved: g.saved || res[g.id].ok, error: res[g.id].error }
        : g));
      if (nextPlans[key].every(g => g.saved)) okKeys.add(key);
    });
    const failedCount = data.length - successCount;

    // Bahan belajar scan struk: nilai akhir yang benar-benar tersimpan.
    pending.forEach(item => {
      if (item.origin === 'receipt' && item.scanId && okKeys.has(item.key)) {
        api.receiptFeedback(item.scanId, feedbackFor(item, true));
      }
    });

    const updated = {};
    pending.forEach(item => {
      if (okKeys.has(item.key)) return;
      // "Sedang diproses" = kiriman lain dengan kunci yang sama belum selesai:
      // belum pasti, bukan gagal permanen.
      const uncertain = pendingKeys.has(item.key);
      if (nextPlans[item.key]) {
        const firstErr = nextPlans[item.key].find(g => !g.saved && g.error)?.error || null;
        updated[item.key] = { ...item, plan: nextPlans[item.key], uncertain, error: firstErr };
      } else {
        updated[item.key] = { ...item, uncertain, error: errByKey[item.key] || null };
      }
    });

    if (successCount > 0) {
      window.dispatchEvent(new CustomEvent('jatahku:txn-added'));
      const done = applyResult(updated, okKeys);
      const heldCount = endSaving();
      // Basic: kuota bulan ini habis sesudah input ini → beri tahu (panel tidak
      // ditutup otomatis supaya pesannya terbaca).
      const quotaNotice = data.find(r => r.quota_notice)?.quota_notice || null;
      const savedText = failedCount ? `${successCount} berhasil, ${failedCount} gagal` : `${successCount} transaksi berhasil disimpan`;
      // Suara/struk yang mulai diproses selama menyimpan: panel jangan ditutup.
      if (done && heldCount === 0 && !inputBusy() && !quotaNotice) {
        setResultMsg({ type: 'success', text: savedText });
        onSaved?.();
      } else {
        setResultMsg({ type: 'mixed', text: quotaNotice ? `${savedText}. ${quotaNotice}` : savedText });
      }
    } else {
      applyResult(updated, new Set(), pendingKeys.size > 0);
      endSaving();
      const firstErr = (result.data || []).find(d => d.error)?.error || 'Gagal menyimpan';
      setResultMsg({ type: 'error', text: firstErr });
    }
  };

  const hasItems = items.length > 0;
  const selectedCount = items.filter(isReady).length;
  const unselectedCount = items.length - selectedCount;
  const hasReceiptCard = items.some(hasReceiptItems);

  return (
    <div className="space-y-4">
      {photoMode === 'ready' && !hasItems && scan.state.stage === STAGE.IDLE && (
        <div className="py-2">
          <ReceiptInput
            size="lg"
            onFile={scan.scanFile}
            onError={handleVoiceError}
            disabled={saving || scanBusy}
          />
        </div>
      )}
      <div>
        <label className="block text-sm text-gray-500 mb-2">
          Bisa catat beberapa sekaligus. Pisahkan dengan koma, baris baru, atau kata "dan".
        </label>
        <div className="flex items-center gap-4 mb-2">
          <ReceiptInput
            size="sm"
            onFile={scan.scanFile}
            onError={handleVoiceError}
            disabled={saving || scanBusy}
          />
          <VoiceInput
            onTranscript={handleVoiceTranscript}
            onError={handleVoiceError}
            onBusyChange={handleVoiceBusy}
            disabled={saving}
          />
        </div>
        <textarea
          className="input w-full h-24 resize-y font-mono text-sm"
          placeholder={`kopi 15k\nsabun 5.000\nair mineral Rp5.000, gojek 12000\ntelor 1,5`}
          value={rawText}
          onChange={e => setRawText(e.target.value)}
          disabled={saving}
        />
        <ReceiptStatusCard
          state={scan.state}
          disabled={saving}
          onRetry={scan.retry}
          onRetake={() => pickReceiptPhoto('camera', { onFile: scan.scanFile, onError: handleVoiceError })}
          onDismiss={scan.reset}
        />
      </div>

      {!hasItems && !saving && (
        <div className="text-center py-4 text-gray-400 text-sm">
          Ketik pengeluaran Anda di atas, atau foto struk
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

          <div className={`${hasReceiptCard ? 'max-h-[65vh]' : 'max-h-64'} overflow-y-auto border border-gray-200 rounded-xl divide-y divide-gray-100`}>
            <div className="hidden md:grid md:grid-cols-12 gap-3 px-3 py-2 bg-gray-50 rounded-t-xl text-xs font-medium text-gray-500">
              <span className="col-span-5">Keterangan</span>
              <span className="col-span-2">Jumlah</span>
              <span className="col-span-4">Amplop</span>
              <span className="col-span-1"></span>
            </div>
            <fieldset disabled={saving} className="px-3">
              {items.map(item => (hasReceiptItems(item) ? (
                <ReceiptCard
                  key={item.key}
                  entry={item}
                  envelopes={envelopes}
                  saving={saving}
                  onChange={handleReceiptChange}
                  onRemove={handleRemove}
                  onFundGroup={handleOpenFundModal}
                  onRaiseLimitGroup={handleRaiseLimit}
                  onRetargetGroup={handleRetargetGroup}
                  onUnlock={handleUnlockReceipt}
                  onSkipRest={handleSkipRest}
                />
              ) : (
                <ItemRow
                  key={item.key}
                  item={item}
                  envelopes={envelopes}
                  onChangeEnvelope={handleEnvelopeChange}
                  onChangeField={handleFieldChange}
                  onRemove={handleRemove}
                  onFundEnvelope={handleOpenFundModal}
                  onRaiseLimit={handleRaiseLimit}
                />
              )))}
            </fieldset>
          </div>
        </>
      )}

      {resultMsg && (
        <div className={`text-sm px-3 py-2 rounded-xl ${
          resultMsg.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' :
          resultMsg.type === 'mixed' ? 'bg-amber-50 text-amber-700 border border-amber-200' :
          'bg-red-50 border border-red-200'
        }`} style={resultMsg.type === 'error' ? {color:'#E24B4A'} : undefined}>
          <div className="font-medium">{resultMsg.text}</div>
          {resultMsg.type === 'error' && isInsufficientFundsError(resultMsg.text) && (() => {
            const candidateItem = items.find(i => isInsufficientFundsError(i.error)) || items.find(i => i.envelopeId) || null;
            const group = candidateItem ? insufficientGroup(candidateItem) : null;
            const targetEnvId = group ? group.envelopeId : candidateItem?.envelopeId;
            const targetEnv = targetEnvId ? envelopes.find(e => e.id === targetEnvId) : null;
            if (!targetEnv) return null;
            return (
              <div className="mt-2.5 pt-2 border-t border-red-200/60 flex items-center justify-between flex-wrap gap-2 text-xs">
                <span className="text-red-700 font-normal">
                  Amplop <strong>{targetEnv.name}</strong> butuh tambahan dana.
                </span>
                <button
                  type="button"
                  onClick={() => handleOpenFundModal(candidateItem.key)}
                  className="bg-brand-600 hover:bg-brand-700 text-white rounded-lg px-2.5 py-1.5 text-xs font-medium flex items-center gap-1.5 shadow-sm transition-all"
                >
                  <Icon name="transfer" size={13} />
                  Geser / Isi Dana ({targetEnv.name})
                </button>
              </div>
            );
          })()}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSaveAll}
          disabled={saving || !hasItems || voiceBusy || scanBusy}
          className="btn-primary disabled:opacity-50"
        >
          {saving ? 'Menyimpan...'
            : scanBusy ? 'Menunggu struk...'
              : voiceBusy ? 'Menunggu suara...'
                : `Simpan Semua${selectedCount > 0 ? ` (${selectedCount})` : ''}`}
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
              onSaved={(info) => {
                setSingleFormKey(k => k + 1);
                if (info?.quotaNotice) setResultMsg({ type: 'mixed', text: info.quotaNotice });
              }}
            />
          </div>
        )}
      </div>

      {fundingTarget && (
        <FundEnvelopeModal
          advisor
          isOpen={!!fundingTarget}
          onClose={() => setFundingTarget(null)}
          targetEnvelope={fundingTarget.envelope}
          neededAmount={fundingTarget.neededAmount}
          envelopes={envelopes}
          onSuccess={handleFundSuccess}
        />
      )}
    </div>
  );
}
