import test from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULT, readStorage, STORAGE_KEY } from './theme.js';

test('theme default mode is dark', () => {
  assert.equal(DEFAULT.mode, 'dark');
  assert.equal(DEFAULT.color, 'hijau');
});

test('readStorage returns DEFAULT when localStorage is empty', () => {
  const store = {};
  globalThis.localStorage = {
    getItem: (k) => store[k] || null,
    setItem: (k, v) => { store[k] = String(v); },
  };

  const theme = readStorage();
  assert.deepEqual(theme, { color: 'hijau', mode: 'dark' });
});

test('readStorage respects user choice when light mode is saved', () => {
  const store = {
    [STORAGE_KEY]: JSON.stringify({ color: 'laut', mode: 'light' }),
  };
  globalThis.localStorage = {
    getItem: (k) => store[k] || null,
    setItem: (k, v) => { store[k] = String(v); },
  };

  const theme = readStorage();
  assert.deepEqual(theme, { color: 'laut', mode: 'light' });
});

test('readStorage falls back to dark mode for invalid mode', () => {
  const store = {
    [STORAGE_KEY]: JSON.stringify({ color: 'hijau', mode: 'invalid' }),
  };
  globalThis.localStorage = {
    getItem: (k) => store[k] || null,
    setItem: (k, v) => { store[k] = String(v); },
  };

  const theme = readStorage();
  assert.deepEqual(theme, { color: 'hijau', mode: 'dark' });
});
