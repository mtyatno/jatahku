import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../lib/api';
import { readCachedConfig, refreshAppConfig } from '../lib/appConfig';
import { CLIENT_HEADER_VALUE } from '../lib/clientInfo';
import { onBackgroundSynced, queuedReceiptItemIds } from '../lib/offlineQueue';
import { STAGE } from '../lib/receiptProgress';
import {
  shareStore, uploadFormFor, shareUploadTimeoutMs, runSharePage, serialRuns, mergeItems, pollTargets, createPoller,
  fetchPendingDetails, pageView, dropLine, ensureShareOwner, pageReads, discardKept, SHARE_TEXT,
} from '../lib/shareInbox';
import { useAuth } from '../hooks/useAuth';
import ProofCard from '../components/ProofCard';
import ReceiptStatusCard from '../components/ReceiptStatusCard';

// Tahap unggahan entri yang sedang dikirim (ReceiptStatusCard, kata benda "bukti").
const IDLE = { stage: STAGE.IDLE, percent: null, progressSeen: false, stageStartedAt: 0, noun: 'bukti', thumbUrl: null, failure: null };

// Bacaan halaman dengan batas waktu (shareInbox.pageReads). Saklar `features.receipt_inbox` dibaca segar dari
// /app/config, bukan nilai pertama dari cache: dengan saklar mati halaman ini menghapus share, jadi tebakan basi bisa
// membuang bukti asli. Gagal (offline) → cache terakhir / bawaan; menggantung 10 dtk → cache terakhir, atau ditahan.
const reads = pageReads({
  getConfig: () => refreshAppConfig({ fetchConfig: () => api.getAppConfig(), client: CLIENT_HEADER_VALUE, force: true }),
  cachedConfig: () => readCachedConfig({ client: CLIENT_HEADER_VALUE })?.config ?? null,
  loadPending: () => api.kotakPending(),
  loadItem: id => api.kotakItem(id),
});

const pendingDetails = (items, handled) => fetchPendingDetails({
  items, handled, loadPending: reads.pending, loadItem: reads.item,
});

