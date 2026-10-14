// Antrean transaksi offline di sisi app. Logika sinkron dipakai bersama service
// worker (lihat offlineSync.js). Event `jatahku:offline-queue` memberi tahu UI
// setiap kali isi antrean berubah (masuk, tersinkron, dicoba lagi, dihapus).
import { idbStore, syncQueue, isPending } from './offlineSync.js';
import { newRef } from './ref.js';

const store = idbStore();

function notify(detail) {
  try {
    window.dispatchEvent(new CustomEvent('jatahku:offline-queue', { detail }));
  } catch {
    // di luar browser (tes) — abaikan
  }
}

export async function enqueueTransaction(payload) {
  const token = localStorage.getItem('jatahku_token');
  await store.add({ ...payload, client_ref: payload.client_ref || newRef(), token, queuedAt: Date.now() });
  notify({ type: 'enqueued' });

  // Background sync: service worker bisa mengirim walau app sudah ditutup.
  if ('serviceWorker' in navigator && 'SyncManager' in window) {
    try {
      const reg = await navigator.serviceWorker.ready;
      await reg.sync.register('sync-transactions');
    } catch {
      // tidak didukung / ditolak — app yang menyinkronkan saat online lagi
    }
  }
}

// Menunggu dikirim (tidak termasuk yang ditolak).
export async function getPendingCount() {
  return (await store.all()).filter(isPending).length;
}

// Ditolak saat sinkron — menunggu keputusan user.
export async function getRejected() {
  return (await store.all()).filter(it => !isPending(it));
}

let running = null;

// Kirim antrean sekarang (satu kiriman batch). send(payloads) → {ok, status, data}.
// Satu sinkron berjalan pada satu waktu.
export function syncNow(send) {
  if (running) return running;
  running = (async () => {
    try {
      const summary = await syncQueue({ store, send, newRef });
      if (summary.saved > 0) {
        try { window.dispatchEvent(new CustomEvent('jatahku:txn-added')); } catch { /* tes */ }
      }
      notify({ type: 'synced', summary });
      return summary;
    } finally {
      running = null;
    }
  })();
  return running;
}

// Coba lagi transaksi yang ditolak (opsional dengan perubahan, mis. amplop lain
// atau raise_daily_limit). Kunci idempotensinya tetap.
export async function retryRejected(id, patch = {}) {
  const item = (await store.all()).find(it => it.id === id);
  if (!item) return;
  const { rejected: _rejected, ...rest } = item;
  await store.put({ ...rest, ...patch });
  notify({ type: 'retry' });
}

export async function discardRejected(id) {
  await store.del(id);
  notify({ type: 'discarded' });
}
