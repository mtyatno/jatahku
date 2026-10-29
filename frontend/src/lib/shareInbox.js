// Kotak share lokal — "Bagikan ke Jatahku" lewat Web Share Target PWA (spec 5b, docs/kotak-struk.md).
//
// Alur: menu Bagikan Android → POST multipart /bagikan → service worker (src/sw.js) menyimpan tiap file dan teksnya
// ke IndexedDB `jatahku-share` (store `shares`) lalu menjawab 303 ke /bagikan?s=<batch>. Halaman /bagikan mengunggah
// entri satu per satu ke Kotak Struk (`uploadFormFor`, tertua dulu lewat `nextToUpload`) dan menghapus entri yang
// sudah diterima server. Semua fungsi di sini murni (tanpa DOM, tanpa `self`): dipakai service worker dan halaman,
// dan diuji dengan node --test.
//
// Privasi: entri berisi gambar/PDF/teks bukti apa adanya (belum disamarkan). Isinya tidak pernah di-log. Entri dihapus
// setelah terunggah, dan seluruh kotak dikosongkan saat user sendiri logout (`clearSharesOnLogout`). Sesi yang
// kedaluwarsa tidak menghapusnya: bukti tetap aman sampai user login lagi.
import { newRef } from './ref.js';
import { PDF_TYPE, uploadTimeoutMs } from './receiptProgress.js';

export const SHARE_DB = 'jatahku-share'; // terpisah dari antrean offline (`jatahku-offline`, offlineSync.js)
export const SHARE_STORE = 'shares';
export const MAX_FILES = 10; // = MAX_FILES_PER_SHARE server (app/services/kotak_struk/config.py)
export const SHARE_SOURCE = 'pwa_share';
export const UPLOAD_WAIT_S = 10; // = WAIT_BOT_S server: tunggu hasil baca sebelum server menjawab

// ── Penyimpanan ─────────────────────────────────────────────────────────────────────────────────────

// Store memori: dipakai bila IndexedDB tidak ada (Node, browser lama). Tidak pernah melempar.
function memoryStore() {
  const map = new Map();
  return {
    all: async () => [...map.values()],
    put: async (entry) => { if (entry && entry.id != null) map.set(entry.id, entry); },
    del: async (id) => { map.delete(id); },
    clear: async () => { map.clear(); },
  };
}

// Satu koneksi per IDBFactory, dipakai ulang oleh semua store (service worker dan halaman masing-masing punya satu).
const connections = new WeakMap();

function openShareDB(idb) {
  let pending = connections.get(idb);
  if (pending) return pending;
  pending = new Promise((resolve, reject) => {
    const req = idb.open(SHARE_DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(SHARE_STORE)) db.createObjectStore(SHARE_STORE, { keyPath: 'id' });
    };
    req.onsuccess = () => {
      const db = req.result;
      const forget = () => { if (connections.get(idb) === pending) connections.delete(idb); };
      // Versi DB berikutnya atau penghapusan DB dari tab lain tidak boleh tertahan koneksi ini; browser juga bisa
      // menutupnya sendiri (data situs dihapus). Panggilan berikutnya membuka ulang.
      db.onversionchange = () => { db.close(); forget(); };
      db.onclose = forget;
      resolve(db);
    };
    req.onerror = () => reject(req.error);
  });
  // Gagal buka (juga lemparan sinkron dari open) tidak disimpan: panggilan berikutnya mencoba lagi.
  pending.catch(() => { if (connections.get(idb) === pending) connections.delete(idb); });
  connections.set(idb, pending);
  return pending;
}

// Satu request dalam satu transaksi. Selesai saat transaksi `complete` (bukan saat request sukses): service worker
// baru menjawab 303 setelah share benar-benar tersimpan.
async function run(idb, mode, op) {
  const db = await openShareDB(idb);
  return new Promise((resolve, reject) => {
    const tx = db.transaction(SHARE_STORE, mode);
    const req = op(tx.objectStore(SHARE_STORE));
    tx.oncomplete = () => resolve(req.result);
    tx.onerror = () => reject(tx.error || req.error);
    tx.onabort = () => reject(tx.error || req.error || new Error('Transaksi IndexedDB dibatalkan'));
  });
}

