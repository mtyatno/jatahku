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
  const capped = new Promise((resolve) => {
    try { setTimer(() => resolve(false), waitMs); } catch { resolve(false); } // pindah ke /login tidak boleh tertahan
  });
  return Promise.race([cleared, capped]).then((ok) => { proceed(); return ok; });
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
