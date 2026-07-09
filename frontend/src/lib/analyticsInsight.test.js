import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildWeekHeatmap, categoryDelta, busiestWeekday } from './analyticsInsight.js';

// ── buildWeekHeatmap ─────────────────────────────────────────────
test('buildWeekHeatmap: grid minggu x 7 hari (Sen-first), level 0-4, padding null', () => {
  // Periode Rab 1 Jul – Sel 7 Jul 2026 (1 Jul 2026 = Rabu)
  const daily = [
    { date: '2026-07-01', total: 100000, count: 2 },
    { date: '2026-07-04', total: 400000, count: 1 }, // max -> level 4 (Sabtu)
    { date: '2026-07-06', total: 200000, count: 3 },
  ];
  const { weeks, max } = buildWeekHeatmap(daily, '2026-07-01', '2026-07-07');
  assert.equal(max, 400000);
  assert.equal(weeks.length, 2);            // Rab-Min + Sen-Sel
  assert.equal(weeks[0][0], null);          // Senin sebelum periode -> null
  assert.equal(weeks[0][1], null);          // Selasa sebelum periode
  assert.equal(weeks[0][2].total, 100000);  // Rabu 1 Jul
  assert.equal(weeks[0][2].level, 1);       // 100k/400k = 0.25 -> level 1
  assert.equal(weeks[0][5].level, 4);       // Sabtu 4 Jul = max
  assert.equal(weeks[0][3].total, 0);       // Kamis 2 Jul tanpa data -> total 0 level 0
  assert.equal(weeks[0][3].level, 0);
  assert.equal(weeks[1][0].total, 200000);  // Senin 6 Jul
  assert.equal(weeks[1][2], null);          // Rabu 8 Jul di luar periode
});

test('buildWeekHeatmap: kosong', () => {
  const { weeks, max } = buildWeekHeatmap([], '2026-07-01', '2026-07-07');
  assert.equal(max, 0);
  assert.equal(weeks[0][2].level, 0);
});

// ── categoryDelta ────────────────────────────────────────────────
test('categoryDelta: naik/turun terurut, amplop baru pct null', () => {
  const cur = [
    { name: 'Pakaian', emoji: '👕', spent: 890000 },
    { name: 'Transport', emoji: '🚗', spent: 62000 },
    { name: 'Hobi', emoji: '🎮', spent: 252000 },
    { name: 'Baru', emoji: '✨', spent: 50000 },
    { name: 'Sama', emoji: '➖', spent: 100000 },
  ];
  const prev = [
    { name: 'Pakaian', emoji: '👕', spent: 120000 },
    { name: 'Transport', emoji: '🚗', spent: 75000 },
    { name: 'Hobi', emoji: '🎮', spent: 80000 },
    { name: 'Sama', emoji: '➖', spent: 100000 },
  ];
  const { up, down } = categoryDelta(cur, prev);
  assert.deepEqual(up.map(u => u.name), ['Baru', 'Pakaian', 'Hobi']); // baru dulu, lalu pct desc
  assert.equal(up[1].pct, 642);   // (890-120)/120 = 641.7 -> 642
  assert.equal(up[0].pct, null);  // baru
  assert.deepEqual(down.map(d => d.name), ['Transport']);
  assert.equal(down[0].pct, -17); // (62-75)/75 = -17.3 -> -17
  assert.ok(!up.concat(down).some(x => x.name === 'Sama')); // tak berubah -> drop
});

test('categoryDelta: prev kosong -> semua baru', () => {
  const { up, down } = categoryDelta([{ name: 'A', emoji: 'a', spent: 10 }], []);
  assert.equal(up.length, 1);
  assert.equal(up[0].pct, null);
  assert.equal(down.length, 0);
});

// ── busiestWeekday ───────────────────────────────────────────────
test('busiestWeekday: hari dengan total terbesar (nama Indonesia)', () => {
  const daily = [
    { date: '2026-07-04', total: 400000 }, // Sabtu
    { date: '2026-07-11', total: 300000 }, // Sabtu
    { date: '2026-07-06', total: 500000 }, // Senin
  ];
  const out = busiestWeekday(daily);
  assert.equal(out.day, 'Sabtu');  // 700k > 500k
  assert.equal(out.total, 700000);
  assert.equal(busiestWeekday([]), null);
});
