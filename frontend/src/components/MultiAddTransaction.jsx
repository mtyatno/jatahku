import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../lib/api';
import { parseMultiExpense, parseAmount } from '../lib/parseAmount';
import { enqueueTransaction, queuedReceiptItemIds } from '../lib/offlineQueue';
import QuickAddTransaction from './QuickAddTransaction';
import VoiceInput from './VoiceInput';
import ReceiptInput, { pickReceiptPhoto } from './ReceiptInput';
import ReceiptStatusCard from './ReceiptStatusCard';
import { useReceiptScan } from '../hooks/useReceiptScan';
import { useAppConfig } from '../hooks/useAppConfig';
import { STAGE, retakeAction, waitingLabel } from '../lib/receiptProgress';
import ReceiptCard from './ReceiptCard';
import {
  receiptToItem, scanMessage, feedbackFor, confidenceLabel, applyDocumentDate, dateNotice, currentPeriod, wibToday,
} from '../lib/receiptScan';
import { applyItemSuggestions } from '../lib/receiptSplit';
import {
  isDailyLimitError, isInsufficientFundsError, hasReceiptItems, receiptPlan, needsDate, isReady, needsEnvelope,
  notReadyMessage, applyRowPatch, withSaveDate, toParts, wantsReceiptFeedback, removalCalls, wantsKeywordSuggestion,
  fundCandidate, showRaisedLimit, alreadyListed, withSaveError, canUnlockPlan,
} from '../lib/multiAddRows';
import { announceKotakChange } from '../lib/pendingProofs';
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

// Struk dicatat per barang, jadi masalah amplop (dana kurang, limit harian,
// pindah amplop) berlaku untuk SEMUA barang yang belum tersimpan di amplop itu.
const patchPlanEnvelope = (item, envelopeId, patch) => ({
  ...item,
  plan: (item.plan || []).map(g => (!g.saved && g.envelopeId === envelopeId ? { ...g, ...patch } : g)),
});

const groupEnvelope = (item, gid) => (item.plan || []).find(g => g.id === gid)?.envelopeId;

