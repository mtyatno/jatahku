import { test } from 'node:test';
import assert from 'node:assert/strict';
import { envelopeRow } from './envelopeRow.js';

const expense = (o) => ({ purpose: 'expense', allocated: 0, rollover: 0, spent: 0, reserved: 0, ...o });

test('expense aman: angka dana bebas, keterangan persen terpakai', () => {
  const r = envelopeRow(expense({ rollover: 4870000, spent: 1385000, remaining: 3485000, free: 3485000, spent_ratio: 0.284 }), null);
  assert.deepEqual(r, { amount: 3485000, tone: 'safe', note: '28% terpakai', noteTone: 'muted' });
});

test('expense mendekati batas jadi amber', () => {
  const r = envelopeRow(expense({ rollover: 457000, spent: 370000, remaining: 87000, free: 87000, spent_ratio: 0.81 }), null);
  assert.equal(r.tone, 'warning');
  assert.equal(r.note, '81% terpakai');
});

test('kurang reserve tetap amber walau terpakai 94%', () => {
  const r = envelopeRow(expense({ rollover: 3512000, spent: 3289174, reserved: 2090000, remaining: 222826, free: -1867174, spent_ratio: 0.94 }), null);
  assert.equal(r.tone, 'warning');
  assert.equal(r.note, 'Tagihan kurang Rp1.86jt');
  assert.equal(r.amount, -1867174);
});

test('overspent jadi merah dengan nominal minusnya', () => {
  const r = envelopeRow(expense({ allocated: 500000, spent: 650000, remaining: -150000, free: -150000, spent_ratio: 1 }), null);
  assert.equal(r.tone, 'danger');
  assert.equal(r.note, 'Minus Rp150rb');
});

test('expense tanpa dana', () => {
  const r = envelopeRow(expense({ remaining: 0, free: 0 }), null);
  assert.equal(r.note, 'Belum ada dana');
  assert.equal(r.tone, 'muted');
});

test('tabungan dengan target: saldo goal + persen target', () => {
  const r = envelopeRow({ purpose: 'saving', free: 1200000 }, { current_balance: 1200000, progress_pct: 40, is_achieved: false, target_date: '2999-01-01' });
  assert.deepEqual(r, { amount: 1200000, tone: 'saving', note: '40% dari target', noteTone: 'muted' });
});

test('tabungan tanpa target', () => {
  const r = envelopeRow({ purpose: 'sinking_fund', free: 300000 }, null);
  assert.equal(r.note, 'Belum ada target');
  assert.equal(r.amount, 300000);
});

test('tabungan lewat tanggal target', () => {
  const r = envelopeRow({ purpose: 'saving' }, { current_balance: 100, progress_pct: 10, is_achieved: false, target_date: '2000-01-01' });
  assert.equal(r.noteTone, 'warning');
  assert.equal(r.note, '10% dari target · terlambat');
});

test('tabungan tercapai', () => {
  const r = envelopeRow({ purpose: 'saving' }, { current_balance: 100, progress_pct: 100, is_achieved: true, target_date: null });
  assert.equal(r.note, 'Target tercapai');
  assert.equal(r.noteTone, 'safe');
});
