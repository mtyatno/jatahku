import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fitDimensions, receiptToItem, scanMessage, feedbackFor } from './receiptScan.js';

test('fitDimensions: foto besar diperkecil ke sisi panjang 1600, rasio tetap', () => {
  assert.deepEqual(fitDimensions(3000, 4000), { width: 1200, height: 1600 });
  assert.deepEqual(fitDimensions(800, 600), { width: 800, height: 600 });
});

test('receiptToItem: hasil scan jadi item dengan tanggal struk', () => {
  const item = receiptToItem({ scan_id: 's1', merchant: 'Indomaret', total: 140500, date: '2026-10-14', confidence: 'tinggi' }, 'k1');
  assert.equal(item.origin, 'receipt');
  assert.equal(item.description, 'Indomaret');
  assert.equal(item.amount, 140500);
  assert.equal(item.transactionDate, '2026-10-14');
  assert.equal(item.envelopeId, '');
});

test('receiptToItem: toko tak terbaca → "Belanja", total kosong → 0', () => {
  const item = receiptToItem({ scan_id: 's2', merchant: null, total: null, date: null, confidence: 'gagal' }, 'k2');
  assert.equal(item.description, 'Belanja');
  assert.equal(item.amount, 0);
});

test('scanMessage: kuota Basic ditampilkan, keyakinan rendah minta cek', () => {
  const m = scanMessage({ merchant: 'Alfamart', total: 45400, confidence: 'sedang', quota: { limit: 15, used: 3, remaining: 12 } });
  assert.equal(m.type, 'mixed');
  assert.match(m.text, /Rp 45\.400/);
  assert.match(m.text, /12 dari 15/);
  const pro = scanMessage({ merchant: 'Alfamart', total: 45400, confidence: 'tinggi', quota: { limit: null } });
  assert.equal(pro.type, 'success');
  assert.doesNotMatch(pro.text, /Sisa scan/);
});

test('receiptToItem: membawa rincian barang & penyesuaian', () => {
  const item = receiptToItem({
    scan_id: 's3', merchant: 'Indomaret', total: 70600, date: null, confidence: 'tinggi',
    items: [{ name: 'IDM F.TIS', amount: 37800, discount: 0, unit_price: 37800, qty: 1, flag: 'ok' }],
    adjustments: [{ label: 'VC PL', amount: 5900, kind: 'discount' }],
  }, 'k3');
  assert.equal(item.receiptItems.length, 1);
  assert.equal(item.receiptItems[0].unitPrice, 37800);
  assert.equal(item.adjustments[0].kind, 'discount');
  assert.deepEqual(item.savedGroups, {});
});

test('scanMessage: rincian cocok / selisih disebut', () => {
  const base = { merchant: 'Indomaret', total: 140500, confidence: 'tinggi', quota: { limit: null } };
  const cocok = scanMessage({ ...base, items: [{}, {}], reconciliation: { status: 'cocok', diff: 0 } });
  assert.match(cocok.text, /2 barang cocok/);
  assert.equal(cocok.type, 'success');
  const beda = scanMessage({ ...base, items: [{}], reconciliation: { status: 'selisih', diff: -7600 } });
  assert.match(beda.text, /selisih Rp 7\.600/);
  assert.equal(beda.type, 'mixed');
});

test('scanMessage: total gagal dibaca → error minta isi manual', () => {
  assert.equal(scanMessage({ total: null, confidence: 'gagal', quota: {} }).type, 'error');
});

test('feedbackFor: nilai akhir yang disimpan user', () => {
  const fb = feedbackFor({ amount: 9200, transactionDate: '2026-10-01', description: 'Indomaret' }, true);
  assert.deepEqual(fb, { saved: true, total: 9200, transaction_date: '2026-10-01', merchant: 'Indomaret' });
  assert.deepEqual(feedbackFor({}, false), { saved: false });
});
