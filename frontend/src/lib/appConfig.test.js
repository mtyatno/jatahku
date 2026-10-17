import test from 'node:test';
import assert from 'node:assert/strict';
import {
  CONFIG_CACHE_KEY, CONFIG_TTL_MS, DEFAULT_CONFIG, initialConfig, isUpdateRequired,
  normalizeConfig, readCachedConfig, refreshAppConfig,
} from './appConfig.js';

function memStorage(initial = {}) {
  const store = { ...initial };
  return {
    store,
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
  };
}

const SERVER = {
  config_version: 1,
  update: { status: 'ok', min_supported_version: null, latest_version: null, store_url: null },
  sales_mode: 'web',
  features: { receipt_inbox: false, push: true },
  links: { privacy: 'https://jatahku.com/privacy.html' },
  ota: { channel: null },
  error_reporting: { enabled: true, sample_rate: 1 },
};

test('default config = perilaku web hari ini', () => {
  assert.equal(DEFAULT_CONFIG.sales_mode, 'web');
  assert.equal(isUpdateRequired(DEFAULT_CONFIG), false);
  assert.equal(DEFAULT_CONFIG.error_reporting.enabled, false);
});

test('normalizeConfig membuang nilai rusak dan menyimpan field baru', () => {
  const c = normalizeConfig({
    update: { status: 'meledak' }, sales_mode: 'gratis',
    features: { a: true, b: 'ya' }, error_reporting: { enabled: true, sample_rate: 7 }, field_baru: 1,
  });
  assert.equal(c.update.status, 'ok');
  assert.equal(c.sales_mode, 'web');
  assert.deepEqual(c.features, { a: true });
  assert.equal(c.error_reporting.sample_rate, 1);
  assert.equal(c.field_baru, 1);
  assert.equal(normalizeConfig(null), DEFAULT_CONFIG);
  assert.equal(normalizeConfig([1]), DEFAULT_CONFIG);
});

test('refresh mengambil dan menyimpan cache', async () => {
  const storage = memStorage();
  const c = await refreshAppConfig({ fetchConfig: async () => SERVER, storage, client: 'web/0.1.0/abc', now: 1000 });
  assert.equal(c.features.push, true);
  const cached = readCachedConfig({ storage, client: 'web/0.1.0/abc' });
  assert.equal(cached.fetchedAt, 1000);
  assert.equal(initialConfig({ storage, client: 'web/0.1.0/abc' }).features.push, true);
});

test('cache segar tidak memanggil jaringan; cache basi diambil ulang', async () => {
  const storage = memStorage();
  let calls = 0;
  const fetchConfig = async () => { calls += 1; return SERVER; };
  await refreshAppConfig({ fetchConfig, storage, now: 0 });
  await refreshAppConfig({ fetchConfig, storage, now: CONFIG_TTL_MS - 1 });
  assert.equal(calls, 1);
  await refreshAppConfig({ fetchConfig, storage, now: CONFIG_TTL_MS });
  assert.equal(calls, 2);
  await refreshAppConfig({ fetchConfig, storage, now: CONFIG_TTL_MS + 1, force: true });
  assert.equal(calls, 3);
});

test('gagal ambil → cache lama berapa pun umurnya → bawaan', async () => {
  const storage = memStorage();
  await refreshAppConfig({ fetchConfig: async () => SERVER, storage, now: 0 });
  const offline = await refreshAppConfig({ fetchConfig: async () => { throw new Error('offline'); }, storage, now: 10 * CONFIG_TTL_MS });
  assert.equal(offline.features.push, true);
  const kosong = await refreshAppConfig({ fetchConfig: async () => null, storage: memStorage(), now: 0 });
  assert.equal(kosong, DEFAULT_CONFIG);
});

test('cache dari versi klien lain diabaikan (status perlu update tidak terbawa)', async () => {
  const storage = memStorage();
  const required = { ...SERVER, update: { status: 'required', store_url: 'https://play.google.com/x' } };
  await refreshAppConfig({ fetchConfig: async () => required, storage, client: 'android/1.0.0/1', now: 0 });
  assert.equal(isUpdateRequired(initialConfig({ storage, client: 'android/1.0.0/1' })), true);
  assert.equal(isUpdateRequired(initialConfig({ storage, client: 'android/1.1.0/2' })), false);
});

test('cache rusak atau storage melempar tidak menjatuhkan aplikasi', async () => {
  assert.equal(readCachedConfig({ storage: memStorage({ [CONFIG_CACHE_KEY]: '{rusak' }) }), null);
  const throwing = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.equal(initialConfig({ storage: throwing }), DEFAULT_CONFIG);
  const c = await refreshAppConfig({ fetchConfig: async () => SERVER, storage: throwing, now: 0 });
  assert.equal(c.features.push, true);
});
