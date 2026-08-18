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

// ── pemisah campuran (koma + newline) dalam satu input ──
test('parseMultiExpense: koma di baris pertama + item newline di baris kedua', () => {
  const items = parseMultiExpense(
    'mobil Rp. 400.000, tagihan Google Rp. 85.000, bendera Rp. 75.000.\nBayar tukang Rp 1.400.000');
  assert.ok(items, 'harus terpecah');
  assert.equal(items.length, 4);
  assert.deepEqual(items.map(i => i.amount), [400000, 85000, 75000, 1400000]);
  assert.equal(items[0].description, 'mobil');
  assert.equal(items[1].description, 'tagihan Google');
  assert.equal(items[3].description, 'Bayar tukang');
});

// ── regresi: kata sambung dalam deskripsi tidak boleh memecah item ──
test('parseMultiExpense: "dan" dalam deskripsi tidak memecah item tanpa jumlah', () => {
  const items = parseMultiExpense('nasi goreng 15 ribu, bakso dan es teh 10 ribu');
  assert.ok(items);
  assert.equal(items.length, 2);
  assert.deepEqual(items.map(i => i.amount), [15000, 10000]);
  assert.equal(items[1].description, 'bakso dan es teh');
});

test('parseMultiExpense: "dan" sebagai pemisah saat kedua sisi ada jumlah', () => {
  const items = parseMultiExpense('kopi 35 ribu dan gojek 20 ribu, makan 25 ribu');
  assert.ok(items);
  assert.equal(items.length, 3);
  assert.deepEqual(items.map(i => i.amount), [35000, 20000, 25000]);
  assert.deepEqual(items.map(i => i.description), ['kopi', 'gojek', 'makan']);
});

// ── spasi murni sebagai pemisah (angka + kata bilangan diglue) ──
test('parseMultiExpense: spasi murni antar item (kata bilangan diglue)', () => {
  const items = parseMultiExpense('kopi 35 ribu gojek 20 ribu');
  assert.ok(items, 'harus terpecah');
  assert.equal(items.length, 2);
  assert.deepEqual(items.map(i => i.amount), [35000, 20000]);
  assert.deepEqual(items.map(i => i.description), ['kopi', 'gojek']);
});

test('parseMultiExpense: spasi murni dengan ribuan bertitik', () => {
  const items = parseMultiExpense('kopi 35.000 gojek 20.000');
  assert.ok(items);
  assert.equal(items.length, 2);
  assert.deepEqual(items.map(i => i.amount), [35000, 20000]);
});

test('parseMultiExpense: campuran koma + spasi murni dalam satu input', () => {
  const items = parseMultiExpense('makan siang 25 ribu, gojek 20 ribu tol 10 ribu');
  assert.ok(items);
  assert.equal(items.length, 3);
  assert.deepEqual(items.map(i => i.amount), [25000, 20000, 10000]);
  assert.deepEqual(items.map(i => i.description), ['makan siang', 'gojek', 'tol']);
});

// ── guard kuantitas: angka polos bukan pemisah item ──
test('parseMultiExpense: angka kuantitas tidak memecah item ("2 kopi")', () => {
  assert.equal(parseMultiExpense('beli 2 kopi 25 ribu'), null);
});

test('parseMultiExpense: angka kuantitas tidak memecah item ("12 bulan")', () => {
  assert.equal(parseMultiExpense('cicilan 12 bulan 500 ribu'), null);
});

test('parseMultiExpense: satu item spasi murni tidak terpecah', () => {
  assert.equal(parseMultiExpense('bayar listrik 350 ribu'), null);
});

test('parseMultiExpense: kata berakhiran "k" bukan token jumlah ("gojek")', () => {
  assert.equal(parseMultiExpense('naik gojek dan bayar tol 25 ribu'), null);
});

// ── parseAmount: prioritaskan jumlah dengan kata pengali ──
test('parseAmount: kuantitas angka polos tidak menang atas jumlah ber-pengali', () => {
  const r = parseAmount('beli 2 kopi 25 ribu');
  assert.ok(r);
  assert.equal(r.amount, 25000);
  assert.equal(r.description, 'beli 2 kopi');
});

test('parseAmount: "2 bulan cicilan 500 ribu" membaca 500 ribu', () => {
  const r = parseAmount('bayar 2 bulan cicilan 500 ribu');
  assert.ok(r);
  assert.equal(r.amount, 500000);
  assert.equal(r.description, 'bayar 2 bulan cicilan');
});

test('parseAmount: tanpa pengali, angka pertama tetap dipakai ("5000 2 pcs")', () => {
  const r = parseAmount('sabun 5000 2 pcs');
  assert.ok(r);
  assert.equal(r.amount, 5000);
  assert.equal(r.description, 'sabun 2 pcs');
});

test('parseAmount: angka tunggal polos tidak berubah ("gojek 15000")', () => {
  const r = parseAmount('gojek 15000');
  assert.ok(r);
  assert.equal(r.amount, 15000);
  assert.equal(r.description, 'gojek');
});
