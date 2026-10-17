import { test } from 'node:test';
import assert from 'node:assert/strict';
import { focusItems, localAction, pageEnabled, rowInsight, summaryLine } from './advisorLangganan.js';

const page = {
  enabled: true,
  per_langganan: { kpr: { id: 'TAG-01:kpr', aturan: 'TAG-01', dismiss: { kunci: 'TAG-01:kpr' } } },
};

test('pageEnabled: hanya bila server bilang enabled', () => {
  assert.equal(pageEnabled(page), true);
  assert.equal(pageEnabled({ enabled: false }), false);
  assert.equal(pageEnabled(null), false);
});

test('rowInsight: per baris, tanpa yang baru disembunyikan', () => {
  assert.equal(rowInsight(page, 'kpr').aturan, 'TAG-01');
  assert.equal(rowInsight(page, 'lain'), null);
  assert.equal(rowInsight(page, 'kpr', ['TAG-01:kpr']), null);
  assert.equal(rowInsight(null, 'kpr'), null);
});

test('localAction: route ke /langganan jadi aksi lokal', () => {
  const self = { kind: 'route', payload: { path: '/langganan' } };
  assert.deepEqual(localAction(self, { recurringId: 'net' }), { type: 'edit', recurringId: 'net' });
  assert.deepEqual(localAction(self, { recurringIds: ['a', 'b'] }), { type: 'focus', recurringIds: ['a', 'b'] });
  assert.deepEqual(localAction({ kind: 'route', payload: { path: '/langganan/' } }), { type: 'sort', mode: 'expensive' });
  assert.equal(localAction({ kind: 'route', payload: { path: '/envelopes' } }, { recurringId: 'net' }), null);
  assert.equal(localAction({ kind: 'pay', payload: { recurring_id: 'net' } }, { recurringId: 'net' }), null);
});

test('summaryLine: angka dari server, hanya diformat', () => {
  const fmt = n => `Rp${n}`;
  assert.equal(summaryLine({ beban_bulanan: 500000, beban_persen: 12 }, fmt),
    'Tagihan rutin Rp500000/bulan · 12% dari dana belanja');
  assert.equal(summaryLine({ beban_bulanan: 500000, beban_persen: null }, fmt), 'Tagihan rutin Rp500000/bulan');
  assert.equal(summaryLine(null, fmt), null);
});

test('focusItems: saring ke id TAG-08', () => {
  const items = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
  assert.deepEqual(focusItems(items, ['a', 'c']).map(i => i.id), ['a', 'c']);
  assert.equal(focusItems(items, []), items);
  assert.equal(focusItems(items, null), items);
});
