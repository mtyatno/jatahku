import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  envelopeStatus, envelopeStrip, fundsBreakdown, freeShare, savingsProgress, dailySeries, monotonePath,
} from './kpiVisuals.js';

const env = (o) => ({
  id: 'e', purpose: 'expense', is_personal: false,
  allocated: 0, rollover: 0, spent: 0, reserved: 0, free: 0, spent_ratio: 0, ...o,
});

test('status follows the envelope bar colors', () => {
  assert.equal(envelopeStatus(env({ rollover: 800000, spent: 840000, free: -40000, spent_ratio: 1.05 })), 'over');
  assert.equal(envelopeStatus(env({ rollover: 1200000, spent: 980000, free: 220000, spent_ratio: 0.82 })), 'low');
  assert.equal(envelopeStatus(env({ rollover: 400000, reserved: 500000, free: -100000 })), 'low');
  assert.equal(envelopeStatus(env({ rollover: 3500000, spent: 1650000, free: 1850000, spent_ratio: 0.47 })), 'ok');
  assert.equal(envelopeStatus(env({})), 'empty');
  assert.equal(envelopeStatus(env({ purpose: 'sinking_fund', rollover: 500000, free: 500000 })), 'saving');
});

test('strip puts envelopes that need attention first', () => {
  const strip = envelopeStrip([
    env({ id: 'a', name: 'Tabungan', purpose: 'saving' }),
    env({ id: 'b', name: 'Makan', rollover: 100, free: 100 }),
    env({ id: 'c', name: 'Belanja', rollover: 100, spent: 150, free: -50, spent_ratio: 1.5 }),
    env({ id: 'd', name: 'Baru' }),
  ]);
  assert.deepEqual(strip.map((s) => s.status), ['over', 'ok', 'saving', 'empty']);
  assert.deepEqual(strip[0], { id: 'c', name: 'Belanja', status: 'over' });
});

test('funds breakdown adds up to allocation plus rollover', () => {
  const envs = [
    env({ rollover: 3500000, spent: 1650000, free: 1850000 }),
    env({ rollover: 900000, reserved: 750000, free: 150000 }),
    env({ rollover: 800000, spent: 840000, free: -40000 }),
    env({ purpose: 'saving', rollover: 1200000, free: 1200000 }),
  ];
  const b = fundsBreakdown(envs);
  assert.deepEqual(b, { spent: 2490000, reserved: 750000, saving: 1200000, free: 1960000 });
  assert.equal(b.spent + b.reserved + b.saving + b.free, 6400000);
  assert.equal(fundsBreakdown([env({ rollover: 100, spent: 300, free: -200 })]).free, 0);
});

test('free share ignores savings envelopes and clamps to 0..1', () => {
  const envs = [
    env({ rollover: 1000, spent: 400, reserved: 200, free: 400 }),
    env({ rollover: 1000, spent: 0, free: 1000, purpose: 'saving' }),
  ];
  assert.equal(freeShare(envs), 0.4);
  assert.equal(freeShare([env({ rollover: 100, spent: 300, free: -200 })]), 0);
  assert.equal(freeShare([env({ purpose: 'saving', rollover: 100 })]), null);
});

test('savings progress splits shared and personal, capping each goal at its target', () => {
  const envs = [
    env({ id: 's1', purpose: 'saving' }),
    env({ id: 'p1', purpose: 'saving', is_personal: true }),
    env({ id: 'p2', purpose: 'sinking_fund', is_personal: true }),
  ];
  const goals = [
    { envelope_id: 's1', target_amount: '10000000', current_balance: '1200000' },
    { envelope_id: 'p1', target_amount: '1000000', current_balance: '1500000' },
    { envelope_id: 'p2', target_amount: '3000000', current_balance: '1000000' },
  ];
  assert.equal(savingsProgress(goals, envs, false), 0.12);
  assert.equal(savingsProgress(goals, envs, true), 0.5);
  assert.equal(savingsProgress([], envs, true), null);
});

test('daily series covers the whole period and leaves future days empty', () => {
  const s = dailySeries([{ date: '2026-09-28', total: 320000 }], '2026-09-27', '2026-10-26', '2026-10-04');
  assert.equal(s.length, 30);
  assert.deepEqual(s[0], { date: '2026-09-27', total: 0 });
  assert.equal(s[1].total, 320000);
  assert.equal(s[7].date, '2026-10-04');
  assert.equal(s[7].total, 0);
  assert.equal(s[8].total, null);
  assert.deepEqual(dailySeries([], null, null, '2026-10-04'), []);
});

test('monotone path never overshoots the data', () => {
  const pts = [[0, 30], [1, 4], [2, 28], [3, 29], [4, 10]];
  const nums = monotonePath(pts).match(/-?\d+(\.\d+)?/g).map(Number);
  const ys = nums.filter((_, i) => i % 2 === 1);
  assert.ok(Math.min(...ys) >= 4 && Math.max(...ys) <= 30);
  assert.equal(monotonePath([[0, 5]]), 'M0,5');
  assert.equal(monotonePath([]), '');
});
