import { test } from 'node:test';
import assert from 'node:assert/strict';
import { envelopeInsight } from './envelopeInsight.js';

test('expense: aman saat ratio < 0.7 dan free > 0', () => {
  const r = envelopeInsight({ purpose: 'expense', free: 1000, spent_ratio: 0.1 }, null);
  assert.deepEqual(r, { text: 'Masih aman, tetap jaga ya!', tone: 'safe' });
});

test('expense: warning di 70%', () => {
  const r = envelopeInsight({ purpose: 'expense', free: 500, spent_ratio: 0.75 }, null);
  assert.equal(r.tone, 'warning');
  assert.equal(r.text, 'Hati-hati, mendekati batas');
});

test('expense: danger di 90%', () => {
  const r = envelopeInsight({ purpose: 'expense', free: 100, spent_ratio: 0.95 }, null);
  assert.equal(r.tone, 'danger');
  assert.equal(r.text, 'Sudah mepet, rem dulu');
});

test('expense: over budget saat free <= 0 diprioritaskan', () => {
  const r = envelopeInsight({ purpose: 'expense', free: 0, spent_ratio: 1 }, null);
  assert.equal(r.tone, 'danger');
  assert.equal(r.text, 'Melewati budget bulan ini');
});

test('saving: tanpa goal -> neutral', () => {
  const r = envelopeInsight({ purpose: 'saving' }, null);
  assert.deepEqual(r, { text: 'Tambahkan target biar terarah', tone: 'neutral' });
});

test('saving: tercapai -> safe', () => {
  const r = envelopeInsight({ purpose: 'saving' }, { is_achieved: true });
  assert.equal(r.text, 'Target tercapai, mantap!');
  assert.equal(r.tone, 'safe');
});

test('saving: lewat target_date & belum tercapai -> warning', () => {
  const r = envelopeInsight({ purpose: 'saving' }, { is_achieved: false, target_date: '2000-01-01' });
  assert.equal(r.tone, 'warning');
  assert.equal(r.text, 'Sedikit tertinggal dari target');
});

test('saving: on track -> safe default', () => {
  const r = envelopeInsight({ purpose: 'saving' }, { is_achieved: false, target_date: '2999-01-01' });
  assert.equal(r.text, 'Menuju target dengan konsisten');
  assert.equal(r.tone, 'safe');
});

test('sinking_fund pakai cabang saving', () => {
  const r = envelopeInsight({ purpose: 'sinking_fund' }, null);
  assert.equal(r.tone, 'neutral');
});
