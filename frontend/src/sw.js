// Custom Service Worker — Jatahku PWA
import { idbStore, syncQueue } from './lib/offlineSync.js';
import { newRef } from './lib/ref.js';
// vite-plugin-pwa (injectManifest) will replace self.__WB_MANIFEST

const manifest = self.__WB_MANIFEST || [];

// Cache name is derived from the precache manifest so it changes on every
// deploy (asset URLs/revisions are content-hashed). A new name means the
// `activate` handler purges ALL previous caches, so users can never be
// stuck on a stale bundle after a deploy.
function manifestVersion(entries) {
  const str = entries
    .map((e) => (typeof e === 'string' ? e : `${e.url}:${e.revision || ''}`))
    .join('|');
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (Math.imul(h, 31) + str.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}
const CACHE = `jatahku-${manifestVersion(manifest)}`;

// Install: pre-cache app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(manifest.map((e) => (typeof e === 'string' ? e : e.url))))
      .then(() => self.skipWaiting())
  );
});

// Activate: remove old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET' || url.protocol === 'chrome-extension:') return;

  // API: bypass service worker entirely — let browser handle directly
  if (url.hostname === 'api.jatahku.com') return;

  // SPA navigation: NetworkFirst — fresh index.html when online, cached fallback offline
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE).then((c) => c.put('/index.html', clone));
          return res;
        })
        .catch(() => caches.match('/index.html'))
    );
    return;
  }

  // Assets (JS, CSS, images): CacheFirst
  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});

// ── Background Sync ──────────────────────────────────────────────
// Antrean transaksi offline dikirim SEKALI lewat /transactions/batch (logika
// bersama app: lib/offlineSync.js). Transaksi yang ditolak tidak dibuang: ditandai
// dan ditampilkan di app untuk diperbaiki / dicoba lagi / dihapus.

const API = 'https://api.jatahku.com';

self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-transactions') {
    event.waitUntil(syncPendingTransactions());
  }
});

async function syncPendingTransactions() {
  const store = idbStore();
  const items = await store.all();
  // Service worker tidak bisa membaca localStorage: pakai token antrean terbaru.
  const token = items
    .filter(it => it.token)
    .sort((a, b) => (b.queuedAt || 0) - (a.queuedAt || 0))[0]?.token;
  if (!token) return;

  const send = async (payloads) => {
    try {
      const res = await fetch(`${API}/transactions/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ items: payloads }),
      });
      const data = await res.json().catch(() => null);
      return { ok: res.ok && Array.isArray(data), status: res.status, data: Array.isArray(data) ? data : (data || {}) };
    } catch {
      return { ok: false, status: 0, data: [] };
    }
  };

  const summary = await syncQueue({ store, send, newRef });
  const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  clients.forEach(c => c.postMessage({ type: 'jatahku:offline-synced', summary }));
  // Masih ada yang menunggu (server sibuk / token kedaluwarsa) → minta browser mencoba lagi nanti.
  if (summary.kept > 0) throw new Error('offline queue: retry later');
}
