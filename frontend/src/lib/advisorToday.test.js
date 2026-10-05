import { test } from 'node:test';
import assert from 'node:assert/strict';
import { todayAdvice } from './advisorToday.js';

// Respons /analytics/prediction: free sudah dipotong belanja hari ini.
const pred = (over) => ({ total_available: 70000, days_left: 26, ...over });
const daily = (free) => pred({ income_type: 'daily', safe_days: 1, free, safe_daily: Math.max(Math.round(free), 0) });

test('harian: aman, belanja hari ini sudah dipotong dari sisa', () => {
  assert.deepEqual(todayAdvice(daily(50000), 20000, 50000),
    { show: true, over: false, overBy: 0, perIncome: true, days: 1 });
});

test('harian: belanja hari ini lebih besar dari sisa bukan berarti lewat', () => {
  // 70rb masuk, 40rb terpakai hari ini, sisa 30rb
  assert.equal(todayAdvice(daily(30000), 40000, 30000).over, false);
});

test('harian: lewat hanya kalau sisa bebas minus, sebesar minusnya', () => {
  assert.deepEqual(todayAdvice(daily(-15000), 85000, 0),
    { show: true, over: true, overBy: 15000, perIncome: true, days: 1 });
});

test('mingguan: lewat kalau belanja hari ini melebihi jatah (sisa ÷ 7)', () => {
  // 50.000 ÷ 7 = 7.143, tampil Rp7.100
  const p = pred({ income_type: 'weekly', safe_days: 7, free: 50000, safe_daily: 7143 });
  assert.deepEqual(todayAdvice(p, 5000, 7100), { show: true, over: false, overBy: 0, perIncome: true, days: 7 });
  assert.deepEqual(todayAdvice(p, 20000, 7100), { show: true, over: true, overBy: 12900, perIncome: true, days: 7 });
});

test('bulanan: kapan lewat sama dengan main, selisih dari jatah yang tampil', () => {
  // 50.000 ÷ 26 = 1.923, tampil Rp1.900; 20.000 − 1.900 = 18.100
  const p = pred({ income_type: 'monthly', safe_days: 26, free: 50000, safe_daily: 1923 });
  assert.deepEqual(todayAdvice(p, 20000, 1900), { show: true, over: true, overBy: 18100, perIncome: false, days: 26 });
  // pemicu memakai safe_daily asli seperti main: 1.910 belum lewat 1.923, 1.924 sudah
  assert.equal(todayAdvice(p, 1910, 1900).over, false);
  assert.equal(todayAdvice(p, 1923, 1900).over, false);
  assert.equal(todayAdvice(p, 1924, 1900).over, true);
  // tanpa jatah, selisih dihitung dari safe_daily asli
  assert.equal(todayAdvice(p, 20000).overBy, 18077);
});

test('tidak tentu dan respons tanpa income_type mengikuti bulanan', () => {
  for (const income_type of ['irregular', undefined]) {
    const t = todayAdvice(pred({ income_type, free: 50000, safe_daily: 1923 }), 20000, 1900);
    assert.deepEqual(t, { show: true, over: true, overBy: 18100, perIncome: false, days: 26 });
  }
});

test('tidak tampil tanpa prediksi, tanpa dana, atau jatah bulanan/mingguan habis', () => {
  assert.equal(todayAdvice(null, 0).show, false);
  assert.equal(todayAdvice(pred({ total_available: 0, free: 1000, safe_daily: 1000 }), 0).show, false);
  assert.equal(todayAdvice(pred({ income_type: 'monthly', free: -5000, safe_daily: -192 }), 0).show, false);
  assert.equal(todayAdvice(pred({ income_type: 'weekly', safe_days: 7, free: -5000, safe_daily: 0 }), 0).show, false);
});
