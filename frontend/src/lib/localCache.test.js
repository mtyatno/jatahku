import { test } from 'node:test';
import assert from 'node:assert/strict';
import { saveCache, loadCache, clearCache, clearAllCache } from './localCache.js';

function memStorage(init = {}) {
  const s = { ...init };
  return {
    getItem: k => (k in s ? s[k] : null),
    setItem: (k, v) => { s[k] = String(v); },
    removeItem: k => { delete s[k]; },
    key: i => Object.keys(s)[i] ?? null,
    get length() { return Object.keys(s).length; },
    dump: () => s,
  };
}

test('simpan, baca, hapus satu kunci', () => {
  const st = memStorage();
  saveCache('envelopes', [{ id: 1 }], st);
  assert.deepEqual(loadCache('envelopes', st), [{ id: 1 }]);
  clearCache('envelopes', st);
  assert.equal(loadCache('envelopes', st), null);
});

test('cache kedaluwarsa setelah 24 jam', () => {
  const st = memStorage({ jatahku_cache_me: JSON.stringify({ data: { id: 'a' }, ts: Date.now() - 25 * 3600 * 1000 }) });
  assert.equal(loadCache('me', st), null);
});

test('logout menghapus semua cache Jatahku, kunci lain tetap', () => {
  const st = memStorage({ theme: 'dark', jatahku_chat_u1: '[]' });
  saveCache('me', { name: 'A' }, st);
  saveCache('envelopes', [1], st);
  saveCache('beranda:u1', { data: {} }, st);
  clearAllCache(st);
  assert.deepEqual(Object.keys(st.dump()).sort(), ['jatahku_chat_u1', 'theme']);
});

test('storage rusak tidak melempar', () => {
  const rusak = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); }, removeItem() { throw new Error('x'); },
    key() { throw new Error('x'); }, get length() { throw new Error('x'); } };
  saveCache('a', 1, rusak);
  assert.equal(loadCache('a', rusak), null);
  clearAllCache(rusak);
  clearAllCache(null);
});
