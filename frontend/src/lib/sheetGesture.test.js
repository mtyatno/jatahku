import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DISMISS_DISTANCE, dragOffset, shouldDismiss } from './sheetGesture.js';

test('tarik jauh menutup, tarik pendek pelan kembali', () => {
  assert.equal(shouldDismiss(DISMISS_DISTANCE, 1000), true);
  assert.equal(shouldDismiss(60, 400), false);
});

test('kibasan cepat menutup walau jaraknya pendek', () => {
  assert.equal(shouldDismiss(50, 60), true);   // ±0.83 px/ms
  assert.equal(shouldDismiss(20, 10), false);  // terlalu pendek — anggap getaran jari
});

test('tarik ke atas tidak menggeser sheet', () => {
  assert.equal(dragOffset(-40), 0);
  assert.equal(dragOffset(35), 35);
  assert.equal(shouldDismiss(-200, 50), false);
});