// Halaman /bagikan ("Bagikan ke Jatahku", spec 5b): menu Bagikan Android → service worker menyimpan share → di sini
// entri lokal diunggah satu per satu ke Kotak Struk, lalu tiap item tampil sebagai ProofCard bertumpuk (ditambah bukti
// lain yang menunggu dicatat). Semua aturan di lib/shareInbox.js (runSharePage, serialRuns, createPoller,
// uploadOutcome, mergeItems, ensureShareOwner, pageReads, …); komponen ini hanya merender dan menyambungkan API, state,
// dan timer. Kotak share hanya dibaca bila milik user yang login; item yang ada di antrean offline tampil hanya-baca.
export default function Bagikan() {
  const [params] = useSearchParams();
  const batchId = params.get('s');
  const err = params.get('err');
  const navigate = useNavigate();
  const userId = useAuth().user?.id ?? null;         // pemilik kotak share (shareInbox.ensureShareOwner)

  const [mode, setMode] = useState(null);           // null = memeriksa saklar | 'off' | 'hold' | 'send'
  const [waiting, setWaiting] = useState(0);        // entri lokal yang belum terkirim (mode 'hold')
  const [storeFailed, setStoreFailed] = useState(false);
  const [progress, setProgress] = useState(IDLE);
  const [kept, setKept] = useState(null);           // pesan entri yang disimpan untuk nanti
  const [keptList, setKeptList] = useState([]);     // entri yang tertahan, untuk daftar Hapus: [{id, label}]
  const [queued, setQueued] = useState(() => new Set());   // id item di antrean offline: kartu hanya-baca
  const [dropped, setDropped] = useState([]);       // entri yang ditolak server: [{name, message}]
  const [items, setItems] = useState([]);           // detail item untuk kartu, satu per id
  const [handled, setHandled] = useState(() => new Set());   // id kartu yang dicatat/dilewati di halaman ini
  const [envelopes, setEnvelopes] = useState([]);
  const [running, setRunning] = useState(false);
  const [polling, setPolling] = useState(false);

  const itemsRef = useRef([]);              // sumber kebenaran untuk async (state bisa basi di closure)
  const handledRef = useRef(handled);
  const startedAt = useRef(new Map());      // id → saat item diterima dari unggahan (batas pantau 30 dtk)
  const life = useRef({ alive: false });    // satu objek per pemasangan: async yang tertinggal berhenti sendiri
  const envLoaded = useRef(false);
  const startRef = useRef(null);            // putaran baru dari tombol "Kirim lagi" (serialRuns pemasangan ini)
  const storeRef = useRef(null);            // kotak share pemasangan ini (tombol Hapus)

  // Detail baru → kartu (satu per id, detail terbaru di tempat yang sama; key kartu tidak pernah berganti).
  const mergeIn = useCallback((me, incoming) => {
    if (!me.alive || !incoming?.length) return;
    itemsRef.current = mergeItems(itemsRef.current, incoming);
    setItems(itemsRef.current);
  }, []);

  useEffect(() => {
    const me = { alive: true, off: false, mode: null };
    life.current = me;
    const store = shareStore();
    storeRef.current = store;

    // Item yang masih dibaca dipantau (GET tiap 1,5 dtk, maks 30 dtk per item) sampai siap/gagal; berhenti saat
    // halaman dilepas dan begitu sebuah putaran mendapati saklar mati. Dimulai juga di sini: item dari `?s=` sebelumnya
    // yang masih dibaca tetap dipantau bila hanya `?s=` yang berganti.
    const poller = createPoller({
      targets: () => (me.off ? [] : pollTargets(itemsRef.current, startedAt.current, Date.now())),
      fetchItem: reads.item,
      onDetails: details => mergeIn(me, details),
      onRunning: setPolling,
    });
    poller.start();

    // Satu entri ke POST /kotak-struk/ dengan teks tahap "bukti" (mengunggah n% → membaca).
    const upload = (entry) => {
      if (me.alive) setProgress({ ...IDLE, stage: STAGE.UPLOADING, stageStartedAt: Date.now() });
      return api.kotakUpload(uploadFormFor(entry), {
        timeoutMs: shareUploadTimeoutMs(entry),
        onProgress: (percent) => {
          if (!me.alive) return;
          setProgress(p => (p.stage === STAGE.UPLOADING
            ? { ...p, percent, progressSeen: true }
            : { ...p, stage: STAGE.UPLOADING, percent, progressSeen: true, stageStartedAt: Date.now() }));
        },
        onUploaded: () => {
          if (!me.alive) return;
          setProgress(p => (p.stage === STAGE.READING ? p : { ...p, stage: STAGE.READING, stageStartedAt: Date.now() }));
        },
      });
    };

    const runOnce = async () => {
      setRunning(true);
      setKept(null);
      const out = await runSharePage({
        getConfig: reads.config,
        isOnline: () => navigator.onLine !== false,
        batchId,
        store,
        ensureOwner: () => ensureShareOwner(store, userId),
        loadQueued: queuedReceiptItemIds,
        onQueued: (ids) => { if (me.alive) setQueued(ids); },
        upload,
        loadPending: () => {
          if (me.alive) setProgress(IDLE);
          return pendingDetails(itemsRef.current, handledRef.current);
        },
        onItem: (item) => {
          if (!me.alive || !item?.id) return;
          if (!startedAt.current.has(item.id)) startedAt.current.set(item.id, Date.now());
          mergeIn(me, [item]);
          poller.start();
        },
        onMode: (m) => {
          me.off = m === 'off';
          me.mode = m;
          if (me.alive) setMode(m);
        },
        alive: () => me.alive,
      });
      if (!me.alive) return;
      setProgress(IDLE);
      setWaiting(out.waiting);
      setStoreFailed(out.storeFailed);
      setKept(out.kept);
      setKeptList(out.keptEntries);
      if (out.dropped.length) setDropped(prev => [...prev, ...out.dropped]);
      mergeIn(me, out.pending);
      setRunning(false);
    };

    // Antrean offline berubah (sinkron dari app atau service worker, coba lagi, dihapus) selama mode kirim: id antrean
    // dan detail kartu diperbarui bersamaan, jadi struk yang baru tersinkron tampil "sudah tercatat", tidak sempat
    // menawarkan Simpan.
    const onQueue = () => {
      if (me.mode !== 'send') return;
      Promise.all([queuedReceiptItemIds(), pendingDetails(itemsRef.current, handledRef.current)]).then(([ids, details]) => {
        if (!me.alive) return;
        setQueued(ids);
        mergeIn(me, details);
      }).catch(() => {});
    };

    // Satu putaran pada satu waktu: event `online` di tengah putaran → satu putaran lagi sesudahnya.
    const start = serialRuns(runOnce, { alive: () => me.alive });
    startRef.current = start;
    start();
    window.addEventListener('online', start);
    window.addEventListener('jatahku:offline-queue', onQueue);
    const offSynced = onBackgroundSynced(onQueue);
    return () => {
      me.alive = false;
      if (startRef.current === start) startRef.current = null;
      poller.stop();
      setPolling(false);   // hanya `?s=` yang berganti: pemantau baru di atas menyalakannya lagi bila masih ada target
      window.removeEventListener('online', start);
      window.removeEventListener('jatahku:offline-queue', onQueue);
      offSynced();
    };
  }, [batchId, mergeIn, userId]);

  // Amplop untuk kartu: dimuat sekali, begitu ada kartu pertama (saklar mati / tanpa kartu: tidak ada permintaan).
  useEffect(() => {
    if (!items.length || envLoaded.current) return;
    envLoaded.current = true;
    const me = life.current;
    api.getEnvelopeSummary().then((list) => { if (me.alive) setEnvelopes(Array.isArray(list) ? list : []); });
  }, [items.length]);

  // Kartu dicatat, dilewati, atau ditolak server (terblokir, tidak ada tindakan lagi) → tandai, lalu segarkan bukti
  // menunggu (flag item lain bisa berubah, mis. bukti yang sama).
  const settle = useCallback(({ item } = {}) => {
    if (!item?.id) return;
    const me = life.current;
    handledRef.current = new Set(handledRef.current).add(item.id);
    setHandled(handledRef.current);
    pendingDetails(itemsRef.current, handledRef.current).then(details => mergeIn(me, details));
  }, [mergeIn]);

  // Hapus: entri yang tertahan (tidak pernah bisa terkirim) dibuang dari HP, lalu daftarnya dihitung ulang; daftar
  // kosong → pesan "belum terkirim" dan "Kirim lagi" hilang. Banner menghitung ulang saat halaman ini ditinggalkan.
  const removeKept = useCallback(async (id) => {
    const me = life.current;
    const left = await discardKept(storeRef.current, id);
    if (!me.alive) return;
    setKeptList(left);
    if (!left.length) setKept(null);
  }, []);

  const view = pageView({ mode, err, storeFailed, waiting, items, handled, running, polling, dropped, kept, keptList });

  // pb-16 di bawah lg: tombol chat dan FAB Layout melayang di bottom-24 (sampai ±152 px dari bawah) sedangkan main
  // hanya memberi pb-24; tanpa ruang ini tombol kanan bawah kartu terakhir (Bukan pengeluaran, Ke Transaksi) tertutup.
  return (
    <div className="max-w-xl mx-auto space-y-4 pb-16 lg:pb-0">
      <h1 className="text-2xl font-display font-bold">Bagikan ke Jatahku</h1>

      {view.checking && <p className="text-sm text-gray-500">Memuat…</p>}
      {view.soon && (
        <div className="card">
          <p className="text-sm text-gray-600">{view.soon}</p>
        </div>
      )}

      {view.notices.length > 0 && (
        <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 text-amber-600 text-sm px-3 py-2 space-y-1">
          {view.notices.map(text => <p key={text}>{text}</p>)}
        </div>
      )}
      {view.banner && (
        <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 text-amber-600 text-sm px-3 py-2">
          {view.banner}
        </div>
      )}

      <ReceiptStatusCard state={progress} />
      {view.results && kept && <p role="status" className="text-sm text-amber-600">{kept}</p>}
      {view.discard && (
        <ul className="space-y-1">
          {keptList.map(entry => (
            <li key={entry.id} className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 truncate text-gray-700">{entry.label}</span>
              <button type="button" onClick={() => removeKept(entry.id)} className="shrink-0 text-red-600 underline font-medium px-2 py-2">
                {SHARE_TEXT.remove}
              </button>
            </li>
          ))}
        </ul>
      )}
      {view.retry && (
        <button type="button" onClick={() => startRef.current?.()} className="btn-outline w-full sm:w-auto">Kirim lagi</button>
      )}
      {view.results && dropped.length > 0 && (
        <ul role="alert" className="space-y-1">
          {dropped.map((d, i) => <li key={i} className="text-sm text-red-600 break-words">{dropLine(d)}</li>)}
        </ul>
      )}

      {view.results && items.map(item => (
        <ProofCard key={item.id} item={item} queued={queued.has(item.id)} envelopes={envelopes} onSaved={settle} onSkipped={settle} onBlocked={settle} />
      ))}

      {view.empty && <p className="text-sm text-gray-500">{view.empty}</p>}
      {view.finished && (
        <button type="button" onClick={() => navigate('/transactions')} className="btn-primary w-full sm:w-auto">
          Ke Transaksi
        </button>
      )}
    </div>
  );
}
