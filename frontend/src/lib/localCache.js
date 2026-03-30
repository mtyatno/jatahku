// Persistent local cache for offline use
// Stores API responses in localStorage so data is available when offline

const PREFIX = 'jatahku_cache_';
const TTL = 24 * 60 * 60 * 1000; // 24 hours

export function saveCache(key, data) {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify({ data, ts: Date.now() }));
  } catch {}
}

export function loadCache(key) {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const { data, ts } = JSON.parse(raw);
    if (Date.now() - ts > TTL) return null;
    return data;
  } catch {
    return null;
  }
}

export function clearCache(key) {
  try { localStorage.removeItem(PREFIX + key); } catch {}
}