function defaultIndexedDB() {
  try {
    return globalThis.indexedDB;
  } catch {
    return undefined; // browser yang memblokir penyimpanan bisa melempar saat indexedDB disentuh
  }
}

// Kotak share: { all(), put(entry), del(id), clear() }, entri ber-keyPath `id`. Tanpa IndexedDB → store memori kosong
// yang tidak melempar. Dengan IndexedDB, error (penyimpanan penuh, DB rusak) menjadi promise yang ditolak.
export function shareStore(idb = defaultIndexedDB()) {
  if (!idb || typeof idb.open !== 'function') return memoryStore();
  return {
    all: () => run(idb, 'readonly', s => s.getAll()),
    put: entry => run(idb, 'readwrite', s => s.put(entry)),
    del: id => run(idb, 'readwrite', s => s.delete(id)),
    clear: () => run(idb, 'readwrite', s => s.clear()),
  };
}

export async function clearShares(store) {
  await store.clear();
}

export const LOGOUT_WAIT_MS = 2000;

// Logout (api.logout): kotak share dikosongkan HANYA saat user sendiri keluar (`revoke === true`). Refresh token
// ditolak memanggil logout({ revoke: false }): bukti yang belum terkirim tetap ada, dan setelah login lagi banner
// membawa user ke /bagikan (spec 5b) — `next` langsung dijalankan (sinkron) dan kotak tidak disentuh.
// Saat user keluar, `next` (pindah ke /login) baru dijalankan setelah penghapusan selesai, gagal, atau lewat `waitMs`:
// navigasi yang langsung jalan memutus penghapusan IndexedDB yang belum selesai (di Chromium kotak sering tidak
// terhapus). Best-effort: tidak pernah melempar atau ditolak; → true bila kotak dikosongkan.
export function clearSharesOnLogout({ revoke } = {}, {
  next = () => {}, makeStore = shareStore, waitMs = LOGOUT_WAIT_MS, setTimer = setTimeout,
} = {}) {
  const proceed = () => { try { next(); } catch { /* logout tetap selesai */ } };
  if (revoke !== true) {
    proceed();
    return Promise.resolve(false);
  }
  let cleared;
  try {
    cleared = clearShares(makeStore()).then(() => true, () => false);
  } catch {
    cleared = Promise.resolve(false);
  }
  let timer;
  const capped = new Promise((resolve) => {
    try { timer = setTimer(() => resolve(false), waitMs); } catch { resolve(false); } // pindah ke /login tidak boleh tertahan
  });
  return Promise.race([cleared, capped]).then((ok) => {
    try { clearTimeout(timer); } catch { /* timer tiruan */ }
    proceed();
    return ok;
  });
}

// ── Menerima share (service worker) ─────────────────────────────────────────────────────────────────

// Hanya POST /bagikan di origin aplikasi sendiri (action share_target). POST lain tidak pernah dicegat.
export function isShareTarget(request, origin) {
  if (!request || request.method !== 'POST') return false;
  try {
    const url = new URL(request.url);
    return url.origin === origin && url.pathname === '/bagikan';
  } catch {
    return false;
  }
}

function sharedFiles(formData) {
  // Nilai bukan file dan file kosong (0 byte, mis. kolom file tanpa isi) tidak bisa dibaca server: diabaikan.
  return formData.getAll('files').filter(v => v instanceof Blob && v.size > 0).slice(0, MAX_FILES);
}

// Nilai teks satu kolom: baris baru diseragamkan ke \n (multipart bisa membawa \r\n), spasi di tepi dibuang.
function field(formData, name) {
  const v = formData.get(name);
  return typeof v === 'string' ? v.replace(/\r\n?/g, '\n').trim() : '';
}

// Judul lalu teks, digabung baris baru (judul yang sama dengan teks tidak diulang); `url` hanya bila tidak ada teks
// lain (aplikasi Android biasanya menaruh tautan di `text`).
function sharedText(formData) {
  const parts = [...new Set([field(formData, 'title'), field(formData, 'text')].filter(Boolean))];
  return parts.length ? parts.join('\n') : field(formData, 'url');
}

