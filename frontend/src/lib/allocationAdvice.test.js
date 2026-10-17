import test from 'node:test';
import assert from 'node:assert/strict';
import { formEnvelopes, percentagesFor, reasonsById, recommendationAllocations } from './allocationAdvice.js';

const rec = {
  sisa_ke: { envelope_id: 't1', name: 'Tabungan' },
  items: [
    { envelope_id: 'm1', recommended_amount: 400000, keyakinan: 'high',
      alasan: [{ aturan: 'AMP-05', teks: 'Terpakai di atas jatah.' }] },
    { envelope_id: 'h1', recommended_amount: 0, keyakinan: 'low', alasan: [] },
    { envelope_id: 't1', recommended_amount: 600000, keyakinan: 'low', alasan: [] },
    { envelope_id: 'k1', recommended_amount: 100000 },
  ],
};

test('recommendationAllocations melewati penerima sisa, nol, dan amplop di luar form', () => {
  assert.deepEqual(recommendationAllocations(rec), { m1: 400000, k1: 100000 });
  assert.deepEqual(recommendationAllocations(rec, new Set(['m1'])), { m1: 400000 });
  assert.deepEqual(recommendationAllocations(null), {});
});

test('recommendationAllocations tanpa sisa_ke memakai semua item', () => {
  assert.deepEqual(recommendationAllocations({ items: rec.items, sisa_ke: { envelope_id: null } }),
    { m1: 400000, t1: 600000, k1: 100000 });
});

test('percentagesFor', () => {
  assert.deepEqual(percentagesFor({ a: 250, b: 333 }, 1000), { a: 25, b: 33 });
  assert.deepEqual(percentagesFor({ a: 1 }, 0), {});
});

test('reasonsById', () => {
  const r = reasonsById(rec);
  assert.deepEqual(r.m1, { alasan: ['Terpakai di atas jatah.'], keyakinan: 'high' });
  assert.deepEqual(r.k1, { alasan: [], keyakinan: null });
});

test('formEnvelopes tidak mencocokkan nama', () => {
  const envs = [{ id: 't1', name: 'Dana' }, { id: 'x', name: 'Tabungan' }];
  assert.deepEqual(formEnvelopes(envs, { envelope_id: 't1' }).map(e => e.id), ['x']);
  assert.equal(formEnvelopes(envs, null).length, 2);
});
