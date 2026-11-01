import { test } from 'node:test';
import assert from 'node:assert/strict';
import { berandaModel, floorRp100, sortEnvelopes, advisorSliceReady } from './berandaModel.js';

const ENVS = [
  { id: 'm', name: 'Makan', allocated: '1000000', rollover: '50000', spent: '400000', free: '600000', remaining: '650000', spent_ratio: 0.4, purpose: 'expense' },
  { id: 't', name: 'Transport', allocated: '0', spent: '0', remaining: '0', spent_ratio: 0, purpose: 'expense' },
  { id: 'l', name: 'Liburan', allocated: '500000', spent: '0', free: '500000', spent_ratio: 0, purpose: 'saving' },
  { id: 'p', name: 'HP', allocated: '200000', spent: '0', free: '200000', spent_ratio: 0, purpose: 'sinking_fund', is_personal: true },
];

test('angka UI lama: total, tabungan, sisa bebas, jatah aman dibulatkan Rp100', () => {
  const m = berandaModel({
    envelopes: ENVS,
    prediction: { safe_daily: 123456.7, total_income: '3000000' },
    daily: [{ date: '2026-11-01', total: 35000, count: 2 }],
    recurringStats: { amount_due: 150000, amount_paid: 50000 },
    goals: [{ envelope_id: 'l' }, { envelope_id: 'm' }],
    isCurrentPeriod: true, today: '2026-11-01',
  });
  assert.equal(m.totalAllocated, 1700000);
  assert.equal(m.totalRollover, 50000);
  assert.equal(m.fundsTotal, 1750000);
  assert.equal(m.totalSpent, 400000);
  assert.equal(m.totalSaving, 700000);
  assert.equal(m.sharedSaving, 500000);
  assert.equal(m.personalSaving, 200000);
  assert.equal(m.sisaBebas, 600000);               // 1.300.000 − 700.000
  assert.equal(m.safeDaily, 123400);
  assert.equal(m.todaySpent, 35000);
  assert.equal(m.todayCount, 2);
  assert.equal(m.income, 3000000);
  assert.equal(m.savingGoalCount, 1);
  assert.deepEqual(m.spending.map(e => e.id), ['m', 't']);
  assert.deepEqual(m.savingEnvelopes.map(e => e.id), ['l', 'p']);
  assert.equal(m.adv, false);
  assert.equal(m.advToday, '2026-11-01');
});

test('AI Advisor aktif: angka KPI dari metrik, hari ini dari generated_at', () => {
  const metrics = { belanja_hari_ini: 35000, j0: 80000, terpakai: 400000, dana_belanja: 1000000, hari_ke: 1,
    hari_total: 30, sisa_bebas: 600000, sisa_bebas_harian: 550000, pemasukan_rumah_tangga: 3000000, pemasukan_saya: 3000000 };
  const full = { enabled: true, generated_at: '2026-11-01T08:00:00+07:00', metrics: { ...metrics, harian: [] } };
  const m = berandaModel({ envelopes: ENVS, advisorDash: full, today: '2026-10-31' });
  assert.equal(m.adv, true);
  assert.equal(m.k.jatah.spent, 35000);
  assert.equal(m.k.sisa.value, 550000);
  assert.equal(m.advToday, '2026-11-01');
  // Potongan KPI dari POST /dashboard/data: metrik tanpa harian → sama, bila advisorSlice.
  const slice = { enabled: true, generated_at: full.generated_at, metrics, kpi: null };
  assert.equal(berandaModel({ advisorDash: slice, today: '2026-11-01' }).adv, false, 'potongan bukan payload utuh');
  const ms = berandaModel({ envelopes: ENVS, advisorDash: slice, advisorSlice: true, today: '2026-10-31' });
  assert.deepEqual(ms.k, m.k);
  assert.equal(ms.advToday, m.advToday);
});

test('periode lalu tidak memakai advisor', () => {
  const full = { enabled: true, generated_at: '2026-11-01T08:00:00+07:00', metrics: { harian: [] } };
  assert.equal(berandaModel({ advisorDash: full, isCurrentPeriod: false, today: '2026-11-01' }).adv, false);
});

test('masukan kosong atau rusak tidak melempar', () => {
  const m = berandaModel({ envelopes: null, daily: null, goals: null, today: '2026-11-01' });
  assert.equal(m.totalSpent, 0);
  assert.equal(m.safeDaily, 0);
  assert.equal(berandaModel().spending.length, 0);
});

test('pembantu', () => {
  assert.equal(floorRp100(199), 100);
  assert.equal(floorRp100(null), 0);
  assert.deepEqual(sortEnvelopes(ENVS.slice(0, 2)).map(e => e.id), ['m', 't']);
  assert.equal(advisorSliceReady({ enabled: false, metrics: {} }), false);
  assert.equal(advisorSliceReady({ enabled: true, metrics: {} }), true);
  assert.equal(advisorSliceReady(null), false);
});
