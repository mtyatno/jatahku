import { test } from 'node:test';
import assert from 'node:assert/strict';
import { dragHeight, keyboardInset, pickSnap, sheetHeights } from './sheetGesture.js';

test('setengah layar mengikuti tinggi HP masing-masing', () => {
  assert.deepEqual(sheetHeights(844, 47), { full: 785, half: 422 });   // iPhone 14
  assert.deepEqual(sheetHeights(640, 0), { full: 628, half: 320 });    // HP layar pendek
  assert.deepEqual(sheetHeights(915, 24), { full: 879, half: 458 });   // Android tinggi
});

test('saat keyboard terbuka, tinggi penuh = ruang di atas keyboard', () => {
  const { full, half } = sheetHeights(844, 47, 844 - 336);
  assert.equal(full, 844 - 336 - 47 - 12);
  assert.ok(half <= full);
});

test('deteksi keyboard dari visual viewport', () => {
  assert.equal(keyboardInset(844, 508, 0), 336);
  assert.equal(keyboardInset(844, 800, 0), 0);    // bilah alamat browser, bukan keyboard
  assert.equal(keyboardInset(844, 508, 120), 216); // iOS menggeser viewport
  assert.equal(keyboardInset(844, undefined), 0);
});

const H = { full: 785, half: 422 };

test('tarik pelan: berhenti di posisi terdekat', () => {
  assert.equal(pickSnap(700, 0, H), 'full');
  assert.equal(pickSnap(500, 0, H), 'half');
  assert.equal(pickSnap(150, 0, H), 'closed');
});

test('kibas ke atas dari setengah → penuh; kibas ke bawah → tutup', () => {
  assert.equal(pickSnap(480, 1.5, H), 'full');
  assert.equal(pickSnap(380, -1.5, H), 'closed');
  assert.equal(pickSnap(700, -1.2, H), 'half'); // dari penuh, kibas sedang → setengah
});

test('tarik melewati penuh ditahan seperti karet', () => {
  assert.equal(dragHeight(422, -100, 785), 522);
  assert.equal(dragHeight(785, -100, 785), 805);
  assert.equal(dragHeight(422, 600, 785), 0);
});
