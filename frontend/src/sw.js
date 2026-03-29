// Custom Service Worker — Jatahku PWA
// vite-plugin-pwa (injectManifest) will replace self.__WB_MANIFEST

const CACHE = 'jatahku-v1';
const manifest = self.__WB_MANIFEST || [];

// Install: pre-cache app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) =>
      cache.addAll(manifest.map((e) => (typeof e === 'string' ? e : e.url)))
    ).then(() => self.skipWaiting())
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

// Fetch: NetworkFirst for API, CacheFirst for assets
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET and chrome-extension
  if (request.method !== 'GET' || url.protocol === 'chrome-extension:') return;

  if (url.hostname === 'api.jatahku.com') {
    // API: try network, fall back to cache
    event.respondWith(
      fetch(request)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE).then((c) => c.put(request, clone));
          return res;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // App shell + assets: cache first
  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request))
  );
});

// ── Background Sync ──────────────────────────────────────────────
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-transactions') {
    event.waitUntil(syncPendingTransactions());
  }
});

function openQueueDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open('jatahku-offline', 1);
    req.onupgradeneeded = (e) =>
      e.target.result.createObjectStore('queue', { keyPath: 'id', autoIncrement: true });
    req.onsuccess = (e) => resolve(e.target.result);
    req.onerror = (e) => reject(e.target.error);
  });
}

async function syncPendingTransactions() {
  const db = await openQueueDB();

  const items = await new Promise((resolve, reject) => {
    const tx = db.transaction('queue', 'readonly');
    const req = tx.objectStore('queue').getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  for (const item of items) {
    const res = await fetch('https://api.jatahku.com/transactions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${item.token}`,
      },
      body: JSON.stringify({
        envelope_id: item.envelope_id,
        amount: item.amount,
        description: item.description,
        source: item.source,
      }),
    });

    if (res.ok) {
      await new Promise((resolve, reject) => {
        const tx = db.transaction('queue', 'readwrite');
        const req = tx.objectStore('queue').delete(item.id);
        req.onsuccess = resolve;
        req.onerror = () => reject(req.error);
      });
    }
    // If not ok (e.g. 401), leave in queue — don't throw so other items still process
  }
}
