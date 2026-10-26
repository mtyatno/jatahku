// Implementasi web lapisan native (ADR-M6, mobile 1.5). Satu-satunya tempat
// kode web menyentuh API khusus browser yang di aplikasi akan berbeda: token,
// antrean offline, simpan/bagikan file, cetak, tautan luar, service worker,
// prompt instal. Antarmukanya dijelaskan di index.js; capacitor.js (paket 3.2)
// mengikuti bentuk yang sama.
//
// createWebNative() menerima global browser sebagai parameter supaya bisa diuji
// dengan tiruan (node --test); `native` di index.js memakai global sungguhan.
import { idbStore } from '../lib/offlineSync.js';
import { CLIENT } from '../lib/clientInfo.js';

export const TOKEN_KEY = 'jatahku_token';
export const REFRESH_KEY = 'jatahku_refresh';
export const PROD_API_URL = 'https://api.jatahku.com';
// Dev: proxy Vite (vite.config.js) meneruskan /api ke server.
export const DEV_API_URL = '/api';
// Penanda "kamera sedang terbuka" (lihat camera di bawah). Dianggap basi setelah 3 menit.
export const CAMERA_MARK_KEY = 'jatahku_camera_open';
export const CAMERA_MARK_MAX_MS = 180000;

export function createWebNative({
  window: win = globalThis.window,
  document: doc = globalThis.document,
  navigator: nav = globalThis.navigator,
  storage = globalThis.localStorage,
  prod = false,
  queueStore = null,
  now = () => Date.now(),
} = {}) {
  // ── Token ────────────────────────────────────────────────────────────────
  // Web: localStorage, kunci sama seperti sebelum 1.5 supaya user tetap login.
  // Nilai juga dipegang di memori: bila storage diblokir, sesi tetap jalan
  // selama halaman terbuka (seperti ApiClient sebelum 1.5).
  const mem = {};
  const read = (key) => {
    if (!(key in mem)) {
      try { mem[key] = storage?.getItem(key) || null; } catch { mem[key] = null; }
    }
    return mem[key];
  };
  const write = (key, value) => {
    mem[key] = value || null;
    try {
      if (value) storage?.setItem(key, value);
      else storage?.removeItem(key);
    } catch { /* storage diblokir: token hanya hidup di memori halaman ini */ }
  };

  const tokens = {
    getAccess: () => read(TOKEN_KEY),
    setAccess: (t) => write(TOKEN_KEY, t),
    getRefresh: () => read(REFRESH_KEY),
    setRefresh: (t) => write(REFRESH_KEY, t),
  };

  // ── Antrean offline ──────────────────────────────────────────────────────
  // Web: IndexedDB, dipakai bersama service worker. Item membawa token karena
  // service worker mengirim antrean saat app tertutup (background sync).
  let store = queueStore;
  const queue = {
    store: () => (store ||= idbStore()),
    withAuth: (item) => ({ ...item, token: tokens.getAccess() }),
    async requestBackgroundSync() {
      if (!nav || !('serviceWorker' in nav) || !win || !('SyncManager' in win)) return;
      try {
        const reg = await nav.serviceWorker.ready;
        await reg.sync.register('sync-transactions');
      } catch {
        // tidak didukung / ditolak — app yang menyinkronkan saat online lagi
      }
    },
    // Hasil sinkron yang dijalankan service worker. → fungsi pelepas.
    onBackgroundSynced(cb) {
      const sw = nav?.serviceWorker;
      if (!sw?.addEventListener) return () => {};
      const onMessage = (e) => {
        if (e.data?.type === 'jatahku:offline-synced') cb(e.data.summary || {});
      };
      sw.addEventListener('message', onMessage);
      return () => sw.removeEventListener?.('message', onMessage);
    },
  };

  // ── File ─────────────────────────────────────────────────────────────────
  const files = {
    // Simpan Blob ke perangkat (web: unduhan browser).
    async save(blob, filename) {
      const url = win.URL.createObjectURL(blob);
      const a = doc.createElement('a');
      a.href = url;
      a.download = filename;
      doc.body.appendChild(a);
      a.click();
      doc.body.removeChild(a);
      // Dicabut belakangan: beberapa browser membaca URL setelah click() selesai.
      win.setTimeout(() => win.URL.revokeObjectURL(url), 1000);
    },
    // Bagikan file lewat lembar bagikan sistem; tanpa dukungan → simpan saja.
    async share(blob, filename, { title } = {}) {
      const FileCtor = win?.File;
      if (FileCtor && typeof nav?.share === 'function' && typeof nav?.canShare === 'function') {
        const file = new FileCtor([blob], filename, { type: blob.type });
        if (nav.canShare({ files: [file] })) {
          try {
            await nav.share({ files: [file], ...(title ? { title } : {}) });
            return 'shared';
          } catch (e) {
            if (e?.name === 'AbortError') return 'cancelled';
          }
        }
      }
      await files.save(blob, filename);
      return 'saved';
    },
  };

  // ── Cetak ────────────────────────────────────────────────────────────────
  // Web: dialog cetak browser untuk PDF yang sudah tampil di iframe. `url`
  // (blob URL PDF) dipakai implementasi aplikasi, yang mencetak lewat plugin.
  const print = {
    pdf({ frame } = {}) {
      const w = frame?.contentWindow;
      if (!w) return;
      w.focus();
      w.print();
    },
  };

  // ── Tautan luar ──────────────────────────────────────────────────────────
  // Dengan `event` (klik <a target=_blank>): web membiarkan browser membuka
  // tautannya; aplikasi akan mencegahnya dan membuka lewat sistem. Tanpa event
  // (dibuka dari kode): tab baru.
  function openExternal(url, event) {
    if (event) return;
    win?.open(url, '_blank', 'noopener,noreferrer');
  }
  // onClick pemanggil jalan lebih dulu dan boleh membatalkan (preventDefault).
  // appUrl: skema aplikasi (mis. tg://) yang dicoba juga, supaya aplikasinya
  // langsung terbuka bila terpasang; halaman tidak berpindah.
  const externalLinkProps = (url, onClick, { appUrl } = {}) => ({
    href: url,
    target: '_blank',
    rel: 'noopener noreferrer',
    onClick: (e) => {
      onClick?.(e);
      if (e?.defaultPrevented) return;
      if (appUrl) {
        const a = doc.createElement('a');
        a.href = appUrl;
        doc.body.appendChild(a);
        a.click();
        doc.body.removeChild(a);
      }
      openExternal(url, e);
    },
  });

  // ── Kamera & galeri ──────────────────────────────────────────────────────
  // Web: <input type=file>. click() HARUS dipanggil sinkron dari handler
  // ketukan (sebelum await apa pun) — Safari iPhone menolak membuka kamera /
  // pemilih file dari tempat lain. Karena itu openPicker() tidak async: Promise
  // dibuat dan input diklik di dalam satu panggilan sinkron.
  //
  // Penanda: di HP Android RAM kecil, OS bisa mematikan PWA saat aplikasi
  // kamera terbuka. Penanda (waktu buka) ditulis sebelum kamera dibuka dan
  // dihapus begitu hasilnya sampai; recover() di app berikutnya yang menemukan
  // penanda masih baru tahu bahwa fotonya tidak sampai (lost).
  // Batasan yang diterima: browser tanpa event `cancel` pada <input type=file> (Chrome/Samsung
  // Internet lama, Safari iOS) tidak menghapus penanda saat kamera dibatalkan, jadi membuka
  // ulang app dalam 3 menit bisa menampilkan toast "foto hilang" yang keliru.
  const markWrite = () => {
    try { storage?.setItem(CAMERA_MARK_KEY, String(now())); } catch { /* storage diblokir: tanpa penanda */ }
  };
  const markClear = () => {
    try { storage?.removeItem(CAMERA_MARK_KEY); } catch { /* storage diblokir */ }
  };
  const markRead = () => {
    try { return storage?.getItem(CAMERA_MARK_KEY) ?? null; } catch { return null; }
  };

  let pendingCamera = null; // selesaikan(null) untuk input yang belum selesai
  function openPicker({ capture }) {
    // Satu input pada satu waktu: yang lama dilepas dan dijawab null.
    pendingCamera?.(null);
    const input = doc.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.style.display = 'none';
    if (capture) input.setAttribute('capture', 'environment');
    return new Promise((resolve) => {
      let done = false;
      const finish = (file) => {
        if (done) return;
        done = true;
        if (pendingCamera === finish) pendingCamera = null;
        try { doc.body.removeChild(input); } catch { /* sudah terlepas */ }
        markClear();
        resolve(file);
      };
      pendingCamera = finish;
      markWrite();
      doc.body.appendChild(input);
      input.addEventListener('change', () => finish(input.files?.[0] ?? null));
      input.addEventListener('cancel', () => finish(null));
      input.click();
    });
  }

  const camera = {
    // Foto dari kamera belakang → File | null (dibatalkan).
    takePhoto: () => openPicker({ capture: true }),
    // Foto dari galeri/berkas → File | null (dibatalkan).
    pickPhoto: () => openPicker({ capture: false }),
    // Dipanggil sekali saat app dibuka. Web tidak bisa memulihkan file yang
    // hilang; lost = true bila kamera baru saja dibuka dan hasilnya tak sampai.
    async recover() {
      const mark = markRead();
      markClear();
      return { file: null, lost: mark != null && now() - Number(mark) < CAMERA_MARK_MAX_MS };
    },
  };

  // ── Info platform ────────────────────────────────────────────────────────
  const platform = {
    name: CLIENT.platform,
    isNative: false,
    apiUrl: prod ? PROD_API_URL : DEV_API_URL,
  };

  // ── PWA: service worker & prompt instal (hanya web) ──────────────────────
  function registerServiceWorker() {
    if (!nav || !('serviceWorker' in nav)) return;
    // Muat ulang begitu service worker baru mengambil alih, supaya user selalu
    // mendapat versi terbaru tanpa hard refresh.
    nav.serviceWorker.addEventListener('controllerchange', () => {
      win.location.reload();
    });
    win.addEventListener('load', () => {
      nav.serviceWorker
        .register('/sw.js', { scope: '/', updateViaCache: 'none' })
        .then((reg) => {
          reg.update();
          doc.addEventListener('visibilitychange', () => {
            if (doc.visibilityState === 'visible') reg.update();
          });
        })
        .catch((err) => {
          console.error('Service worker registration failed:', err);
        });
    });
  }

  // cb(prompt) saat browser menawarkan instal; prompt.prompt() menampilkan
  // dialognya, prompt.userChoice → {outcome}. → fungsi pelepas.
  function onInstallPrompt(cb) {
    if (!win?.addEventListener) return () => {};
    const handler = (e) => {
      e.preventDefault();
      cb(e);
    };
    win.addEventListener('beforeinstallprompt', handler);
    return () => win.removeEventListener('beforeinstallprompt', handler);
  }

  // Dipanggil sekali sebelum UI dirender (main.jsx). Web tidak perlu menunggu
  // apa pun; aplikasi memuat token dari Keystore/Keychain di sini.
  async function init() {
    registerServiceWorker();
  }

  return { init, platform, tokens, queue, files, camera, print, openExternal, externalLinkProps, onInstallPrompt };
}
