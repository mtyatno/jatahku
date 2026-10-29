// Kotak share lokal — "Bagikan ke Jatahku" lewat Web Share Target PWA (spec 5b, docs/kotak-struk.md).
//
// Alur: menu Bagikan Android → POST multipart /bagikan → service worker (src/sw.js) menyimpan tiap file dan teksnya
// ke IndexedDB `jatahku-share` (store `shares`) lalu menjawab 303 ke /bagikan?s=<batch>. Halaman /bagikan mengunggah
// entri satu per satu ke Kotak Struk (`uploadFormFor`, urutan `nextToUpload`: tertua dulu, entri yang gagal ke
// belakang) dan menghapus entri yang sudah diterima server. Semua fungsi di sini murni (tanpa DOM, tanpa `self`):
// dipakai service worker dan halaman, dan diuji dengan node --test.
//
// Privasi: entri berisi gambar/PDF/teks bukti apa adanya (belum disamarkan). Isinya tidak pernah di-log. Entri dihapus
// setelah terunggah, dan seluruh kotak dikosongkan saat user sendiri logout (`clearSharesOnLogout`). Sesi yang
// kedaluwarsa tidak menghapusnya: bukti tetap aman sampai user login lagi. Kotak milik satu akun (`ensureShareOwner`):
// akun lain yang login di HP itu mendapati kotak dikosongkan sebelum dibaca.
import { newRef } from './ref.js';
import { PDF_MAX_BYTES, PDF_TYPE, isPdfHead, uploadTimeoutMs } from './receiptProgress.js';

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
    touch: async (id, patch) => {
      if (!map.has(id)) return false;
      map.set(id, { ...map.get(id), ...patch });
      return true;
    },
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