// Simpan satu share sebagai satu batch → batchId. Entri file {id, batchId, seq, name, type, blob, createdAt} (maks
// MAX_FILES, sisanya diabaikan) dan satu entri teks {id, batchId, seq, text, type: 'text/plain', createdAt}. `seq` =
// urutan dalam share (nextToUpload). Tanpa file dan teks: tidak menyimpan apa pun, tetap mengembalikan batchId.
// Gagal di tengah → entri batch ini yang sudah tersimpan dihapus lagi, lalu melempar (share tidak setengah tersimpan).
export async function saveShare(store, formData, { now = Date.now, newId = newRef } = {}) {
  const batchId = newId();
  const createdAt = now();
  const entries = sharedFiles(formData).map((file, seq) => ({
    id: newId(), batchId, seq, name: file.name || '', type: file.type || '', blob: file, createdAt,
  }));
  const text = sharedText(formData);
  if (text) entries.push({ id: newId(), batchId, seq: entries.length, text, type: 'text/plain', createdAt });

  const saved = [];
  try {
    for (const entry of entries) {
      await store.put(entry);
      saved.push(entry.id);
    }
  } catch (err) {
    for (const id of saved) {
      try { await store.del(id); } catch { /* best-effort */ }
    }
    throw err;
  }
  return batchId;
}

// 303 dengan Location relatif. Bukan Response.redirect: itu butuh URL absolut di luar service worker (Node melempar);
// browser menyelesaikan Location relatif terhadap URL permintaan.
function seeOther(location) {
  return new Response(null, { status: 303, headers: { Location: location } });
}

// Penangan POST /bagikan di service worker → selalu 303: ke /bagikan?s=<batch>, atau /bagikan?err=baca bila form
// tidak bisa dibaca atau disimpan. Tidak pernah melempar (navigasi share tidak boleh berakhir di halaman error).
export async function handleShareTarget(request, { store, now = Date.now, newId = newRef } = {}) {
  let formData;
  try {
    formData = await request.formData();
  } catch {
    return seeOther('/bagikan?err=baca');
  }
  try {
    const batchId = await saveShare(store, formData, { now, newId });
    return seeOther(`/bagikan?s=${encodeURIComponent(batchId)}`);
  } catch {
    return seeOther('/bagikan?err=baca');
  }
}

// ── Mengunggah (halaman /bagikan) ───────────────────────────────────────────────────────────────────

const order = e => [Number(e.createdAt) || 0, Number(e.seq) || 0];

// Entri berikutnya untuk diunggah: share tertua dulu, dalam satu share sesuai urutan dibagikan. Kosong → null.
export function nextToUpload(entries) {
  if (!Array.isArray(entries) || entries.length === 0) return null;
  return entries.reduce((best, e) => {
    const [t, s] = order(e);
    const [bt, bs] = order(best);
    return t < bt || (t === bt && s < bs) ? e : best;
  });
}

// FormData untuk POST /kotak-struk/ (api.kotakUpload): tepat satu dari `file`/`text` (server menolak keduanya),
// `upload_id` = id entri (kirim ulang tidak membuat item ganda), `wait` detik menunggu hasil baca.
export function uploadFormFor(entry, { wait = UPLOAD_WAIT_S } = {}) {
  const fd = new FormData();
  if (entry.blob) fd.append('file', entry.blob, entry.name || 'bukti');
  else fd.append('text', entry.text ?? '');
  fd.append('source', SHARE_SOURCE);
  fd.append('upload_id', entry.id);
  fd.append('wait', String(wait));
  return fd;
}

// Batas waktu satu unggahan (xhrUpload). File share dikirim apa adanya, tidak dikompres (foto ≤ 8 MB, PDF ≤ 10 MB),
// jadi aturan waktu PDF receiptProgress (60 dtk + 1 dtk per 25 kB, maks 5 menit) dipakai untuk semua file; teks 60 dtk.
export function shareUploadTimeoutMs(entry) {
  return uploadTimeoutMs(entry?.blob ? { type: PDF_TYPE, size: entry.blob.size } : null);
}

