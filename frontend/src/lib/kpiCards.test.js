import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  rpFull, rpCompact, dailyMeter, predictionOver, daysLabel, periodDayLabel, periodProgress,
  savingRateLabel, cashFlowLabel, billsProgress,
} from './kpiCards.js';

test('amounts match the design format', () => {
  assert.equal(rpFull(297100), 'Rp297.100');
  assert.equal(rpFull(153249), 'Rp153.200');
  assert.equal(rpCompact(1684000), 'Rp1,68 jt');
  assert.equal(rpCompact(8000000), 'Rp8 jt');
  assert.equal(rpCompact(1600000), 'Rp1,6 jt');
  assert.equal(rpCompact(490000), 'Rp490 rb');
  assert.equal(rpCompact(153200), 'Rp153 rb');
  assert.equal(rpCompact(-1340000), '–Rp1,34 jt');
  assert.equal(rpCompact(0), 'Rp0');
});

test('over the daily limit: full red bar, marker at the limit, over amount floored', () => {
  const m = dailyMeter(297100, 153200);
  assert.equal(m.over, true);
  assert.equal(m.fill, 1);
  assert.ok(Math.abs(m.marker - 153200 / 297100) < 1e-9);
  assert.equal(m.overBy, 143900);
});

test('under the daily limit: partial bar, no marker', () => {
  const m = dailyMeter(50000, 153200);
  assert.equal(m.over, false);
  assert.equal(m.marker, null);
  assert.ok(Math.abs(m.fill - 50000 / 153200) < 1e-9);
  assert.equal(m.overBy, 0);
});

test('no safe amount left', () => {
  assert.deepEqual(dailyMeter(0, 0), { fill: 0, marker: null, over: false, overBy: 0 });
});

test('Prediksi lewat compares with allocation plus rollover', () => {
  assert.equal(predictionOver({ predicted_total: 11280000, total_available: 18200000 }), false);
  assert.equal(predictionOver({ predicted_total: 19000000, total_available: 18200000 }), true);
  assert.equal(predictionOver(null), false);
});

test('day labels follow safe_days and the period', () => {
  assert.equal(daysLabel({ safe_days: 11 }), 'untuk 11 hari');
  assert.equal(daysLabel({ safe_days: 1 }), 'untuk 1 hari');
  assert.equal(periodDayLabel({ days_passed: 19, days_left: 11 }), 'Hari ke-19 dari 30');
  assert.ok(Math.abs(periodProgress({ days_passed: 19, days_left: 11 }) - 19 / 30) < 1e-9);
  assert.equal(periodProgress(null), 0);
});

test('saving rate reads 0% without income', () => {
  assert.equal(savingRateLabel({ total_income: 0, saving_rate: 0 }), 'saving rate 0%');
  assert.equal(savingRateLabel({ saving_rate: 34.6 }), 'saving rate 35%');
});

test('cash flow keeps its minus sign', () => {
  assert.equal(cashFlowLabel({ predicted_cash_flow: -1340000 }), 'Arus kas diprediksi –Rp1,34 jt di akhir periode');
  assert.equal(cashFlowLabel({ predicted_cash_flow: 2500000 }), 'Arus kas diprediksi Rp2,5 jt di akhir periode');
});

test('bill progress is by amount', () => {
  const b = billsProgress({ amount_paid: 490000, amount_due: 1600000 });
  assert.equal(b.total, 2090000);
  assert.ok(Math.abs(b.fill - 490000 / 2090000) < 1e-9);
  assert.equal(billsProgress(null).fill, 0);
});