// Di bawah baris struk/bukti: alasan blokir dari server dan aturan tanggal dokumen (lib/receiptScan.dateNotice):
// pertanyaan "Catat untuk tanggal berapa?" dengan pilihan Hari ini / tanggal dokumen, atau keterangan tanggal yang
// belum lewat. Dipakai ItemRow dan ReceiptCard.
function RowNotices({ item, onPickDate, className = '' }) {
  const today = wibToday();
  const notice = dateNotice(item, today);
  if (!item.blockedReason && !notice) return null;
  return (
    <div className={`space-y-1 ${className}`}>
      {item.blockedReason && <p className="text-xs font-medium text-red-600">{item.blockedReason}</p>}
      {notice && <p className="text-xs text-amber-700">{notice.text}</p>}
      {notice?.choices && (
        <div className="flex items-center gap-2 flex-wrap">
          {notice.choices.map(choice => {
            const picked = item.transactionDate === choice.date;
            return (
              <button
                key={choice.label}
                type="button"
                aria-pressed={picked}
                onClick={() => onPickDate(item.key, choice.date)}
                className={`px-2.5 py-1 rounded-full border text-xs whitespace-nowrap disabled:opacity-50 ${picked
                  ? 'border-brand-400 bg-brand-50 text-brand-600 font-medium'
                  : 'border-gray-200 text-gray-600 hover:border-brand-400 hover:text-brand-600'}`}
              >
                {choice.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ItemRow({ item, envelopes, periodStart, onChangeEnvelope, onChangeField, onRemove, onFundEnvelope, onRaiseLimit }) {
  const isShortage = isInsufficientFundsError(item.error);
  const isOverDailyLimit = isDailyLimitError(item.error);
  const isReceipt = item.origin === 'receipt';
  const doubtful = isReceipt && item.confidence !== 'tinggi';
  const blocked = !!item.blockedReason;
  const needsEnvelopeMark = !item.envelopeId && !blocked;

  // Hasil simpan belum pasti: isian dikunci supaya kirim ulang (kunci yang sama)
  // tidak membawa nilai berbeda dari yang mungkin sudah tercatat.
  return (
    <fieldset disabled={!!item.uncertain} className={`
      group flex flex-col md:grid md:grid-cols-12 gap-2 md:gap-3 items-start md:items-center
      py-2 md:py-1.5 border-b border-gray-100 last:border-0
      ${needsEnvelopeMark ? 'bg-amber-50/50 -mx-2 px-2 rounded' : ''}
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
              className={`input text-xs py-1 w-full md:w-40 ${needsDate(item) ? 'border-amber-400 ring-1 ring-amber-200' : ''}`}
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
          className={`input text-sm py-1.5 w-full ${needsEnvelopeMark ? 'border-amber-400 ring-1 ring-amber-200' : ''}`}
          value={item.envelopeId}
          disabled={blocked}
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
        {showRaisedLimit(item, periodStart) && (
          <span className="text-xs text-brand-600" title="Limit harian dinaikkan sementara saat disimpan">limit ↑</span>
        )}
        {item.saving && <span className="text-xs text-gray-400">...</span>}
      </div>
      {isReceipt && (
        <RowNotices
          item={item}
          onPickDate={(key, date) => onChangeField(key, 'transactionDate', date)}
          className="md:col-span-12 w-full"
        />
      )}
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
  // Tombol PDF dan pembacaan PDF hanya saat saklar `receipt_inbox` menyala; saklar mati = form seperti dulu.
  const allowPdf = useAppConfig().features?.receipt_inbox === true;
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
  // Periode anggaran berjalan untuk aturan tanggal dokumen (receiptScan.applyDocumentDate). Diambil sekali per
  // form, saat struk pertama mulai dibaca (form tanpa scan tidak memintanya); gagal → dicoba lagi pada scan
  // berikutnya. Selama belum ada, struk dari periode lalu tidak ditanya (seperti dulu).
  const [period, setPeriod] = useState(null);
  const periodRef = useRef({ value: null, loading: false });
  const loadPeriod = useCallback(() => {
    const p = periodRef.current;
    if (p.value || p.loading) return;
    p.loading = true;
    api.getPeriods(1)
      .then(list => {
        p.value = currentPeriod(list);
        if (p.value) setPeriod(p.value);
      })
      .catch(() => {})
      .finally(() => { p.loading = false; });
  }, []);
  // Id item Kotak Struk di antrean offline, dibaca setiap kali scan mulai (hasil scan tetap diproses sinkron): item
  // yang sudah disimpan offline tidak menjadi baris kedua (multiAddRows.alreadyListed).
  const queuedRef = useRef(null);
  const handleScanBusy = useCallback((b) => {
    inputBusyRef.current.scan = b;
    setScanBusy(b);
    if (b) {
      loadPeriod();
      queuedReceiptItemIds().then((ids) => { queuedRef.current = ids; }, () => {});
    }
  }, [loadPeriod]);
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

  // Suntingan baris lewat applyRowPatch: error simpan sebelumnya hilang, blokir dari server tetap.
  const handleEnvelopeChange = (key, value) => {
    setItems(prev => prev.map(item =>
      item.key === key ? applyRowPatch(item, { envelopeId: value, suggested: false, touched: true }) : item
    ));
  };

  const handleFieldChange = (key, field, value) => {
    setItems(prev => prev.map(item => (item.key === key ? applyRowPatch(item, { [field]: value }) : item)));
  };

  const handleReceiptChange = (key, patch) => {
    setItems(prev => prev.map(item => (item.key === key ? applyRowPatch(item, patch) : item)));
  };

  // Bagian yang gagal dipindah ke amplop lain (nominal tetap).
  // Barang yang belum tersimpan di amplop bagian `gid` dipindah ke amplop lain.
  const handleRetargetGroup = (key, gid, envelopeId) => {
    setItems(prev => prev.map(item => (item.key === key
      ? patchPlanEnvelope(item, groupEnvelope(item, gid), { envelopeId, error: null, raiseLimit: false }) : item)));
  };

  // Belum ada bagian tersimpan → rincian boleh diubah lagi (rencana dihitung ulang; multiAddRows.canUnlockPlan).
  const handleUnlockReceipt = (key) => {
    setItems(prev => prev.map(item => (item.key === key && canUnlockPlan(item)
      ? { ...item, plan: null, error: null } : item)));
  };

  // Baris struk/bukti keluar dari daftar tanpa dicatat: umpan balik "tidak disimpan" (struk belanja saja) dan item
  // Kotak Struk dilewati (alasan batal) supaya tidak menunggu dicatat; tidak selama baris lain masih memakai item itu.
  // Best-effort: galat dan offline diabaikan (sudah tercatat sebagian → server menjawab 409, tidak apa-apa). Dilewati
  // (2xx) → event jatahku:kotak-changed: banner bukti menunggu langsung menghitung ulang.
  const sendRemoval = (item) => {
    if (!item) return;
    const { feedback, skip } = removalCalls(item, items);
    if (feedback) api.receiptFeedback(feedback, feedbackFor(item, false));
    if (skip) api.kotakSkip(skip, 'batal').then(res => announceKotakChange(res, window)).catch(() => {});
  };

  // Sebagian sudah tercatat; sisanya dilewati (struk keluar dari daftar).
  const handleSkipRest = (key) => {
    sendRemoval(items.find(i => i.key === key));
    setItems(prev => prev.filter(i => i.key !== key));
  };

  const handleRemove = (key) => {
    sendRemoval(items.find(i => i.key === key));
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

  // Satu item Kotak Struk = satu baris: foto yang sama lagi (juga yang sudah disimpan offline) hanya diberi tahu.
  // Tanggal dokumen di luar periode berjalan ditanya dulu, tanggal yang belum lewat jadi hari ini (aturan bot).
  // QRIS/transfer memakai saran amplop server; saran kata kunci tidak menimpanya.
  const handleReceiptResult = (result) => {
    const listed = alreadyListed(result, itemsRef.current, queuedRef.current);
    if (listed) {
      setResultMsg(listed);
      return;
    }
    const item = applyDocumentDate(receiptToItem(result, nextKey()), { period: periodRef.current.value, today: wibToday() });
    setItems(prev => [item, ...prev]);
    setResultMsg(scanMessage(result));
    if (wantsKeywordSuggestion(item)) applySuggestions([item]);
    suggestReceiptItems(item);
  };

  // Baca struk: tahap prosesnya tampil di ReceiptStatusCard; Simpan ditahan selama berjalan.
  const scan = useReceiptScan({ onResult: handleReceiptResult, onBusyChange: handleScanBusy, allowPdf });

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

  // Payload per transaksi: lib/multiAddRows toPayload/toParts (receipt_item_id ikut di setiap bagian).
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
      setResultMsg({ type: 'error', text: notReadyMessage(items) });
      return;
    }
    // Setiap transaksi diberi kunci idempotensi sekali, lalu dipakai ulang di
    // percobaan berikutnya; rencana struk dibekukan bersama kuncinya. Tanggal struk/bukti
    // yang belum lewat diganti hari ini di sini, sebelum payload, antrean offline, dan feedbackFor.
    const today = wibToday();
    const plans = {};
    const snapshot = items.map(row => {
      if (!isReady(row)) return row;
      const item = withSaveDate(row, today);
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

    // Bahan belajar scan struk: nilai akhir yang benar-benar tersimpan (struk belanja saja;
    // bukti bayar belajar di server saat tercatat).
    pending.forEach(item => {
      if (wantsReceiptFeedback(item) && okKeys.has(item.key)) {
        api.receiptFeedback(item.scanId, feedbackFor(item, true));
      }
    });

    const updated = {};
    pending.forEach(item => {
      if (okKeys.has(item.key)) return;
      // "Sedang diproses" = kiriman lain dengan kunci yang sama belum selesai:
      // belum pasti, bukan gagal permanen.
      // Penolakan bukti (409) menjadi alasan blokir yang terlihat; galat lain tetap `error` (withSaveError).
      const uncertain = pendingKeys.has(item.key);
      if (nextPlans[item.key]) {
        const firstErr = nextPlans[item.key].find(g => !g.saved && g.error)?.error || null;
        updated[item.key] = withSaveError({ ...item, plan: nextPlans[item.key], uncertain }, firstErr);
      } else {
        updated[item.key] = withSaveError({ ...item, uncertain }, errByKey[item.key] || null);
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
  const unselectedCount = items.filter(needsEnvelope).length;
  const hasReceiptCard = items.some(hasReceiptItems);
  const periodStart = period?.start ?? null;

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
            allowPdf={allowPdf}
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
          onRetake={() => pickReceiptPhoto(retakeAction(scan.state.noun).source, { onFile: scan.scanFile, onError: handleVoiceError })}
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
                  notice={<RowNotices item={item} onPickDate={(key, date) => handleReceiptChange(key, { transactionDate: date })} />}
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
                  periodStart={periodStart}
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
            const candidateItem = fundCandidate(items, periodStart);
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
            : scanBusy ? waitingLabel(scan.state.noun)
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