// ── Halaman /bagikan ────────────────────────────────────────────────────────────────────────────────
// Alur halaman sebagai fungsi murni (Bagikan.jsx hanya merender dan memanggil API): saklar fitur, offline, unggah
// satu per satu, kartu bukti per item, pemantauan item yang masih dibaca, dan tombol Ke Transaksi.

export const POLL_MS = 1500;          // item yang masih dibaca dipantau (GET /kotak-struk/{id}) tiap 1,5 dtk …
export const POLL_LIMIT_MS = 30000;   // … paling lama 30 dtk sejak diterima

export const SHARE_TEXT = Object.freeze({
  soon: 'Fitur ini segera hadir.',
  errSw: 'Buka Jatahku sekali, lalu bagikan lagi.',
  errBaca: 'File yang dibagikan tidak bisa dibaca. Coba bagikan lagi.',
  storageHint: 'Kalau memori HP penuh, kosongkan sedikit lalu bagikan lagi.',
  notSent: 'Bukti belum terkirim. Akan dikirim lagi saat online.',
  cannotSend: 'Bukti tidak bisa dikirim.',
  tooMany: 'Terlalu banyak bukti. Coba lagi sebentar.', // = MSG_RATE server, untuk 429 tanpa detail
  empty: 'Tidak ada bukti yang menunggu.',
});

// Banner entri yang belum terkirim (offline). 0 → null.
export function offlineBannerText(n) {
  return n > 0 ? `${n} bukti menunggu dikirim. Akan dikirim saat online.` : null;
}

const textDetail = res => (typeof res?.data?.detail === 'string' && res.data.detail.trim() ? res.data.detail : null);

// Hasil api.kotakUpload → apa yang dilakukan pada entri lokal:
//   done → hapus entri, tampilkan `item` (201 baru / 200 item yang sama untuk upload_id itu);
//   drop → hapus entri, tampilkan `message`: 413/415/422, server tidak akan pernah menerima isi ini. Detail bukan teks
//          (validasi FastAPI berupa daftar, HTML nginx) → "Bukti tidak bisa dikirim." (G13);
//   keep → entri tetap, putaran berhenti, dikirim lagi nanti (upload_id sama: tidak dobel): tanpa jawaban/batas waktu,
//          5xx, 401 (sesi; refresh gagal → ke /login, entri aman), 429 (pesan server), dan 4xx lain (tidak dibuang).
export function uploadOutcome(res) {
  if (res?.ok) return { action: 'done', item: res.data };
  const status = Number(res?.status) || 0;
  if (status === 0 || res?.timedOut || status >= 500 || status === 401) return { action: 'keep', message: SHARE_TEXT.notSent };
  if (status === 413 || status === 415 || status === 422) return { action: 'drop', message: textDetail(res) || SHARE_TEXT.cannotSend };
  if (status === 429) return { action: 'keep', message: textDetail(res) || SHARE_TEXT.tooMany };
  return { action: 'keep', message: textDetail(res) || SHARE_TEXT.notSent };
}

const IN_PROGRESS = new Set(['diterima', 'diproses']);

// Item yang masih dibaca server dipantau sampai berubah status atau lewat POLL_LIMIT_MS sejak `startedAt`.
export function needsPolling(item, startedAt, now) {
  return IN_PROGRESS.has(item?.status) && now - startedAt < POLL_LIMIT_MS;
}

// Saklar `features.receipt_inbox` dari config /app/config: 'on' | 'off' | 'unknown'. Server selalu mengirim nilai
// boolean; tanpa nilai boolean (DEFAULT_CONFIG: belum pernah terbaca, tanpa cache) = belum diketahui.
export function shareFlag(config) {
  const v = config?.features?.receipt_inbox;
  return v === true ? 'on' : v === false ? 'off' : 'unknown';
}

// Yang dilakukan halaman untuk saklar dan koneksi ini:
//   'off'  → "Fitur ini segera hadir.", entri batch `?s=` dihapus, TANPA permintaan Kotak (D1, G12);
//   'hold' → offline, atau saklar belum diketahui (jangan menghapus berdasarkan tebakan): entri tetap, banner jumlahnya;
//   'send' → unggah entri lokal, lalu tampilkan bukti menunggu.
export function sharePageMode({ flag, online } = {}) {
  if (flag === 'off') return 'off';
  if (online === false || flag !== 'on') return 'hold';
  return 'send';
}

