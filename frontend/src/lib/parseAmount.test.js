import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseMultiExpense, parseAmount } from './parseAmount.js';

// ── pemisah koma setelah angka (transkrip suara: "35.000, gojek 20.000") ──
test('parseMultiExpense: koma pemisah langsung setelah angka (tanpa spasi) tetap split', () => {
  const items = parseMultiExpense('kopi 15000, gojek 20 ribu');
  assert.ok(items, 'harus terpecah');
  assert.equal(items.length, 2);
  assert.equal(items[0].amount, 15000);
  assert.equal(items[0].description, 'kopi');
  assert.equal(items[1].amount, 20000);
  assert.equal(items[1].description, 'gojek');
});

test('parseMultiExpense: angka ribuan titik + koma pemisah (format umum Whisper id-ID)', () => {
  const items = parseMultiExpense('kopi 35.000, gojek 20.000');
  assert.ok(items, 'harus terpecah');
  assert.equal(items.length, 2);
  assert.equal(items[0].amount, 35000);
  assert.equal(items[0].description, 'kopi');
  assert.equal(items[1].amount, 20000);
  assert.equal(items[1].description, 'gojek');
});

test('parseMultiExpense: campuran angka titik + kata, 3 item', () => {
  const items = parseMultiExpense('nasi 12.000, kopi 8 ribu, gojek 15.000');
  assert.ok(items, 'harus terpecah');
  assert.equal(items.length, 3);
  assert.deepEqual(items.map(i => i.amount), [12000, 8000, 15000]);
  assert.equal(items[0].description, 'nasi');
  assert.equal(items[1].description, 'kopi');
  assert.equal(items[2].description, 'gojek');
});

// ── koma desimal tetap dilindungi ──
test('parseMultiExpense: koma desimal "1,5" tidak memecah item', () => {
  // koma di antara angka = desimal, bukan pemisah item
  assert.equal(parseMultiExpense('telor 1,5'), null);
  assert.ok(parseAmount('telor 1,5'), 'tetap ter-parse sebagai satu item');
});

// ── regresi bentuk yang sudah jalan ──
test('parseMultiExpense: regresi koma setelah kata ("35 ribu, gojek")', () => {
  const items = parseMultiExpense('kopi 35 ribu, gojek 20 ribu');
  assert.ok(items);
  assert.equal(items.length, 2);
  assert.deepEqual(items.map(i => i.amount), [35000, 20000]);
});

test('parseMultiExpense: regresi placeholder textarea ("Rp5.000, gojek 12000")', () => {
  const items = parseMultiExpense('air mineral Rp5.000, gojek 12000');
  assert.ok(items);
  assert.equal(items.length, 2);
  assert.deepEqual(items.map(i => i.amount), [5000, 12000]);
});
