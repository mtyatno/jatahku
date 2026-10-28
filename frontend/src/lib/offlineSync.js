// Antrean transaksi offline — logika bersama app & service worker (tanpa DOM).
//
// Sinkron mengirim semua item yang menunggu SEKALI lewat POST /transactions/batch
// (maks CHUNK per kiriman), bukan satu request per transaksi: lebih ringan untuk
// server, dan kuota Basic memperlakukan satu sinkron sebagai satu input.
//
// Hasil per item:
//   tersimpan               → dihapus dari antrean
//   "sedang diproses"       → tetap menunggu (dicoba lagi pada sinkron berikutnya)
//   ditolak (dana kurang, kuota habis, amplop dikunci, …) → TIDAK dibuang:
//     ditandai `rejected` {message, at}, ditampilkan ke user untuk diperbaiki,
//     dicoba lagi, atau dihapus. Tidak dikirim ulang otomatis (tanpa beban berulang).
// Kiriman gagal / respons tidak jelas (offline, 401, 409, 5xx) → semua tetap menunggu
// dan sinkron berhenti sampai pemicu berikutnya (online lagi / app dibuka).

export const DB_NAME = 'jatahku-offline';
export const STORE = 'queue';
export const CHUNK = 50;

let dbPromise = null;

function openQueueDB() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = (e) => {
        e.target.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
      };
      req.onsuccess = (e) => resolve(e.target.result);
      req.onerror = (e) => { dbPromise = null; reject(e.target.error); };
    });
  }
  return dbPromise;
}

// Penyimpanan antrean di IndexedDB (app & service worker memakai DB yang sama).
export function idbStore() {
  const run = async (mode, fn) => {
    const db = await openQueueDB();
    return new Promise((resolve, reject) => {
      const req = fn(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  };
  return {
    all: () => run('readonly', s => s.getAll()),
    add: item => run('readwrite', s => s.add(item)),
    put: item => run('readwrite', s => s.put(item)),
    del: id => run('readwrite', s => s.delete(id)),
  };
}

export const isPending = item => !item.rejected;

// Item antrean → baris POST /transactions/batch. `receipt_item_id` (baris struk/bukti dari form Catat) ikut
// dikirim: tanpa itu bukti tidak diklaim (bisa tercatat dua kali) dan aturan tanggal dokumen server tidak berlaku.
export function toBatchItem(item) {
  return {
    envelope_id: item.envelope_id,
    amount: item.amount,
    description: item.description || 'Pengeluaran',
    source: item.source || 'webapp',
    is_private: !!item.is_private,
    ...(item.transaction_date ? { transaction_date: item.transaction_date } : {}),
    ...(item.raise_daily_limit ? { raise_daily_limit: true } : {}),
    ...(item.client_ref ? { client_ref: item.client_ref } : {}),
    ...(item.receipt_item_id ? { receipt_item_id: item.receipt_item_id } : {}),
  };
}

// Hasil satu kiriman batch → nasib tiap item. `invalid` = seluruh kiriman ditolak
// validasi (422): satu item rusak menggagalkan semuanya, jadi pemanggil memisahkannya.
export function classifyBatch(items, res) {
  const out = { done: [], keep: [], rejected: [], notice: null, invalid: false, failed: false };
  if (res && res.status === 422) {
    out.invalid = true;
    return out;
  }
  if (!res || !res.ok || !Array.isArray(res.data)) {
    out.failed = true;
    out.keep = items.map(it => it.id);
    return out;
  }
  const byIndex = new Map(res.data.map(r => [r.index, r]));
  items.forEach((it, i) => {
    const r = byIndex.get(i);
    if (!r) out.keep.push(it.id);
    else if (r.ok) out.done.push(it.id);
    else if (r.pending) out.keep.push(it.id);
    else out.rejected.push({ id: it.id, message: r.error || 'Ditolak server.' });
    if (r && r.quota_notice) out.notice = r.quota_notice;
  });
  return out;
}

// Kirim semua item yang menunggu. store: {all, put, del}; send(payloads) →
// {ok, status, data}; newRef() → kunci idempotensi baru.
export async function syncQueue({ store, send, newRef, now = () => Date.now() }) {
  const summary = { saved: 0, rejected: 0, kept: 0, notice: null };
  const pending = (await store.all()).filter(isPending);
  if (pending.length === 0) return summary;

  const valid = [];
  for (const it of pending) {
    if (!it.envelope_id || !(Number(it.amount) > 0)) {
      await store.put({ ...it, rejected: { message: 'Data transaksi tidak lengkap (amplop/nominal).', at: now() } });
      summary.rejected += 1;
      continue;
    }
    if (!it.client_ref) {
      // Antrean lama belum punya kunci: simpan dulu, supaya kirim ulang memakai
      // kunci yang sama dan tidak mencatat dua kali.
      it.client_ref = newRef();
      await store.put(it);
    }
    valid.push(it);
  }

  const apply = async (chunk, outcome) => {
    const byId = new Map(chunk.map(it => [it.id, it]));
    for (const id of outcome.done) { await store.del(id); summary.saved += 1; }
    for (const { id, message } of outcome.rejected) {
      await store.put({ ...byId.get(id), rejected: { message, at: now() } });
      summary.rejected += 1;
    }
    summary.kept += outcome.keep.length;
    if (outcome.notice) summary.notice = outcome.notice;
  };

  for (let i = 0; i < valid.length; i += CHUNK) {
    const chunk = valid.slice(i, i + CHUNK);
    const outcome = classifyBatch(chunk, await send(chunk.map(toBatchItem)));
    if (outcome.invalid) {
      // Pisahkan item yang membuat kiriman tidak valid: kirim satu per satu.
      let stopped = false;
      for (let j = 0; j < chunk.length; j += 1) {
        const it = chunk[j];
        const one = classifyBatch([it], await send([toBatchItem(it)]));
        if (one.invalid) one.rejected.push({ id: it.id, message: 'Data transaksi tidak valid.' });
        await apply([it], one);
        if (one.failed) {
          summary.kept += (chunk.length - j - 1) + (valid.length - (i + chunk.length));
          stopped = true;
          break;
        }
      }
      if (stopped) break;
      continue;
    }
    await apply(chunk, outcome);
    if (outcome.failed) {
      summary.kept += valid.length - (i + chunk.length); // sisa tidak dikirim sekarang
      break;
    }
  }
  return summary;
}