// Hapus entri satu batch (saklar mati: berkas bukti asli tidak boleh tertinggal di HP). → jumlah yang terhapus.
// Tidak pernah melempar: kotak yang tidak bisa dibaca atau dihapus dilewati.
export async function discardBatch(store, batchId) {
  if (!batchId) return 0;
  let entries;
  try {
    entries = await store.all();
  } catch {
    return 0;
  }
  let n = 0;
  for (const e of entries) {
    if (e?.batchId !== batchId) continue;
    try {
      await store.del(e.id);
      n += 1;
    } catch { /* best-effort */ }
  }
  return n;
}

// Satu putaran halaman /bagikan (dibuka, atau event `online`). I/O disuntikkan, supaya urutan dan gerbang saklar
// teruji di Node:
//   getConfig()     → config /app/config terbaru (gagal → cache terakhir / bawaan, lihat appConfig.refreshAppConfig)
//   isOnline()      → navigator.onLine
//   batchId         → `?s=` (hanya untuk saklar mati)
//   store           → shareStore()
//   upload(entry)   → hasil api.kotakUpload (satu entri, progres diurus pemanggil)
//   loadPending()   → detail item untuk kartu sesudah antrean lokal (fetchPendingDetails)
//   onItem(item)    → item dari unggahan, langsung saat diterima server
//   onMode(mode)    → begitu mode diputuskan (sharePageMode)
//   alive()         → false: halaman ditutup; tidak ada unggahan baru dan bukti menunggu tidak dimuat
// → { mode, waiting, items, pending, dropped: [{name, message}], kept: pesan|null, storeFailed }. Tidak melempar.
// Saklar mati: hanya getConfig yang dipanggil (lalu entri batch dihapus). Unggahan satu per satu, tertua dulu
// (nextToUpload); tiap entri dicoba sekali per putaran, juga bila menghapusnya gagal (dikirim ulang lain kali dengan
// upload_id yang sama → item yang sama, tidak dobel).
export async function runSharePage({
  getConfig, isOnline = () => true, batchId = null, store, upload, loadPending,
  onItem = () => {}, onMode = () => {}, alive = () => true,
} = {}) {
  const out = { mode: 'hold', waiting: 0, items: [], pending: [], dropped: [], kept: null, storeFailed: false };
  let config = null;
  try {
    config = await getConfig();
  } catch {
    config = null;
  }
  out.mode = sharePageMode({ flag: shareFlag(config), online: isOnline() });
  try { onMode(out.mode); } catch { /* tampilan saja */ }
  if (out.mode === 'off') {
    await discardBatch(store, batchId);
    return out;
  }

  let entries = [];
  try {
    entries = (await store.all()) || [];
  } catch {
    out.storeFailed = true;
  }
  if (out.mode === 'hold') {
    out.waiting = entries.length;
    return out;
  }

  const tried = new Set();
  while (alive()) {
    const entry = nextToUpload(entries.filter(e => !tried.has(e.id)));
    if (!entry) break;
    tried.add(entry.id);
    let res = null;
    try {
      res = await upload(entry);
    } catch {
      res = null;
    }
    const verdict = uploadOutcome(res);
    if (verdict.action === 'keep') {
      out.kept = verdict.message;
      break;
    }
    try { await store.del(entry.id); } catch { /* lihat di atas: tidak dobel */ }
    if (verdict.action === 'done') {
      out.items.push(verdict.item);
      try { onItem(verdict.item); } catch { /* tampilan saja */ }
    } else {
      out.dropped.push({ name: entry.name || '', message: verdict.message });
    }
  }
  if (!alive()) return out;
  try {
    out.pending = (await loadPending()) || [];
  } catch {
    out.pending = [];
  }
  return out;
}

