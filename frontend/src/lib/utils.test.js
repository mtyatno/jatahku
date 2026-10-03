import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatShortSigned } from './utils.js';

test('formatShortSigned menyingkat angka minus', () => {
  assert.equal(formatShortSigned(-1867174), '-Rp1.86jt');
  assert.equal(formatShortSigned(-150000), '-Rp150rb');
});

test('formatShortSigned sama dengan formatShort untuk angka positif', () => {
  assert.equal(formatShortSigned(3485000), 'Rp3.48jt');
  assert.equal(formatShortSigned(0), 'Rp0');
});
