// Persistent local cache for offline use
// Stores API responses in localStorage so data is available when offline.
// Isinya data keuangan (profil, saldo amplop, transaksi): dihapus semua saat logout (`clearAllCache`),
// supaya user lain di perangkat yang sama tidak pernah melihatnya lewat jalur offline.
// Kunci per ruang (Plugin R4): ruang selain ruang keluarga mendapat akhiran `@<id ruang>` (`ruangAktif.js`).
import { ruangCacheSuffix } from './ruangAktif.js';

const PREFIX = 'jatahku_cache_';
const TTL = 24 * 60 * 60 * 1000; // 24 hours

const store = (storage) => (storage === undefined ? globalThis.localStorage : storage);

export function saveCache(key, data, storage) {
  try {
    store(storage).setItem(PREFIX + key + ruangCacheSuffix(storage), JSON.stringify({ data, ts: Date.now() }));
  } catch {}
}

export function loadCache(key, storage) {
  try {
    const raw = store(storage).getItem(PREFIX + key + ruangCacheSuffix(storage));
    if (!raw) return null;
    const { data, ts } = JSON.parse(raw);
    if (Date.now() - ts > TTL) return null;
    return data;
  } catch {
    return null;
  }
}

export function clearCache(key, storage) {
  try { store(storage).removeItem(PREFIX + key + ruangCacheSuffix(storage)); } catch {}
}

// Saat logout: hapus semua cache Jatahku di perangkat ini (semua akun).
export function clearAllCache(storage) {
  try {
    const s = store(storage);
    const keys = [];
    for (let i = 0; i < (s?.length || 0); i++) {
      const k = s.key(i);
      if (k && k.startsWith(PREFIX)) keys.push(k);
    }
    keys.forEach(k => s.removeItem(k));
  } catch {}
}