// Satu putaran halaman pada satu waktu (D8): start() selama putaran berjalan tidak memulai putaran kedua yang
// bersamaan (unggahan tetap satu per satu, tiap entri sekali), tetapi menjadwalkan tepat SATU putaran lagi sesudahnya:
// event `online` di tengah putaran berarti ada entri yang mungkin tersimpan karena offline. `alive()` false (halaman
// ditutup) → tidak ada putaran baru. Putaran yang melempar tidak memutus antrean. → start(): janji yang selesai saat
// tidak ada putaran lagi; tidak pernah ditolak.
export function serialRuns(run, { alive = () => true } = {}) {
  let active = false;
  let again = false;
  return async function start() {
    if (active) {
      again = true;
      return;
    }
    if (!alive()) return;
    active = true;
    try {
      do {
        again = false;
        try { await run(); } catch { /* putaran berikutnya tetap jalan */ }
      } while (again && alive());
    } finally {
      active = false;
    }
  };
}

// Urutan status: jawaban lama yang tiba belakangan (pantauan vs daftar bukti menunggu) tidak boleh memundurkan kartu.
// diterima/diproses setara (worker memulihkan item macet ke diterima).
const STATUS_RANK = { diterima: 0, diproses: 0, siap: 1, gagal: 1, tercatat: 2, dilewati: 2, kedaluwarsa: 2 };
const rank = item => STATUS_RANK[item?.status] ?? 1;

// Kartu ProofCard: satu per item.id (D5). Detail yang datang menggantikan detail lama di tempat yang sama (tidak
// pindah urutan, `key` tetap), kecuali statusnya lebih awal; id baru ditambah di belakang. Tanpa id diabaikan.
// Tidak mengubah `list`.
export function mergeItems(list, incoming) {
  const out = Array.isArray(list) ? [...list] : [];
  for (const item of Array.isArray(incoming) ? incoming : []) {
    if (!item?.id) continue;
    const i = out.findIndex(x => x.id === item.id);
    if (i < 0) out.push(item);
    else if (rank(item) >= rank(out[i])) out[i] = item;
  }
  return out;
}

// Id item yang perlu dipantau sekarang. `startedAt`: Map id → saat item pertama diterima dari unggahan.
export function pollTargets(items, startedAt, now) {
  if (!Array.isArray(items) || !startedAt) return [];
  return items.filter(it => needsPolling(it, startedAt.get(it.id), now)).map(it => it.id);
}

// Pemantauan item yang masih dibaca server (D5): satu rantai timer untuk semua item, GET tiap `interval` selama
// `targets()` tidak kosong. start() memulai rantai bila belum berjalan dan ada target (→ true); stop() saat halaman
// dilepas: timer dibatalkan, jawaban GET yang masih berjalan diabaikan, tidak ada GET baru, dan pemantau ini selesai.
//   targets()       → id yang perlu dipantau sekarang (pollTargets; saklar mati → []); kosong → rantai berhenti
//   fetchItem(id)   → detail terbaru atau null (api.kotakItem); lemparan dianggap null
//   onDetails(list) → detail yang terbaca (tanpa null), sekali per GET
//   onRunning(bool) → rantai mulai/berhenti (tombol Ke Transaksi menunggu pemantauan selesai); tidak sesudah stop()
export function createPoller({
  targets, fetchItem, onDetails = () => {}, onRunning = () => {}, interval = POLL_MS,
  setTimer = setTimeout, clearTimer = clearTimeout,
} = {}) {
  let timer = null;
  let running = false;
  let stopped = false;
  const ids = () => {
    if (stopped) return [];
    try { return targets() || []; } catch { return []; }
  };
  const tell = (on) => { try { onRunning(on); } catch { /* tampilan saja */ } };
  const halt = () => {
    running = false;
    timer = null;
    if (!stopped) tell(false);
  };
  const tick = async () => {
    timer = null;
    const due = ids();
    if (!due.length) return halt();
    const details = await Promise.all(due.map(id => Promise.resolve().then(() => fetchItem(id)).catch(() => null)));
    if (stopped) return halt();
    try { onDetails(details.filter(Boolean)); } catch { /* tampilan saja */ }
    if (!ids().length) return halt();
    timer = setTimer(tick, interval);
    return undefined;
  };
  return {
    start() {
      if (stopped || running || !ids().length) return false;
      running = true;
      tell(true);
      timer = setTimer(tick, interval);
      return true;
    },
    stop() {
      stopped = true;
      if (timer !== null) clearTimer(timer);
      timer = null;
      running = false;
    },
    get running() { return running; },
  };
}

