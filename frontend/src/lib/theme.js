export const STORAGE_KEY = 'jatahku_theme';
export const VALID_COLORS = ['hijau', 'laut', 'senja'];
export const VALID_MODES = ['light', 'dark'];
export const DEFAULT = { color: 'hijau', mode: 'dark' };

export function readStorage(storage = globalThis.localStorage) {
  try {
    if (!storage) return DEFAULT;
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT;
    const p = JSON.parse(raw);
    return {
      color: VALID_COLORS.includes(p.color) ? p.color : DEFAULT.color,
      mode: VALID_MODES.includes(p.mode) ? p.mode : DEFAULT.mode,
    };
  } catch {
    return DEFAULT;
  }
}
