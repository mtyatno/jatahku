import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  buildDailySeries, dailyTicks, tickLabel, niceStep, axisLabel,
  transfersInto, attentionItems, attentionOverflow, breakdownSegments,
} from './dashboardInsights.js';

test('buildDailySeries: status per hari terhadap batas aman, hari depan = future', () => {
  const s = buildDailySeries(
    [{ date: '2026-10-01', total: 100000 }, { date: '2026-10-02', total: 200000 }],
    '2026-09-30', '2026-10-04', '2026-10-03', 153000,
  );
  assert.deepEqual(s.map(r => r.status), ['empty', 'ok', 'over', 'empty', 'future']);
  assert.equal(s[3].isToday, true);
});

test('buildDailySeries: tanpa batas aman semua belanja dianggap dalam jatah', () => {
  const s = buildDailySeries([{ date: '2026-10-01', total: 900000 }], '2026-10-01', '2026-10-01', '2026-10-31', 0);
  assert.equal(s[0].status, 'ok');
});

test('dailyTicks & tickLabel: awal, tanggal 1, kelipatan 7, akhir', () => {
  const s = buildDailySeries([], '2026-09-27', '2026-10-26', '2026-10-15', 0);
  const t = dailyTicks(s);
  assert.deepEqual(t.map(d => tickLabel(d, s)), ['27 Sep', '1 Okt', '8', '15', '22', '26']);
});

test('niceStep & axisLabel', () => {
  assert.equal(niceStep(380000), 200000);
  assert.equal(niceStep(2_100_000), 2_000_000);
  assert.equal(axisLabel(200000), '200rb');
  assert.equal(axisLabel(1_500_000), '1,5jt');
});

test('transfersInto: hitung transfer masuk per amplop tujuan dengan sumbernya', () => {
  const t = transfersInto([
    { amount: '0', source: 'Transfer: Makan & Jajan → Transport', allocations: [{ envelope: 'Makan & Jajan', amount: '-50000' }, { envelope: 'Transport', amount: '50000' }] },
    { amount: '0', source: 'Transfer: Makan & Jajan → Transport', allocations: [{ envelope: 'Makan & Jajan', amount: '-20000' }, { envelope: 'Transport', amount: '20000' }] },
    { amount: '5000000', source: 'Gaji', allocations: [{ envelope: 'Transport', amount: '100000' }] },
  ]);
  assert.deepEqual(t.Transport, { count: 2, amount: 70000, sources: { 'Makan & Jajan': 70000 } });
});

const env = (id, name, jatah, spent, extra = {}) => ({
  id, name, allocated: jatah, rollover: 0, spent, reserved: 0, free: jatah - spent, remaining: jatah - spent, purpose: 'expense', ...extra,
});

test('attentionItems: tagihan telat, income kosong, amplop habis (tanpa dobel amplop tagihan)', () => {
  const items = attentionItems({
    isCurrentPeriod: true,
    today: '2026-10-15',
    income: 0,
    subscriptions: [{ id: 'r1', envelope_id: 'a', description: 'Bayar KPR Rumah', amount: 1600000, next_run: '2026-10-06', status: 'overdue', is_active: true }],
    envelopes: [env('a', 'Tagihan & Cicilan', 3400000, 3810000), env('b', 'Transport', 450000, 450000), env('c', 'Hiburan & Self Care', 135000, 135000), env('d', 'Makan', 4420000, 2960000), env('s', 'Darurat', 0, 0, { purpose: 'saving' })],
    transfers: { Transport: { count: 7, amount: 391500, sources: { 'Makan & Jajan': 391500 } } },
    advisorCards: [{ id: 'env_depletion:b', type: 'env_depletion', severity: 'danger', title: 'Transport: dana sudah habis' }],
  });
  assert.deepEqual(items.map(i => i.title), [
    'KPR Rumah telat 9 hari',
    'Income belum dicatat',
    'Transport habis, ditambal 7×',
    'Hiburan & Self Care habis',
  ]);
  assert.equal(items[0].detail, 'Rp1.600.000 · amplop Tagihan & Cicilan minus');
  assert.equal(items[2].detail, 'Rp391.500 dari Makan & Jajan');
  assert.equal(attentionOverflow(items), 'Hiburan & Self Care juga sudah habis');
});

test('attentionItems: periode lampau kosong', () => {
  assert.deepEqual(attentionItems({ isCurrentPeriod: false }), []);
});

test('breakdownSegments: 3 terbesar + Lainnya', () => {
  const { total, segments } = breakdownSegments([
    { name: 'A', spent: 50 }, { name: 'B', spent: 30 }, { name: 'C', spent: 10 }, { name: 'D', spent: 6 }, { name: 'E', spent: 4 },
  ]);
  assert.equal(total, 100);
  assert.deepEqual(segments.map(s => [s.name, s.amount]), [['A', 50], ['B', 30], ['C', 10], ['Lainnya (2 amplop)', 10]]);
});