// Detail untuk kartu sesudah antrean lokal habis, dan sesudah kartu dicatat/dilewati (D5): bukti menunggu
// (GET /kotak-struk/?status=siap), lalu detail terbaru kartu `siap` yang belum ditangani di halaman ini tetapi tidak
// ada lagi di daftar itu (dicatat, dilewati, atau kedaluwarsa di tempat lain). Gagal → dilewati (tidak melempar).
export async function fetchPendingDetails({ items = [], handled = new Set(), loadPending, loadItem } = {}) {
  let pending = [];
  try {
    pending = (await loadPending()) || [];
  } catch {
    pending = [];
  }
  const listed = new Set(pending.map(it => it?.id));
  const stale = items.filter(it => it?.status === 'siap' && !handled.has(it.id) && !listed.has(it.id)).map(it => it.id);
  const fresh = await Promise.all(stale.map(id => Promise.resolve().then(() => loadItem(id)).catch(() => null)));
  return [...pending, ...fresh.filter(Boolean)];
}

// Tombol Ke Transaksi: tidak ada unggahan atau pantauan yang berjalan, dan setiap kartu sudah ditangani di halaman ini
// (dicatat/dilewati) atau tidak bisa ditindaklanjuti (gagal, tercatat, dilewati, kedaluwarsa, atau masih dibaca
// sesudah batas pantau). Tanpa kartu → true.
export function pageFinished({ items = [], handled = new Set(), running = false, polling = false } = {}) {
  if (running || polling) return false;
  return items.every(it => it?.status !== 'siap' || handled.has(it.id));
}

// Baris pemberitahuan di atas halaman: `?err=sw` (POST lolos ke server, service worker belum aktif), `?err=baca`
// (service worker gagal membaca/menyimpan share, termasuk memori penuh: baris kedua, D3), dan kotak share yang tidak
// bisa dibaca halaman ini. Hanya setelah saklar diketahui menyala/ditahan (`mode` 'hold'/'send'): selama memeriksa
// tidak ada yang berkedip, dan dengan saklar mati hanya "Fitur ini segera hadir." yang tampil.
export function pageNotices({ mode = null, err = null, storeFailed = false } = {}) {
  if (mode !== 'hold' && mode !== 'send') return [];
  const lines = [];
  if (err === 'sw') lines.push(SHARE_TEXT.errSw);
  if (err === 'baca') lines.push(SHARE_TEXT.errBaca, SHARE_TEXT.storageHint);
  if (storeFailed && !lines.includes(SHARE_TEXT.errBaca)) lines.push(SHARE_TEXT.errBaca);
  return lines;
}

// Satu baris entri yang dibuang (drop): "nama file: pesan"; entri teks tanpa nama.
export function dropLine({ name = '', message = '' } = {}) {
  return name ? `${name}: ${message}` : message;
}

// Yang tampil di halaman untuk keadaan ini (Bagikan.jsx hanya merender):
//   checking → "Memuat…" selama saklar diperiksa; soon → saklar mati: satu-satunya teks, dan `results` false (kartu,
//              pesan unggah, dan entri dibuang dari putaran sebelumnya disembunyikan: kartu tidak boleh memanggil
//              Kotak Struk saat saklar mati);
//   notices  → pageNotices; banner → offline/ditahan dengan entri menunggu;
//   finished → tombol Ke Transaksi (hanya mode kirim, pageFinished); empty → tidak ada kartu dan tidak ada pesan unggah.
export function pageView({
  mode = null, err = null, storeFailed = false, waiting = 0, items = [], handled = new Set(), running = false,
  polling = false, dropped = [], kept = null,
} = {}) {
  const finished = mode === 'send' && pageFinished({ items, handled, running, polling });
  return {
    checking: mode === null,
    soon: mode === 'off' ? SHARE_TEXT.soon : null,
    results: mode !== 'off',
    notices: pageNotices({ mode, err, storeFailed }),
    banner: mode === 'hold' ? offlineBannerText(waiting) : null,
    finished,
    empty: finished && items.length === 0 && dropped.length === 0 && !kept ? SHARE_TEXT.empty : null,
  };
}
