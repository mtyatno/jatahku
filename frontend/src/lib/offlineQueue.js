// Antrean transaksi offline di sisi app. Logika sinkron dipakai bersama service
// worker (lihat offlineSync.js). Event `jatahku:offline-queue` memberi tahu UI
// setiap kali isi antrean berubah (masuk, tersinkron, dicoba lagi, dihapus).
// Tempat menyimpan antrean ditentukan lapisan native (web: IndexedDB bersama
// service worker; aplikasi: penyimpanan native, ADR-M11).
import { syncQueue, isPending, receiptItemIdsOf } from './offlineSync.js';
import { newRef } from './ref.js';
import { native } from '../native/index.js';

const store = native.queue.store();

function notify(detail) {
  try {
    window.dispatchEvent(new CustomEvent('jatahku:offline-queue', { detail }));
  } catch {
    // di luar browser (tes) — abaikan
  }
}

export async function enqueueTransaction(payload) {
  await store.add(native.queue.withAuth({ ...payload, client_ref: payload.client_ref || newRef(), queuedAt: Date.now() }));
  notify({ type: 'enqueued' });

  // Kirim walau app sudah ditutup (web: background sync service worker).
  await native.queue.requestBackgroundSync();
}

// Hasil sinkron yang dijalankan di latar (web: service worker). → fungsi pelepas.
export const onBackgroundSynced = (cb) => native.queue.onBackgroundSynced(cb);

// Menunggu dikirim (tidak termasuk yang ditolak).
export async function getPendingCount() {
  return (await store.all()).filter(isPending).length;
}

// Id item Kotak Struk di antrean, menunggu maupun ditolak (offlineSync.receiptItemIdsOf). Gagal membaca → Set kosong:
// form Catat dan /bagikan tidak pernah tertahan oleh antrean yang tidak terbaca.
export async function queuedReceiptItemIds() {
  try {
    return receiptItemIdsOf(await store.all());
  } catch {
    return new Set();
  }
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