// Kotak share: { all(), put(entry), del(id), clear(), touch(id, patch) }, entri ber-keyPath `id`. Tanpa IndexedDB →
// store memori kosong yang tidak melempar. Dengan IndexedDB, error (penyimpanan penuh, DB rusak) menjadi promise yang
// ditolak. touch: ubah entri yang MASIH ada (baca + tulis dalam satu transaksi) → true; entri yang sudah dihapus
// (logout, tab lain) tidak pernah dibuat ulang → false.
export function shareStore(idb = defaultIndexedDB()) {
  if (!idb || typeof idb.open !== 'function') return memoryStore();
  return {
    all: () => run(idb, 'readonly', s => s.getAll()),
    put: entry => run(idb, 'readwrite', s => s.put(entry)),
    del: id => run(idb, 'readwrite', s => s.delete(id)),
    clear: () => run(idb, 'readwrite', s => s.clear()),
    touch: (id, patch) => run(idb, 'readwrite', (s) => {
      const req = s.get(id);
      req.onsuccess = () => { if (req.result) s.put({ ...req.result, ...patch }); };
      return req;
    }).then(prev => !!prev),
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

// ── Pemilik kotak share ─────────────────────────────────────────────────────────────────────────────
// Entri tidak membawa id user, dan sesi yang kedaluwarsa tidak mengosongkan kotak. Karena itu kotak dicap dengan
// pemiliknya (localStorage `SHARE_OWNER_KEY` = akun token sesi tab ini, `tokenSubject`) oleh pembacanya (banner,
// /bagikan), bukan oleh jalur login: sebelum kotak dibaca, akun lain yang login di HP yang sama mendapati kotak
// dikosongkan dulu. Logout oleh user sendiri mengosongkan kotak tetapi tidak menghapus cap: share yang dibagikan
// sesudahnya (belum login) hanya terkirim ke akun yang sama; bila akun lain yang login berikutnya, share itu dihapus
// (privasi lebih penting).

export const SHARE_OWNER_KEY = 'jatahku_share_owner';

// Pemilik = klaim `sub` access token yang dipakai tab ini (JWT, app/core/security.py: id user), yaitu akun yang
// menerima unggahan /bagikan. Bukan profil di layar (useAuth): bila /auth/me gagal sesudah login, profil itu bisa
// salinan cache akun sebelumnya. Tanda tangan tidak diperiksa (tugas server). Token tidak ada atau tidak terbaca →
// null, jadi pemanggil menganggap kotak tidak terbaca (gagal tertutup). Tidak pernah melempar.
export function tokenSubject(token) {
  if (typeof token !== 'string') return null;
  const part = token.split('.')[1];
  if (!part) return null;
  try {
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/');
    const binary = atob(b64 + '='.repeat((4 - (b64.length % 4)) % 4));
    const claims = JSON.parse(new TextDecoder().decode(Uint8Array.from(binary, c => c.charCodeAt(0))));
    return typeof claims?.sub === 'string' && claims.sub ? claims.sub : null;
  } catch {
    return null;
  }
}

// Cap pemilik yang tersimpan vs akun token sesi (tokenSubject) → 'claim' (belum ada pemilik: dicap), 'keep' (akun yang
// sama), atau 'clear' (akun lain: kotak dikosongkan dulu). `userId` wajib (ensureShareOwner memeriksanya lebih dulu).
export function shareOwnerAction(storedOwnerId, userId) {
  if (storedOwnerId === null || storedOwnerId === undefined || storedOwnerId === '') return 'claim';
  return String(storedOwnerId) === String(userId) ? 'keep' : 'clear';
}

// Panggil sebelum membaca kotak → true bila kotak boleh dibaca user ini. 'claim' menulis cap; 'keep' tidak menulis
// apa pun; 'clear' mengosongkan kotak LEBIH DULU, baru menulis cap baru (cap tidak pernah berganti selama entri akun
// lain masih ada). Gagal tertutup: tanpa user, localStorage yang tidak ada/melempar, atau kotak yang gagal dikosongkan
// → false (kotak dianggap tidak terbaca), tanpa menyentuh kotak bila cap tidak terbaca. Tidak pernah melempar/ditolak.
// `opts.storage` = localStorage tiruan (tes); bawaan globalThis.localStorage.
export async function ensureShareOwner(store, userId, opts = {}) {
  if (userId === null || userId === undefined || userId === '') return false;
  let storage;
  let stored;
  try {
    storage = opts?.storage === undefined ? globalThis.localStorage : opts.storage;
    stored = storage.getItem(SHARE_OWNER_KEY);
  } catch {
    return false;
  }
  const action = shareOwnerAction(stored, userId);
  if (action === 'keep') return true;
  if (action === 'clear') {
    try {
      await clearShares(store);
    } catch {
      return false;   // cap lama tetap: pembacaan berikutnya mencoba mengosongkan lagi
    }
  }
  try {
    storage.setItem(SHARE_OWNER_KEY, String(userId));
  } catch {
    return false;
  }
  return true;
}

// Pemeriksaan pemilik untuk satu pemakai yang membaca berkali-kali (banner: hitung ulang bisa bertumpuk). Panggilan
// selama pemeriksaan berjalan memakai janji yang sama (kotak dikosongkan paling banyak sekali per pemakai); sesudah
// selesai, panggilan berikutnya memeriksa lagi (cap bisa berganti di tab lain). → () => Promise<boolean>.
export function ownerGate(store, userId, opts) {
  let inflight = null;
  return () => {
    if (!inflight) inflight = ensureShareOwner(store, userId, opts).finally(() => { inflight = null; });
    return inflight;
  };
}

// Entri kotak untuk hitungan banner: hanya bila kotak milik user ini (`owned()` → true); selain itu [] tanpa membaca
// kotak.
export async function ownedShares(store, owned) {
  return (await owned()) ? store.all() : [];
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

// Urutan unggah: belum pernah dicoba (triedAt kosong = 0) dulu, lalu yang paling lama tidak dicoba, lalu share tertua
// dan urutan dalam share. `triedAt` dicatat saat unggahan sebuah entri berakhir `keep` (runSharePage): entri yang terus
// gagal (file tidak terbaca, 5xx per file) pindah ke belakang dan tidak menahan entri lain selamanya.
const order = e => [Number(e.triedAt) || 0, Number(e.createdAt) || 0, Number(e.seq) || 0];
const earlier = (a, b) => {
  for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return a[i] < b[i];
  return false;
};

// Entri berikutnya untuk diunggah (urutan di atas). Kosong → null.
export function nextToUpload(entries) {
  if (!Array.isArray(entries) || entries.length === 0) return null;
  return entries.reduce((best, e) => (earlier(order(e), order(best)) ? e : best));
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
  // File > 10 MB dibuang di HP (oversizeMessage): teks yang sama dengan intake server (kotak_struk/intake.py).
  pdfTooBig: 'PDF terlalu besar (maks 10 MB)', // = MSG_PDF_BIG
  photoTooBig: 'Foto terlalu besar (maks 8 MB)', // = MSG_IMAGE_BIG
  badType: 'Kirim foto (JPG/PNG/WebP), PDF, atau teks', // = MSG_TYPE (415)
  // Daftar entri yang tertahan (keptEntries): tombol per entri, dan label entri teks (entri file: nama filenya).
  remove: 'Hapus',
  textEntry: 'teks',
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
  // 2xx tanpa item (bukan jawaban API Kotak Struk, mis. halaman HTML dari proxy) → simpan: entri lokal hanya dihapus
  // bila server terbukti menerima bukti itu.
  if (res?.ok) return res.data?.id ? { action: 'done', item: res.data } : { action: 'keep', message: SHARE_TEXT.notSent };
  const status = Number(res?.status) || 0;
  if (status === 0 || res?.timedOut || status >= 500 || status === 401) return { action: 'keep', message: SHARE_TEXT.notSent };
  if (status === 413 || status === 415 || status === 422) return { action: 'drop', message: textDetail(res) || SHARE_TEXT.cannotSend };
  if (status === 429) return { action: 'keep', message: textDetail(res) || SHARE_TEXT.tooMany };
  return { action: 'keep', message: textDetail(res) || SHARE_TEXT.notSent };
}

// ── File yang tidak mungkin diterima server: diputuskan di HP, tanpa mengunggah ─────────────────────────────────
// Server membaca paling banyak PDF_MAX_BYTES + 1 byte dan mengenali jenis dari isinya (intake.py): file > 10 MB tidak
// pernah diterima. Mengunggahnya hanya membuang kuota data dan, di koneksi lambat, bisa berakhir di batas waktu (keep)
// alih-alih 413 sehingga menahan antrean.

const SNIFF_BYTES = 12; // cukup untuk tanda WebP (RIFF....WEBP)
const startsWith = (b, sig, at = 0) => sig.every((v, i) => b[at + i] === v);

// Jenis isi dari byte awal, sama dengan server (kotak_struk/extract.py sniff_type): JPG/PNG/WebP/PDF; selain itu null.
export function sniffShareType(head) {
  if (!head) return null;
  const b = head instanceof ArrayBuffer ? new Uint8Array(head) : head;
  if (startsWith(b, [0xff, 0xd8, 0xff])) return 'image/jpeg';
  if (startsWith(b, [0x89, 0x50, 0x4e, 0x47])) return 'image/png';
  if (startsWith(b, [0x52, 0x49, 0x46, 0x46]) && startsWith(b, [0x57, 0x45, 0x42, 0x50], 8)) return 'image/webp';
  if (isPdfHead(b)) return PDF_TYPE;
  return null;
}

// Pesan untuk file > 10 MB: yang sama dengan jawaban server untuk isi itu (PDF → 413 PDF, JPG/PNG/WebP → 413 foto,
// isi lain → 415). `head` = byte awal file, null bila tidak terbaca: menurut tipe yang dibagikan. File ≤ 10 MB atau teks
// → null (diunggah; batas foto 8 MB tetap diputuskan server).
export function oversizeMessage(entry, head) {
  const blob = entry?.blob;
  if (!blob || !(Number(blob.size) > PDF_MAX_BYTES)) return null;
  if (head) {
    const kind = sniffShareType(head);
    if (kind === PDF_TYPE) return SHARE_TEXT.pdfTooBig;
    return kind ? SHARE_TEXT.photoTooBig : SHARE_TEXT.badType;
  }
  return (entry.type || blob.type) === PDF_TYPE ? SHARE_TEXT.pdfTooBig : SHARE_TEXT.photoTooBig;
}

// Byte awal sebuah Blob, atau null bila tidak terbaca (berkas IndexedDB rusak/hilang). Tidak melempar.
async function headOf(blob) {
  try {
    return new Uint8Array(await blob.slice(0, SNIFF_BYTES).arrayBuffer());
  } catch {
    return null;
  }
}

// Penolakan lokal untuk satu entri: pesan (dibuang tanpa diunggah) atau null. Byte awal hanya dibaca untuk file > 10 MB.
async function localRefusal(entry) {
  if (!oversizeMessage(entry, null)) return null;
  return oversizeMessage(entry, await headOf(entry.blob));
}

const IN_PROGRESS = new Set(['diterima', 'diproses']);

// Item yang masih dibaca server dipantau sampai berubah status atau lewat POLL_LIMIT_MS sejak `startedAt`.
export function needsPolling(item, startedAt, now) {
  return IN_PROGRESS.has(item?.status) && now - startedAt < POLL_LIMIT_MS;
}

// ── Batas waktu baca halaman /bagikan ──────────────────────────────────────────────────────────────────
// Permintaan `fetch` biasa tidak punya batas waktu; koneksi yang menggantung tidak boleh menahan halaman di "Memuat…"
// atau menahan putaran (tanpa Ke Transaksi / Kirim lagi).

export const CONFIG_WAIT_MS = 10000;   // /app/config
export const READ_WAIT_MS = 20000;     // bukti menunggu (GET /kotak-struk/?status=siap) dan satu item (GET /kotak-struk/{id})

// Nilai atau penolakan `promise` bila datang sebelum `ms`; selain itu `fallback`. Hanya berhenti menunggu: permintaannya
// tidak dibatalkan, dan jawaban yang datang sesudah batas waktu diabaikan. Timer bisa disuntikkan (tes).
export function withTimeout(promise, ms, fallback, { setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimer(() => {
      if (settled) return;
      settled = true;
      resolve(fallback);
    }, ms);
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      try { clearTimer(timer); } catch { /* timer tiruan */ }
      fn(value);
    };
    Promise.resolve(promise).then(v => finish(resolve, v), e => finish(reject, e));
  });
}

// Bacaan halaman /bagikan dengan batas waktu, dari pembaca aslinya (Bagikan.jsx: api + appConfig):
//   config()  → getConfig() paling lama CONFIG_WAIT_MS, lalu config cache terakhir (`cachedConfig()`, readCachedConfig)
//               atau null: saklar belum diketahui → ditahan seperti offline (shareFlag/sharePageMode);
//   pending() → loadPending() paling lama READ_WAIT_MS, lalu [];
//   item(id)  → loadItem(id) paling lama READ_WAIT_MS, lalu null (pantauan, detail kartu yang hilang, cek ulang struk).
export function pageReads({ getConfig, cachedConfig = () => null, loadPending, loadItem }, timers = {}) {
  const cached = () => {
    try { return cachedConfig() ?? null; } catch { return null; }
  };
  return {
    config: () => withTimeout(Promise.resolve().then(getConfig), CONFIG_WAIT_MS, cached(), timers),
    pending: () => withTimeout(Promise.resolve().then(loadPending), READ_WAIT_MS, [], timers),
    item: id => withTimeout(Promise.resolve().then(() => loadItem(id)), READ_WAIT_MS, null, timers),
  };
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

// Entri yang tertahan di kotak share (putaran berhenti dengan keep) untuk daftar Hapus di /bagikan → [{id, label}]:
// label = nama file (file tanpa nama: "bukti", sama dengan nama unggahannya), atau "teks" untuk entri teks. Urutan
// share: tertua dulu, lalu urutan dalam share. Bukan daftar → [].
export function keptEntries(entries) {
  return (Array.isArray(entries) ? entries : [])
    .filter(e => e && e.id != null)
    .sort((a, b) => (Number(a.createdAt) || 0) - (Number(b.createdAt) || 0) || (Number(a.seq) || 0) - (Number(b.seq) || 0))
    .map(e => ({ id: e.id, label: e.blob ? (e.name || 'bukti') : SHARE_TEXT.textEntry }));
}

// Tombol Hapus: entri yang tidak pernah bisa terkirim dibuang, lalu kotak dihitung ulang → daftar yang tersisa
// (keptEntries). Hapus gagal → entri tetap terdaftar; kotak tidak terbaca → []. Tidak melempar.
export async function discardKept(store, id) {
  try { await store.del(id); } catch { /* dihitung ulang di bawah */ }
  try {
    return keptEntries(await store.all());
  } catch {
    return [];
  }
}

// Satu putaran halaman /bagikan (dibuka, atau event `online`). I/O disuntikkan, supaya urutan dan gerbang saklar
// teruji di Node:
//   getConfig()     → config /app/config terbaru (gagal → cache terakhir / bawaan, lihat appConfig.refreshAppConfig;
//                     menggantung → pageReads.config)
//   isOnline()      → navigator.onLine
//   batchId         → `?s=` (hanya untuk saklar mati)
//   store           → shareStore()
//   ensureOwner()   → true bila kotak milik user yang login (ensureShareOwner); dipanggil sebelum kotak dibaca, hanya
//                     saat saklar tidak mati. false/melempar → kotak dianggap tidak terbaca (storeFailed)
//   loadQueued()    → Set id item di antrean offline (offlineQueue.queuedReceiptItemIds); mode kirim saja, sekali,
//                     sebelum unggahan dan kartu pertama. onQueued(set) menerimanya; melempar → Set kosong
//   upload(entry)   → hasil api.kotakUpload (satu entri, progres diurus pemanggil)
//   loadPending()   → detail item untuk kartu sesudah antrean lokal (fetchPendingDetails)
//   onItem(item)    → item dari unggahan, langsung saat diterima server
//   onMode(mode)    → begitu mode diputuskan (sharePageMode)
//   alive()         → false: halaman ditutup; tidak ada unggahan baru dan bukti menunggu tidak dimuat
//   now()           → waktu untuk `triedAt`
// → { mode, waiting, items, pending, dropped: [{name, message}], kept: pesan|null, keptEntries, queued, storeFailed }.
// Tidak melempar. Saklar mati: hanya getConfig yang dipanggil (lalu entri batch dihapus; pemilik dan antrean offline
// tidak dibaca). Unggahan satu per satu menurut nextToUpload; tiap entri dicoba sekali per putaran, juga bila
// menghapusnya gagal (dikirim ulang lain kali dengan upload_id yang sama → item yang sama, tidak dobel). File > 10 MB
// dibuang tanpa diunggah (oversizeMessage). Keep menghentikan putaran (offline, 429, 5xx: entri lain tidak akan
// bernasib lain), mencatat `triedAt` pada entrinya, dan `keptEntries` = entri yang masih di kotak (daftar Hapus).
export async function runSharePage({
  getConfig, isOnline = () => true, batchId = null, store, upload, loadPending,
  ensureOwner = async () => true, loadQueued = async () => new Set(), onQueued = () => {},
  onItem = () => {}, onMode = () => {}, alive = () => true, now = Date.now,
} = {}) {
  const out = {
    mode: 'hold', waiting: 0, items: [], pending: [], dropped: [], kept: null, keptEntries: [], queued: new Set(),
    storeFailed: false,
  };
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

  let owned = false;
  try {
    owned = (await ensureOwner()) === true;
  } catch {
    owned = false;
  }
  let entries = [];
  if (!owned) {
    out.storeFailed = true;
  } else {
    try {
      entries = (await store.all()) || [];
    } catch {
      out.storeFailed = true;
    }
  }
  if (out.mode === 'hold') {
    out.waiting = entries.length;
    return out;
  }

  // Sebelum kartu pertama: item yang simpanannya masih di antrean offline tampil hanya-baca (proofFormat.readOnlyNotice).
  try {
    const ids = await loadQueued();
    out.queued = ids instanceof Set ? ids : new Set();
  } catch {
    out.queued = new Set();
  }
  try { onQueued(out.queued); } catch { /* tampilan saja */ }

  const tried = new Set();
  const gone = new Set();
  while (alive()) {
    const entry = nextToUpload(entries.filter(e => !tried.has(e.id)));
    if (!entry) break;
    tried.add(entry.id);
    const refused = await localRefusal(entry);
    let verdict = refused ? { action: 'drop', message: refused } : null;
    if (!verdict) {
      let res = null;
      try {
        res = await upload(entry);
      } catch {
        res = null;
      }
      verdict = uploadOutcome(res);
    }
    if (verdict.action === 'keep') {
      out.kept = verdict.message;
      // Ke belakang antrean (nextToUpload). Hanya entri yang masih ada (touch): logout di tengah putaran tidak
      // menghidupkannya lagi. Gagal → urutan saja yang tidak berubah.
      try { await store.touch(entry.id, { triedAt: now() }); } catch { /* urutan saja */ }
      break;
    }
    try {
      await store.del(entry.id);
      gone.add(entry.id);
    } catch { /* lihat di atas: tidak dobel */ }
    if (verdict.action === 'done') {
      out.items.push(verdict.item);
      try { onItem(verdict.item); } catch { /* tampilan saja */ }
    } else {
      out.dropped.push({ name: entry.name || '', message: verdict.message });
    }
  }
  if (out.kept) {
    // Daftar Hapus: isi kotak sekarang (kotak tidak terbaca → sisa putaran ini).
    let left;
    try {
      left = await store.all();
    } catch {
      left = entries.filter(e => !gone.has(e.id));
    }
    out.keptEntries = keptEntries(left);
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
//   finished → tombol Ke Transaksi (hanya mode kirim, pageFinished); empty → tidak ada kartu dan tidak ada pesan unggah;
//   retry    → tombol "Kirim lagi";
//   discard  → daftar entri yang tertahan (`keptList`, keptEntries) dengan tombol Hapus per entri: sesudah putaran mode
//              kirim berhenti dengan entri disimpan (keep), tanpa putaran berjalan.
export function pageView({
  mode = null, err = null, storeFailed = false, waiting = 0, items = [], handled = new Set(), running = false,
  polling = false, dropped = [], kept = null, keptList = [],
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
    // Tombol "Kirim lagi": putaran berhenti dengan entri yang disimpan (keep) atau entri ditahan, tanpa putaran berjalan.
    // Tanpa event `online` halaman tidak mencoba lagi sendiri (mis. 503 saat deploy, koneksi tersendat).
    retry: !running && ((mode === 'send' && !!kept) || (mode === 'hold' && waiting > 0)),
    discard: !running && mode === 'send' && !!kept && Array.isArray(keptList) && keptList.length > 0,
  };
}
