// Config klien dari `GET /app/config` (paket mobile 1.3, ADR-M9/M10) dengan
// cache lokal. Aturannya: config TIDAK PERNAH memblokir aplikasi. Gagal ambil
// → pakai cache terakhir (berapa pun umurnya) → pakai DEFAULT_CONFIG, yang
// sama dengan perilaku web hari ini.

export const CONFIG_CACHE_KEY = 'jatahku_app_config';
export const CONFIG_TTL_MS = 60 * 60 * 1000; // ambil ulang paling cepat tiap jam

const UPDATE_STATUSES = ['ok', 'recommended', 'required'];
const SALES_MODES = ['none', 'store', 'web'];

export const DEFAULT_CONFIG = Object.freeze({
  config_version: 1,
  update: { status: 'ok', min_supported_version: null, latest_version: null, store_url: null },
  sales_mode: 'web',
  features: {},
  links: {},
  ota: { channel: null, bundle_url: null, bundle_version: null, min_native_version: null },
  error_reporting: { enabled: false, sample_rate: 0 },
});

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

// Respons server → bentuk yang aman dipakai komponen. Field tak dikenal dari
// server versi baru dibiarkan; nilai rusak diganti bawaan.
export function normalizeConfig(raw) {
  if (!isObj(raw)) return DEFAULT_CONFIG;
  const update = isObj(raw.update) ? raw.update : {};
  const features = {};
  if (isObj(raw.features)) {
    for (const [k, v] of Object.entries(raw.features)) if (typeof v === 'boolean') features[k] = v;
  }
  const er = isObj(raw.error_reporting) ? raw.error_reporting : {};
  return {
    ...raw,
    update: {
      ...DEFAULT_CONFIG.update,
      ...update,
      status: UPDATE_STATUSES.includes(update.status) ? update.status : 'ok',
    },
    sales_mode: SALES_MODES.includes(raw.sales_mode) ? raw.sales_mode : DEFAULT_CONFIG.sales_mode,
    features,
    links: isObj(raw.links) ? raw.links : {},
    ota: { ...DEFAULT_CONFIG.ota, ...(isObj(raw.ota) ? raw.ota : {}) },
    error_reporting: {
      enabled: er.enabled === true,
      sample_rate: Number.isFinite(er.sample_rate) ? Math.min(1, Math.max(0, er.sample_rate)) : 0,
    },
  };
}

function safeStorage(storage) {
  try {
    return storage ?? (typeof localStorage !== 'undefined' ? localStorage : null);
  } catch {
    return null;
  }
}

// Cache disimpan bersama identitas klien: setelah aplikasi diperbarui,
// status "perlu update" milik versi lama tidak boleh terbawa.
export function readCachedConfig({ storage, client } = {}) {
  const s = safeStorage(storage);
  if (!s) return null;
  try {
    const entry = JSON.parse(s.getItem(CONFIG_CACHE_KEY) || 'null');
    if (!isObj(entry) || !isObj(entry.config) || !Number.isFinite(entry.fetchedAt)) return null;
    if (client && entry.client !== client) return null;
    return { config: normalizeConfig(entry.config), fetchedAt: entry.fetchedAt };
  } catch {
    return null;
  }
}

export function writeCachedConfig(config, { storage, client, now = Date.now() } = {}) {
  const s = safeStorage(storage);
  if (!s) return;
  try {
    s.setItem(CONFIG_CACHE_KEY, JSON.stringify({ config, client: client ?? null, fetchedAt: now }));
  } catch {}
}

// Config untuk render pertama, tanpa jaringan.
export function initialConfig(opts = {}) {
  return readCachedConfig(opts)?.config ?? DEFAULT_CONFIG;
}

// fetchConfig: () => Promise<object|null> (null/throw = gagal).
export async function refreshAppConfig({ fetchConfig, storage, client, now = Date.now(), force = false } = {}) {
  const cached = readCachedConfig({ storage, client });
  if (!force && cached && now - cached.fetchedAt < CONFIG_TTL_MS) return cached.config;
  try {
    const raw = await fetchConfig();
    if (isObj(raw)) {
      const config = normalizeConfig(raw);
      writeCachedConfig(config, { storage, client, now });
      return config;
    }
  } catch {}
  return cached?.config ?? DEFAULT_CONFIG;
}

export function isUpdateRequired(config) {
  return config?.update?.status === 'required';
}
