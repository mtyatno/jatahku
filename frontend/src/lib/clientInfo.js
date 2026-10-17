// Identitas klien untuk header `X-Jatahku-Client: <platform>/<versi>/<build>`
// (ADR-M9, aturan mobile #3 di AGENTS.md). Nilainya ditanam saat build
// (vite.config.js): web = 'web' / versi package.json / 7 huruf commit.
// Build aplikasi mengisi JATAHKU_PLATFORM sendiri; komponen tidak pernah
// menebak platform.

export const CLIENT_HEADER = 'X-Jatahku-Client';

const PLATFORMS = ['web', 'android', 'ios'];
const VERSION_RE = /^\d{1,4}(\.\d{1,4}){0,2}$/;

function clean(value, re) {
  const s = String(value ?? '').trim();
  return re.test(s) ? s : '';
}

export function clientHeaderValue({ platform, version, build } = {}) {
  const p = PLATFORMS.includes(platform) ? platform : 'web';
  const v = clean(version, VERSION_RE) || '0.0.0';
  const b = clean(build, /^[0-9A-Za-z._-]{1,40}$/) || 'dev';
  return `${p}/${v}/${b}`;
}

/* global __APP_PLATFORM__, __APP_VERSION__, __APP_COMMIT__ */
export const CLIENT = {
  platform: typeof __APP_PLATFORM__ !== 'undefined' ? __APP_PLATFORM__ : 'web',
  version: typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : '0.0.0',
  build: typeof __APP_COMMIT__ !== 'undefined' && __APP_COMMIT__ !== 'unknown' ? __APP_COMMIT__.slice(0, 7) : 'dev',
};

export const CLIENT_HEADER_VALUE = clientHeaderValue(CLIENT);

// Header lain + identitas klien. Tidak menimpa header yang sudah diisi pemanggil.
export function withClientHeader(headers = {}) {
  return { [CLIENT_HEADER]: CLIENT_HEADER_VALUE, ...headers };
}
